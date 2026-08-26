from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


SOW_TEMPLATE_MEP_NET_NEW = "MEP_NET_NEW"
SOW_STATUSES = ("DRAFT", "FINALIZED", "PENDING_APPROVAL", "APPROVED", "REJECTED")


class SOWTemplateVersion(Base):
    __tablename__ = "sow_template_versions"
    __table_args__ = (UniqueConstraint("template_key", "version_no", name="uq_sow_template_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    template_key: Mapped[str] = mapped_column(String(60), index=True)
    label: Mapped[str] = mapped_column(String(160))
    product_type: Mapped[str] = mapped_column(String(20), default="MEP")
    customer_type: Mapped[str] = mapped_column(String(40), default="Net_New")
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_sha256: Mapped[str] = mapped_column(String(64))
    change_reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    activated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SOW(Base):
    __tablename__ = "sows"
    __table_args__ = (UniqueConstraint("estimate_revision_id", "sow_revision_no", name="uq_sow_estimate_revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    estimate_revision_id: Mapped[int] = mapped_column(ForeignKey("estimate_revisions.id"), index=True)
    template_version_id: Mapped[int] = mapped_column(ForeignKey("sow_template_versions.id"), index=True)
    sow_revision_no: Mapped[int] = mapped_column(Integer, default=1)
    # Renderer/composition behavior is persisted so later document enhancements never
    # retroactively change an approved historical SOW's canonical content/hash.
    composition_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    sow_date: Mapped[date] = mapped_column(Date)
    agreement_type: Mapped[str] = mapped_column(String(160), default="Software as a Service Agreement")
    invoice_frequency: Mapped[str] = mapped_column(String(20), default="Weekly")
    project_objective: Mapped[str] = mapped_column(Text, default="")
    rest_api_required: Mapped[bool] = mapped_column(Boolean, default=False)
    barcode_printer_count: Mapped[int] = mapped_column(Integer, default=0)
    erp_version: Mapped[str] = mapped_column(String(160), default="")
    erp_base_code_version: Mapped[str] = mapped_column(String(160), default="")
    erp_tools_release: Mapped[str] = mapped_column(String(160), default="")
    erp_os_version: Mapped[str] = mapped_column(String(200), default="")
    erp_database_version: Mapped[str] = mapped_column(String(200), default="")
    mep_product_version: Mapped[str] = mapped_column(String(160), default="")
    epp_product_version: Mapped[str] = mapped_column(String(160), default="")
    print_methods: Mapped[str] = mapped_column(Text, default="")
    erp_deployment_model: Mapped[str] = mapped_column(String(200), default="")
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approved_text_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finalized_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submitted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    approver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejected_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    template_version: Mapped[SOWTemplateVersion] = relationship()
    hypercare_locations: Mapped[list["SOWHypercareLocation"]] = relationship(cascade="all, delete-orphan", order_by="SOWHypercareLocation.sort_order")
    devices: Mapped[list["SOWDevice"]] = relationship(cascade="all, delete-orphan", order_by="SOWDevice.sort_order")


class SOWHypercareLocation(Base):
    __tablename__ = "sow_hypercare_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    sow_id: Mapped[int] = mapped_column(ForeignKey("sows.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(240), default="")
    country: Mapped[str] = mapped_column(String(120), default="")
    support_type: Mapped[str] = mapped_column(String(40), default="Remote")
    allocated_hours: Mapped[float] = mapped_column(Float, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SOWDevice(Base):
    __tablename__ = "sow_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    sow_id: Mapped[int] = mapped_column(ForeignKey("sows.id", ondelete="CASCADE"), index=True)
    device_type: Mapped[str] = mapped_column(String(120), default="Handheld Unit")
    make_model: Mapped[str] = mapped_column(String(240), default="")
    os_version: Mapped[str] = mapped_column(String(160), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
