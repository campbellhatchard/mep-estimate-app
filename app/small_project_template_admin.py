from __future__ import annotations

from datetime import datetime

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_domain import _take_route
from .cip_models import PRODUCT_CIP, PRODUCT_MEP
from .cip_sow.core import CIP_TEMPLATE_LABEL, SOW_TEMPLATE_CIP_NET_NEW, validate_cip_template
from .database import get_db
from .models import User
from .services.audit import record
from .small_project_sow import (
    SMALL_PROJECT_TEMPLATE_KEYS,
    SOW_TEMPLATE_CIP_SMALL_PROJECT,
    SOW_TEMPLATE_MEP_SMALL_PROJECT,
    small_project_template_meta,
    validate_small_project_template,
)
from .sow_models import SOWTemplateVersion, SOW_TEMPLATE_MEP_NET_NEW
from . import sow_service

ALL_SOW_TEMPLATE_KEYS = (
    SOW_TEMPLATE_MEP_NET_NEW,
    SOW_TEMPLATE_CIP_NET_NEW,
    SOW_TEMPLATE_MEP_SMALL_PROJECT,
    SOW_TEMPLATE_CIP_SMALL_PROJECT,
)
TEMPLATE_ADMIN_ROLES = ("ADMIN", "TOOLS_ADMIN")


def _template_meta(template_key: str) -> tuple[str, str, str]:
    """Return label, product type and customer type for a controlled template family."""
    if template_key == SOW_TEMPLATE_MEP_NET_NEW:
        return "MEP New Client SOW", PRODUCT_MEP, "Net_New"
    if template_key == SOW_TEMPLATE_CIP_NET_NEW:
        return CIP_TEMPLATE_LABEL, PRODUCT_CIP, "Net_New"
    if template_key in SMALL_PROJECT_TEMPLATE_KEYS:
        meta = small_project_template_meta(template_key)
        return meta["label"], meta["product_type"], meta["customer_type"]
    raise ValueError(f"Unknown SOW template type: {template_key}")


def _validate_template(content: bytes, template_key: str) -> list[str]:
    if template_key == SOW_TEMPLATE_MEP_NET_NEW:
        return sow_service.validate_template(content)
    if template_key == SOW_TEMPLATE_CIP_NET_NEW:
        return validate_cip_template(content)
    if template_key in SMALL_PROJECT_TEMPLATE_KEYS:
        return validate_small_project_template(content)
    return ["Unknown SOW template type"]


def register_small_project_template_admin(app, core) -> None:
    """Extend the existing SOW Template Administration page to four families.

    This deliberately replaces only the admin GET/upload/activate handlers installed by
    the existing CIP SOW layer. Estimate/SOW workflow routes remain untouched. The common
    template download route continues to serve every SOWTemplateVersion by id.
    """
    _take_route(app, "/admin/sow-templates", "GET")
    _take_route(app, "/admin/sow-templates/upload", "POST")
    _take_route(app, "/admin/sow-templates/{tid}/activate", "POST")

    @app.get("/admin/sow-templates", response_class=HTMLResponse)
    def sow_templates_admin(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, *TEMPLATE_ADMIN_ROLES)

        def versions(template_key: str):
            return (
                db.query(SOWTemplateVersion)
                .filter(SOWTemplateVersion.template_key == template_key)
                .order_by(desc(SOWTemplateVersion.version_no))
                .all()
            )

        users = {u.id: u.username for u in db.query(User).all()}
        return core.templates.TemplateResponse(
            "sow_templates_dual.html",
            {
                "request": request,
                "user": user,
                "mep_versions": versions(SOW_TEMPLATE_MEP_NET_NEW),
                "cip_versions": versions(SOW_TEMPLATE_CIP_NET_NEW),
                "mep_sp_versions": versions(SOW_TEMPLATE_MEP_SMALL_PROJECT),
                "cip_sp_versions": versions(SOW_TEMPLATE_CIP_SMALL_PROJECT),
                "users": users,
            },
        )

    @app.post("/admin/sow-templates/upload")
    async def upload_sow_template(
        request: Request,
        file: UploadFile = File(...),
        change_reason: str = Form(...),
        template_key: str = Form(SOW_TEMPLATE_MEP_NET_NEW),
        db: Session = Depends(get_db),
    ):
        user = core.current_user(request, db)
        core.require_role(user, *TEMPLATE_ADMIN_ROLES)
        if template_key not in ALL_SOW_TEMPLATE_KEYS:
            raise HTTPException(400, "Unknown SOW template type.")
        if not file.filename or not file.filename.lower().endswith(".docx"):
            raise HTTPException(400, "Upload a .docx Word template.")
        reason = change_reason.strip()
        if not reason:
            raise HTTPException(400, "A change reason is required.")

        content = await file.read()
        missing = _validate_template(content, template_key)
        if missing:
            raise HTTPException(
                400,
                "Template validation failed. Missing required marker(s): "
                + ", ".join(missing),
            )

        latest = (
            db.query(SOWTemplateVersion)
            .filter(SOWTemplateVersion.template_key == template_key)
            .order_by(desc(SOWTemplateVersion.version_no))
            .first()
        )
        label, product_type, customer_type = _template_meta(template_key)
        row = SOWTemplateVersion(
            template_key=template_key,
            label=label,
            product_type=product_type,
            customer_type=customer_type,
            version_no=(latest.version_no + 1 if latest else 1),
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
    def activate_sow_template(
        tid: int, request: Request, db: Session = Depends(get_db)
    ):
        user = core.current_user(request, db)
        core.require_role(user, *TEMPLATE_ADMIN_ROLES)
        row = db.get(SOWTemplateVersion, tid)
        if not row:
            raise HTTPException(404, "SOW template version not found")
        if row.template_key not in ALL_SOW_TEMPLATE_KEYS:
            raise HTTPException(400, "Unknown SOW template type.")
        if row.status != "DRAFT":
            raise HTTPException(409, "Only a Draft SOW template can be activated.")
        missing = _validate_template(row.content, row.template_key)
        if missing:
            raise HTTPException(
                400, "Template validation failed: " + ", ".join(missing)
            )

        current = (
            db.query(SOWTemplateVersion)
            .filter(
                SOWTemplateVersion.template_key == row.template_key,
                SOWTemplateVersion.status == "ACTIVE",
            )
            .all()
        )
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