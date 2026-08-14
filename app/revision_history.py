from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_domain import _take_route, revision_product
from .cip_models import CIPNonBillableAllocation, PRODUCT_CIP, PRODUCT_MEP
from .cip_revision import copy_cip_revision
from .database import get_db
from .models import (
    AuditEvent,
    CalculationAdjustment,
    ConfigurationVersion,
    DetailAdjustment,
    EstimateApplication,
    EstimateCustomApplication,
    EstimateRevision,
    User,
)
from .services.audit import record
from .services.cip_calculation import recalculate_and_store as cip_recalculate_and_store
from .services.calculation import ENGINE_VERSION, recalculate_and_store as mep_recalculate_and_store

WORKING_STATUSES = ("DRAFT", "REVIEW")
LOCKED_STATUSES = ("APPROVED", "FINAL", "SUPERSEDED")


def _working_revision(db: Session, estimate_id: int, *, exclude_id: int | None = None):
    query = db.query(EstimateRevision).filter(
        EstimateRevision.estimate_id == estimate_id,
        EstimateRevision.status.in_(WORKING_STATUSES),
    )
    if exclude_id is not None:
        query = query.filter(EstimateRevision.id != exclude_id)
    return query.order_by(desc(EstimateRevision.revision_no)).first()


def _copy_mep_revision(db: Session, core, src: EstimateRevision, user, rebase: bool):
    maxrev = db.query(EstimateRevision).filter(EstimateRevision.estimate_id == src.estimate_id).order_by(desc(EstimateRevision.revision_no)).first().revision_no
    cv = core.active_config(db) if rebase else db.get(ConfigurationVersion, src.config_version_id)
    data = {
        column.name: getattr(src, column.name)
        for column in EstimateRevision.__table__.columns
        if column.name not in {
            "id", "revision_no", "status", "config_version_id", "created_at", "updated_at", "row_version",
            "calculated_hours", "calculated_fees", "low_hours", "high_hours", "duration_months",
        }
    }
    data.update(
        revision_no=maxrev + 1,
        status="DRAFT",
        config_version_id=cv.id,
        engine_version=ENGINE_VERSION,
        created_by=user.id,
        row_version=1,
        schedule_needs_refresh=True,
    )
    rev = EstimateRevision(**data)
    db.add(rev)
    db.flush()

    for row in db.query(EstimateApplication).filter(EstimateApplication.revision_id == src.id).all():
        db.add(EstimateApplication(
            revision_id=rev.id,
            kind=row.kind,
            catalog_key=row.catalog_key,
            label=row.label,
            config_type=row.config_type,
            sort_order=row.sort_order,
        ))
    for row in db.query(EstimateCustomApplication).filter(EstimateCustomApplication.revision_id == src.id).all():
        db.add(EstimateCustomApplication(
            revision_id=rev.id,
            description=row.description,
            complexity=row.complexity,
            sort_order=row.sort_order,
        ))
    if rebase:
        core.append_catalog_entries(db, rev)

    # A new working revision must begin as an exact estimating copy of its source.
    for row in db.query(DetailAdjustment).filter(DetailAdjustment.revision_id == src.id).all():
        db.add(DetailAdjustment(
            revision_id=rev.id,
            line_key=row.line_key,
            description=row.description,
            mod_hours=row.mod_hours,
            notes=row.notes,
        ))
    for row in db.query(CalculationAdjustment).filter(CalculationAdjustment.revision_id == src.id).all():
        db.add(CalculationAdjustment(
            revision_id=rev.id,
            line_key=row.line_key,
            adjust_hours=row.adjust_hours,
            notes=row.notes,
        ))

    record(
        db,
        event_type="REVISION_CREATED",
        user_id=user.id,
        estimate_id=rev.estimate_id,
        revision_id=rev.id,
        config_version_id=cv.id,
        old_value=f"Rev {src.revision_no}",
        new_value=f"Rev {rev.revision_no}",
        reason=("Rebased to current MEP configuration" if rebase else f"New MEP estimate revision from Rev {src.revision_no}"),
    )
    mep_recalculate_and_store(db, rev)
    db.commit()
    return rev


def _copy_cip_with_adjustments(db: Session, core, src: EstimateRevision, user, rebase: bool):
    rev = copy_cip_revision(db, core, src, user, rebase)

    # CIP scope-level development/testing adjustments are copied by copy_cip_revision.
    # Carry the phase adjustments and customer non-billable allocations as well.
    for row in db.query(CalculationAdjustment).filter(CalculationAdjustment.revision_id == src.id).all():
        db.add(CalculationAdjustment(
            revision_id=rev.id,
            line_key=row.line_key,
            adjust_hours=row.adjust_hours,
            notes=row.notes,
        ))
    for row in db.query(CIPNonBillableAllocation).filter(CIPNonBillableAllocation.revision_id == src.id).all():
        db.add(CIPNonBillableAllocation(
            revision_id=rev.id,
            line_key=row.line_key,
            hours=row.hours,
            notes=row.notes,
        ))
    cip_recalculate_and_store(db, rev)
    db.commit()
    return rev


