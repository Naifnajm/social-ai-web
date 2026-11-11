from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import EncryptedString
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
    # two-step sign-in with an authenticator app (see two_step.py)
    totp_secret: Mapped[str | None] = mapped_column(EncryptedString(300))
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_step: Mapped[int | None] = mapped_column(Integer)  # a code works once
    recovery_codes: Mapped[list | None] = mapped_column(JSON)    # sha256 of the unused recovery codes

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")
    passkeys = relationship("Passkey", back_populates="user", cascade="all, delete-orphan", order_by="Passkey.id")

    @property
    def two_step(self) -> bool:
        return self.totp_enabled_at is not None


class Passkey(TimestampMixin, Base):
    """A passkey (Face ID, Touch ID, Windows Hello, a phone, a security key) that signs in without a password."""

    __tablename__ = "passkeys"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)  # base64url
    public_key: Mapped[str] = mapped_column(Text)  # base64url COSE key
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[list | None] = mapped_column(JSON)
    name: Mapped[str] = mapped_column(String(80), default="Passkey")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="passkeys")
