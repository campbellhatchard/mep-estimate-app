from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .assumptions import EstimateAssumption
from .cip_models import CIPNonBillableAllocation, CIPRevisionInput, CIPScopeItem, EstimateProduct
from .database import get_db
from .models import (
    AuditEvent,
    CalculationAdjustment,
    DetailAdjustment,
    Estimate,
    EstimateApplication,
    EstimateCustomApplication,
    EstimateRevision,
    ScheduleTask,
)
from .sow_models import SOW, SOWDevice, SOWHypercareLocation


DELETE_ROLES = ("ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")


def _delete_for_revision_ids(db: Session, model, revision_ids: list[int]) -> None:
    if not revision_ids:
        return
    db.query(model).filter(model.revision_id.in_(revision_ids)).delete(synchronize_session=False)


def _delete_sow_data(db: Session, revision_ids: list[int]) -> None:
    if not revision_ids:
        return
    sow_ids = [row[0] for row in db.query(SOW.id).filter(SOW.estimate_revision_id.in_(revision_ids)).all()]
    if not sow_ids:
        return
    db.query(SOWHypercareLocation).filter(SOWHypercareLocation.sow_id.in_(sow_ids)).delete(synchronize_session=False)
    db.query(SOWDevice).filter(SOWDevice.sow_id.in_(sow_ids)).delete(synchronize_session=False)

    # Future SOW extensions are expected to use an on-delete cascade from sows. The
    # explicit child cleanup above also keeps SQLite regression tests deterministic.
    db.query(SOW).filter(SOW.id.in_(sow_ids)).delete(synchronize_session=False)


def register_estimate_delete(app, core) -> None:
    @app.post("/estimate/{rid}/delete")
    def delete_estimate(rid: int, request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, *DELETE_ROLES)
        rev = db.get(EstimateRevision, rid)
        if not rev:
            raise HTTPException(404, "Estimate revision not found")

        estimate = db.get(Estimate, rev.estimate_id)
        if not estimate:
            raise HTTPException(404, "Estimate not found")

        revisions = (
            db.query(EstimateRevision)
            .filter(EstimateRevision.estimate_id == estimate.id)
            .order_by(EstimateRevision.revision_no)
            .all()
        )

        # A permanent Estimate delete is intentionally limited to the original Draft.
        # Once an estimate has historical revisions, the record is part of the controlled
        # approval history and cannot be removed by this action.
        if (
            len(revisions) != 1
            or revisions[0].id != rid
            or revisions[0].status != "DRAFT"
        ):
            raise HTTPException(
                409,
                "Only an estimate with a single Draft revision can be permanently deleted.",
            )

        revision_ids = [item.id for item in revisions]
        estimate_id = estimate.id

        try:
            _delete_sow_data(db, revision_ids)

            _delete_for_revision_ids(db, EstimateAssumption, revision_ids)
            _delete_for_revision_ids(db, CIPNonBillableAllocation, revision_ids)
            _delete_for_revision_ids(db, CIPScopeItem, revision_ids)
            _delete_for_revision_ids(db, ScheduleTask, revision_ids)
            _delete_for_revision_ids(db, CalculationAdjustment, revision_ids)
            _delete_for_revision_ids(db, DetailAdjustment, revision_ids)
            _delete_for_revision_ids(db, EstimateApplication, revision_ids)
            _delete_for_revision_ids(db, EstimateCustomApplication, revision_ids)

            db.query(CIPRevisionInput).filter(CIPRevisionInput.revision_id.in_(revision_ids)).delete(synchronize_session=False)

            # Deletion is permanent, so estimate/revision audit rows are removed with the
            # estimate rather than retaining orphaned business data.
            db.query(AuditEvent).filter(
                (AuditEvent.estimate_id == estimate_id) | (AuditEvent.revision_id.in_(revision_ids))
            ).delete(synchronize_session=False)

            db.query(EstimateRevision).filter(EstimateRevision.id.in_(revision_ids)).delete(synchronize_session=False)
            db.query(EstimateProduct).filter(EstimateProduct.estimate_id == estimate_id).delete(synchronize_session=False)
            db.query(Estimate).filter(Estimate.id == estimate_id).delete(synchronize_session=False)
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(
                409,
                "The estimate could not be deleted because dependent data remains. No data was removed.",
            ) from exc

        return RedirectResponse("/estimates", status_code=303)
