"""Add Small Project SOW persisted configuration foundation.

Revision ID: a31c7e92f615
Revises: e91f4c2a6b10
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a31c7e92f615"
down_revision: Union[str, Sequence[str], None] = "e91f4c2a6b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "small_project_sow_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sow_id", sa.Integer(), nullable=False),
        sa.Column("install_mode", sa.String(length=20), nullable=False),
        sa.Column("key_user_training_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["sow_id"], ["sows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sow_id", name="uq_small_project_sow_config_sow"),
    )
    op.create_index(
        "ix_small_project_sow_configs_sow_id",
        "small_project_sow_configs",
        ["sow_id"],
        unique=False,
    )

    op.create_table(
        "small_project_sow_deliverables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.Integer(), nullable=False),
        sa.Column("deliverable_key", sa.String(length=60), nullable=False),
        sa.Column("include", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scope_description", sa.Text(), nullable=False),
        sa.Column("detail_notes", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["config_id"], ["small_project_sow_configs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "config_id", "deliverable_key", name="uq_sp_sow_deliverable_key"
        ),
    )
    op.create_index(
        "ix_small_project_sow_deliverables_config_id",
        "small_project_sow_deliverables",
        ["config_id"],
        unique=False,
    )

    op.create_table(
        "small_project_sow_methodologies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.Integer(), nullable=False),
        sa.Column("methodology_key", sa.String(length=60), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["config_id"], ["small_project_sow_configs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "config_id", "methodology_key", name="uq_sp_sow_methodology_key"
        ),
    )
    op.create_index(
        "ix_small_project_sow_methodologies_config_id",
        "small_project_sow_methodologies",
        ["config_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_small_project_sow_methodologies_config_id",
        table_name="small_project_sow_methodologies",
    )
    op.drop_table("small_project_sow_methodologies")
    op.drop_index(
        "ix_small_project_sow_deliverables_config_id",
        table_name="small_project_sow_deliverables",
    )
    op.drop_table("small_project_sow_deliverables")
    op.drop_index(
        "ix_small_project_sow_configs_sow_id",
        table_name="small_project_sow_configs",
    )
    op.drop_table("small_project_sow_configs")
