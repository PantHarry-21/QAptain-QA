"""add is_smoke to scenarios and kg_backed columns

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-10

"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = 'd5e6f7a8b9c0'
down_revision: str = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_smoke flag to scenarios — smoke tests always run first as sanity checks
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.add_column(
            sa.Column("is_smoke", sa.Boolean(), nullable=True, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.drop_column("is_smoke")
