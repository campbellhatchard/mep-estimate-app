from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from . import sow_service
from .cip_domain import _take_route, revision_product
from .cip_sow.core import SOW_TEMPLATE_CIP_NET_NEW, cip_go_live_support_hours
from .cip_sow.docx import verify_cip_approved_content
from .database import get_db
from .models import EstimateRevision, User
from .services.audit import record
from .small_project_models import SmallProjectSOWConfig
from .small_project_sow import (
    SOW_TEMPLATE_CIP_SMALL_PROJECT,
    SOW_TEMPLATE_MEP_SMALL_PROJECT,
)
from .small_project_workflow import (
    small_project_support_hours,
    verify_small_project_approved_content,
)
from .sow_models import SOW, SOWDevice, SOWHypercareLocation, SOWTemplateVersion, SOW_TEMPLATE_MEP_NET_NEW


SUPPORTED_FAMILIES = {
    SOW_TEMPLATE_MEP_NET_NEW,
    SOW_TEMPLATE_CIP_NET_NEW,
    SOW_TEMPLATE_MEP_SMALL_PROJECT,
    SOW_TEMPLATE_CIP_SMALL_PROJECT,
}

COMMON_MANUAL_FIELDS = (
    "agreement_type",
    "invoice_frequency",
    "project_objective",
    "barcode_printer_count",
    "erp_version",
    "erp_base_code_version",
    "erp_tools_release",
    "erp_os_version",
    "erp_database_version",
    "epp_product_version",
    "print_methods",
    "erp_deployment_model",
)


def _template_key(db: Session, sow: SOW) -> str:
    template = db.get(SOWTemplateVersion, sow.template_version_id)
    return template.template_key if template else ""


def _previous_estimate_revision(db: Session, rev: EstimateRevision) -> EstimateRevision | None:
    if int(rev.revision_no or 0) <= 1:
        return None
    return (
        db.query(EstimateRevision)
        .filter(
            EstimateRevision.estimate_id == rev.estimate_id,
            EstimateRevision.revision_no < rev.revision_no,
        )
        .order_by(desc(EstimateRevision.revision_no))
        .first()
    )


def _source_sow(db: Session, prior: EstimateRevision, template_key: str) -> SOW | None:
    candidates = (
        db.query(SOW)
        .filter(SOW.estimate_revision_id == prior.id)
        .order_by(desc(SOW.sow_revision_no))
        .all()
    )
    candidates = [row for row in candidates if _template_key(db, row) == template_key]
    if not candidates:
        return None
    priority = {"APPROVED": 0, "REJECTED": 1, "FINALIZED": 2}
    eligible = [row for row in candidates if row.status in priority]
    if not eligible:
        return None
    return min(eligible, key=lambda row: (priority[row.status], -row.sow_revision_no))


def _verify_approved_source(
    db: Session, source: SOW, source_rev: EstimateRevision, template_key: str
) -> None:
    if source.status != "APPROVED":
        return
    if template_key == SOW_TEMPLATE_MEP_NET_NEW:
        sow_service.verify_approved_content(db, source, source_rev)
    elif template_key == SOW_TEMPLATE_CIP_NET_NEW:
        verify_cip_approved_content(db, source, source_rev)
    elif template_key in {SOW_TEMPLATE_MEP_SMALL_PROJECT, SOW_TEMPLATE_CIP_SMALL_PROJECT}:
        verify_small_project_approved_content(db, source, source_rev)


def _new_support_hours(
    db: Session, rev: EstimateRevision, template_key: str
) -> float:
    if template_key == SOW_TEMPLATE_CIP_NET_NEW:
        return cip_go_live_support_hours(db, rev)
    if template_key in {SOW_TEMPLATE_MEP_SMALL_PROJECT, SOW_TEMPLATE_CIP_SMALL_PROJECT}:
        return small_project_support_hours(db, rev, revision_product(db, rev))
    return sow_service.go_live_support_hours(db, rev)


def _copy_base_manual_fields(source: SOW, dest: SOW, template_key: str) -> None:
    for field in COMMON_MANUAL_FIELDS:
        setattr(dest, field, getattr(source, field))
    if template_key in {SOW_TEMPLATE_MEP_NET_NEW, SOW_TEMPLATE_MEP_SMALL_PROJECT}:
        dest.mep_product_version = source.mep_product_version
        dest.rest_api_required = source.rest_api_required


def _copy_devices(db: Session, source: SOW, dest: SOW) -> None:
    db.query(SOWDevice).filter(SOWDevice.sow_id == dest.id).delete(synchronize_session=False)
    for row in source.devices:
        db.add(
            SOWDevice(
                sow_id=dest.id,
                device_type=row.device_type,
                make_model=row.make_model,
                os_version=row.os_version,
                sort_order=row.sort_order,
            )
        )


