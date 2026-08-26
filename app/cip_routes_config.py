import re

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_domain import _int, _take_route, active_config_for_product, configuration_product
from .cip_models import ConfigurationProduct, PRODUCT_CIP, PRODUCT_MEP
from .database import get_db
from .models import AuditEvent, ConfigItem, ConfigurationVersion, User
from .runtime_time import utc_now
from .services.audit import record

CONFIG_PREPARE_ROLES = ("ADMIN", "TOOLS_ADMIN")
CONFIG_REVIEW_ROLES = ("ADMIN", "TOOLS_ADMIN")
CONFIG_ACTIVATE_ROLES = ("ADMIN", "TOOLS_ADMIN")
PREPARATION_EVENT_TYPES = (
    "CONFIG_VERSION_CREATED",
    "CONFIG_VERSION_REOPENED",
    "CONFIG_VALUE_CHANGED",
    "CONFIG_ITEM_ADDED",
    "CIP_RELEASE_ADDED",
)


def _next_config_version_name(db: Session, product: str) -> str:
    """Return a readable, unique draft name even for multiple creations in one minute."""
    stamp = utc_now().strftime("%Y.%m.%d.%H%M")
    base_name = f"{product} Estimate Model {stamp}"
    name = base_name
    suffix = 2
    while db.query(ConfigurationVersion.id).filter(ConfigurationVersion.name == name).first():
        name = f"{base_name}-{suffix:02d}"
        suffix += 1
    return name


def _prepared_by_ids(db: Session, version: ConfigurationVersion) -> set[int]:
    """Return every user who materially participated in preparing this version.

    Separation of duties is based on actual preparation participation, not merely the
    creator. A reviewer therefore cannot edit a draft and later approve it under a
    different role assignment.
    """
    ids: set[int] = set()
    if version.created_by:
        ids.add(int(version.created_by))
    if version.submitted_by:
        ids.add(int(version.submitted_by))
    rows = (
        db.query(AuditEvent.user_id)
        .filter(
            AuditEvent.config_version_id == version.id,
            AuditEvent.event_type.in_(PREPARATION_EVENT_TYPES),
            AuditEvent.user_id.isnot(None),
        )
        .all()
    )
    ids.update(int(row[0]) for row in rows if row[0] is not None)
    return ids


def _governance_context(db: Session, version: ConfigurationVersion, user: User) -> dict:
    prepared_ids = _prepared_by_ids(db, version)
    actor_ids = {
        value
        for value in (
            version.created_by,
            version.submitted_by,
            version.reviewed_by,
            version.approved_by,
            *prepared_ids,
        )
        if value
    }
    usernames = {}
    if actor_ids:
        usernames = {
            row.id: row.username
            for row in db.query(User).filter(User.id.in_(actor_ids)).all()
        }
    prepared_by_names = [
        usernames.get(uid, f"User {uid}") for uid in sorted(prepared_ids)
    ]
    return {
        "can_prepare_config": user.has_role(*CONFIG_PREPARE_ROLES),
        "can_review_config": user.has_role(*CONFIG_REVIEW_ROLES)
        and user.id not in prepared_ids,
        "can_activate_config": user.has_role(*CONFIG_ACTIVATE_ROLES),
        "prepared_by_names": prepared_by_names,
        "governance_usernames": usernames,
    }


