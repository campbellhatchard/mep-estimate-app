"""small project SOW configuration

Revision ID: f4a9c3d2e811
Revises: e91f4c2a6b10
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "f4a9c3d2e811"
down_revision = "e91f4c2a6b10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "small_project_sow_configs",
        sa.Column("sow_id", sa.Integer(), nullable=False),
        sa.Column("contracting_entity", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("mep_install_mode", sa.String(length=30), nullable=False, server_default=""),
        sa.Column("epp_deployment_model", sa.String(length=30), nullable=False, server_default=""),
        sa.Column("key_user_count", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("deliverables_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("methodology_json", sa.Text(), nullable=False, server_default="[]"),
        sa.ForeignKeyConstraint(["sow_id"], ["sows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("sow_id"),
    )


def downgrade():
    op.drop_table("small_project_sow_configs")
