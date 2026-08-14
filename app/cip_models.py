from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

PRODUCT_MEP = "MEP"
PRODUCT_CIP = "CIP"


class EstimateProduct(Base):
    __tablename__ = "estimate_products"
    estimate_id: Mapped[int] = mapped_column(ForeignKey("estimates.id", ondelete="CASCADE"), primary_key=True)
    product_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)


class ConfigurationProduct(Base):
    __tablename__ = "configuration_products"
    config_version_id: Mapped[int] = mapped_column(ForeignKey("configuration_versions.id", ondelete="CASCADE"), primary_key=True)
    product_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)


class CIPRevisionInput(Base):
    __tablename__ = "cip_revision_inputs"
    revision_id: Mapped[int] = mapped_column(ForeignKey("estimate_revisions.id", ondelete="CASCADE"), primary_key=True)
    release_key: Mapped[str] = mapped_column(String(40), nullable=False)
    deployed_over: Mapped[str] = mapped_column(String(80), default="Standalone")
    project_type: Mapped[str] = mapped_column(String(80), default="CIP Install")
    gateway: Mapped[bool] = mapped_column(Boolean, default=False)
    epp_install: Mapped[str] = mapped_column(String(30), default="No")
    label_sites: Mapped[int] = mapped_column(Integer, default=0)
    labels_required: Mapped[bool] = mapped_column(Boolean, default=False)
    label_count: Mapped[int] = mapped_column(Integer, default=0)
    custom_boomi_required: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_boomi_count: Mapped[int] = mapped_column(Integer, default=0)
    rest_required: Mapped[bool] = mapped_column(Boolean, default=False)
    rest_interface_count: Mapped[int] = mapped_column(Integer, default=0)
    consultant_access_setup: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding: Mapped[bool] = mapped_column(Boolean, default=False)
    user_count: Mapped[str] = mapped_column(String(40), default="1 to 50")
    testing_cycles: Mapped[int] = mapped_column(Integer, default=1)
    go_live_sites: Mapped[int] = mapped_column(Integer, default=0)
    go_live_type: Mapped[str] = mapped_column(String(60), default="None")
    uat_sites: Mapped[int] = mapped_column(Integer, default=1)
    base_test_pct: Mapped[float] = mapped_column(Float, default=0.20)
    security_method: Mapped[str] = mapped_column(String(30), default="None")
    pacejet: Mapped[bool] = mapped_column(Boolean, default=False)
    write_test_scripts: Mapped[bool] = mapped_column(Boolean, default=False)
    end_user_documentation: Mapped[bool] = mapped_column(Boolean, default=False)
    end_user_training: Mapped[bool] = mapped_column(Boolean, default=False)
    cip_desktop_dev_training: Mapped[bool] = mapped_column(Boolean, default=False)
    mobile_dev_training: Mapped[bool] = mapped_column(Boolean, default=False)
    test_ihu: Mapped[bool] = mapped_column(Boolean, default=False)
    test_lot_serial: Mapped[bool] = mapped_column(Boolean, default=False)
    test_food_pharma: Mapped[bool] = mapped_column(Boolean, default=False)
    test_location_dimension: Mapped[bool] = mapped_column(Boolean, default=False)
    test_setup_customer_data: Mapped[bool] = mapped_column(Boolean, default=False)
    test_monitored_session: Mapped[bool] = mapped_column(Boolean, default=False)
    low_factor: Mapped[float] = mapped_column(Float, default=0.10)
    high_factor: Mapped[float] = mapped_column(Float, default=0.25)


class CIPScopeItem(Base):
    __tablename__ = "cip_scope_items"
    __table_args__ = (UniqueConstraint("revision_id", "category", "catalog_key", name="uq_cip_scope_revision_category_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("estimate_revisions.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    catalog_key: Mapped[str] = mapped_column(String(180))
    label: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    config_type: Mapped[str] = mapped_column(String(40), default="No Config")
    added_hours: Mapped[float] = mapped_column(Float, default=0)
    adjustment_notes: Mapped[str] = mapped_column(Text, default="")
    testing_adjustment: Mapped[float] = mapped_column(Float, default=0)
    testing_notes: Mapped[str] = mapped_column(Text, default="")
    app_count: Mapped[int] = mapped_column(Integer, default=0)
    integration_added_hours: Mapped[float] = mapped_column(Float, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class CIPNonBillableAllocation(Base):
    __tablename__ = "cip_nonbillable_allocations"
    __table_args__ = (UniqueConstraint("revision_id", "line_key", name="uq_cip_nonbillable_revision_line"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("estimate_revisions.id", ondelete="CASCADE"), index=True)
    line_key: Mapped[str] = mapped_column(String(140))
    hours: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
