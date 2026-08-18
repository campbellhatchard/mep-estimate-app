from __future__ import annotations

import json
from datetime import datetime

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_domain import revision_product
from .cip_models import PRODUCT_MEP
from .database import SessionLocal, get_db
from .models import EstimateRevision, User, UserRole
from .services.audit import record
from .sow_models import SOW, SOWDevice, SOWHypercareLocation, SOWTemplateVersion, SOW_TEMPLATE_MEP_NET_NEW
from .sow_service import (
    AGREEMENT_TYPES, DEVICE_TYPES, INVOICE_FREQUENCIES, SUPPORT_TYPES,
    content_hash_for, copy_rejected_sow, create_sow, go_live_support_hours,
    latest_sow, render_pdf, seed_initial_sow_template, sha256_bytes,
    sow_eligible, validate_finalize, validate_template, verify_approved_content,
)

PREP_ROLES = ("ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")


def _sow_or_404(db: Session, sid: int) -> SOW:
    sow = db.get(SOW, sid)
    if not sow: raise HTTPException(404, "SOW not found")
    return sow


def _rev_for_sow(db: Session, sow: SOW) -> EstimateRevision:
    rev = db.get(EstimateRevision, sow.estimate_revision_id)
    if not rev: raise HTTPException(404, "Estimate revision not found")
    return rev


def _active_sow_approvers(db: Session) -> list[User]:
    return (
        db.query(User)
        .join(UserRole, UserRole.user_id == User.id)
        .filter(User.active.is_(True), UserRole.role == "SOW_APPROVER")
        .order_by(User.username_normalized)
        .all()
    )


def _audit_field(db, user, rev, sow, field, old, new):
    if old == new: return
    record(db, event_type="SOW_FIELD_CHANGED", user_id=user.id, estimate_id=rev.estimate_id,
           revision_id=rev.id, field_name=f"SOW:{sow.id}:{field}", old_value=old, new_value=new)


def _as_int(v, default=0):
    try: return int(str(v).strip())
    except Exception: return default


def _as_float(v, default=0.0):
    try: return float(str(v).strip())
    except Exception: return default


def _replace_child_rows(db: Session, sow: SOW, form, user, rev):
    old_h = json.dumps([[x.description, x.country, x.support_type, float(x.allocated_hours or 0)] for x in sow.hypercare_locations], ensure_ascii=False)
    db.query(SOWHypercareLocation).filter(SOWHypercareLocation.sow_id == sow.id).delete(synchronize_session=False)
    descs = form.getlist("hypercare_description"); countries = form.getlist("hypercare_country")
    support = form.getlist("hypercare_support_type"); hours = form.getlist("hypercare_hours")
    new_h = []
    for idx in range(max(len(descs), len(countries), len(support), len(hours))):
        d = str(descs[idx] if idx < len(descs) else "").strip()
        c = str(countries[idx] if idx < len(countries) else "").strip()
        st = str(support[idx] if idx < len(support) else "Remote").strip() or "Remote"
        h = _as_float(hours[idx] if idx < len(hours) else 0)
        if not d and not c and h == 0: continue
        row = SOWHypercareLocation(sow_id=sow.id, description=d, country=c,
                                   support_type=st if st in SUPPORT_TYPES else "Remote",
                                   allocated_hours=h, sort_order=idx)
        db.add(row); new_h.append([d, c, row.support_type, h])
    _audit_field(db, user, rev, sow, "HYPERCARE_LOCATIONS", old_h, json.dumps(new_h, ensure_ascii=False))

    old_d = json.dumps([[x.device_type, x.make_model, x.os_version] for x in sow.devices], ensure_ascii=False)
    db.query(SOWDevice).filter(SOWDevice.sow_id == sow.id).delete(synchronize_session=False)
    types = form.getlist("device_type"); models = form.getlist("device_make_model"); oses = form.getlist("device_os_version")
    new_d = []
    for idx in range(max(len(types), len(models), len(oses))):
        typ = str(types[idx] if idx < len(types) else "Handheld Unit").strip() or "Handheld Unit"
        model = str(models[idx] if idx < len(models) else "").strip(); osv = str(oses[idx] if idx < len(oses) else "").strip()
        if not model: continue
        row = SOWDevice(sow_id=sow.id, device_type=typ if typ in DEVICE_TYPES else "Other", make_model=model, os_version=osv, sort_order=idx)
        db.add(row); new_d.append([row.device_type, model, osv])
    _audit_field(db, user, rev, sow, "DEVICES", old_d, json.dumps(new_d, ensure_ascii=False))


