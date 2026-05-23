"""add email fields to leads

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2025-02-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8e9f0a1b2c3'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('leads', sa.Column('email', sa.String(255), nullable=True))
    op.add_column('leads', sa.Column('email_source', sa.String(50), nullable=True))

def downgrade() -> None:
    op.drop_column('leads', 'email_source')
    op.drop_column('leads', 'email')
