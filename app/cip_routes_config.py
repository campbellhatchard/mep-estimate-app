import re
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_domain import _int, active_config_for_product, configuration_product
from .cip_models import ConfigurationProduct, PRODUCT_CIP, PRODUCT_MEP
from .database import get_db
from .models import ConfigItem, ConfigurationVersion
from .services.audit import record


def register_config_routes(app, core):
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
        return core.templates.TemplateResponse("data.html", {"request": request, "user": user, "versions": versions, "version": selected, "items": items, "categories": categories, "q": q, "category": category, "product_type": product})

    @app.post("/data/version/new")
    async def new_config_version(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, "ADMIN"); form = await request.form(); product = str(form.get("product", PRODUCT_MEP)).upper()
        if product not in (PRODUCT_MEP, PRODUCT_CIP): raise HTTPException(400, "Unknown configuration product")
        src = active_config_for_product(db, product); stamp = datetime.utcnow().strftime("%Y.%m.%d.%H%M")
        version = ConfigurationVersion(name=f"{product} Estimate Model {stamp}", status="DRAFT", created_by=user.id, change_reason=f"Draft {product} configuration cloned from active model")
        db.add(version); db.flush(); db.add(ConfigurationProduct(config_version_id=version.id, product_type=product))
        for item in db.query(ConfigItem).filter(ConfigItem.config_version_id == src.id):
            db.add(ConfigItem(config_version_id=version.id, category=item.category, key=item.key, label=item.label, value_number=item.value_number, value_text=item.value_text, value_type=item.value_type, unit=item.unit, description=item.description, parent_key=item.parent_key, sort_order=item.sort_order, active=item.active))
        record(db, event_type="CONFIG_VERSION_CREATED", user_id=user.id, config_version_id=version.id, old_value=src.name, new_value=version.name); db.commit()
        return RedirectResponse(f"/data?product={product}&version={version.id}", 303)

    @app.post("/data/version/{vid}/activate")
    def activate_config(vid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, "ADMIN"); version = db.get(ConfigurationVersion, vid)
        if not version or version.status != "DRAFT": raise HTTPException(409, "Only a draft can be activated")
        product = configuration_product(db, version.id)
        for active in db.query(ConfigurationVersion).filter(ConfigurationVersion.status == "ACTIVE").all():
            if active.id != version.id and configuration_product(db, active.id) == product: active.status = "RETIRED"
        version.status = "ACTIVE"; version.activated_at = datetime.utcnow(); version.approval_status = "ACTIVE"
        record(db, event_type="CONFIG_VERSION_ACTIVATED", user_id=user.id, config_version_id=version.id, new_value=version.name, reason=version.change_reason); db.commit()
        return RedirectResponse(f"/data?product={product}&version={version.id}", 303)

    @app.post("/cip/data/release/new")
    async def add_cip_release(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db); core.require_role(user, "ADMIN"); form = await request.form(); vid = _int(form, "version_id", 0); version = db.get(ConfigurationVersion, vid)
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
