"""add test_datasets table

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-10

"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = 'e6f7a8b9c0d1'
down_revision: str = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_datasets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("application_id", sa.String(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("label", sa.String(512), nullable=False),
        sa.Column("data_type", sa.String(50), nullable=True),
        sa.Column("text_value", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(2048), nullable=True),
        sa.Column("file_name", sa.String(512), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_datasets_application_id", "test_datasets", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_test_datasets_application_id", table_name="test_datasets")
    op.drop_table("test_datasets")
