"""Scheduled performance reports e-mailed every week or month."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, WorkspaceMixin


class ReportSchedule(WorkspaceMixin, Base):
    __tablename__ = "report_schedules"

    name: Mapped[str] = mapped_column(String(160))
    recipients: Mapped[list] = mapped_column(JSON, default=list)  # e-mail addresses
    frequency: Mapped[str] = mapped_column(String(10), default="weekly")  # weekly | monthly
    weekday: Mapped[int] = mapped_column(Integer, default=0)  # 0 = Monday (weekly)
    month_day: Mapped[int] = mapped_column(Integer, default=1)  # 1–28 (monthly)
    hour: Mapped[int] = mapped_column(Integer, default=8)  # local hour of the workspace (0–23)
    period: Mapped[str] = mapped_column(String(12), default="last_7")  # last_7 | last_30 | prev_month
    account_ids: Mapped[list | None] = mapped_column(JSON)  # only these accounts (empty = all)
    language: Mapped[str] = mapped_column(String(5), default="ar")  # ar | en
    include_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    send_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
