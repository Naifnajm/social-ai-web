"""Content ideas: one suggestion with its reasons, caption, carousel slides or video script and a time."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, WorkspaceMixin

FORMATS = ("post", "carousel", "video")
STATES = ("new", "scheduled", "draft", "rejected", "expired")
REASONS = ("top_post", "format", "question", "rising", "event", "pillar", "product", "best_time", "brief")


class ContentIdea(WorkspaceMixin, Base):
    __tablename__ = "content_ideas"

    state: Mapped[str] = mapped_column(String(12), default="new", index=True)
    format: Mapped[str] = mapped_column(String(10), default="post")
    language: Mapped[str] = mapped_column(String(5), default="ar")
    title: Mapped[str] = mapped_column(String(200))
    reasons: Mapped[list] = mapped_column(JSON, default=list)        # [{"kind": "question", "label": "..."}]
    caption: Mapped[str] = mapped_column(Text, default="")
    variants: Mapped[dict | None] = mapped_column(JSON)              # {"x": "shorter text"}
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    slides: Mapped[list] = mapped_column(JSON, default=list)         # [{"title": "...", "body": "..."}]
    video: Mapped[dict | None] = mapped_column(JSON)                 # {"hook", "duration", "scenes": [...], "voiceover"}
    platforms: Mapped[list] = mapped_column(JSON, default=list)
    account_ids: Mapped[list] = mapped_column(JSON, default=list)
    suggested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    slot_label: Mapped[str | None] = mapped_column(String(80))
    pillar_id: Mapped[int | None] = mapped_column(ForeignKey("content_pillars.id", ondelete="SET NULL"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    media_ids: Mapped[list] = mapped_column(JSON, default=list)      # rendered carousel slides
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))
    ai_written: Mapped[bool] = mapped_column(Boolean, default=False)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected_reason: Mapped[str | None] = mapped_column(String(30))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
