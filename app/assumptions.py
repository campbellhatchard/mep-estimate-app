from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .database import Base, get_db
from .models import EstimateRevision
from .services.audit import record


class EstimateAssumption(Base):
    __tablename__ = "estimate_assumptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("estimate_revisions.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# SQLAlchemy declarative classes support adding mapped relationships after class declaration.
# Keeping this shared revision feature outside the MEP-specific model block avoids coupling
# assumptions to either estimating product.
if not hasattr(EstimateRevision, "assumptions"):
    EstimateRevision.assumptions = relationship(
        EstimateAssumption,
        cascade="all, delete-orphan",
        order_by=EstimateAssumption.sort_order,
        lazy="select",
    )


def _editable_revision(core, db: Session, request: Request, rid: int):
    user = core.current_user(request, db)
    core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
    rev = core.revision_or_404(db, rid)
    if rev.status != "DRAFT":
        raise HTTPException(409, "Assumptions can only be changed while the revision is Draft.")
    return user, rev


def _assumption_or_404(db: Session, rid: int, aid: int) -> EstimateAssumption:
    row = db.query(EstimateAssumption).filter(
        EstimateAssumption.id == aid,
        EstimateAssumption.revision_id == rid,
    ).first()
    if not row:
        raise HTTPException(404, "Assumption not found")
    return row


def register_assumption_routes(app, core):
    @app.post("/estimate/{rid}/assumptions")
    def add_assumption(rid: int, request: Request, db: Session = Depends(get_db)):
        user, rev = _editable_revision(core, db, request, rid)
        max_order = db.query(func.max(EstimateAssumption.sort_order)).filter(
            EstimateAssumption.revision_id == rid
        ).scalar()
        row = EstimateAssumption(revision_id=rid, text="", sort_order=int(max_order or 0) + 1)
        db.add(row)
        db.flush()
        record(
            db,
            event_type="ASSUMPTION_ADDED",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            field_name=f"ASSUMPTION:{row.id}",
            new_value="",
        )
        db.commit()
        return JSONResponse({"id": row.id, "sort_order": row.sort_order, "text": row.text})

    @app.post("/estimate/{rid}/assumptions/{aid}")
    async def update_assumption(rid: int, aid: int, request: Request, db: Session = Depends(get_db)):
        user, rev = _editable_revision(core, db, request, rid)
        row = _assumption_or_404(db, rid, aid)
        form = await request.form()
        text = str(form.get("text", "")).strip()
        if len(text) > 5000:
            raise HTTPException(400, "An assumption cannot exceed 5,000 characters.")
        if text != row.text:
            old = row.text
            row.text = text
            record(
                db,
                event_type="ASSUMPTION_UPDATED",
                user_id=user.id,
                estimate_id=rev.estimate_id,
                revision_id=rev.id,
                field_name=f"ASSUMPTION:{row.id}",
                old_value=old,
                new_value=text,
            )
            db.commit()
        return JSONResponse({"id": row.id, "text": row.text})

    @app.post("/estimate/{rid}/assumptions/{aid}/delete")
    def delete_assumption(rid: int, aid: int, request: Request, db: Session = Depends(get_db)):
        user, rev = _editable_revision(core, db, request, rid)
        row = _assumption_or_404(db, rid, aid)
        old = row.text
        record(
            db,
            event_type="ASSUMPTION_DELETED",
            user_id=user.id,
            estimate_id=rev.estimate_id,
            revision_id=rev.id,
            field_name=f"ASSUMPTION:{row.id}",
            old_value=old,
        )
        db.delete(row)
        db.commit()
        return JSONResponse({"deleted": aid})
