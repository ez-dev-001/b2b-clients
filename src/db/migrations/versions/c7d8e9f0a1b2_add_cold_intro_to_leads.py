"""Add cold_intro field to leads table

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-02-23
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'c7d8e9f0a1b2'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('cold_intro', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('leads', 'cold_intro')
