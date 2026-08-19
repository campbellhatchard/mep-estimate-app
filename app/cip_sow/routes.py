from __future__ import annotations

from datetime import datetime

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..cip_domain import _take_route, revision_product
from ..cip_models import PRODUCT_CIP, PRODUCT_MEP
from ..database import SessionLocal, get_db
from ..models import User
from ..services.audit import record
from ..sow_models import SOWTemplateVersion
from .. import sow_routes, sow_service
from .core import CIP_TEMPLATE_LABEL, SOW_TEMPLATE_CIP_NET_NEW, cip_sow_eligible, create_cip_sow, seed_cip_sow_template, validate_template_for_key
from .docx import cip_content_hash_for, validate_cip_finalize, verify_cip_approved_content
from .pdf import render_cip_pdf
from .views import _cip_sow_context, _product_for_sow, _save_cip_sow

def register_cip_sow(app, core) -> None:
    @app.on_event("startup")
    def seed_cip_sow_on_startup():
        db = SessionLocal()
        try:
            seed_cip_sow_template(db)
        finally:
            db.close()

    mep_estimate_sow = _take_route(app, "/estimate/{rid}/sow", "GET")
    mep_create_sow = _take_route(app, "/estimate/{rid}/sow/create", "POST")
    mep_sow_page = _take_route(app, "/sow/{sid}", "GET")
    mep_save_sow = _take_route(app, "/sow/{sid}/save", "POST")
    mep_finalize_sow = _take_route(app, "/sow/{sid}/finalize", "POST")
    mep_approve_sow = _take_route(app, "/sow/{sid}/approve", "POST")
    mep_sow_pdf = _take_route(app, "/sow/{sid}/pdf", "GET")
    mep_sow_docx = _take_route(app, "/sow/{sid}/docx", "GET")
    _take_route(app, "/admin/sow-templates", "GET")
    _take_route(app, "/admin/sow-templates/upload", "POST")
    _take_route(app, "/admin/sow-templates/{tid}/activate", "POST")

    @app.get("/estimate/{rid}/sow", response_class=HTMLResponse)
    def estimate_sow_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP:
            return mep_estimate_sow(rid, request, db)
        user = core.current_user(request, db)
        sow = sow_service.latest_sow(db, rid)
        if sow:
            return RedirectResponse(f"/sow/{sow.id}", 303)
        return core.templates.TemplateResponse(
            "cip_sow_empty.html",
            {
                "request": request,
                "user": user,
                "rev": rev,
                "estimate": rev.estimate,
                "active_tab": "sow",
                "eligible": cip_sow_eligible(rev),
                "product_type": PRODUCT_CIP,
            },
        )

    @app.post("/estimate/{rid}/sow/create")
    def create_sow_dispatch(rid: int, request: Request, db: Session = Depends(get_db)):
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) == PRODUCT_MEP:
            return mep_create_sow(rid, request, db)
        user = core.current_user(request, db)
        core.require_role(user, *sow_routes.PREP_ROLES)
        try:
            sow = create_cip_sow(db, rev, user)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/sow/{sow.id}", 303)

    @app.get("/sow/{sid}", response_class=HTMLResponse)
    def sow_page_dispatch(sid: int, request: Request, db: Session = Depends(get_db)):
        sow = sow_routes._sow_or_404(db, sid)
        if _product_for_sow(db, sow) == PRODUCT_MEP:
            return mep_sow_page(sid, request, db)
        user = core.current_user(request, db)
        return core.templates.TemplateResponse(
            "cip_sow.html", _cip_sow_context(db, request, core, sow, user)
        )

    @app.post("/sow/{sid}/save")
    async def save_sow_dispatch(sid: int, request: Request, db: Session = Depends(get_db)):
        sow = sow_routes._sow_or_404(db, sid)
        if _product_for_sow(db, sow) == PRODUCT_MEP:
            return await mep_save_sow(sid, request, db)
        user = core.current_user(request, db)
        core.require_role(user, *sow_routes.PREP_ROLES)
        rev = sow_routes._rev_for_sow(db, sow)
        if sow.status != "DRAFT":
            raise HTTPException(409, "Only a Draft SOW can be edited.")
        form = await request.form()
        _save_cip_sow(db, sow, rev, user, form)
        db.commit()
        return RedirectResponse(f"/sow/{sid}", 303)

    @app.post("/sow/{sid}/finalize")
    def finalize_sow_dispatch(sid: int, request: Request, db: Session = Depends(get_db)):
        sow = sow_routes._sow_or_404(db, sid)
        if _product_for_sow(db, sow) == PRODUCT_MEP:
            return mep_finalize_sow(sid, request, db)
        user = core.current_user(request, db)
        core.require_role(user, *sow_routes.PREP_ROLES)
        rev = sow_routes._rev_for_sow(db, sow)
        if sow.status != "DRAFT":
            raise HTTPException(409, "Only a Draft SOW can be finalized.")
        errors = validate_cip_finalize(db, sow, rev)
        if errors:
            raise HTTPException(400, " ".join(errors))
        sow.status = "FINALIZED"
        sow.finalized_by = user.id
        sow.finalized_at = datetime.utcnow()
        record(
            db,
            event_type="SOW_FINALIZED",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            field_name=f"SOW:{sow.id}",
            old_value="DRAFT",
            new_value="FINALIZED",
        )
        db.commit()
        return RedirectResponse(f"/sow/{sid}", 303)

    @app.post("/sow/{sid}/approve")
    def approve_sow_dispatch(sid: int, request: Request, db: Session = Depends(get_db)):
        sow = sow_routes._sow_or_404(db, sid)
        if _product_for_sow(db, sow) == PRODUCT_MEP:
            return mep_approve_sow(sid, request, db)
        user = core.current_user(request, db)
        if not user.has_role("SOW_APPROVER"):
            raise HTTPException(403, "SOW Approver role required")
        rev = sow_routes._rev_for_sow(db, sow)
        if sow.status != "PENDING_APPROVAL":
            raise HTTPException(409, "Only a SOW Pending Approval can be approved.")
        if sow.approver_id != user.id:
            raise HTTPException(403, "This SOW is assigned to another approver.")
        if sow.submitted_by == user.id:
            raise HTTPException(409, "The SOW submitter cannot approve their own SOW.")
        digest, text, _ = cip_content_hash_for(db, sow, rev)
        sow.status = "APPROVED"
        sow.approved_by = user.id
        sow.approved_at = datetime.utcnow()
        sow.content_hash = digest
        sow.approved_text_snapshot = text
        record(
            db,
            event_type="SOW_APPROVED",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            field_name=f"SOW:{sow.id}",
            old_value="PENDING_APPROVAL",
            new_value="APPROVED",
            reason=f"Content hash {digest}",
        )
        db.commit()
        return RedirectResponse(f"/sow/{sid}", 303)

    @app.get("/sow/{sid}/pdf")
    def sow_pdf_dispatch(sid: int, request: Request, db: Session = Depends(get_db)):
        sow = sow_routes._sow_or_404(db, sid)
        if _product_for_sow(db, sow) == PRODUCT_MEP:
            return mep_sow_pdf(sid, request, db)
        core.current_user(request, db)
        rev = sow_routes._rev_for_sow(db, sow)
        try:
            content = render_cip_pdf(db, sow, rev)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                    f'inline; filename="{rev.estimate.estimate_number}-CIP-SOW-R{sow.sow_revision_no}.pdf"'
            },
        )

    @app.get("/sow/{sid}/docx")
    def sow_docx_dispatch(sid: int, request: Request, db: Session = Depends(get_db)):
        sow = sow_routes._sow_or_404(db, sid)
        if _product_for_sow(db, sow) == PRODUCT_MEP:
            return mep_sow_docx(sid, request, db)
        user = core.current_user(request, db)
        rev = sow_routes._rev_for_sow(db, sow)
        if sow.status != "APPROVED":
            raise HTTPException(409, "The Word SOW is available only after SOW approval.")
        try:
            content = verify_cip_approved_content(db, sow, rev)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        record(
            db,
            event_type="SOW_DOCX_GENERATED",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            field_name=f"SOW:{sow.id}",
        )
        db.commit()
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{rev.estimate.estimate_number}-CIP-SOW-R{sow.sow_revision_no}.docx"'
            },
        )

    @app.get("/admin/sow-templates", response_class=HTMLResponse)
    def sow_templates_admin(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN")
        mep_versions = (
            db.query(SOWTemplateVersion)
            .filter(SOWTemplateVersion.template_key == "MEP_NET_NEW")
            .order_by(desc(SOWTemplateVersion.version_no))
            .all()
        )
        cip_versions = (
            db.query(SOWTemplateVersion)
            .filter(SOWTemplateVersion.template_key == SOW_TEMPLATE_CIP_NET_NEW)
            .order_by(desc(SOWTemplateVersion.version_no))
            .all()
        )
        users = {u.id: u.username for u in db.query(User).all()}
        return core.templates.TemplateResponse(
            "sow_templates_dual.html",
            {
                "request": request,
                "user": user,
                "mep_versions": mep_versions,
                "cip_versions": cip_versions,
                "users": users,
            },
        )

    @app.post("/admin/sow-templates/upload")
    async def upload_sow_template(
        request: Request,
        file: UploadFile = File(...),
        change_reason: str = Form(...),
        template_key: str = Form("MEP_NET_NEW"),
        db: Session = Depends(get_db),
    ):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN")
        if template_key not in ("MEP_NET_NEW", SOW_TEMPLATE_CIP_NET_NEW):
            raise HTTPException(400, "Unknown SOW template type.")
        if not file.filename or not file.filename.lower().endswith(".docx"):
            raise HTTPException(400, "Upload a .docx Word template.")
        reason = change_reason.strip()
        if not reason:
            raise HTTPException(400, "A change reason is required.")
        content = await file.read()
        missing = validate_template_for_key(content, template_key)
        if missing:
            raise HTTPException(
                400, "Template validation failed. Missing required marker(s): " + ", ".join(missing)
            )
        maxv = (
            db.query(SOWTemplateVersion)
            .filter(SOWTemplateVersion.template_key == template_key)
            .order_by(desc(SOWTemplateVersion.version_no))
            .first()
        )
        is_cip = template_key == SOW_TEMPLATE_CIP_NET_NEW
        row = SOWTemplateVersion(
            template_key=template_key,
            label=CIP_TEMPLATE_LABEL if is_cip else "MEP New Client SOW",
            product_type=PRODUCT_CIP if is_cip else PRODUCT_MEP,
            customer_type="Net_New",
            version_no=(maxv.version_no + 1 if maxv else 1),
            status="DRAFT",
            filename=file.filename,
            content=content,
            content_sha256=sow_service.sha256_bytes(content),
            change_reason=reason,
            created_by=user.id,
        )
        db.add(row)
        db.flush()
        record(
            db,
            event_type="SOW_TEMPLATE_UPLOADED",
            user_id=user.id,
            field_name=f"SOW_TEMPLATE:{row.template_key}:{row.version_no}",
            new_value=row.filename,
            reason=reason,
        )
        db.commit()
        return RedirectResponse("/admin/sow-templates", 303)

    @app.post("/admin/sow-templates/{tid}/activate")
    def activate_sow_template(tid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN")
        row = db.get(SOWTemplateVersion, tid)
        if not row:
            raise HTTPException(404, "SOW template version not found")
        if row.status != "DRAFT":
            raise HTTPException(409, "Only a Draft SOW template can be activated.")
        missing = validate_template_for_key(row.content, row.template_key)
        if missing:
            raise HTTPException(400, "Template validation failed: " + ", ".join(missing))
        current = db.query(SOWTemplateVersion).filter(
            SOWTemplateVersion.template_key == row.template_key,
            SOWTemplateVersion.status == "ACTIVE",
        ).all()
        now = datetime.utcnow()
        for old in current:
            old.status = "RETIRED"
            old.retired_at = now
            record(
                db,
                event_type="SOW_TEMPLATE_RETIRED",
                user_id=user.id,
                field_name=f"SOW_TEMPLATE:{old.template_key}:{old.version_no}",
                old_value="ACTIVE",
                new_value="RETIRED",
                reason=f"Superseded by template v{row.version_no}",
            )
        row.status = "ACTIVE"
        row.activated_by = user.id
        row.activated_at = now
        record(
            db,
            event_type="SOW_TEMPLATE_ACTIVATED",
            user_id=user.id,
            field_name=f"SOW_TEMPLATE:{row.template_key}:{row.version_no}",
            old_value="DRAFT",
            new_value="ACTIVE",
            reason=row.change_reason,
        )
        db.commit()
        return RedirectResponse("/admin/sow-templates", 303)
