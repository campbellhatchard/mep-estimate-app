"""Add revision-level estimate assumptions.

Revision ID: d8e4a2b7c901
Revises: c3f0a9d271b4
Create Date: 2026-08-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e4a2b7c901"
down_revision: Union[str, Sequence[str], None] = "c3f0a9d271b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "estimate_assumptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["estimate_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_estimate_assumptions_revision_id", "estimate_assumptions", ["revision_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_estimate_assumptions_revision_id", table_name="estimate_assumptions")
    op.drop_table("estimate_assumptions")
