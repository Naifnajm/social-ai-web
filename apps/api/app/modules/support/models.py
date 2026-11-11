"""Support tickets: a person of a workspace writes to the platform team, the team answers in the admin."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, WorkspaceMixin, utcnow

STATUSES = ("open", "answered", "closed")          # open: waiting for the team; answered: waiting for the person
CATEGORIES = ("problem", "question", "billing", "idea")


class SupportTicket(WorkspaceMixin, Base):
    __tablename__ = "support_tickets"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20), default="problem")
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    error_ref: Mapped[str | None] = mapped_column(String(12), index=True)  # ErrorEvent.ref, when sent from an error
    context: Mapped[dict | None] = mapped_column(JSON)  # what the app knew: page, error code and text, browser
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    unread_by_user: Mapped[bool] = mapped_column(Boolean, default=False)

    messages: Mapped[list["SupportMessage"]] = relationship(back_populates="ticket", cascade="all, delete-orphan",
                                                            order_by="SupportMessage.id")


class SupportMessage(TimestampMixin, Base):
    __tablename__ = "support_messages"

    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    staff: Mapped[bool] = mapped_column(Boolean, default=False)  # written by the platform team
    body: Mapped[str] = mapped_column(Text)

    ticket: Mapped[SupportTicket] = relationship(back_populates="messages")
