"""support tickets and the log of failures shown to people

Revision ID: e6f4a0b3c5d7
Revises: d5e3f9a2b4c6
Create Date: 2026-11-11 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f4a0b3c5d7'
down_revision: Union[str, Sequence[str], None] = 'd5e3f9a2b4c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_stamps = lambda: [  # noqa: E731
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
]


def upgrade() -> None:
    op.create_table(
        'error_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ref', sa.String(12), nullable=False),
        sa.Column('status', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(40), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('path', sa.String(500), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id', ondelete='SET NULL'), nullable=True),
        *_stamps(),
    )
    op.create_index('ix_error_events_ref', 'error_events', ['ref'], unique=True)
    op.create_index('ix_error_events_user_id', 'error_events', ['user_id'])
    op.create_index('ix_error_events_workspace_id', 'error_events', ['workspace_id'])

    op.create_table(
        'support_tickets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('subject', sa.String(200), nullable=False),
        sa.Column('category', sa.String(20), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('error_ref', sa.String(12), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('unread_by_user', sa.Boolean(), nullable=False),
        *_stamps(),
    )
    for column in ('workspace_id', 'user_id', 'status', 'error_ref', 'last_message_at'):
        op.create_index(f'ix_support_tickets_{column}', 'support_tickets', [column])

    op.create_table(
        'support_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('support_tickets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('staff', sa.Boolean(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        *_stamps(),
    )
    op.create_index('ix_support_messages_ticket_id', 'support_messages', ['ticket_id'])


def downgrade() -> None:
    op.drop_table('support_messages')
    op.drop_table('support_tickets')
    op.drop_table('error_events')
