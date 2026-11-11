"""platform-paid AI: managed providers and a monthly AI limit per member

Revision ID: d5e3f9a2b4c6
Revises: c4d2e8f1a3b5
Create Date: 2026-11-11 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e3f9a2b4c6'
down_revision: Union[str, Sequence[str], None] = 'c4d2e8f1a3b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ai_providers', sa.Column('managed', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('memberships', sa.Column('ai_monthly_limit', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('memberships', 'ai_monthly_limit')
    op.drop_column('ai_providers', 'managed')
