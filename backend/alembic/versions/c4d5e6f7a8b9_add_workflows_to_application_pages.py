"""add_workflows_to_application_pages

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-09 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Column already added by b3c4d5e6f7a8 — use IF NOT EXISTS to be idempotent
    op.execute("ALTER TABLE application_pages ADD COLUMN IF NOT EXISTS workflows JSON")


def downgrade() -> None:
    pass  # managed by b3c4d5e6f7a8 downgrade
