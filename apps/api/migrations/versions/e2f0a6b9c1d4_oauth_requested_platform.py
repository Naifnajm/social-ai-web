"""Remember which network the person clicked when several share one login (Instagram uses Facebook Login).

Revision ID: e2f0a6b9c1d4
Revises: d1e9f5a8b0c3
"""
import sqlalchemy as sa
from alembic import op

revision = "e2f0a6b9c1d4"
down_revision = "d1e9f5a8b0c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("social_oauth_sessions", sa.Column("requested", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("social_oauth_sessions", "requested")
