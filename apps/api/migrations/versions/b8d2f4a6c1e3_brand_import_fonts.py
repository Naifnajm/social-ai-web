"""Brand kits from a design system: dark-background logo, reference images, font files and pending imports.

Revision ID: b8d2f4a6c1e3
Revises: a3c7e9f1b2d4
"""
import sqlalchemy as sa
from alembic import op

revision = "b8d2f4a6c1e3"
down_revision = "a3c7e9f1b2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brand_kits", sa.Column("logo_dark_media_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_brand_kits_logo_dark_media_id_media"), "brand_kits", "media",
                          ["logo_dark_media_id"], ["id"], ondelete="SET NULL")
    op.add_column("brand_kits", sa.Column("reference_media_ids", sa.JSON(), nullable=True))
    op.create_table(
        "brand_fonts",
        sa.Column("brand_kit_id", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("family", sa.String(length=120), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("style", sa.String(length=10), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("has_arabic", sa.Boolean(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["brand_kit_id"], ["brand_kits.id"], name=op.f("fk_brand_fonts_brand_kit_id_brand_kits"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], name=op.f("fk_brand_fonts_media_id_media"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_brand_fonts_workspace_id_workspaces"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_fonts")),
    )
    op.create_index(op.f("ix_brand_fonts_brand_kit_id"), "brand_fonts", ["brand_kit_id"])
    op.create_index(op.f("ix_brand_fonts_workspace_id"), "brand_fonts", ["workspace_id"])
    op.create_table(
        "brand_imports",
        sa.Column("token", sa.String(length=40), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_brand_imports_created_by_id_users"),
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"],
                                name=op.f("fk_brand_imports_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_imports")),
    )
    op.create_index(op.f("ix_brand_imports_token"), "brand_imports", ["token"], unique=True)
    op.create_index(op.f("ix_brand_imports_expires_at"), "brand_imports", ["expires_at"])
    op.create_index(op.f("ix_brand_imports_workspace_id"), "brand_imports", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("brand_imports")
    op.drop_table("brand_fonts")
    op.drop_constraint(op.f("fk_brand_kits_logo_dark_media_id_media"), "brand_kits", type_="foreignkey")
    op.drop_column("brand_kits", "reference_media_ids")
    op.drop_column("brand_kits", "logo_dark_media_id")
