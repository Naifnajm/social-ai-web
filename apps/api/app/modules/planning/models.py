"""Campaigns and content pillars (the planning builder owns services/routers and may add columns here).

Dates: ``date_start`` / ``date_end`` hold a *day*. They are stored at 12:00 UTC of that day so the day is the same
in every time zone from UTC-11 to UTC+11 (see :func:`app.modules.planning.service.as_day`).
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, WorkspaceMixin


class Campaign(WorkspaceMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(160))
    tagline: Mapped[str | None] = mapped_column(String(200))
    goal: Mapped[str | None] = mapped_column(Text)
    date_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    color: Mapped[str] = mapped_column(String(9), default="#111111")
    state: Mapped[str] = mapped_column(String(12), default="planned")  # planned | running | finished
    budget: Mapped[float | None] = mapped_column(Float)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # planning additions
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_state: Mapped[bool] = mapped_column(Boolean, default=True)  # start / finish by the dates
    target_posts: Mapped[int | None] = mapped_column(Integer)  # optional goal: number of posts


class ContentPillar(WorkspaceMixin, Base):
    __tablename__ = "content_pillars"

    name: Mapped[str] = mapped_column(String(120))
    color: Mapped[str] = mapped_column(String(9), default="#71717a")
    description: Mapped[str | None] = mapped_column(Text)
    target_share: Mapped[int] = mapped_column(Integer, default=25)  # % of posts
    # planning additions
    position: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
