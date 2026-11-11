"""brand kit details: more colours, heading font, about, audience, personality, language, emojis, rules

Revision ID: b3c9d1e7f2a4
Revises: afa12860fcdc
Create Date: 2026-11-11 00:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c9d1e7f2a4'
down_revision: Union[str, Sequence[str], None] = 'afa12860fcdc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = [
    ('color_accent', sa.String(length=9)), ('color_background', sa.String(length=9)),
    ('font_heading', sa.String(length=80)), ('description', sa.Text()), ('industry', sa.String(length=120)),
    ('audience', sa.Text()), ('personality', sa.String(length=300)), ('language_style', sa.String(length=20)),
    ('emoji_style', sa.String(length=10)), ('cta', sa.String(length=200)), ('banned_words', sa.Text()),
    ('sample_posts', sa.Text()), ('website', sa.String(length=300)),
]


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column('brand_kits', sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _type in reversed(COLUMNS):
        op.drop_column('brand_kits', name)
