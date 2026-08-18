"""Add Cloud Inventory Platform estimating domain.

Revision ID: c3f0a9d271b4
Revises: 8b61f43a2d7c
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3f0a9d271b4"
down_revision: Union[str, None] = "8b61f43a2d7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("estimate_products", sa.Column("estimate_id", sa.Integer(), nullable=False), sa.Column("product_type", sa.String(length=10), nullable=False), sa.ForeignKeyConstraint(["estimate_id"], ["estimates.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("estimate_id"))
    op.create_index(op.f("ix_estimate_products_product_type"), "estimate_products", ["product_type"], unique=False)
    op.create_table("configuration_products", sa.Column("config_version_id", sa.Integer(), nullable=False), sa.Column("product_type", sa.String(length=10), nullable=False), sa.ForeignKeyConstraint(["config_version_id"], ["configuration_versions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("config_version_id"))
    op.create_index(op.f("ix_configuration_products_product_type"), "configuration_products", ["product_type"], unique=False)
    op.create_table(
        "cip_revision_inputs",
        sa.Column("revision_id", sa.Integer(), nullable=False), sa.Column("release_key", sa.String(length=40), nullable=False),
        sa.Column("deployed_over", sa.String(length=80), nullable=False, server_default="Standalone"), sa.Column("project_type", sa.String(length=80), nullable=False, server_default="CIP Install"),
        sa.Column("gateway", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("epp_install", sa.String(length=30), nullable=False, server_default="No"),
        sa.Column("label_sites", sa.Integer(), nullable=False, server_default="0"), sa.Column("labels_required", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("label_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("custom_boomi_required", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("custom_boomi_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rest_required", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("rest_interface_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consultant_access_setup", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("onboarding", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("user_count", sa.String(length=40), nullable=False, server_default="1 to 50"), sa.Column("testing_cycles", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("go_live_sites", sa.Integer(), nullable=False, server_default="0"), sa.Column("go_live_type", sa.String(length=60), nullable=False, server_default="None"),
        sa.Column("uat_sites", sa.Integer(), nullable=False, server_default="1"), sa.Column("base_test_pct", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("security_method", sa.String(length=30), nullable=False, server_default="None"), sa.Column("pacejet", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_test_scripts", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("end_user_documentation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("end_user_training", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("cip_desktop_dev_training", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mobile_dev_training", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("test_ihu", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("test_lot_serial", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("test_food_pharma", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("test_location_dimension", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("test_setup_customer_data", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("test_monitored_session", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("low_factor", sa.Float(), nullable=False, server_default="0.1"), sa.Column("high_factor", sa.Float(), nullable=False, server_default="0.25"),
        sa.ForeignKeyConstraint(["revision_id"], ["estimate_revisions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("revision_id"),
    )
    op.create_table(
        "cip_scope_items", sa.Column("id", sa.Integer(), nullable=False), sa.Column("revision_id", sa.Integer(), nullable=False), sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("catalog_key", sa.String(length=180), nullable=False), sa.Column("label", sa.String(length=300), nullable=False, server_default=""), sa.Column("description", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("config_type", sa.String(length=40), nullable=False, server_default="No Config"), sa.Column("added_hours", sa.Float(), nullable=False, server_default="0"),
        sa.Column("adjustment_notes", sa.Text(), nullable=False, server_default=""), sa.Column("testing_adjustment", sa.Float(), nullable=False, server_default="0"), sa.Column("testing_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("app_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("integration_added_hours", sa.Float(), nullable=False, server_default="0"), sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["revision_id"], ["estimate_revisions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("revision_id", "category", "catalog_key", name="uq_cip_scope_revision_category_key"),
    )
    op.create_index(op.f("ix_cip_scope_items_revision_id"), "cip_scope_items", ["revision_id"], unique=False); op.create_index(op.f("ix_cip_scope_items_category"), "cip_scope_items", ["category"], unique=False)
    op.create_table("cip_nonbillable_allocations", sa.Column("id", sa.Integer(), nullable=False), sa.Column("revision_id", sa.Integer(), nullable=False), sa.Column("line_key", sa.String(length=140), nullable=False), sa.Column("hours", sa.Float(), nullable=False, server_default="0"), sa.Column("notes", sa.Text(), nullable=False, server_default=""), sa.ForeignKeyConstraint(["revision_id"], ["estimate_revisions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("revision_id", "line_key", name="uq_cip_nonbillable_revision_line"))
    op.create_index(op.f("ix_cip_nonbillable_allocations_revision_id"), "cip_nonbillable_allocations", ["revision_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cip_nonbillable_allocations_revision_id"), table_name="cip_nonbillable_allocations"); op.drop_table("cip_nonbillable_allocations")
    op.drop_index(op.f("ix_cip_scope_items_category"), table_name="cip_scope_items"); op.drop_index(op.f("ix_cip_scope_items_revision_id"), table_name="cip_scope_items"); op.drop_table("cip_scope_items")
    op.drop_table("cip_revision_inputs"); op.drop_index(op.f("ix_configuration_products_product_type"), table_name="configuration_products"); op.drop_table("configuration_products")
    op.drop_index(op.f("ix_estimate_products_product_type"), table_name="estimate_products"); op.drop_table("estimate_products")
