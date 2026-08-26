"""Version SOW renderer composition behavior.

Revision ID: b72e19c4d3a8
Revises: a31c7e92f615
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b72e19c4d3a8"
down_revision: Union[str, Sequence[str], None] = "a31c7e92f615"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing controlled SOWs are renderer version 1. New v0.3.19 SOW creation
    # explicitly opts into version 2 so historical approved hashes remain reproducible.
    op.add_column(
        "sows",
        sa.Column(
            "composition_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sows", "composition_version")
