from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from typing import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_models import (
    CIPNonBillableAllocation,
    CIPRevisionInput,
    CIPScopeItem,
    ConfigurationProduct,
    EstimateProduct,
    PRODUCT_CIP,
    PRODUCT_MEP,
)
from .cip_seed import seed_cip_database
from .database import SessionLocal, get_db
from .estimate_numbering import EstimateNumberExhausted, current_business_date, next_estimate_number
from .models import (
    AuditEvent,
    CalculationAdjustment,
    ConfigItem,
    ConfigurationVersion,
    Estimate,
    EstimateRevision,
    ScheduleTask,
)
from .route_architecture import take_route as _take_route
from .seed import slug
from .services.audit import record
from .services.cip_calculation import (
    CIPConfig,
    CIP_ENGINE_VERSION,
    calculation as cip_calculation,
    recalculate_and_store as cip_recalculate_and_store,
)
from .services.cip_schedule import generate_cip_schedule


STANDARD_SCOPE = {
    "DESKTOP": "CIP Desktop Application",
    "MOBILE": "CIP Mobile Application",
    "INTEGRATION": "CIP Integration",
}
CUSTOM_SLOTS = {"CUSTOM_DESKTOP": 16, "CUSTOM_MOBILE": 16, "REPORT": 16}


def configuration_product(db: Session, version_id: int) -> str:
    row = db.get(ConfigurationProduct, version_id)
    return row.product_type if row else PRODUCT_MEP


def estimate_product(db: Session, estimate_id: int) -> str:
    row = db.get(EstimateProduct, estimate_id)
    return row.product_type if row else PRODUCT_MEP


def revision_product(db: Session, rev: EstimateRevision) -> str:
    return estimate_product(db, rev.estimate_id)


def active_config_for_product(db: Session, product_type: str) -> ConfigurationVersion:
    versions = db.query(ConfigurationVersion).filter(ConfigurationVersion.status == "ACTIVE").order_by(desc(ConfigurationVersion.activated_at), desc(ConfigurationVersion.id)).all()
    for version in versions:
        if configuration_product(db, version.id) == product_type:
            return version
    raise HTTPException(500, f"No active {product_type} configuration")


def _latest_release(cfg: CIPConfig):
    return cfg.latest_release()


def _ensure_custom_slots(db: Session, rev: EstimateRevision):
    for category, count in CUSTOM_SLOTS.items():
        existing = {row.catalog_key for row in db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rev.id, CIPScopeItem.category == category).all()}
        prefix = {"CUSTOM_DESKTOP": "Custom Desktop Application", "CUSTOM_MOBILE": "Custom Mobile Application", "REPORT": "Report"}[category]
        for idx in range(1, count + 1):
            key = f"{category}_{idx:02d}"
            if key in existing:
                continue
            db.add(CIPScopeItem(revision_id=rev.id, category=category, catalog_key=key, label=f"{prefix} {idx}", description="", config_type="No Config", sort_order=idx))
    db.flush()


def _ensure_dynamic_scope(db: Session, rev: EstimateRevision, inp: CIPRevisionInput):
    specs = [
        ("LABEL", max(0, inp.label_count), "Label"),
        ("CUSTOM_BOOMI", max(0, inp.custom_boomi_count), "Custom Boomi Integration"),
        ("REST", max(0, inp.rest_interface_count), "RESTful Interface"),
    ]
    for category, count, label_prefix in specs:
        existing = {row.sort_order: row for row in db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rev.id, CIPScopeItem.category == category).all()}
        for idx in range(1, count + 1):
            if idx in existing:
                continue
            db.add(CIPScopeItem(revision_id=rev.id, category=category, catalog_key=f"{category}_{idx:02d}", label=f"{label_prefix} {idx}", description=f"Label {idx}" if category == "LABEL" else "", config_type="Baseline", sort_order=idx))
    db.flush()


def sync_cip_catalog(db: Session, rev: EstimateRevision, release_key: str, *, force: bool = False, preserve_by_label: dict[tuple[str, str], str] | None = None):
    cfg = CIPConfig(db, rev.config_version_id)
    preserve_by_label = preserve_by_label or {}
    for scope_category, config_category in STANDARD_SCOPE.items():
        existing = db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rev.id, CIPScopeItem.category == scope_category).all()
        if existing and not force:
            continue
        if force and existing:
            db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rev.id, CIPScopeItem.category == scope_category).delete(synchronize_session=False)
        items = [item for item in cfg.by_cat.get(config_category, []) if item.active and item.parent_key == release_key]
        for idx, item in enumerate(items):
            selected = preserve_by_label.get((scope_category, item.label.casefold()), "No Config")
            db.add(CIPScopeItem(revision_id=rev.id, category=scope_category, catalog_key=item.key, label=item.label, config_type=selected, sort_order=idx))
    _ensure_custom_slots(db, rev)
    db.flush()


def _cip_input(db: Session, rid: int) -> CIPRevisionInput:
    inp = db.get(CIPRevisionInput, rid)
    if not inp:
        raise HTTPException(404, "CIP estimate inputs not found")
    return inp


def _update_cip_field(db: Session, rev: EstimateRevision, inp: CIPRevisionInput, user, field: str, value):
    old = getattr(inp, field)
    if old != value:
        setattr(inp, field, value)
        rev.row_version += 1
        record(db, event_type="ESTIMATE_FIELD_CHANGED", user_id=user.id, estimate_id=rev.estimate_id, revision_id=rev.id, field_name=f"CIP:{field}", old_value=old, new_value=value)