def _sow_context(db: Session, request: Request, core, sow: SOW, user):
    rev = _rev_for_sow(db, sow)
    support_hours = go_live_support_hours(db, rev)
    allocated = sum(float(x.allocated_hours or 0) for x in sow.hypercare_locations)
    history = db.query(SOW).filter(SOW.estimate_revision_id == rev.id).order_by(desc(SOW.sow_revision_no)).all()
    users = {u.id: u.username for u in db.query(User).all()}
    return {
        "request": request, "user": user, "sow": sow, "rev": rev, "estimate": rev.estimate,
        "active_tab": "sow", "readonly": sow.status != "DRAFT", "history": history,
        "approvers": _active_sow_approvers(db), "users": users,
        "agreement_types": AGREEMENT_TYPES, "invoice_frequencies": INVOICE_FREQUENCIES,
        "support_types": SUPPORT_TYPES, "device_types": DEVICE_TYPES,
        "go_live_support_hours": support_hours, "allocated_hours": allocated,
        "unallocated_hours": support_hours - allocated,
        "can_approve": user.has_role("SOW_APPROVER") and sow.status == "PENDING_APPROVAL" and sow.approver_id == user.id,
        "can_prepare": user.has_role(*PREP_ROLES),
    }


def register_sow(app, core):
    @app.on_event("startup")
    def seed_sow_template_on_startup():
        db = SessionLocal()
        try: seed_initial_sow_template(db)
        finally: db.close()

    @app.get("/estimate/{rid}/sow", response_class=HTMLResponse)
    def estimate_sow(rid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) != PRODUCT_MEP: raise HTTPException(409, "A CIP SOW template has not been configured yet.")
        sow = latest_sow(db, rid)
        if sow: return RedirectResponse(f"/sow/{sow.id}", 303)
        return core.templates.TemplateResponse("sow_empty.html", {"request": request, "user": user, "rev": rev,
            "estimate": rev.estimate, "active_tab": "sow", "eligible": sow_eligible(rev), "product_type": PRODUCT_MEP})

    @app.post("/estimate/{rid}/sow/create")
    def create_estimate_sow(rid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *PREP_ROLES)
        rev = core.revision_or_404(db, rid)
        if revision_product(db, rev) != PRODUCT_MEP: raise HTTPException(409, "CIP SOW is not available yet.")
        try: sow = create_sow(db, rev, user)
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/sow/{sow.id}", 303)

    @app.get("/sow/{sid}", response_class=HTMLResponse)
    def sow_page(sid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); sow = _sow_or_404(db, sid)
        return core.templates.TemplateResponse("sow.html", _sow_context(db, request, core, sow, user))

    @app.post("/sow/{sid}/save")
    async def save_sow(sid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *PREP_ROLES)
        sow = _sow_or_404(db, sid); rev = _rev_for_sow(db, sow)
        if sow.status != "DRAFT": raise HTTPException(409, "Only a Draft SOW can be edited.")
        form = await request.form()
        fields = {
            "agreement_type": str(form.get("agreement_type", sow.agreement_type)).strip(),
            "invoice_frequency": str(form.get("invoice_frequency", sow.invoice_frequency)).strip(),
            "project_objective": str(form.get("project_objective", sow.project_objective)).strip(),
            "rest_api_required": str(form.get("rest_api_required", "")).lower() in ("1", "true", "yes", "on"),
            "barcode_printer_count": _as_int(form.get("barcode_printer_count", sow.barcode_printer_count)),
            "erp_version": str(form.get("erp_version", sow.erp_version)).strip(),
            "erp_base_code_version": str(form.get("erp_base_code_version", sow.erp_base_code_version)).strip(),
            "erp_tools_release": str(form.get("erp_tools_release", sow.erp_tools_release)).strip(),
            "erp_os_version": str(form.get("erp_os_version", sow.erp_os_version)).strip(),
            "erp_database_version": str(form.get("erp_database_version", sow.erp_database_version)).strip(),
            "mep_product_version": str(form.get("mep_product_version", sow.mep_product_version)).strip(),
            "epp_product_version": str(form.get("epp_product_version", sow.epp_product_version)).strip(),
            "print_methods": str(form.get("print_methods", sow.print_methods)).strip(),
            "erp_deployment_model": str(form.get("erp_deployment_model", sow.erp_deployment_model)).strip(),
        }
        for field, value in fields.items():
            old = getattr(sow, field); _audit_field(db, user, rev, sow, field, old, value); setattr(sow, field, value)
        _replace_child_rows(db, sow, form, user, rev)
        db.commit(); return RedirectResponse(f"/sow/{sid}", 303)

    @app.post("/sow/{sid}/finalize")
    def finalize_sow(sid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *PREP_ROLES)
        sow = _sow_or_404(db, sid); rev = _rev_for_sow(db, sow)
        if sow.status != "DRAFT": raise HTTPException(409, "Only a Draft SOW can be finalized.")
        errors = validate_finalize(db, sow, rev)
        if errors: raise HTTPException(400, " ".join(errors))
        sow.status = "FINALIZED"; sow.finalized_by = user.id; sow.finalized_at = datetime.utcnow()
        record(db, event_type="SOW_FINALIZED", user_id=user.id, estimate_id=rev.estimate_id,
               revision_id=rev.id, field_name=f"SOW:{sow.id}", old_value="DRAFT", new_value="FINALIZED")
        db.commit(); return RedirectResponse(f"/sow/{sid}", 303)

    @app.post("/sow/{sid}/return-draft")
    def return_sow_to_draft(sid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *PREP_ROLES)
        sow = _sow_or_404(db, sid); rev = _rev_for_sow(db, sow)
        if sow.status != "FINALIZED": raise HTTPException(409, "Only a Finalized SOW can be returned to Draft before submission.")
        sow.status = "DRAFT"; sow.finalized_by = None; sow.finalized_at = None
        record(db, event_type="SOW_RETURNED_TO_DRAFT", user_id=user.id, estimate_id=rev.estimate_id,
               revision_id=rev.id, field_name=f"SOW:{sow.id}", old_value="FINALIZED", new_value="DRAFT")
        db.commit(); return RedirectResponse(f"/sow/{sid}", 303)

    @app.post("/sow/{sid}/send-approval")
    async def send_approval(sid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *PREP_ROLES)
        sow = _sow_or_404(db, sid); rev = _rev_for_sow(db, sow)
        if sow.status != "FINALIZED": raise HTTPException(409, "Finalize the SOW before sending it for approval.")
        form = await request.form(); approver_id = _as_int(form.get("approver_id")); approver = db.get(User, approver_id)
        if not approver or not approver.active or not approver.has_role("SOW_APPROVER"): raise HTTPException(400, "Select an active SOW Approver.")
        if approver.id == user.id: raise HTTPException(409, "The SOW submitter cannot approve their own SOW.")
        sow.status = "PENDING_APPROVAL"; sow.submitted_by = user.id; sow.submitted_at = datetime.utcnow(); sow.approver_id = approver.id
        record(db, event_type="SOW_SENT_FOR_APPROVAL", user_id=user.id, estimate_id=rev.estimate_id,
               revision_id=rev.id, field_name=f"SOW:{sow.id}", old_value="FINALIZED", new_value="PENDING_APPROVAL",
               reason=f"Assigned to {approver.username}")
        db.commit(); return RedirectResponse(f"/sow/{sid}", 303)

    @app.post("/sow/{sid}/approve")
    def approve_sow(sid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        if not user.has_role("SOW_APPROVER"): raise HTTPException(403, "SOW Approver role required")
        sow = _sow_or_404(db, sid); rev = _rev_for_sow(db, sow)
        if sow.status != "PENDING_APPROVAL": raise HTTPException(409, "Only a SOW Pending Approval can be approved.")
        if sow.approver_id != user.id: raise HTTPException(403, "This SOW is assigned to another approver.")
        if sow.submitted_by == user.id: raise HTTPException(409, "The SOW submitter cannot approve their own SOW.")
        h, text, _ = content_hash_for(db, sow, rev)
        sow.status = "APPROVED"; sow.approved_by = user.id; sow.approved_at = datetime.utcnow(); sow.content_hash = h; sow.approved_text_snapshot = text
        record(db, event_type="SOW_APPROVED", user_id=user.id, estimate_id=rev.estimate_id,
               revision_id=rev.id, field_name=f"SOW:{sow.id}", old_value="PENDING_APPROVAL", new_value="APPROVED", reason=f"Content hash {h}")
        db.commit(); return RedirectResponse(f"/sow/{sid}", 303)

    @app.post("/sow/{sid}/reject")
    async def reject_sow(sid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        if not user.has_role("SOW_APPROVER"): raise HTTPException(403, "SOW Approver role required")
        sow = _sow_or_404(db, sid); rev = _rev_for_sow(db, sow)
        if sow.status != "PENDING_APPROVAL": raise HTTPException(409, "Only a SOW Pending Approval can be rejected.")
        if sow.approver_id != user.id: raise HTTPException(403, "This SOW is assigned to another approver.")
        form = await request.form(); reason = str(form.get("reason", "")).strip()
        if not reason: raise HTTPException(400, "A rejection reason is required.")
        sow.status = "REJECTED"; sow.rejected_by = user.id; sow.rejected_at = datetime.utcnow(); sow.rejection_reason = reason
        record(db, event_type="SOW_REJECTED", user_id=user.id, estimate_id=rev.estimate_id,
               revision_id=rev.id, field_name=f"SOW:{sow.id}", old_value="PENDING_APPROVAL", new_value="REJECTED", reason=reason)
        db.commit(); return RedirectResponse(f"/sow/{sid}", 303)

    @app.post("/sow/{sid}/new-revision")
    def new_sow_revision(sid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *PREP_ROLES)
        source = _sow_or_404(db, sid); rev = _rev_for_sow(db, source)
        try: dest = copy_rejected_sow(db, source, rev, user)
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f"/sow/{dest.id}", 303)

    @app.get("/sow/{sid}/pdf")
    def sow_pdf(sid: int, request: Request, db: Session = Depends(get_db)):
        core.current_user(request, db); sow = _sow_or_404(db, sid); rev = _rev_for_sow(db, sow)
        try: content = render_pdf(db, sow, rev)
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc
        return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{rev.estimate.estimate_number}-SOW-R{sow.sow_revision_no}.pdf"'})

    @app.get("/sow/{sid}/docx")
    def sow_docx(sid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); sow = _sow_or_404(db, sid); rev = _rev_for_sow(db, sow)
        if sow.status != "APPROVED": raise HTTPException(409, "The Word SOW is available only after SOW approval.")
        try: content = verify_approved_content(db, sow, rev)
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc
        record(db, event_type="SOW_DOCX_GENERATED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id, field_name=f"SOW:{sow.id}")
        db.commit()
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{rev.estimate.estimate_number}-SOW-R{sow.sow_revision_no}.docx"'})

    @app.get("/approvals", response_class=HTMLResponse)
    def approvals(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); estimate_rows = []; sow_rows = []
        if user.has_role("ADMIN", "APPROVER"):
            estimate_rows = db.query(EstimateRevision).filter(EstimateRevision.status == "REVIEW").order_by(EstimateRevision.updated_at).all()
        if user.has_role("SOW_APPROVER"):
            pending = db.query(SOW).filter(SOW.status == "PENDING_APPROVAL", SOW.approver_id == user.id).order_by(SOW.submitted_at).all()
            sow_rows = [{"sow": s, "rev": db.get(EstimateRevision, s.estimate_revision_id)} for s in pending]
        return core.templates.TemplateResponse("approvals.html", {"request": request, "user": user, "estimate_rows": estimate_rows, "sow_rows": sow_rows})

    @app.get("/admin/sow-templates", response_class=HTMLResponse)
    def sow_templates_admin(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, "ADMIN")
        versions = db.query(SOWTemplateVersion).filter(SOWTemplateVersion.template_key == SOW_TEMPLATE_MEP_NET_NEW).order_by(desc(SOWTemplateVersion.version_no)).all()
        users = {u.id: u.username for u in db.query(User).all()}
        return core.templates.TemplateResponse("sow_templates.html", {"request": request, "user": user, "versions": versions, "users": users})

    @app.post("/admin/sow-templates/upload")
    async def upload_sow_template(request: Request, file: UploadFile = File(...), change_reason: str = Form(...), db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, "ADMIN")
        if not file.filename or not file.filename.lower().endswith(".docx"): raise HTTPException(400, "Upload a .docx Word template.")
        reason = change_reason.strip()
        if not reason: raise HTTPException(400, "A change reason is required.")
        content = await file.read(); missing = validate_template(content)
        if missing: raise HTTPException(400, "Template validation failed. Missing required marker(s): " + ", ".join(missing))
        maxv = db.query(SOWTemplateVersion).filter(SOWTemplateVersion.template_key == SOW_TEMPLATE_MEP_NET_NEW).order_by(desc(SOWTemplateVersion.version_no)).first()
        row = SOWTemplateVersion(template_key=SOW_TEMPLATE_MEP_NET_NEW, label="MEP New Client SOW", product_type=PRODUCT_MEP,
            customer_type="Net_New", version_no=(maxv.version_no + 1 if maxv else 1), status="DRAFT", filename=file.filename,
            content=content, content_sha256=sha256_bytes(content), change_reason=reason, created_by=user.id)
        db.add(row); db.flush()
        record(db, event_type="SOW_TEMPLATE_UPLOADED", user_id=user.id, field_name=f"SOW_TEMPLATE:{row.template_key}:{row.version_no}", new_value=row.filename, reason=reason)
        db.commit(); return RedirectResponse("/admin/sow-templates", 303)

    @app.post("/admin/sow-templates/{tid}/activate")
    def activate_sow_template(tid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, "ADMIN")
        row = db.get(SOWTemplateVersion, tid)
        if not row: raise HTTPException(404, "SOW template version not found")
        if row.status != "DRAFT": raise HTTPException(409, "Only a Draft SOW template can be activated.")
        missing = validate_template(row.content)
        if missing: raise HTTPException(400, "Template validation failed: " + ", ".join(missing))
        current = db.query(SOWTemplateVersion).filter(SOWTemplateVersion.template_key == row.template_key, SOWTemplateVersion.status == "ACTIVE").all(); now = datetime.utcnow()
        for old in current:
            old.status = "RETIRED"; old.retired_at = now
            record(db, event_type="SOW_TEMPLATE_RETIRED", user_id=user.id, field_name=f"SOW_TEMPLATE:{old.template_key}:{old.version_no}", old_value="ACTIVE", new_value="RETIRED", reason=f"Superseded by template v{row.version_no}")
        row.status = "ACTIVE"; row.activated_by = user.id; row.activated_at = now
        record(db, event_type="SOW_TEMPLATE_ACTIVATED", user_id=user.id, field_name=f"SOW_TEMPLATE:{row.template_key}:{row.version_no}", old_value="DRAFT", new_value="ACTIVE", reason=row.change_reason)
        db.commit(); return RedirectResponse("/admin/sow-templates", 303)

    @app.get("/admin/sow-templates/{tid}/download")
    def download_sow_template(tid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, "ADMIN")
        row = db.get(SOWTemplateVersion, tid)
        if not row: raise HTTPException(404, "SOW template version not found")
        return Response(row.content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="{row.filename}"'})
