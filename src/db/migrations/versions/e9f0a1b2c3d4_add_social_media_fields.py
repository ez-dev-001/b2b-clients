"""add social media fields to leads

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2025-02-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'e9f0a1b2c3d4'
down_revision = 'd8e9f0a1b2c3'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('leads', sa.Column('instagram', sa.String(255), nullable=True))
    op.add_column('leads', sa.Column('facebook', sa.String(255), nullable=True))
    op.add_column('leads', sa.Column('telegram', sa.String(255), nullable=True))
    op.add_column('leads', sa.Column('tiktok', sa.String(255), nullable=True))

def downgrade() -> None:
    op.drop_column('leads', 'tiktok')
    op.drop_column('leads', 'telegram')
    op.drop_column('leads', 'facebook')
    op.drop_column('leads', 'instagram')