def register_config_routes(app, core):
    # Replace the legacy generic configuration handlers so MEP and CIP use one
    # product-aware authorization boundary for all controlled mutations.
    _take_route(app, "/data", "GET")
    _take_route(app, "/data/version/new", "POST")
    _take_route(app, "/data/version/{vid}/activate", "POST")
    _take_route(app, "/data/item/{item_id}", "POST")
    _take_route(app, "/data/item/new", "POST")

    @app.get("/data", response_class=HTMLResponse)
    def data_page(request: Request, version: int | None = None, product: str = PRODUCT_MEP, q: str = "", category: str = "", db: Session = Depends(get_db)):
        user = core.current_user(request, db); product = product.upper() if product.upper() in (PRODUCT_MEP, PRODUCT_CIP) else PRODUCT_MEP
        if version:
            selected = db.get(ConfigurationVersion, version)
            if not selected: raise HTTPException(404, "Configuration version not found")
            product = configuration_product(db, selected.id)
        else: selected = active_config_for_product(db, product)
        versions = [x for x in db.query(ConfigurationVersion).order_by(desc(ConfigurationVersion.id)).all() if configuration_product(db, x.id) == product]
        query = db.query(ConfigItem).filter(ConfigItem.config_version_id == selected.id)
        if q: query = query.filter((ConfigItem.label.ilike(f"%{q}%")) | (ConfigItem.key.ilike(f"%{q}%")) | (ConfigItem.description.ilike(f"%{q}%")))
        if category: query = query.filter(ConfigItem.category == category)
        items = query.order_by(ConfigItem.category, ConfigItem.sort_order, ConfigItem.label).all()
        categories = [x[0] for x in db.query(ConfigItem.category).filter(ConfigItem.config_version_id == selected.id).distinct().order_by(ConfigItem.category).all()]
        ctx = {"request": request, "user": user, "versions": versions, "version": selected, "items": items, "categories": categories, "q": q, "category": category, "product_type": product}
        ctx.update(_governance_context(db, selected, user))
        return core.templates.TemplateResponse("data.html", ctx)

    @app.post("/data/version/new")
    async def new_config_version(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *CONFIG_PREPARE_ROLES); form = await request.form(); product = str(form.get("product", PRODUCT_MEP)).upper()
        if product not in (PRODUCT_MEP, PRODUCT_CIP): raise HTTPException(400, "Unknown configuration product")
        src = active_config_for_product(db, product)
        version = ConfigurationVersion(name=_next_config_version_name(db, product), status="DRAFT", created_by=user.id, change_reason=f"Draft {product} configuration cloned from active model", approval_status="DRAFT")
        db.add(version); db.flush(); db.add(ConfigurationProduct(config_version_id=version.id, product_type=product))
        for item in db.query(ConfigItem).filter(ConfigItem.config_version_id == src.id):
            db.add(ConfigItem(config_version_id=version.id, category=item.category, key=item.key, label=item.label, value_number=item.value_number, value_text=item.value_text, value_type=item.value_type, unit=item.unit, description=item.description, parent_key=item.parent_key, sort_order=item.sort_order, active=item.active))
        record(db, event_type="CONFIG_VERSION_CREATED", user_id=user.id, config_version_id=version.id, old_value=src.name, new_value=version.name); db.commit()
        return RedirectResponse(f"/data?product={product}&version={version.id}", 303)

    @app.post("/data/version/{vid}/submit")
    def submit_config(vid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *CONFIG_PREPARE_ROLES); version = db.get(ConfigurationVersion, vid)
        if not version or version.status != "DRAFT": raise HTTPException(409, "Only a draft configuration can be submitted for review")
        now = utc_now()
        version.status = "PENDING_REVIEW"
        version.approval_status = "PENDING_REVIEW"
        version.submitted_by = user.id
        version.submitted_at = now
        version.reviewed_by = None
        version.reviewed_at = None
        version.approved_by = None
        version.approved_at = None
        record(db, event_type="CONFIG_VERSION_SUBMITTED", user_id=user.id, config_version_id=version.id, old_value="DRAFT", new_value="PENDING_REVIEW", reason=version.change_reason)
        db.commit()
        product = configuration_product(db, version.id)
        return RedirectResponse(f"/data?product={product}&version={version.id}", 303)

    @app.post("/data/version/{vid}/review")
    async def review_config(vid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *CONFIG_REVIEW_ROLES); version = db.get(ConfigurationVersion, vid)
        if not version or version.status != "PENDING_REVIEW": raise HTTPException(409, "Only a configuration pending review can be approved or rejected")
        if user.id in _prepared_by_ids(db, version):
            raise HTTPException(409, "Separation of duties prevents a configuration preparer or submitter from reviewing this version")
        form = await request.form(); action = str(form.get("action", "")).strip().lower(); reason = str(form.get("reason", "")).strip()
        if action not in ("approve", "reject"): raise HTTPException(400, "Review action must be approve or reject")
        if not reason: raise HTTPException(400, "Review reason is required")
        now = utc_now(); version.reviewed_by = user.id; version.reviewed_at = now
        if action == "approve":
            version.status = "APPROVED"; version.approval_status = "APPROVED"; version.approved_by = user.id; version.approved_at = now
            event_type = "CONFIG_VERSION_APPROVED"; new_value = "APPROVED"
        else:
            version.status = "REJECTED"; version.approval_status = "REJECTED"; version.approved_by = None; version.approved_at = None
            event_type = "CONFIG_VERSION_REJECTED"; new_value = "REJECTED"
        record(db, event_type=event_type, user_id=user.id, config_version_id=version.id, old_value="PENDING_REVIEW", new_value=new_value, reason=reason)
        db.commit()
        product = configuration_product(db, version.id)
        return RedirectResponse(f"/data?product={product}&version={version.id}", 303)

    @app.post("/data/version/{vid}/reopen")
    async def reopen_config(vid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *CONFIG_PREPARE_ROLES); version = db.get(ConfigurationVersion, vid)
        if not version or version.status != "REJECTED": raise HTTPException(409, "Only a rejected configuration can be reopened")
        form = await request.form(); reason = str(form.get("reason", "")).strip()
        if not reason: raise HTTPException(400, "Reopen reason is required")
        version.status = "DRAFT"; version.approval_status = "DRAFT"
        version.submitted_by = None; version.submitted_at = None
        version.reviewed_by = None; version.reviewed_at = None
        version.approved_by = None; version.approved_at = None
        record(db, event_type="CONFIG_VERSION_REOPENED", user_id=user.id, config_version_id=version.id, old_value="REJECTED", new_value="DRAFT", reason=reason)
        db.commit()
        product = configuration_product(db, version.id)
        return RedirectResponse(f"/data?product={product}&version={version.id}", 303)

    @app.post("/data/version/{vid}/activate")
    def activate_config(vid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *CONFIG_ACTIVATE_ROLES); version = db.get(ConfigurationVersion, vid)
        if not version or version.status != "APPROVED": raise HTTPException(409, "Only an independently approved configuration can be activated")
        prepared_by = _prepared_by_ids(db, version)
        if not version.approved_by or not version.approved_at or version.approved_by in prepared_by:
            raise HTTPException(409, "Configuration approval evidence does not satisfy separation of duties")
        product = configuration_product(db, version.id)
        for active in db.query(ConfigurationVersion).filter(ConfigurationVersion.status == "ACTIVE").all():
            if active.id != version.id and configuration_product(db, active.id) == product: active.status = "RETIRED"
        version.status = "ACTIVE"; version.activated_at = utc_now(); version.approval_status = "ACTIVE"
        record(db, event_type="CONFIG_VERSION_ACTIVATED", user_id=user.id, config_version_id=version.id, old_value="APPROVED", new_value=version.name, reason=version.change_reason); db.commit()
        return RedirectResponse(f"/data?product={product}&version={version.id}", 303)

    @app.post("/data/item/{item_id}")
    async def update_config_item(item_id: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *CONFIG_PREPARE_ROLES); item = db.get(ConfigItem, item_id)
        if not item: raise HTTPException(404, "Calculation Data element not found")
        version = db.get(ConfigurationVersion, item.config_version_id)
        if not version or version.status != "DRAFT": raise HTTPException(409, "Only draft configuration versions can be edited")
        form = await request.form(); old = f"{item.label}|{item.value_number}|{item.value_text}|{item.active}"
        item.label = str(form.get("label", item.label)); item.description = str(form.get("description", item.description or ""))
        raw = str(form.get("value_number", "")).strip(); item.value_number = float(raw) if raw else None
        item.value_text = str(form.get("value_text", item.value_text or "")) or None; item.active = core.bool_form(form, "active")
        reason = str(form.get("reason", "")).strip()
        if not reason: raise HTTPException(400, "Change reason is required")
        record(db, event_type="CONFIG_VALUE_CHANGED", user_id=user.id, config_version_id=version.id, field_name=item.key, old_value=old, new_value=f"{item.label}|{item.value_number}|{item.value_text}|{item.active}", reason=reason); db.commit()
        product = configuration_product(db, version.id)
        return RedirectResponse(f"/data?product={product}&version={version.id}&q={item.key}", 303)

    @app.post("/data/item/new")
    async def new_config_item(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *CONFIG_PREPARE_ROLES); form = await request.form(); vid = _int(form, "version_id", 0); version = db.get(ConfigurationVersion, vid)
        if not version or version.status != "DRAFT": raise HTTPException(409, "Add items to a draft configuration")
        category = str(form.get("category", "")).strip(); label = str(form.get("label", "")).strip(); key = str(form.get("key", "")).strip() or core.slug(label)
        if not category or not label: raise HTTPException(400, "Category and label are required")
        reason = str(form.get("reason", "")).strip()
        if not reason: raise HTTPException(400, "Change reason is required")
        raw = str(form.get("value_number", "")).strip(); number = float(raw) if raw else None
        item = ConfigItem(config_version_id=vid, category=category, key=key, label=label, value_number=number, value_text=str(form.get("value_text", "")).strip() or None, value_type=str(form.get("value_type", "text")), parent_key=str(form.get("parent_key", "")).strip() or None, active=True, sort_order=999)
        db.add(item); record(db, event_type="CONFIG_ITEM_ADDED", user_id=user.id, config_version_id=vid, field_name=key, new_value=label, reason=reason); db.commit()
        product = configuration_product(db, vid)
        return RedirectResponse(f"/data?product={product}&version={vid}&q={key}", 303)

    @app.post("/cip/data/release/new")
    async def add_cip_release(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, *CONFIG_PREPARE_ROLES); form = await request.form(); vid = _int(form, "version_id", 0); version = db.get(ConfigurationVersion, vid)
        if not version or version.status != "DRAFT" or configuration_product(db, vid) != PRODUCT_CIP: raise HTTPException(409, "Add a CIP release only to a draft CIP configuration.")
        label = str(form.get("label", "")).strip(); reason = str(form.get("reason", "")).strip(); match = re.fullmatch(r"Release\s+(\d+)\.(\d+)", label, flags=re.IGNORECASE)
        if not match: raise HTTPException(400, "Release must use the format 'Release 26.3'.")
        if not reason: raise HTTPException(400, "Change reason is required.")
        release_key = f"RELEASE_{match.group(1)}_{match.group(2)}"; rank = int(match.group(1)) * 10 + int(match.group(2))
        if db.query(ConfigItem).filter(ConfigItem.config_version_id == vid, ConfigItem.category == "CIP Release", ConfigItem.key == release_key).first(): raise HTTPException(409, "That CIP release already exists.")
        releases = db.query(ConfigItem).filter(ConfigItem.config_version_id == vid, ConfigItem.category == "CIP Release", ConfigItem.active.is_(True)).order_by(desc(ConfigItem.value_number)).all(); prior = releases[0] if releases else None
        db.add(ConfigItem(config_version_id=vid, category="CIP Release", key=release_key, label=f"Release {match.group(1)}.{match.group(2)}", value_number=rank, value_type="catalog", sort_order=rank, active=True, description="CIP software release; catalog initially cloned from the prior active release."))
        if prior:
            for category_name in ("CIP Desktop Application", "CIP Mobile Application", "CIP Integration"):
                for source in db.query(ConfigItem).filter(ConfigItem.config_version_id == vid, ConfigItem.category == category_name, ConfigItem.parent_key == prior.key).all():
                    suffix = source.key.split(":", 1)[-1]
                    db.add(ConfigItem(config_version_id=vid, category=category_name, key=f"{release_key}:{suffix}", label=source.label, value_number=source.value_number, value_text=source.value_text, value_type=source.value_type, unit=source.unit, description=source.description, parent_key=release_key, sort_order=source.sort_order, active=source.active))
        record(db, event_type="CIP_RELEASE_ADDED", user_id=user.id, config_version_id=vid, field_name=release_key, new_value=label, reason=reason); db.commit()
        return RedirectResponse(f"/data?product=CIP&version={vid}&category=CIP+Release", 303)
