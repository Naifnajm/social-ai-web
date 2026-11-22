"""The trail of what happened to an account: sign-ins, password and e-mail changes, two-step sign-in, and every
change a platform administrator made (including what they did while viewing the app as the person).

Rows are never deleted, also not when the account is erased (they then point to the anonymized account)."""
from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class UserEvent(TimestampMixin, Base):
    __tablename__ = "user_events"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)  # whose account
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)  # who did it
    # set when a platform administrator acted while viewing the app as the person
    impersonator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(60), index=True)  # login, password.changed, admin.email, impersonation.start…
    summary: Mapped[str | None] = mapped_column(String(500))
    payload: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
