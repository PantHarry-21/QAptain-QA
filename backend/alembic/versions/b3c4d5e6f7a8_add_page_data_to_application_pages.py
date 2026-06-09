"""add_page_data_and_workflows_to_application_pages

Revision ID: b3c4d5e6f7a8
Revises: 7e4f8a9b2c1d
Create Date: 2026-06-09 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = '7e4f8a9b2c1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('application_pages',
        sa.Column('page_data', sa.JSON(), nullable=True))
    op.add_column('application_pages',
        sa.Column('workflows', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('application_pages', 'page_data')
    op.drop_column('application_pages', 'workflows')
