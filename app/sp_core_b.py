from __future__ import annotations

import json
from sqlalchemy.orm import Session

from . import sow_service
from .cip_models import PRODUCT_CIP, PRODUCT_MEP
from .models import EstimateRevision, User
from .services.audit import record
from .sow_models import SOW, SOWHypercareLocation
from .small_project_models import (
    SMALL_PROJECT_INSTALL_MODES, SMALL_PROJECT_METHODOLOGY_MODES,
    SmallProjectSOWConfig, SmallProjectSOWDeliverable, SmallProjectSOWMethodology,
)
from .sp_core_a import (
    _config, _product_for_revision, SMALL_PROJECT_INSTALL_MODES as CORE_INSTALL_MODES,
    SMALL_PROJECT_METHODOLOGY_MODES as CORE_METHODOLOGY_MODES,
    small_project_support_hours,
)

# Re-export the canonical tuples from the foundation model through this workflow layer.
SMALL_PROJECT_INSTALL_MODES = CORE_INSTALL_MODES
SMALL_PROJECT_METHODOLOGY_MODES = CORE_METHODOLOGY_MODES


def _deliverable_map(cfg: SmallProjectSOWConfig) -> dict[str, SmallProjectSOWDeliverable]:
    return {row.deliverable_key: row for row in cfg.deliverables}


def _methodology_map(cfg: SmallProjectSOWConfig) -> dict[str, SmallProjectSOWMethodology]:
    return {row.methodology_key: row for row in cfg.methodologies}


def appendix_included(db: Session, sow: SOW, rev: EstimateRevision) -> bool:
    cfg = _config(db, sow)
    product = _product_for_revision(db, rev)
    deliverables = _deliverable_map(cfg)
    if product == PRODUCT_MEP:
        return cfg.install_mode != "None"
    return bool(deliverables.get("CIP_INSTALL") and deliverables["CIP_INSTALL"].include)


def _auto_methodology(
    db: Session,
    sow: SOW,
    rev: EstimateRevision,
    cfg: SmallProjectSOWConfig,
    key: str,
) -> bool:
    d = _deliverable_map(cfg)
    included = {k for k, row in d.items() if row.include}
    product = _product_for_revision(db, rev)
    any_work = bool(included)
    app_work = bool(included & {"BASELINE_APPS", "CUSTOM_APPS", "REPORTS", "LABELS", "SECURITY", "INTEGRATIONS"})
    install_work = (
        cfg.install_mode != "None"
        if product == PRODUCT_MEP
        else "CIP_INSTALL" in included
    )
    epp_work = "EPP" in included
    support_hours = small_project_support_hours(db, rev, product)

    rules = {
        "PLANNING": any_work,
        "KICKOFF": any_work,
        "ADW": install_work or epp_work,
        "REQUIREMENTS": app_work,
        "DEPLOYMENT": any_work,
        "UNIT_TESTING": app_work or install_work or epp_work,
        "DEVICE_CONFIG": bool(included & {"BASELINE_APPS", "CUSTOM_APPS"}),
        "KEY_USER_TRAINING": cfg.key_user_training_count > 0 and bool(included & {"BASELINE_APPS", "CUSTOM_APPS"}),
        "UAT": app_work,
        "LIMITED_LOAD_TEST": False,
        "GO_LIVE_PREP": support_hours > 0 or app_work,
        "HYPERCARE": support_hours > 0,
    }
    return bool(rules.get(key, False))


def methodology_included(
    db: Session,
    sow: SOW,
    rev: EstimateRevision,
    cfg: SmallProjectSOWConfig,
    row: SmallProjectSOWMethodology,
) -> bool:
    if row.mode == "Include":
        return True
    if row.mode == "Exclude":
        return False
    return _auto_methodology(db, sow, rev, cfg, row.methodology_key)


def _audit_field(db, user, rev, sow, field, old, new):
    if old == new:
        return
    record(
        db,
        event_type="SOW_FIELD_CHANGED",
        user_id=user.id,
        estimate_id=rev.estimate_id,
        revision_id=rev.id,
        field_name=f"SOW:{sow.id}:{field}",
        old_value=old,
        new_value=new,
    )


