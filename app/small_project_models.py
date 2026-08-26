from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Install mode is only meaningful for MEP Small Project. Cloud and On-Premises are
# mutually exclusive, and neither is required when no installation work is in scope.
# CIP Small Project remains hosted-only and therefore uses "None".
SMALL_PROJECT_INSTALL_MODES = ("Cloud", "On_Prem", "None")
SMALL_PROJECT_METHODOLOGY_MODES = ("Auto", "Include", "Exclude")


class SmallProjectSOWConfig(Base):
    """Top-level persisted Small Project configuration for one SOW."""

    __tablename__ = "small_project_sow_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sow_id: Mapped[int] = mapped_column(
        ForeignKey("sows.id", ondelete="CASCADE"), unique=True, index=True
    )
    install_mode: Mapped[str] = mapped_column(String(20), default="None")
    key_user_training_count: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    deliverables: Mapped[list["SmallProjectSOWDeliverable"]] = relationship(
        cascade="all, delete-orphan",
        order_by="SmallProjectSOWDeliverable.sort_order",
    )
    methodologies: Mapped[list["SmallProjectSOWMethodology"]] = relationship(
        cascade="all, delete-orphan",
        order_by="SmallProjectSOWMethodology.sort_order",
    )


class SmallProjectSOWDeliverable(Base):
    """One modular Small Project deliverable section."""

    __tablename__ = "small_project_sow_deliverables"
    __table_args__ = (
        UniqueConstraint(
            "config_id", "deliverable_key", name="uq_sp_sow_deliverable_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("small_project_sow_configs.id", ondelete="CASCADE"), index=True
    )
    deliverable_key: Mapped[str] = mapped_column(String(60))
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    scope_description: Mapped[str] = mapped_column(Text, default="")
    detail_notes: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SmallProjectSOWMethodology(Base):
    """One methodology section and its Auto/Include/Exclude control."""

    __tablename__ = "small_project_sow_methodologies"
    __table_args__ = (
        UniqueConstraint(
            "config_id", "methodology_key", name="uq_sp_sow_methodology_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("small_project_sow_configs.id", ondelete="CASCADE"), index=True
    )
    methodology_key: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(20), default="Auto")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
