"""Retire OpenAI Sora (the API closed on 24 September 2026): switch its model rows off and clear it as a default.

Revision ID: c0d8e4f7a9b2
Revises: b9c7d3e6f8a1
Create Date: 2026-11-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c0d8e4f7a9b2"
down_revision: Union[str, Sequence[str], None] = "b9c7d3e6f8a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE ai_models SET active = false WHERE name IN ('sora-2', 'sora-2-pro')")
    op.execute("UPDATE ai_providers SET video_model = NULL WHERE video_model LIKE 'sora%'")


def downgrade() -> None:
    pass  # nothing to restore: the service no longer exists
