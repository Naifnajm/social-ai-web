"""Radar sources: setup options and monthly cap, real reach only (nullable), cross-source dedupe hash and the
teammate a mention is assigned to.

Revision ID: c4e8a2f6b9d1
Revises: b8d2f4a6c1e3
"""
import sqlalchemy as sa
from alembic import op

revision = "c4e8a2f6b9d1"
down_revision = "b8d2f4a6c1e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listening_queries", sa.Column("monthly_cap_usd", sa.Float(), nullable=True))
    op.add_column("listening_queries", sa.Column("options", sa.JSON(), nullable=True))
    op.alter_column("listening_mentions", "reach", existing_type=sa.Integer(), nullable=True)
    # the old reach was a made-up formula for Instagram (likes × 10 + comments × 20): forget it
    op.execute("UPDATE listening_mentions SET reach = NULL WHERE source = 'instagram' OR reach = 0")
    op.add_column("listening_mentions", sa.Column("content_hash", sa.String(length=40), nullable=True))
    op.create_index(op.f("ix_listening_mentions_content_hash"), "listening_mentions", ["content_hash"])
    op.add_column("listening_mentions", sa.Column("assigned_to_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_listening_mentions_assigned_to_id_users"), "listening_mentions", "users",
                          ["assigned_to_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(op.f("fk_listening_mentions_assigned_to_id_users"), "listening_mentions", type_="foreignkey")
    op.drop_column("listening_mentions", "assigned_to_id")
    op.drop_index(op.f("ix_listening_mentions_content_hash"), table_name="listening_mentions")
    op.drop_column("listening_mentions", "content_hash")
    op.execute("UPDATE listening_mentions SET reach = 0 WHERE reach IS NULL")
    op.alter_column("listening_mentions", "reach", existing_type=sa.Integer(), nullable=False)
    op.drop_column("listening_queries", "options")
    op.drop_column("listening_queries", "monthly_cap_usd")
