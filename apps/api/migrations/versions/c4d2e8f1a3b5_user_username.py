"""users.username: an optional sign-in name next to the e-mail

Revision ID: c4d2e8f1a3b5
Revises: b3c9d1e7f2a4
Create Date: 2026-11-11 02:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d2e8f1a3b5'
down_revision: Union[str, Sequence[str], None] = 'b3c9d1e7f2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('username', sa.String(length=30), nullable=True))
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_column('users', 'username')
