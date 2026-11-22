"""Radar tables: listening queries, the mentions they found and the events detected in them."""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, WorkspaceMixin

# Every source the radar can read (the registry in ``registry.py`` describes each one: access path, needs, cost).
SOURCES = ("owned", "instagram", "facebook", "threads", "youtube", "youtube_comments", "google_business", "linkedin",
           "news", "web", "x", "reddit", "tiktok", "telegram", "app_store", "google_play")
# Sources that cost nothing per use (quota-limited at most); the others are charged from the AI credits.
FREE_SOURCES = ("owned", "instagram", "facebook", "threads", "youtube", "youtube_comments", "google_business",
                "linkedin", "news", "telegram", "app_store", "google_play")
MENTION_STATES = ("new", "reviewed", "muted", "converted", "spam")
SENTIMENTS = ("positive", "neutral", "negative")
INTENTS = ("question", "purchase", "complaint", "praise", "news", "other")
EMOTIONS = ("joy", "trust", "anger", "anticipation", "sadness", "surprise", "none")
EVENT_KINDS = ("crisis", "spike", "opportunity", "competitor", "influencer", "rising")
SEVERITIES = ("urgent", "high", "normal", "info")
EVENT_STATES = ("open", "acted", "dismissed")
FEEDBACK = ("useful", "not_useful", "wrong")


class ListeningQuery(WorkspaceMixin, Base):
    """What the workspace listens for: its brand words, filters, competitors and sources."""
    __tablename__ = "listening_queries"

    name: Mapped[str] = mapped_column(String(120))
    keywords: Mapped[list] = mapped_column(JSON, default=list)          # any of these (brand words, @handle, #tag)
    required: Mapped[list] = mapped_column(JSON, default=list)          # and one of these (optional)
    excluded: Mapped[list] = mapped_column(JSON, default=list)          # and none of these
    languages: Mapped[list] = mapped_column(JSON, default=list)         # ["ar", "en"]; empty = all
    countries: Mapped[list] = mapped_column(JSON, default=list)         # ["SA", "AE"]; empty = all
    competitors: Mapped[list] = mapped_column(JSON, default=list)       # [{"name": "...", "keywords": [...]}]
    sources: Mapped[list] = mapped_column(JSON, default=list)           # subset of SOURCES
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    x_monthly_cap: Mapped[int] = mapped_column(Integer, default=3000)   # posts read from X per month
    # $ this setup may spend per month on paid sources (X, web search, data providers); None = no cap
    monthly_cap_usd: Mapped[float | None] = mapped_column(Float)
    # per-source lists: {"telegram_channels": [...], "app_store_ids": [...], "google_play_ids": [...],
    # "subreddits": [...], "youtube_channel_ids": [...]}
    options: Mapped[dict | None] = mapped_column(JSON)
    cursors: Mapped[dict | None] = mapped_column(JSON)                  # per source: since id / date / quota use
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Mention(WorkspaceMixin, Base):
    """One public post, comment, review or article that matched a query."""
    __tablename__ = "listening_mentions"
    __table_args__ = (UniqueConstraint("query_id", "source", "external_id"),)

    query_id: Mapped[int] = mapped_column(ForeignKey("listening_queries.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    platform: Mapped[str | None] = mapped_column(String(20))            # network of an "owned" mention
    external_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(1000))
    author_name: Mapped[str | None] = mapped_column(String(200))
    author_handle: Mapped[str | None] = mapped_column(String(200))
    author_followers: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    lang: Mapped[str | None] = mapped_column(String(8))
    country: Mapped[str | None] = mapped_column(String(2))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    brand: Mapped[str | None] = mapped_column(String(120), index=True)  # None = the workspace's own brand
    # people who saw it, only when the source says so (views / impressions); None = unknown, never invented.
    # The UI shows the author's followers as an "estimated" potential reach instead.
    reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engagement: Mapped[int] = mapped_column(Integer, default=0)
    sentiment: Mapped[str | None] = mapped_column(String(10), index=True)
    intent: Mapped[str | None] = mapped_column(String(12))
    topic: Mapped[str | None] = mapped_column(String(60))
    emotion: Mapped[str | None] = mapped_column(String(14))
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    corrected: Mapped[bool] = mapped_column(Boolean, default=False)     # a person fixed the classification
    status: Mapped[str] = mapped_column(String(12), default="new", index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("social_accounts.id", ondelete="SET NULL"))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("inbox_conversations.id", ondelete="SET NULL"))
    extra: Mapped[dict | None] = mapped_column(JSON)
    content_hash: Mapped[str | None] = mapped_column(String(40), index=True)  # normalized text: cross-source dedupe
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class RadarEvent(WorkspaceMixin, Base):
    """Something out of the ordinary, written as: what happened, why it matters, what to do."""
    __tablename__ = "listening_events"

    query_id: Mapped[int] = mapped_column(ForeignKey("listening_queries.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    severity: Mapped[str] = mapped_column(String(10), default="normal")
    state: Mapped[str] = mapped_column(String(10), default="open", index=True)
    key: Mapped[str] = mapped_column(String(160), index=True)           # de-duplication key
    brand: Mapped[str | None] = mapped_column(String(120))
    topic: Mapped[str | None] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    what: Mapped[str] = mapped_column(Text, default="")
    why: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    draft: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ai_written: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[str | None] = mapped_column(String(12))
    acted_action: Mapped[str | None] = mapped_column(String(20))
    acted_ref: Mapped[str | None] = mapped_column(String(200))
    acted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
