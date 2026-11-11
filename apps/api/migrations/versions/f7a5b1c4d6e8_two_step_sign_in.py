"""two-step sign-in: authenticator app codes, recovery codes and passkeys

Revision ID: f7a5b1c4d6e8
Revises: e6f4a0b3c5d7
Create Date: 2026-11-11 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7a5b1c4d6e8'
down_revision: Union[str, Sequence[str], None] = 'e6f4a0b3c5d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('totp_secret', sa.String(300), nullable=True))
    op.add_column('users', sa.Column('totp_enabled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('totp_last_step', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('recovery_codes', sa.JSON(), nullable=True))
    op.create_table(
        'passkeys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('credential_id', sa.String(512), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('sign_count', sa.Integer(), nullable=False),
        sa.Column('transports', sa.JSON(), nullable=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_passkeys_user_id', 'passkeys', ['user_id'])
    op.create_index('ix_passkeys_credential_id', 'passkeys', ['credential_id'], unique=True)


def downgrade() -> None:
    op.drop_table('passkeys')
    op.drop_column('users', 'recovery_codes')
    op.drop_column('users', 'totp_last_step')
    op.drop_column('users', 'totp_enabled_at')
    op.drop_column('users', 'totp_secret')
