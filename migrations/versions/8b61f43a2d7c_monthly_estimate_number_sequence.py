"""Add monthly estimate number sequence table.

Revision ID: 8b61f43a2d7c
Revises: 7f2a6c4d91e0
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8b61f43a2d7c"
down_revision: Union[str, None] = "7f2a6c4d91e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "estimate_number_sequences",
        sa.Column("period_key", sa.String(length=6), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("period_key"),
    )

    # Defensive backfill for any database that already contains YYYYMMNNN estimates.
    # Existing pre-v0.2.1 estimate numbers are shorter and therefore do not participate.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO estimate_number_sequences (period_key, last_number)
            SELECT SUBSTR(estimate_number, 1, 6),
                   MAX(CAST(SUBSTR(estimate_number, 7, 3) AS INTEGER))
            FROM estimates
            WHERE LENGTH(estimate_number) = 9
            GROUP BY SUBSTR(estimate_number, 1, 6)
            """
        )
    )


def downgrade() -> None:
    op.drop_table("estimate_number_sequences")
