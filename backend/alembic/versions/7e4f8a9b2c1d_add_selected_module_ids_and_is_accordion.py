"""add_selected_module_ids_and_is_accordion

Revision ID: 7e4f8a9b2c1d
Revises: 5c9061208463
Create Date: 2026-06-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7e4f8a9b2c1d'
down_revision: Union[str, None] = '5c9061208463'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('explore_sessions',
        sa.Column('selected_module_ids', sa.JSON(), nullable=True))
    op.add_column('application_modules',
        sa.Column('is_accordion', sa.Boolean(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('explore_sessions', 'selected_module_ids')
    op.drop_column('application_modules', 'is_accordion')
