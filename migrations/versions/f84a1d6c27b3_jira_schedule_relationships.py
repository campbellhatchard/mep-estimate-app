"""Add explicit Jira schedule task relationships.

Revision ID: f84a1d6c27b3
Revises: b72e19c4d3a8
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa


revision = "f84a1d6c27b3"
down_revision = "b72e19c4d3a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_task_relationships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("source_task_id", sa.Integer(), nullable=False),
        sa.Column("target_task_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(length=40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["estimate_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_task_id"], ["schedule_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_task_id"], ["schedule_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id",
            "source_task_id",
            "target_task_id",
            "relationship_type",
            name="uq_schedule_task_relationship",
        ),
    )
    op.create_index(
        op.f("ix_schedule_task_relationships_revision_id"),
        "schedule_task_relationships",
        ["revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_schedule_task_relationships_source_task_id"),
        "schedule_task_relationships",
        ["source_task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_schedule_task_relationships_target_task_id"),
        "schedule_task_relationships",
        ["target_task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_schedule_task_relationships_relationship_type"),
        "schedule_task_relationships",
        ["relationship_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_schedule_task_relationships_relationship_type"),
        table_name="schedule_task_relationships",
    )
    op.drop_index(
        op.f("ix_schedule_task_relationships_target_task_id"),
        table_name="schedule_task_relationships",
    )
    op.drop_index(
        op.f("ix_schedule_task_relationships_source_task_id"),
        table_name="schedule_task_relationships",
    )
    op.drop_index(
        op.f("ix_schedule_task_relationships_revision_id"),
        table_name="schedule_task_relationships",
    )
    op.drop_table("schedule_task_relationships")
