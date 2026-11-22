"""OAuth clients, authorization requests and codes, grants (a connected app) with their tokens, personal API keys and
the audit trail of what connected apps did. Every secret (code, token, key, client secret) is stored as a sha256
hash: what is in the database cannot be used."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


class OAuthClient(TimestampMixin, Base):
    """An application that may ask users for access: registered dynamically (RFC 7591) or described by a client ID
    metadata document (``client_id`` is then the https URL of that document)."""

    __tablename__ = "connect_clients"

    client_id: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    client_name: Mapped[str] = mapped_column(String(200))
    redirect_uris: Mapped[list] = mapped_column(JSON, default=list)
    client_uri: Mapped[str | None] = mapped_column(String(500))
    logo_uri: Mapped[str | None] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(10), default="dcr")  # dcr | cimd
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(30), default="none")
    client_secret_hash: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # cimd: last time the document was read


class OAuthRequest(TimestampMixin, Base):
    """A validated authorization request waiting for the user's decision on the consent page (15 minutes)."""

    __tablename__ = "connect_requests"

    request_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_pk: Mapped[int] = mapped_column(ForeignKey("connect_clients.id", ondelete="CASCADE"), index=True)
    redirect_uri: Mapped[str] = mapped_column(String(1000))
    state: Mapped[str | None] = mapped_column(String(1000))
    code_challenge: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list] = mapped_column(JSON, default=list)  # offered on the consent page
    preselected: Mapped[list] = mapped_column(JSON, default=list)
    resource: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client = relationship("OAuthClient")


class OAuthGrant(TimestampMixin, Base):
    """A connected app: the user allowed ``client`` to act in ``workspace`` with ``scopes``. Revoking it (disconnect)
    ends every token issued under it."""

    __tablename__ = "connect_grants"

    client_pk: Mapped[int] = mapped_column(ForeignKey("connect_clients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    resource: Mapped[str] = mapped_column(String(500))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    client = relationship("OAuthClient")


class OAuthCode(TimestampMixin, Base):
    """Authorization code (10 minutes, single use, bound to the PKCE challenge and the redirect URI)."""

    __tablename__ = "connect_codes"

    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    grant_id: Mapped[int] = mapped_column(ForeignKey("connect_grants.id", ondelete="CASCADE"), index=True)
    redirect_uri: Mapped[str] = mapped_column(String(1000))
    code_challenge: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthToken(TimestampMixin, Base):
    """An access token (1 hour) or a refresh token (30 days, rotated: each one can be used once)."""

    __tablename__ = "connect_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # access | refresh
    grant_id: Mapped[int] = mapped_column(ForeignKey("connect_grants.id", ondelete="CASCADE"), index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # refresh: exchanged
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    grant = relationship("OAuthGrant")


class ApiKey(TimestampMixin, Base):
    """Personal API key of a workspace admin (shown once). It acts as that user, with their current role."""

    __tablename__ = "connect_api_keys"

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(24))  # first characters, to recognise the key in the list
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ConnectAudit(TimestampMixin, Base):
    """What a connected app or API key did: every write, publish and send (who, through which app or key, what)."""

    __tablename__ = "connect_audit"

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    grant_id: Mapped[int | None] = mapped_column(ForeignKey("connect_grants.id", ondelete="SET NULL"), index=True)
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("connect_api_keys.id", ondelete="SET NULL"), index=True)
    client_name: Mapped[str] = mapped_column(String(200))
    tool: Mapped[str] = mapped_column(String(60))
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    summary: Mapped[str | None] = mapped_column(Text)
    ref: Mapped[str | None] = mapped_column(String(80))  # e.g. "post:12", "conversation:3", "job:9"
    details: Mapped[dict | None] = mapped_column(JSON)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