def _bool(form, key: str) -> bool:
    return str(form.get(key, "")).lower() in ("1", "true", "yes", "on")


def _int(form, key: str, default=0) -> int:
    try:
        return int(float(form.get(key, default) or default))
    except Exception:
        return default


def _float(form, key: str, default=0.0) -> float:
    try:
        return float(form.get(key, default) or default)
    except Exception:
        return default


def validate_cip(db: Session, rev: EstimateRevision, inp: CIPRevisionInput):
    errors = []
    cfg = CIPConfig(db, rev.config_version_id)
    if not cfg.item_by_key("CIP Release", inp.release_key): errors.append("The selected CIP release is not active in this configuration.")
    if inp.epp_install != "No" and inp.label_sites < 1: errors.append("At least one label-printing site is required when EPP is installed.")
    if inp.epp_install == "No" and inp.label_sites > 0: errors.append("Label-printing site count must be zero when EPP is not installed.")
    if inp.labels_required and inp.label_count < 1: errors.append("Label Count must be at least 1 when Labels Required is Yes.")
    if not inp.labels_required and inp.label_count > 0: errors.append("Label Count is greater than zero while Labels Required is No.")
    if inp.label_count > 20: errors.append("Label Count must be between 0 and 20.")
    if inp.custom_boomi_required and inp.custom_boomi_count < 1: errors.append("Custom Boomi Count must be at least 1 when Custom Boomi Integrations is Yes.")
    if not inp.custom_boomi_required and inp.custom_boomi_count > 0: errors.append("Custom Boomi Count is greater than zero while Custom Boomi Integrations is No.")
    if inp.custom_boomi_count > 20: errors.append("Custom Boomi Count must be between 0 and 20.")
    if inp.rest_required and inp.rest_interface_count < 1: errors.append("RESTful Interface Count must be at least 1 when RESTful Interfaces is Yes.")
    if not inp.rest_required and inp.rest_interface_count > 0: errors.append("RESTful Interface Count is greater than zero while RESTful Interfaces is No.")
    if inp.rest_interface_count > 20: errors.append("RESTful Interface Count must be between 0 and 20.")
    if inp.go_live_type != "None" and inp.go_live_sites < 1: errors.append("Number of Go-Live Sites must be at least 1 when a Go-Live Support Type is selected.")
    if inp.testing_cycles not in (1, 2, 3): errors.append("Testing Cycles must be 1, 2, or 3.")
    if inp.uat_sites not in (1, 2, 3): errors.append("Number of Sites for UAT must be 1, 2, or 3.")
    if rev.billing_rate <= 0: errors.append("Billing Rate must be greater than zero.")
    for category in ("CUSTOM_DESKTOP", "CUSTOM_MOBILE", "REPORT"):
        rows = db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rev.id, CIPScopeItem.category == category).all()
        for row in rows:
            if row.config_type != "No Config" and not row.description.strip(): errors.append(f"{row.label} has effort selected but no description.")
    if errors:
        raise HTTPException(400, " ".join(errors))


def _cip_context(db: Session, rev: EstimateRevision):
    inp = _cip_input(db, rev.id)
    cfg = CIPConfig(db, rev.config_version_id)
    lines, summary, details, detail_summary = cip_calculation(db, rev)
    releases = sorted([x for x in cfg.by_cat.get("CIP Release", []) if x.active], key=lambda x: (float(x.value_number or 0), x.sort_order))
    deployed = cfg.item_by_label("CIP Deployed Over", inp.deployed_over)
    expected = int(float(deployed.value_number or 0)) if deployed else 0
    warning = f"{expected} baseline Boomi integrations require configuration." if expected > 0 else "Custom Boomi integrations may be required for this deployment platform."
    def scope(category):
        return db.query(CIPScopeItem).filter(CIPScopeItem.revision_id == rev.id, CIPScopeItem.category == category).order_by(CIPScopeItem.sort_order).all()
    return {
        "rev": rev, "estimate": rev.estimate, "inp": inp, "cfg": cfg, "summary": summary,
        "releases": releases, "customer_types": cfg.labels("CIP Customer Type"), "project_types": cfg.labels("CIP Project Type"),
        "deployed_over": cfg.labels("CIP Deployed Over"), "currencies": cfg.labels("Currency"), "entities": cfg.labels("Entity"),
        "epp_install_options": cfg.labels("CIP EPP Install"), "user_counts": cfg.labels("CIP User Count"),
        "go_live": cfg.labels("CIP Go Live"), "security": cfg.labels("CIP Security Method"), "config_types": cfg.labels("CIP Config Type"),
        "custom_complexity": cfg.labels("CIP Custom Complexity"), "report_complexity": cfg.labels("CIP Report Complexity"),
        "desktop": scope("DESKTOP"), "mobile": scope("MOBILE"), "integrations": scope("INTEGRATION"),
        "custom_desktop": scope("CUSTOM_DESKTOP"), "custom_mobile": scope("CUSTOM_MOBILE"), "reports": scope("REPORT"),
        "warning": warning, "readonly": rev.status in ("APPROVED", "FINAL", "SUPERSEDED"), "product_type": PRODUCT_CIP,
    }