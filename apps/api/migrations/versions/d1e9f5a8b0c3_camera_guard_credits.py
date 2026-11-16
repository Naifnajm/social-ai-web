"""Camera settings on AI images/videos, brand guard, AI credits with the platform markup.

Revision ID: d1e9f5a8b0c3
Revises: c0d8e4f7a9b2
"""
import sqlalchemy as sa
from alembic import op

revision = "d1e9f5a8b0c3"
down_revision = "c0d8e4f7a9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brand_kits", sa.Column("guard_mode", sa.String(10), nullable=False, server_default="guide"))
    op.add_column("brand_kits", sa.Column("photo_style", sa.JSON(), nullable=True))
    op.add_column("brand_kits", sa.Column("visual_rules", sa.Text(), nullable=True))
    op.add_column("media_jobs", sa.Column("shot", sa.JSON(), nullable=True))
    op.add_column("media_jobs", sa.Column("brand_kit_id", sa.Integer(),
                                          sa.ForeignKey("brand_kits.id", ondelete="SET NULL"), nullable=True))
    op.add_column("media_jobs", sa.Column("brand_score", sa.Integer(), nullable=True))
    op.add_column("production_nodes", sa.Column("shot", sa.JSON(), nullable=True))
    op.add_column("ai_usage", sa.Column("price", sa.Float(), nullable=True))
    op.add_column("subscriptions", sa.Column("credit_balance", sa.Float(), nullable=False, server_default="0"))
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("credits", sa.Float(), nullable=False),
        sa.Column("balance_after", sa.Float(), nullable=False),
        sa.Column("amount_paid", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("ref", sa.String(160), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_credit_transactions_workspace_id", "credit_transactions", ["workspace_id"])
    op.create_index("ix_credit_transactions_ref", "credit_transactions", ["ref"])
    # platform AI used so far is priced at its cost (no retroactive markup)
    op.execute("UPDATE ai_usage SET price = cost WHERE provider_id IS NULL OR provider_id IN "
               "(SELECT id FROM ai_providers WHERE managed)")


def downgrade() -> None:
    op.drop_table("credit_transactions")
    op.drop_column("subscriptions", "credit_balance")
    op.drop_column("ai_usage", "price")
    op.drop_column("production_nodes", "shot")
    op.drop_column("media_jobs", "brand_score")
    op.drop_column("media_jobs", "brand_kit_id")
    op.drop_column("media_jobs", "shot")
    op.drop_column("brand_kits", "visual_rules")
    op.drop_column("brand_kits", "photo_style")
    op.drop_column("brand_kits", "guard_mode")
