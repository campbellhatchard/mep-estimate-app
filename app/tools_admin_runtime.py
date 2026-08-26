from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from .cip_domain import _take_route, configuration_product
from .database import get_db
from .models import ConfigItem
from .services.audit import record
from .sow_models import SOWTemplateVersion


def _bool_form(form, key: str) -> bool:
    return str(form.get(key, "")).lower() in ("1", "true", "yes", "on")


def _data_redirect(version_id: int, key: str, db: Session) -> RedirectResponse:
    product = configuration_product(db, version_id)
    return RedirectResponse(
        f"/data?product={product}&version={version_id}&q={key}", 303
    )


def register_tools_admin_runtime(app, core) -> None:
    """Apply the Tools Admin authorization boundary to shared legacy routes.

    CIP configuration-version routes and the four-family SOW template administration
    routes are registered elsewhere. These three shared routes remain in the legacy
    application layer, so replace them here after all product/admin route registration.
    """
    _take_route(app, "/data/item/{item_id}", "POST")
    _take_route(app, "/data/item/new", "POST")
    _take_route(app, "/admin/sow-templates/{tid}/download", "GET")

    @app.post("/data/item/{item_id}")
    async def update_config_item(
        item_id: int, request: Request, db: Session = Depends(get_db)
    ):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "TOOLS_ADMIN")
        item = db.get(ConfigItem, item_id)
        if not item:
            raise HTTPException(404, "Calculation Data element not found")
        version = db.get(core.ConfigurationVersion, item.config_version_id)
        if not version or version.status != "DRAFT":
            raise HTTPException(409, "Only draft configuration versions can be edited")

        form = await request.form()
        old = f"{item.label}|{item.value_number}|{item.value_text}|{item.active}"
        item.label = str(form.get("label", item.label)).strip()
        item.description = str(form.get("description", item.description or "")).strip()
        raw = str(form.get("value_number", "")).strip()
        item.value_number = float(raw) if raw else None
        item.value_text = str(form.get("value_text", item.value_text or "")).strip() or None
        item.active = _bool_form(form, "active")
        reason = str(form.get("reason", "")).strip()
        if not reason:
            raise HTTPException(400, "Change reason is required")

        record(
            db,
            event_type="CONFIG_VALUE_CHANGED",
            user_id=user.id,
            config_version_id=version.id,
            field_name=item.key,
            old_value=old,
            new_value=f"{item.label}|{item.value_number}|{item.value_text}|{item.active}",
            reason=reason,
        )
        db.commit()
        return _data_redirect(version.id, item.key, db)

    @app.post("/data/item/new")
    async def new_config_item(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "TOOLS_ADMIN")
        form = await request.form()
        try:
            version_id = int(form.get("version_id"))
        except (TypeError, ValueError):
            raise HTTPException(400, "A Draft configuration version is required")
        version = db.get(core.ConfigurationVersion, version_id)
        if not version or version.status != "DRAFT":
            raise HTTPException(409, "Add items to a draft configuration")

        category = str(form.get("category", "")).strip()
        label = str(form.get("label", "")).strip()
        key = str(form.get("key", "")).strip() or core.slug(label)
        reason = str(form.get("reason", "")).strip()
        if not category or not label:
            raise HTTPException(400, "Category and label are required")
        if not reason:
            raise HTTPException(400, "Change reason is required")
        raw = str(form.get("value_number", "")).strip()
        number = float(raw) if raw else None
        item = ConfigItem(
            config_version_id=version_id,
            category=category,
            key=key,
            label=label,
            value_number=number,
            value_text=str(form.get("value_text", "")).strip() or None,
            value_type=str(form.get("value_type", "text")),
            parent_key=str(form.get("parent_key", "")).strip() or None,
            active=True,
            sort_order=999,
        )
        db.add(item)
        record(
            db,
            event_type="CONFIG_ITEM_ADDED",
            user_id=user.id,
            config_version_id=version_id,
            field_name=key,
            new_value=label,
            reason=reason,
        )
        db.commit()
        return _data_redirect(version_id, key, db)

    @app.get("/admin/sow-templates/{tid}/download")
    def download_sow_template(
        tid: int, request: Request, db: Session = Depends(get_db)
    ):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "TOOLS_ADMIN")
        row = db.get(SOWTemplateVersion, tid)
        if not row:
            raise HTTPException(404, "SOW template version not found")
        return Response(
            row.content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{row.filename}"'},
        )
