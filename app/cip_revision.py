from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_domain import (
    STANDARD_SCOPE, _cip_input, _ensure_custom_slots, _ensure_dynamic_scope, _latest_release,
    active_config_for_product, sync_cip_catalog,
)
from .cip_models import CIPRevisionInput, CIPScopeItem, EstimateProduct, PRODUCT_CIP
from .estimate_numbering import EstimateNumberExhausted, current_business_date, next_estimate_number
from .models import ConfigurationVersion, Estimate, EstimateRevision
from .services.audit import record
from .services.cip_calculation import CIPConfig, CIP_ENGINE_VERSION, recalculate_and_store as cip_recalculate_and_store


def copy_cip_revision(db: Session, core, src: EstimateRevision, user, rebase: bool):
    maxrev = db.query(EstimateRevision).filter(EstimateRevision.estimate_id == src.estimate_id).order_by(desc(EstimateRevision.revision_no)).first().revision_no
    cv = active_config_for_product(db, PRODUCT_CIP) if rebase else db.get(ConfigurationVersion, src.config_version_id)
    data = {column.name: getattr(src, column.name) for column in EstimateRevision.__table__.columns if column.name not in {
        "id", "revision_no", "status", "config_version_id", "created_at", "updated_at", "row_version",
        "calculated_hours", "calculated_fees", "low_hours", "high_hours", "duration_months",
    }}
    data.update(revision_no=maxrev + 1, status="DRAFT", config_version_id=cv.id, engine_version=CIP_ENGINE_VERSION, created_by=user.id, row_version=1, schedule_needs_refresh=True)
    rev = EstimateRevision(**data); db.add(rev); db.flush()
    old_inp = _cip_input(db, src.id)
    inp_data = {column.name: getattr(old_inp, column.name) for column in CIPRevisionInput.__table__.columns if column.name != "revision_id"}
    new_cfg = CIPConfig(db, cv.id)
    if rebase and not new_cfg.item_by_key("CIP Release", inp_data["release_key"]):
        inp_data["release_key"] = new_cfg.latest_release().key
    inp = CIPRevisionInput(revision_id=rev.id, **inp_data); db.add(inp); db.flush()
    old_rows = db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == src.id).order_by(CIPScopeItem.sort_order).all()
    if rebase:
        preserve = {(row.category, row.label.casefold()): row.config_type for row in old_rows if row.category in STANDARD_SCOPE}
        sync_cip_catalog(db, rev, inp.release_key, force=True, preserve_by_label=preserve)
        old_rows = [row for row in old_rows if row.category not in STANDARD_SCOPE]
    for row in old_rows:
        db.add(CIPScopeItem(revision_id=rev.id, category=row.category, catalog_key=row.catalog_key, label=row.label,
            description=row.description, config_type=row.config_type, added_hours=row.added_hours,
            adjustment_notes=row.adjustment_notes, testing_adjustment=row.testing_adjustment,
            testing_notes=row.testing_notes, app_count=row.app_count, integration_added_hours=row.integration_added_hours,
            sort_order=row.sort_order))
    # SessionLocal deliberately uses autoflush=False. Persist copied scope before the
    # ensure helpers query for existing keys; otherwise they cannot see the pending
    # rows and may create duplicate custom/dynamic slots in the same revision.
    db.flush()
    _ensure_custom_slots(db, rev); _ensure_dynamic_scope(db, rev, inp)
    record(db, event_type="REVISION_CREATED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id,
        config_version_id=cv.id, old_value=f"Rev {src.revision_no}", new_value=f"Rev {rev.revision_no}",
        reason="Rebased to current CIP configuration" if rebase else "New CIP estimate revision")
    cip_recalculate_and_store(db, rev); db.commit(); return rev


def create_cip_estimate(db: Session, core, user):
    business_day = current_business_date()
    try:
        number = next_estimate_number(db, business_day)
    except EstimateNumberExhausted as exc:
        db.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc
    cv = active_config_for_product(db, PRODUCT_CIP); cfg = CIPConfig(db, cv.id); release = _latest_release(cfg)
    entity = next((x for x in cfg.by_cat.get("Entity", []) if x.active), None)
    estimate = Estimate(estimate_number=number, created_by=user.id); db.add(estimate); db.flush()
    db.add(EstimateProduct(estimate_id=estimate.id, product_type=PRODUCT_CIP))
    rev = EstimateRevision(estimate_id=estimate.id, revision_no=1, status="DRAFT", config_version_id=cv.id,
        engine_version=CIP_ENGINE_VERSION, customer_type="Net_New", proposal_date=business_day, project_start=business_day,
        billing_rate=250, currency="US Dollar", entity=entity.label if entity else "", project_type="CIP Install",
        erp="Standalone", epp_install="No", user_count="1 to 50", test_cycles=1, go_live_sites=0,
        go_live_type="None", uat_sites=1, base_test_pct=0.20, security_method="None", created_by=user.id)
    db.add(rev); db.flush()
    inp = CIPRevisionInput(revision_id=rev.id, release_key=release.key, deployed_over="Standalone", project_type="CIP Install",
        epp_install="No", user_count="1 to 50", testing_cycles=1, go_live_type="None", uat_sites=1, base_test_pct=0.20,
        low_factor=cfg.param("DEFAULT_LOW_FACTOR"), high_factor=cfg.param("DEFAULT_HIGH_FACTOR"))
    db.add(inp); db.flush(); sync_cip_catalog(db, rev, release.key, force=True); _ensure_dynamic_scope(db, rev, inp)
    record(db, event_type="ESTIMATE_CREATED", user_id=user.id, estimate_id=estimate.id, revision_id=rev.id,
        config_version_id=cv.id, new_value=number, reason="Cloud Inventory Platform estimate")
    cip_recalculate_and_store(db, rev); db.commit(); return rev