def _as_int(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _as_float(value, default=0.0):
    try:
        return float(str(value).strip())
    except Exception:
        return default


def _save_hypercare(db: Session, sow: SOW, rev: EstimateRevision, user: User, form) -> None:
    old = json.dumps(
        [
            [x.description, x.country, x.support_type, float(x.allocated_hours or 0)]
            for x in sow.hypercare_locations
        ],
        ensure_ascii=False,
    )
    db.query(SOWHypercareLocation).filter(
        SOWHypercareLocation.sow_id == sow.id
    ).delete(synchronize_session=False)
    descriptions = form.getlist("hypercare_description")
    countries = form.getlist("hypercare_country")
    support_types = form.getlist("hypercare_support_type")
    hours = form.getlist("hypercare_hours")
    new = []
    count = max(len(descriptions), len(countries), len(support_types), len(hours))
    for index in range(count):
        description = str(descriptions[index] if index < len(descriptions) else "").strip()
        country = str(countries[index] if index < len(countries) else "").strip()
        support = str(support_types[index] if index < len(support_types) else "Remote").strip()
        allocated = _as_float(hours[index] if index < len(hours) else 0)
        if not description and not country and allocated == 0:
            continue
        support = support if support in sow_service.SUPPORT_TYPES else "Remote"
        db.add(
            SOWHypercareLocation(
                sow_id=sow.id,
                description=description,
                country=country,
                support_type=support,
                allocated_hours=allocated,
                sort_order=index,
            )
        )
        new.append([description, country, support, allocated])
    _audit_field(
        db, user, rev, sow, "HYPERCARE_LOCATIONS", old, json.dumps(new, ensure_ascii=False)
    )


def save_small_project_sow(
    db: Session,
    sow: SOW,
    rev: EstimateRevision,
    user: User,
    form,
) -> None:
    cfg = _config(db, sow)
    product = _product_for_revision(db, rev)

    fields = {
        "agreement_type": str(form.get("agreement_type", sow.agreement_type)).strip(),
        "invoice_frequency": str(form.get("invoice_frequency", sow.invoice_frequency)).strip(),
        "project_objective": str(form.get("project_objective", sow.project_objective)).strip(),
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
        old = getattr(sow, field)
        _audit_field(db, user, rev, sow, field, old, value)
        setattr(sow, field, value)

    requested_install = str(form.get("install_mode", cfg.install_mode)).strip()
    install_mode = (
        requested_install
        if product == PRODUCT_MEP and requested_install in SMALL_PROJECT_INSTALL_MODES
        else "None"
    )
    _audit_field(db, user, rev, sow, "INSTALL_MODE", cfg.install_mode, install_mode)
    cfg.install_mode = install_mode

    key_users = max(0, min(20, _as_int(form.get("key_user_training_count"), cfg.key_user_training_count)))
    _audit_field(
        db,
        user,
        rev,
        sow,
        "KEY_USER_TRAINING_COUNT",
        cfg.key_user_training_count,
        key_users,
    )
    cfg.key_user_training_count = key_users

    for row in cfg.deliverables:
        include = str(form.get(f"deliverable_include_{row.id}", "")).lower() in (
            "1", "true", "yes", "on"
        )
        description = str(
            form.get(f"deliverable_scope_{row.id}", row.scope_description)
        ).strip()
        notes = str(form.get(f"deliverable_notes_{row.id}", row.detail_notes)).strip()
        _audit_field(db, user, rev, sow, f"DELIVERABLE:{row.deliverable_key}:INCLUDE", row.include, include)
        _audit_field(db, user, rev, sow, f"DELIVERABLE:{row.deliverable_key}:SCOPE", row.scope_description, description)
        _audit_field(db, user, rev, sow, f"DELIVERABLE:{row.deliverable_key}:NOTES", row.detail_notes, notes)
        if product == PRODUCT_MEP and row.deliverable_key == "MEP_INSTALL":
            include = cfg.install_mode != "None"
            if include and not description.strip():
                description = (
                    "Provision and configure MEP in the Cloud Inventory® managed cloud."
                    if cfg.install_mode == "Cloud"
                    else "Install and configure MEP in the Customer-designated on-premises environment."
                )
        row.include = include
        row.scope_description = description
        row.detail_notes = notes

    for row in cfg.methodologies:
        mode = str(form.get(f"methodology_mode_{row.id}", row.mode)).strip()
        if mode not in SMALL_PROJECT_METHODOLOGY_MODES:
            mode = "Auto"
        _audit_field(db, user, rev, sow, f"METHODOLOGY:{row.methodology_key}", row.mode, mode)
        row.mode = mode

    _save_hypercare(db, sow, rev, user, form)
    db.commit()


def validate_small_project_finalize(
    db: Session, sow: SOW, rev: EstimateRevision
) -> list[str]:
    cfg = _config(db, sow)
    product = _product_for_revision(db, rev)
    errors: list[str] = []

    if sow.agreement_type not in sow_service.AGREEMENT_TYPES:
        errors.append("Select a valid Agreement Type.")
    if sow.invoice_frequency not in sow_service.INVOICE_FREQUENCIES:
        errors.append("Select Weekly or Monthly invoice frequency.")
    if not sow.project_objective.strip():
        errors.append("Project Objective is required.")
    if not any(row.include for row in cfg.deliverables):
        errors.append("Select at least one Small Project deliverable.")
    if product == PRODUCT_MEP and cfg.install_mode not in SMALL_PROJECT_INSTALL_MODES:
        errors.append("Select a valid MEP installation mode.")
    if cfg.key_user_training_count < 0:
        errors.append("Key User Training Count cannot be negative.")

    if appendix_included(db, sow, rev):
        if not sow.mep_product_version.strip():
            errors.append(
                f"{'CIP' if product == PRODUCT_CIP else 'MEP'} Product Version is required when Appendix A is included."
            )
        epp = _deliverable_map(cfg).get("EPP")
        if epp and epp.include:
            if not sow.epp_product_version.strip():
                errors.append("EPP Product Version is required when EPP is included.")
            if not sow.print_methods.strip():
                errors.append("Print Methods are required when EPP is included.")

    support_hours = small_project_support_hours(db, rev, product)
    allocated = sum(float(x.allocated_hours or 0) for x in sow.hypercare_locations)
    if abs(allocated - support_hours) > 0.01:
        errors.append(
            f"Hypercare allocations must equal the approved Go-Live Support hours "
            f"({support_hours:g}). Currently allocated: {allocated:g}."
        )
    if support_hours > 0:
        for index, row in enumerate(sow.hypercare_locations, 1):
            if row.allocated_hours > 0 and not row.description.strip():
                errors.append(f"Hypercare location {index} needs a Location Description.")
            if row.allocated_hours > 0 and not row.country.strip():
                errors.append(f"Hypercare location {index} needs a Country.")
    return errors
