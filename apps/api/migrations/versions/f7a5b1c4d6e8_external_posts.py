"""external posts: history and posts scheduled in Meta's own tools (read-only mirror)

Revision ID: f7a5b1c4d6e8
Revises: e6f4a0b3c5d7
Create Date: 2026-11-11 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7a5b1c4d6e8'
down_revision: Union[str, Sequence[str], None] = 'e6f4a0b3c5d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'external_posts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('social_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', sa.String(20), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('kind', sa.String(12), nullable=False, server_default='published'),
        sa.Column('text', sa.Text()),
        sa.Column('permalink', sa.String(1000)),
        sa.Column('media_url', sa.String(2000)),
        sa.Column('media_type', sa.String(20)),
        sa.Column('published_at', sa.DateTime(timezone=True)),
        sa.Column('scheduled_at', sa.DateTime(timezone=True)),
        sa.Column('comments_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('synced_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('account_id', 'external_id'),
    )
    for column in ('workspace_id', 'account_id', 'platform', 'kind', 'published_at', 'scheduled_at'):
        op.create_index('ix_external_posts_%s' % column, 'external_posts', [column])


def downgrade() -> None:
    op.drop_table('external_posts')
