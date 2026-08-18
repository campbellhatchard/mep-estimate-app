"""Add controlled MEP SOW template and approval workflow.

Revision ID: e91f4c2a6b10
Revises: d8e4a2b7c901
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e91f4c2a6b10"
down_revision: Union[str, Sequence[str], None] = "d8e4a2b7c901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sow_template_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_key", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("product_type", sa.String(length=20), nullable=False),
        sa.Column("customer_type", sa.String(length=40), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_by", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["activated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key", "version_no", name="uq_sow_template_version"),
    )
    op.create_index("ix_sow_template_versions_template_key", "sow_template_versions", ["template_key"], unique=False)
    op.create_index("ix_sow_template_versions_status", "sow_template_versions", ["status"], unique=False)

    op.create_table(
        "sows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("estimate_revision_id", sa.Integer(), nullable=False),
        sa.Column("template_version_id", sa.Integer(), nullable=False),
        sa.Column("sow_revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("sow_date", sa.Date(), nullable=False),
        sa.Column("agreement_type", sa.String(length=160), nullable=False),
        sa.Column("invoice_frequency", sa.String(length=20), nullable=False),
        sa.Column("project_objective", sa.Text(), nullable=False),
        sa.Column("rest_api_required", sa.Boolean(), nullable=False),
        sa.Column("barcode_printer_count", sa.Integer(), nullable=False),
        sa.Column("erp_version", sa.String(length=160), nullable=False),
        sa.Column("erp_base_code_version", sa.String(length=160), nullable=False),
        sa.Column("erp_tools_release", sa.String(length=160), nullable=False),
        sa.Column("erp_os_version", sa.String(length=200), nullable=False),
        sa.Column("erp_database_version", sa.String(length=200), nullable=False),
        sa.Column("mep_product_version", sa.String(length=160), nullable=False),
        sa.Column("epp_product_version", sa.String(length=160), nullable=False),
        sa.Column("print_methods", sa.Text(), nullable=False),
        sa.Column("erp_deployment_model", sa.String(length=200), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("approved_text_snapshot", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finalized_by", sa.Integer(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_by", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("approver_id", sa.Integer(), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by", sa.Integer(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["estimate_revision_id"], ["estimate_revisions.id"]),
        sa.ForeignKeyConstraint(["template_version_id"], ["sow_template_versions.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["finalized_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("estimate_revision_id", "sow_revision_no", name="uq_sow_estimate_revision"),
    )
    op.create_index("ix_sows_estimate_revision_id", "sows", ["estimate_revision_id"], unique=False)
    op.create_index("ix_sows_template_version_id", "sows", ["template_version_id"], unique=False)
    op.create_index("ix_sows_status", "sows", ["status"], unique=False)
    op.create_index("ix_sows_approver_id", "sows", ["approver_id"], unique=False)

    op.create_table(
        "sow_hypercare_locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sow_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.Column("country", sa.String(length=120), nullable=False),
        sa.Column("support_type", sa.String(length=40), nullable=False),
        sa.Column("allocated_hours", sa.Float(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["sow_id"], ["sows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sow_hypercare_locations_sow_id", "sow_hypercare_locations", ["sow_id"], unique=False)

    op.create_table(
        "sow_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sow_id", sa.Integer(), nullable=False),
        sa.Column("device_type", sa.String(length=120), nullable=False),
        sa.Column("make_model", sa.String(length=240), nullable=False),
        sa.Column("os_version", sa.String(length=160), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["sow_id"], ["sows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sow_devices_sow_id", "sow_devices", ["sow_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sow_devices_sow_id", table_name="sow_devices")
    op.drop_table("sow_devices")
    op.drop_index("ix_sow_hypercare_locations_sow_id", table_name="sow_hypercare_locations")
    op.drop_table("sow_hypercare_locations")
    op.drop_index("ix_sows_approver_id", table_name="sows")
    op.drop_index("ix_sows_status", table_name="sows")
    op.drop_index("ix_sows_template_version_id", table_name="sows")
    op.drop_index("ix_sows_estimate_revision_id", table_name="sows")
    op.drop_table("sows")
    op.drop_index("ix_sow_template_versions_status", table_name="sow_template_versions")
    op.drop_index("ix_sow_template_versions_template_key", table_name="sow_template_versions")
    op.drop_table("sow_template_versions")