def _copy_hypercare(
    db: Session,
    source: SOW,
    dest: SOW,
    rev: EstimateRevision,
    template_key: str,
) -> bool:
    source_rows = sorted(source.hypercare_locations, key=lambda row: (row.sort_order, row.id))
    dest_rows = sorted(dest.hypercare_locations, key=lambda row: (row.sort_order, row.id))

    for index, row in enumerate(dest_rows):
        row.allocated_hours = 0.0
        if index >= len(source_rows):
            continue
        prior = source_rows[index]
        row.description = prior.description
        row.country = prior.country
        row.support_type = prior.support_type

    new_total = float(_new_support_hours(db, rev, template_key) or 0)
    prior_total = sum(float(row.allocated_hours or 0) for row in source_rows)
    preserve_hours = (
        len(source_rows) == len(dest_rows)
        and abs(prior_total - new_total) <= 0.01
    )
    if preserve_hours:
        for index, row in enumerate(dest_rows):
            row.allocated_hours = float(source_rows[index].allocated_hours or 0)
    return preserve_hours


def _copy_small_project_manual_fields(
    db: Session, source: SOW, dest: SOW, template_key: str
) -> None:
    source_cfg = (
        db.query(SmallProjectSOWConfig)
        .filter(SmallProjectSOWConfig.sow_id == source.id)
        .first()
    )
    dest_cfg = (
        db.query(SmallProjectSOWConfig)
        .filter(SmallProjectSOWConfig.sow_id == dest.id)
        .first()
    )
    if not source_cfg or not dest_cfg:
        return

    if template_key == SOW_TEMPLATE_MEP_SMALL_PROJECT:
        dest_cfg.install_mode = source_cfg.install_mode
    dest_cfg.key_user_training_count = source_cfg.key_user_training_count

    source_deliverables = {row.deliverable_key: row for row in source_cfg.deliverables}
    for row in dest_cfg.deliverables:
        prior = source_deliverables.get(row.deliverable_key)
        if not prior:
            continue
        row.scope_description = prior.scope_description
        row.detail_notes = prior.detail_notes

    source_methods = {row.methodology_key: row for row in source_cfg.methodologies}
    for row in dest_cfg.methodologies:
        prior = source_methods.get(row.methodology_key)
        if prior and prior.mode in {"Include", "Exclude"}:
            row.mode = prior.mode


def carry_forward_sow_content(
    db: Session, dest: SOW, rev: EstimateRevision, user: User
) -> SOW | None:
    template_key = _template_key(db, dest)
    if template_key not in SUPPORTED_FAMILIES:
        return None
    prior_rev = _previous_estimate_revision(db, rev)
    if not prior_rev:
        return None
    source = _source_sow(db, prior_rev, template_key)
    if not source:
        return None

    try:
        _verify_approved_source(db, source, prior_rev, template_key)
    except ValueError as exc:
        record(
            db,
            event_type="SOW_CARRY_FORWARD_BLOCKED",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            field_name=f"SOW:{dest.id}",
            old_value=f"SOW:{source.id}",
            new_value="Defaults retained",
            reason=str(exc),
        )
        db.commit()
        return None

    _copy_base_manual_fields(source, dest, template_key)
    _copy_devices(db, source, dest)
    hours_preserved = _copy_hypercare(db, source, dest, rev, template_key)
    if template_key in {SOW_TEMPLATE_MEP_SMALL_PROJECT, SOW_TEMPLATE_CIP_SMALL_PROJECT}:
        _copy_small_project_manual_fields(db, source, dest, template_key)

    record(
        db,
        event_type="SOW_CONTENT_CARRIED_FORWARD",
        user_id=user.id,
        estimate_id=rev.estimate_id,
        revision_id=rev.id,
        field_name=f"SOW:{dest.id}",
        old_value=f"Estimate Rev {prior_rev.revision_no}; SOW {source.id} Rev {source.sow_revision_no}",
        new_value=f"Estimate Rev {rev.revision_no}; SOW {dest.id} Rev {dest.sow_revision_no}",
        reason=(
            f"User-authored content carried from {template_key}. "
            f"New-estimate scope/commercial defaults retained; Hypercare hours "
            f"{'preserved' if hours_preserved else 'cleared for reconciliation'} to the new approved estimate."
        ),
    )
    db.commit()
    return source


def register_sow_lineage_carry_forward(app, core) -> None:
    """Wrap final four-family SOW creation and opt new SOWs into composition v2."""
    previous_create = _take_route(app, "/estimate/{rid}/sow/create", "POST")
    if previous_create is None:
        raise RuntimeError("SOW create route must exist before lineage carry-forward is registered")

    @app.post("/estimate/{rid}/sow/create")
    def create_sow_with_carry_forward(
        rid: int, request: Request, db: Session = Depends(get_db)
    ):
        user = core.current_user(request, db)
        rev = core.revision_or_404(db, rid)
        existing = sow_service.latest_sow(db, rid)
        response = previous_create(rid, request, db)
        if existing is not None:
            return response

        location = getattr(response, "headers", {}).get("location", "")
        try:
            sow_id = int(location.rstrip("/").rsplit("/", 1)[-1])
        except (TypeError, ValueError):
            return response
        dest = db.get(SOW, sow_id)
        if dest and dest.estimate_revision_id == rid:
            dest.composition_version = 2
            db.commit()
            carry_forward_sow_content(db, dest, rev, user)
        return response
