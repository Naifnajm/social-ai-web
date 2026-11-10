"""Social accounts, posts and per-account publishing results — the shared heart of the platform.

Feature ownership (services/routers): the *publishing* builder owns accounts, OAuth, publishing and metrics;
other features read these tables and add their behaviour through their own modules.
"""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import EncryptedString
from app.core.db import Base, TimestampMixin, WorkspaceMixin

PLATFORMS = ("facebook", "instagram", "linkedin", "x", "tiktok", "threads", "telegram", "whatsapp")
PUBLISH_PLATFORMS = ("facebook", "instagram", "linkedin", "x", "tiktok", "threads", "telegram")  # not whatsapp
POST_STATES = ("draft", "to_approve", "scheduled", "publishing", "posted", "partial", "failed")


class SocialAccount(WorkspaceMixin, Base):
    __tablename__ = "social_accounts"

    name: Mapped[str] = mapped_column(String(160))
    platform: Mapped[str] = mapped_column(String(20), index=True)
    username: Mapped[str | None] = mapped_column(String(160))
    external_id: Mapped[str | None] = mapped_column(String(200), index=True)  # page id, IG user id, chat id…
    avatar_url: Mapped[str | None] = mapped_column(String(1000))
    access_token: Mapped[str | None] = mapped_column(EncryptedString(4000))
    refresh_token: Mapped[str | None] = mapped_column(EncryptedString(4000))
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict | None] = mapped_column(JSON)  # platform specifics (tiktok privacy, twilio sid, webhook secret…)
    secrets: Mapped[str | None] = mapped_column(EncryptedString(4000))  # JSON of extra secrets (twilio token…)
    state: Mapped[str] = mapped_column(String(20), default="connected")  # draft | connected | expired | error
    last_error: Mapped[str | None] = mapped_column(Text)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    followers: Mapped[int] = mapped_column(Integer, default=0)
    followers_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # inbox / assistant (used by the inbox feature)
    inbox_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    bot_settings: Mapped[dict | None] = mapped_column(JSON)


class AccountStat(WorkspaceMixin, Base):
    """Daily snapshot of an account (followers) for growth charts."""

    __tablename__ = "account_stats"
    __table_args__ = (UniqueConstraint("account_id", "day"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("social_accounts.id", ondelete="CASCADE"), index=True)
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    followers: Mapped[int] = mapped_column(Integer, default=0)


post_accounts = Table(
    "post_accounts", Base.metadata,
    Column("post_id", ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
    Column("account_id", ForeignKey("social_accounts.id", ondelete="CASCADE"), primary_key=True),
)


class PostMedia(Base):
    """Ordered media of a post. ``role``: feed (default) or story."""

    __tablename__ = "post_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(10), default="feed")


class Post(WorkspaceMixin, Base):
    __tablename__ = "posts"

    name: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text)
    variants: Mapped[dict | None] = mapped_column(JSON)  # {platform: text}
    platform_media: Mapped[dict | None] = mapped_column(JSON)  # {platform: [media ids]} (formats per network)
    state: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # drafts planned for a day
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ai_brief: Mapped[str | None] = mapped_column(Text)
    publish_as: Mapped[str] = mapped_column(String(12), default="feed")  # feed | story | feed_story
    brand_template_id: Mapped[int | None] = mapped_column(Integer)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    pillar_id: Mapped[int | None] = mapped_column(ForeignKey("content_pillars.id", ondelete="SET NULL"), index=True)
    # approvals
    requested_action: Mapped[str | None] = mapped_column(String(12))  # publish | schedule (what approval unlocks)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(Text)
    approval_requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approval_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # evergreen reposting
    evergreen: Mapped[bool] = mapped_column(Boolean, default=False)
    recycle_interval_days: Mapped[int] = mapped_column(Integer, default=30)
    recycle_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recycle_rewrite: Mapped[bool] = mapped_column(Boolean, default=False)
    last_recycled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recycle_count: Mapped[int] = mapped_column(Integer, default=0)
    recycled_from_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))
    source_ref: Mapped[str | None] = mapped_column(String(120))  # e.g. "board:12", "product:abc"

    accounts = relationship("SocialAccount", secondary=post_accounts, order_by="SocialAccount.id")
    media_links = relationship("PostMedia", order_by="PostMedia.position", cascade="all, delete-orphan")
    targets = relationship("PostTarget", back_populates="post", cascade="all, delete-orphan")


class PostTarget(WorkspaceMixin, Base):
    """Result of a post on one account (one row per account): state, link, metrics, story result."""

    __tablename__ = "post_targets"
    __table_args__ = (UniqueConstraint("post_id", "account_id"),)

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("social_accounts.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    state: Mapped[str] = mapped_column(String(12), default="pending")  # pending | posted | failed
    external_id: Mapped[str | None] = mapped_column(String(255))
    external_ref: Mapped[str | None] = mapped_column(String(255))
    external_url: Mapped[str | None] = mapped_column(String(1000))
    error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    media_type: Mapped[str | None] = mapped_column(String(12))  # text | image | carousel | video | audio
    text_length: Mapped[int] = mapped_column(Integer, default=0)
    hashtag_count: Mapped[int] = mapped_column(Integer, default=0)
    story_state: Mapped[str | None] = mapped_column(String(12))  # pending | posted | failed | skipped
    story_external_id: Mapped[str | None] = mapped_column(String(255))
    story_error: Mapped[str | None] = mapped_column(Text)
    story_url: Mapped[str | None] = mapped_column(String(1000))
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    video_views: Mapped[int] = mapped_column(Integer, default=0)
    engagements: Mapped[int] = mapped_column(Integer, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    metrics_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    post = relationship("Post", back_populates="targets")
    account = relationship("SocialAccount")


class OAuthSession(WorkspaceMixin, Base):
    """Short-lived link between an OAuth redirect and the admin (and workspace) who started it."""

    __tablename__ = "social_oauth_sessions"

    state_token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(20))
    code_verifier: Mapped[str | None] = mapped_column(EncryptedString(400))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    app_source: Mapped[str] = mapped_column(String(12), default="platform")  # workspace | platform
    locale: Mapped[str] = mapped_column(String(5), default="ar")
