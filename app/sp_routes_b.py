from __future__ import annotations

from datetime import datetime
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from . import sow_routes, sow_service
from .cip_domain import _take_route
from .cip_models import CIPRevisionInput, PRODUCT_CIP
from .database import get_db
from .services.audit import record
from .sp_core_a import _product_for_revision, create_small_project_sow, is_small_project_sow, small_project_estimate_eligible
from .sp_core_b import save_small_project_sow, validate_small_project_finalize
from .sp_render_b import render_small_project_pdf, small_project_content_hash_for
from .sp_routes_a import _small_project_context, copy_rejected_small_project_sow

def register_small_project_sow_workflow(app, core) -> None:
    estimate_sow_previous = _take_route(app, "/estimate/{rid}/sow", "GET")
    create_sow_previous = _take_route(app, "/estimate/{rid}/sow/create", "POST")
    sow_page_previous = _take_route(app, "/sow/{sid}", "GET")
    save_sow_previous = _take_route(app, "/sow/{sid}/save", "POST")
    finalize_previous = _take_route(app, "/sow/{sid}/finalize", "POST")
    approve_previous = _take_route(app, "/sow/{sid}/approve", "POST")
    new_revision_previous = _take_route(app, "/sow/{sid}/new-revision", "POST")
    pdf_previous = _take_route(app, "/sow/{sid}/pdf", "GET")

    @app.get("/estimate/{rid}/sow", response_class=HTMLResponse)
    def estimate_sow_dispatch(
        rid: int, request: Request, db: Session = Depends(get_db)
    ):
        rev = core.revision_or_404(db, rid)
        if not (
            rev.customer_type == "Install_Base"
            and (
                rev.project_type == "Small Project"
                or (
                    _product_for_revision(db, rev) == PRODUCT_CIP
                    and (db.get(CIPRevisionInput, rev.id) is not None)
                    and db.get(CIPRevisionInput, rev.id).project_type == "Small Project"
                )
            )
        ):
            return estimate_sow_previous(rid, request, db)

        user = core.current_user(request, db)
        sow = sow_service.latest_sow(db, rid)
        if sow:
            return RedirectResponse(f"/sow/{sow.id}", 303)
        return core.templates.TemplateResponse(
            "small_project_sow_empty.html",
            {
                "request": request,
                "user": user,
                "rev": rev,
                "estimate": rev.estimate,
                "active_tab": "sow",
                "eligible": small_project_estimate_eligible(db, rev),
                "product_type": _product_for_revision(db, rev),
            },
        )

    @app.post("/estimate/{rid}/sow/create")
    def create_sow_dispatch(
        rid: int, request: Request, db: Session = Depends(get_db)
    ):
        rev = core.revision_or_404(db, rid)
        if not (
            rev.customer_type == "Install_Base"
            and (
                rev.project_type == "Small Project"
                or (
                    _product_for_revision(db, rev) == PRODUCT_CIP
                    and (db.get(CIPRevisionInput, rev.id) is not None)
                    and db.get(CIPRevisionInput, rev.id).project_type == "Small Project"
                )
            )
        ):
            return create_sow_previous(rid, request, db)
        user = core.current_user(request, db)
        core.require_role(user, *sow_routes.PREP_ROLES)
        try:
            sow = create_small_project_sow(db, rev, user)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/sow/{sow.id}", 303)

    @app.get("/sow/{sid}", response_class=HTMLResponse)
    def sow_page_dispatch(
        sid: int, request: Request, db: Session = Depends(get_db)
    ):
        sow = sow_routes._sow_or_404(db, sid)
        if not is_small_project_sow(db, sow):
            return sow_page_previous(sid, request, db)
        user = core.current_user(request, db)
        return core.templates.TemplateResponse(
            "small_project_sow.html",
            _small_project_context(db, request, core, sow, user),
        )

    @app.post("/sow/{sid}/save")
    async def save_sow_dispatch(
        sid: int, request: Request, db: Session = Depends(get_db)
    ):
        sow = sow_routes._sow_or_404(db, sid)
        if not is_small_project_sow(db, sow):
            return await save_sow_previous(sid, request, db)
        user = core.current_user(request, db)
        core.require_role(user, *sow_routes.PREP_ROLES)
        rev = sow_routes._rev_for_sow(db, sow)
        if sow.status != "DRAFT":
            raise HTTPException(409, "Only a Draft SOW can be edited.")
        form = await request.form()
        save_small_project_sow(db, sow, rev, user, form)
        return RedirectResponse(f"/sow/{sid}", 303)

    @app.post("/sow/{sid}/finalize")
    def finalize_sow_dispatch(
        sid: int, request: Request, db: Session = Depends(get_db)
    ):
        sow = sow_routes._sow_or_404(db, sid)
        if not is_small_project_sow(db, sow):
            return finalize_previous(sid, request, db)
        user = core.current_user(request, db)
        core.require_role(user, *sow_routes.PREP_ROLES)
        rev = sow_routes._rev_for_sow(db, sow)
        if sow.status != "DRAFT":
            raise HTTPException(409, "Only a Draft SOW can be finalized.")
        errors = validate_small_project_finalize(db, sow, rev)
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
    def approve_sow_dispatch(
        sid: int, request: Request, db: Session = Depends(get_db)
    ):
        sow = sow_routes._sow_or_404(db, sid)
        if not is_small_project_sow(db, sow):
            return approve_previous(sid, request, db)
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
        digest, text, _ = small_project_content_hash_for(db, sow, rev)
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

    @app.post("/sow/{sid}/new-revision")
    def new_revision_dispatch(
        sid: int, request: Request, db: Session = Depends(get_db)
    ):
        source = sow_routes._sow_or_404(db, sid)
        if not is_small_project_sow(db, source):
            return new_revision_previous(sid, request, db)
        user = core.current_user(request, db)
        core.require_role(user, *sow_routes.PREP_ROLES)
        rev = sow_routes._rev_for_sow(db, source)
        try:
            dest = copy_rejected_small_project_sow(db, source, rev, user)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/sow/{dest.id}", 303)

    @app.get("/sow/{sid}/pdf")
    def sow_pdf_dispatch(
        sid: int, request: Request, db: Session = Depends(get_db)
    ):
        sow = sow_routes._sow_or_404(db, sid)
        if not is_small_project_sow(db, sow):
            return pdf_previous(sid, request, db)
        core.current_user(request, db)
        rev = sow_routes._rev_for_sow(db, sow)
        try:
            content = render_small_project_pdf(db, sow, rev)
            if sow.status != "APPROVED":
                from .sow_review_runtime import watermark_pdf
                content = watermark_pdf(content)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                    f'inline; filename="{rev.estimate.estimate_number}-{_product_for_revision(db, rev)}-Small-Project-SOW-R{sow.sow_revision_no}.pdf"'
            },
        )
