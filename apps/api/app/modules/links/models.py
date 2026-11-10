"""Tracked short links (UTM-tagged), their clicks, and conversions (orders / leads) attributed to social posts."""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, WorkspaceMixin


class TrackedLink(WorkspaceMixin, Base):
    """A short link ``/r/<code>`` that redirects to ``url`` with UTM tags. One per (post, account, url)."""

    __tablename__ = "tracked_links"
    __table_args__ = (UniqueConstraint("workspace_id", "post_id", "account_id", "url_hash",
                                       name="uq_tracked_links_target"),)

    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10), default="post")  # post | manual
    label: Mapped[str | None] = mapped_column(String(160))
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("social_accounts.id", ondelete="SET NULL"))
    platform: Mapped[str | None] = mapped_column(String(20), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    utm_source: Mapped[str | None] = mapped_column(String(120))
    utm_medium: Mapped[str | None] = mapped_column(String(120))
    utm_campaign: Mapped[str | None] = mapped_column(String(200))
    clicks: Mapped[int] = mapped_column(Integer, default=0)  # counted clicks (no bots, deduplicated)
    last_click_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LinkClick(WorkspaceMixin, Base):
    """One counted click. ``visitor`` is a daily-salted hash of IP + browser (no raw IP is stored)."""

    __tablename__ = "link_clicks"

    link_id: Mapped[int] = mapped_column(ForeignKey("tracked_links.id", ondelete="CASCADE"), index=True)
    visitor: Mapped[str] = mapped_column(String(32), index=True)
    referrer: Mapped[str | None] = mapped_column(String(300))
    device: Mapped[str | None] = mapped_column(String(12))  # mobile | desktop | tablet


class Conversion(WorkspaceMixin, Base):
    """A sale, lead or sign-up reported by the pixel, the server API or by hand, attributed to a post / network."""

    __tablename__ = "conversions"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "external_id", name="uq_conversions_external"),)

    kind: Mapped[str] = mapped_column(String(12), default="order")  # order | lead | signup | other
    value: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str | None] = mapped_column(String(3))
    external_id: Mapped[str | None] = mapped_column(String(120))  # order number (deduplication)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(10), default="api")  # pixel | api | manual
    link_id: Mapped[int | None] = mapped_column(ForeignKey("tracked_links.id", ondelete="SET NULL"), index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"), index=True)
    platform: Mapped[str | None] = mapped_column(String(20), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    utm_source: Mapped[str | None] = mapped_column(String(120))
    utm_medium: Mapped[str | None] = mapped_column(String(120))
    utm_campaign: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(String(300))
