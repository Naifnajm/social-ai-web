"""Shared bearer layer for ``/mcp``: scopes, hashing, token issuance and resolving a bearer token (OAuth access token
or personal API key) to a principal (user, workspace, scopes, which app or key).

    principal = resolve_bearer(db, "sk_stravica_…")   # Principal | None
"""
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import utcnow
from app.core.i18n import lazy
from app.modules.auth.models import User
from app.modules.workspaces.models import Membership, Workspace

from .models import ApiKey, OAuthGrant, OAuthToken

SCOPES = ("read", "write", "publish", "inbox")
DEFAULT_SCOPES = ("read",)
SAFE_DEFAULT = ("read", "write")  # preselected on the consent page; publish and inbox are opt-in
IGNORED_SCOPES = ("offline_access",)  # some clients add it to get a refresh token: we always give one
SCOPE_LABELS = {
    "read": lazy("Read your workspace: accounts, posts, analytics, brand kit, radar, ideas"),
    "write": lazy("Create drafts, upload media and generate AI images, videos and voice (uses AI credits)"),
    "publish": lazy("Schedule and publish posts publicly on your social accounts"),
    "inbox": lazy("Read your inbox and reply to real people"),
}

ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=10)
REQUEST_TTL = timedelta(minutes=15)
API_KEY_PREFIX = "sk_stravica_"
API_KEY_DAYS = (30, 90, 365)
LAST_USED_EVERY = timedelta(minutes=1)  # do not write last_used_at on every request


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def issuer() -> str:
    return settings.public_api_url.rstrip("/")


def mcp_url() -> str:
    """The canonical URL of the MCP server (the OAuth ``resource`` and the protected resource identifier)."""
    return issuer() + "/mcp"


def resource_metadata_url() -> str:
    return issuer() + "/.well-known/oauth-protected-resource/mcp"


def clean_scopes(values) -> list[str]:
    """Known scopes, in canonical order (unknown ones dropped)."""
    if isinstance(values, str):
        values = values.split()
    wanted = set(values or [])
    return [s for s in SCOPES if s in wanted]


def unknown_scopes(raw: str | None) -> list[str]:
    return [s for s in (raw or "").split() if s not in SCOPES and s not in IGNORED_SCOPES]


def issue_tokens(db: Session, grant: OAuthGrant, scopes: list[str]) -> dict:
    """A new access + refresh token pair for ``grant`` (token response body, RFC 6749 §5.1)."""
    access, refresh = new_secret(), new_secret()
    now = utcnow()
    db.add(OAuthToken(token_hash=sha256(access), kind="access", grant_id=grant.id, scopes=scopes,
                      expires_at=now + ACCESS_TTL))
    db.add(OAuthToken(token_hash=sha256(refresh), kind="refresh", grant_id=grant.id, scopes=scopes,
                      expires_at=now + REFRESH_TTL))
    db.flush()
    return {"access_token": access, "token_type": "Bearer", "expires_in": int(ACCESS_TTL.total_seconds()),
            "refresh_token": refresh, "scope": " ".join(scopes)}


def revoke_grant(db: Session, grant: OAuthGrant) -> None:
    now = utcnow()
    grant.revoked_at = grant.revoked_at or now
    for token in db.scalars(select(OAuthToken).where(OAuthToken.grant_id == grant.id, OAuthToken.revoked_at.is_(None))):
        token.revoked_at = now
    db.flush()


@dataclass
class Principal:
    """Who is calling ``/mcp``: resolved from the bearer token, re-checked on every request."""

    user_id: int
    workspace_id: int
    scopes: list[str]
    client_name: str
    grant_id: int | None = None
    api_key_id: int | None = None
    rate_key: str = ""
    extra: dict = field(default_factory=dict)

    def has(self, *scopes: str) -> bool:
        return all(s in self.scopes for s in scopes)


def _member_ok(db: Session, user_id: int, workspace_id: int) -> bool:
    user = db.get(User, user_id)
    workspace = db.get(Workspace, workspace_id)
    if not user or not user.is_active or not workspace or workspace.status != "active":
        return False
    return db.scalar(select(Membership.id).where(Membership.user_id == user_id,
                                                 Membership.workspace_id == workspace_id)) is not None


def resolve_bearer(db: Session, token: str) -> Principal | None:
    """The principal of an access token or API key, or None when it is unknown, expired, revoked, issued for another
    resource, or its user is no longer an active member of the workspace."""
    if not token or len(token) > 512:
        return None
    now = utcnow()
    digest = sha256(token)
    if token.startswith(API_KEY_PREFIX):
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == digest))
        if not key or key.revoked_at or aware(key.expires_at) <= now:
            return None
        if not _member_ok(db, key.user_id, key.workspace_id):
            return None
        if not key.last_used_at or aware(key.last_used_at) < now - LAST_USED_EVERY:
            key.last_used_at = now
        return Principal(user_id=key.user_id, workspace_id=key.workspace_id, scopes=clean_scopes(key.scopes),
                         client_name=key.name, api_key_id=key.id, rate_key=f"key:{key.id}")
    row = db.scalar(select(OAuthToken).where(OAuthToken.token_hash == digest, OAuthToken.kind == "access"))
    if not row or row.revoked_at or aware(row.expires_at) <= now:
        return None
    grant = row.grant
    if not grant or grant.revoked_at or grant.resource.rstrip("/") != mcp_url():
        return None
    if not _member_ok(db, grant.user_id, grant.workspace_id):
        return None
    if not grant.last_used_at or aware(grant.last_used_at) < now - LAST_USED_EVERY:
        grant.last_used_at = now
    return Principal(user_id=grant.user_id, workspace_id=grant.workspace_id, scopes=clean_scopes(row.scopes),
                     client_name=grant.client.client_name if grant.client else "app", grant_id=grant.id,
                     rate_key=f"grant:{grant.id}")
