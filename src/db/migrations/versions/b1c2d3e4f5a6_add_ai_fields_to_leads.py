"""add_ai_fields_to_leads

Revision ID: b1c2d3e4f5a6
Revises: 26a98ce5e52f
Create Date: 2026-02-22 23:52:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = '26a98ce5e52f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('clean_name', sa.String(length=255), nullable=True))
    op.add_column('leads', sa.Column('lead_score', sa.Integer(), nullable=True))
    op.add_column('leads', sa.Column('ai_summary', sa.Text(), nullable=True))
    op.add_column('leads', sa.Column('ai_processed', sa.Boolean(), nullable=True, server_default='false'))


def downgrade() -> None:
    op.drop_column('leads', 'ai_processed')
    op.drop_column('leads', 'ai_summary')
    op.drop_column('leads', 'lead_score')
    op.drop_column('leads', 'clean_name')
