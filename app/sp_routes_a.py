from __future__ import annotations

from fastapi import Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from . import sow_routes, sow_service
from .models import EstimateRevision, User
from .sow_models import SOW
from .small_project_models import SmallProjectSOWConfig, SmallProjectSOWDeliverable, SmallProjectSOWMethodology
from .sp_core_a import METHODOLOGY_SPECS, WEEKEND_HOLIDAY_CLAUSE, _config, _product_for_revision, small_project_support_hours
from .sp_core_b import SMALL_PROJECT_INSTALL_MODES, SMALL_PROJECT_METHODOLOGY_MODES, appendix_included, methodology_included


def copy_rejected_small_project_sow(
    db: Session, source: SOW, rev: EstimateRevision, user: User
) -> SOW:
    source_cfg = _config(db, source)
    dest = sow_service.copy_rejected_sow(db, source, rev, user)
    existing = (
        db.query(SmallProjectSOWConfig)
        .filter(SmallProjectSOWConfig.sow_id == dest.id)
        .first()
    )
    if existing:
        return dest

    cfg = SmallProjectSOWConfig(
        sow_id=dest.id,
        install_mode=source_cfg.install_mode,
        key_user_training_count=source_cfg.key_user_training_count,
    )
    db.add(cfg)
    db.flush()
    for row in source_cfg.deliverables:
        db.add(
            SmallProjectSOWDeliverable(
                config_id=cfg.id,
                deliverable_key=row.deliverable_key,
                include=row.include,
                name=row.name,
                scope_description=row.scope_description,
                detail_notes=row.detail_notes,
                sort_order=row.sort_order,
            )
        )
    for row in source_cfg.methodologies:
        db.add(
            SmallProjectSOWMethodology(
                config_id=cfg.id,
                methodology_key=row.methodology_key,
                mode=row.mode,
                sort_order=row.sort_order,
            )
        )
    db.commit()
    return dest


def _small_project_context(
    db: Session, request: Request, core, sow: SOW, user: User
) -> dict:
    rev = sow_routes._rev_for_sow(db, sow)
    cfg = _config(db, sow)
    product = _product_for_revision(db, rev)
    support_hours = small_project_support_hours(db, rev, product)
    allocated = sum(float(x.allocated_hours or 0) for x in sow.hypercare_locations)
    history = (
        db.query(SOW)
        .filter(SOW.estimate_revision_id == rev.id)
        .order_by(desc(SOW.sow_revision_no))
        .all()
    )
    users = {u.id: u.username for u in db.query(User).all()}
    methodology_state = {
        row.id: methodology_included(db, sow, rev, cfg, row)
        for row in cfg.methodologies
    }
    return {
        "request": request,
        "user": user,
        "sow": sow,
        "rev": rev,
        "estimate": rev.estimate,
        "config": cfg,
        "product_type": product,
        "active_tab": "sow",
        "readonly": sow.status != "DRAFT",
        "history": history,
        "approvers": sow_routes._active_sow_approvers(db),
        "users": users,
        "agreement_types": sow_service.AGREEMENT_TYPES,
        "invoice_frequencies": sow_service.INVOICE_FREQUENCIES,
        "support_types": sow_service.SUPPORT_TYPES,
        "install_modes": SMALL_PROJECT_INSTALL_MODES,
        "methodology_modes": SMALL_PROJECT_METHODOLOGY_MODES,
        "methodology_titles": dict(METHODOLOGY_SPECS),
        "methodology_state": methodology_state,
        "go_live_support_hours": support_hours,
        "allocated_hours": allocated,
        "unallocated_hours": support_hours - allocated,
        "appendix_included": appendix_included(db, sow, rev),
        "can_approve": (
            user.has_role("SOW_APPROVER")
            and sow.status == "PENDING_APPROVAL"
            and sow.approver_id == user.id
        ),
        "can_prepare": user.has_role(*sow_routes.PREP_ROLES),
        "weekend_clause": WEEKEND_HOLIDAY_CLAUSE,
    }
