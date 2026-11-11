from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(30), unique=True, index=True)  # optional sign-in name, lower case
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(String(100))
    locale: Mapped[str] = mapped_column(String(5), default="ar")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Riyadh")
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=1)  # bump to sign out everywhere
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_workspace_id: Mapped[int | None] = mapped_column(Integer)

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")
