from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ScheduleTaskRelationship(Base):
    __tablename__ = "schedule_task_relationships"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "source_task_id",
            "target_task_id",
            "relationship_type",
            name="uq_schedule_task_relationship",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey("estimate_revisions.id", ondelete="CASCADE"), index=True
    )
    source_task_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_tasks.id", ondelete="CASCADE"), index=True
    )
    target_task_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_tasks.id", ondelete="CASCADE"), index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(40), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