def register_revision_history(app, core):
    # Replace the legacy lifecycle and revision endpoints after MEP/CIP dispatch has been registered.
    _take_route(app, "/estimate/{rid}/status/{action}", "POST")
    _take_route(app, "/estimate/{rid}/new-revision", "POST")

    @app.get("/estimate/{rid}/revisions", response_class=HTMLResponse)
    def revision_history(rid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        rev = core.revision_or_404(db, rid)
        revisions = db.query(EstimateRevision).filter(
            EstimateRevision.estimate_id == rev.estimate_id
        ).order_by(desc(EstimateRevision.revision_no)).all()
        users = {row.id: row.username for row in db.query(User).all()}
        configs = {
            row.id: row.name
            for row in db.query(ConfigurationVersion).filter(
                ConfigurationVersion.id.in_({r.config_version_id for r in revisions})
            ).all()
        }
        approval_events = db.query(AuditEvent).filter(
            AuditEvent.estimate_id == rev.estimate_id,
            AuditEvent.event_type == "ESTIMATE_APPROVED",
        ).order_by(desc(AuditEvent.created_at)).all()
        approved_by_revision = {}
        for event in approval_events:
            approved_by_revision.setdefault(event.revision_id, event)
        current_approved = next((r for r in revisions if r.status in ("APPROVED", "FINAL")), None)
        working = next((r for r in revisions if r.status in WORKING_STATUSES), None)
        rows = []
        for item in revisions:
            event = approved_by_revision.get(item.id)
            rows.append({
                "rev": item,
                "config_name": configs.get(item.config_version_id, f"Config {item.config_version_id}"),
                "created_by": users.get(item.created_by, "System"),
                "approved_at": event.created_at if event else None,
                "approved_by": users.get(event.user_id, "System") if event else "",
                "is_current_approved": bool(current_approved and current_approved.id == item.id),
            })
        return core.templates.TemplateResponse("revision_history.html", {
            "request": request,
            "user": user,
            "rev": rev,
            "estimate": rev.estimate,
            "rows": rows,
            "working": working,
            "current_approved": current_approved,
            "product_type": revision_product(db, rev),
        })

    @app.post("/estimate/{rid}/new-revision")
    def new_revision(rid: int, request: Request, rebase: bool = False, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
        src = core.revision_or_404(db, rid)
        if src.status not in LOCKED_STATUSES:
            raise HTTPException(409, "Create a new revision only from an Approved, Final, or Superseded revision.")

        working = _working_revision(db, src.estimate_id, exclude_id=src.id)
        if working:
            # Do not create competing Draft/Review branches. Return the user to the active working revision.
            return RedirectResponse(f"/estimate/{working.id}", 303)

        if revision_product(db, src) == PRODUCT_CIP:
            new_rev = _copy_cip_with_adjustments(db, core, src, user, rebase)
        else:
            new_rev = _copy_mep_revision(db, core, src, user, rebase)
        return RedirectResponse(f"/estimate/{new_rev.id}", 303)

    @app.post("/estimate/{rid}/status/{action}")
    def status_action(rid: int, action: str, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        rev = core.revision_or_404(db, rid)
        action = action.lower()
        old = rev.status

        if action == "submit":
            core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
            if old != "DRAFT":
                raise HTTPException(409, "Only a Draft revision can be submitted for review.")
            new = "REVIEW"
        elif action == "return":
            core.require_role(user, "ADMIN", "REVIEWER", "APPROVER")
            if old != "REVIEW":
                raise HTTPException(409, "Only a revision in Review can be returned to Draft.")
            new = "DRAFT"
        elif action == "approve":
            core.require_role(user, "ADMIN", "APPROVER")
            if old != "REVIEW":
                raise HTTPException(409, "Only a revision in Review can be approved.")
            latest = db.query(EstimateRevision).filter(
                EstimateRevision.estimate_id == rev.estimate_id
            ).order_by(desc(EstimateRevision.revision_no)).first()
            if latest and latest.id != rev.id:
                raise HTTPException(409, "Only the latest revision can be approved.")

            # The previous approved revision remains valid through Draft/Review and is superseded
            # only as part of the atomic approval of this newer revision.
            prior_approved = db.query(EstimateRevision).filter(
                EstimateRevision.estimate_id == rev.estimate_id,
                EstimateRevision.id != rev.id,
                EstimateRevision.status.in_(("APPROVED", "FINAL")),
            ).all()
            for prior in prior_approved:
                prior_old = prior.status
                prior.status = "SUPERSEDED"
                record(
                    db,
                    event_type="ESTIMATE_SUPERSEDED",
                    user_id=user.id,
                    estimate_id=prior.estimate_id,
                    revision_id=prior.id,
                    old_value=prior_old,
                    new_value="SUPERSEDED",
                    reason=f"Superseded by approval of Rev {rev.revision_no}",
                )
            new = "APPROVED"
        elif action == "supersede":
            core.require_role(user, "ADMIN", "APPROVER")
            if old not in ("APPROVED", "FINAL"):
                raise HTTPException(409, "Only an Approved or Final revision can be superseded.")
            new = "SUPERSEDED"
        else:
            raise HTTPException(400, "Unknown action")

        rev.status = new
        record(
            db,
            event_type=f"ESTIMATE_{new}",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            old_value=old,
            new_value=new,
        )
        db.commit()
        return RedirectResponse(f"/estimate/{rid}", 303)
