"""Add multi-role user assignments and email address.

Revision ID: 7f2a6c4d91e0
Revises: 4dc3c5aaf598
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7f2a6c4d91e0"
down_revision: Union[str, None] = "4dc3c5aaf598"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.create_table(
        "user_roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role", name="uq_user_role"),
    )
    op.create_index(op.f("ix_user_roles_role"), "user_roles", ["role"], unique=False)
    op.create_index(op.f("ix_user_roles_user_id"), "user_roles", ["user_id"], unique=False)

    # Preserve every existing user's current role as their first multi-role assignment.
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO user_roles (user_id, role) "
        "SELECT id, role FROM users WHERE role IS NOT NULL AND role <> ''"
    ))


def downgrade() -> None:
    op.drop_index(op.f("ix_user_roles_user_id"), table_name="user_roles")
    op.drop_index(op.f("ix_user_roles_role"), table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_column("users", "email")
