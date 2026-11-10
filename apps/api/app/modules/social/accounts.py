"""Social accounts: tokens (auto-refresh), connection checks, OAuth upsert, follower snapshots."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.http import ApiError

from . import oauth
from .models import PUBLISH_PLATFORMS, AccountStat, SocialAccount
from .platforms import get_publisher

_logger = logging.getLogger(__name__)
USABLE_STATES = ("connected", "draft")


def aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def can_publish(account: SocialAccount) -> bool:
    return account.platform in PUBLISH_PLATFORMS and account.active


def mark_failed(account: SocialAccount, exc: ApiError) -> None:
    """Flag the account after an API error (401 → reconnect needed)."""
    if exc.status == 401:
        account.state = "expired"
        account.last_error = exc.message[:500]


def valid_token(db: Session, account: SocialAccount) -> str:
    """A usable access token, refreshed first when it expires within 5 minutes."""
    if not account.access_token:
        raise ApiError(f"No access token for {account.name}. Connect the account first.")
    expires = aware(account.token_expires_at)
    if expires and expires <= utcnow() + timedelta(minutes=5):
        apply_refresh(db, account)
        if account.state == "expired":
            raise ApiError(account.last_error or "The token has expired. Please reconnect the account.", 401)
    return account.access_token


def apply_refresh(db: Session, account: SocialAccount) -> bool:
    try:
        values = oauth.refresh(db, account)
    except ApiError as exc:
        account.state = "expired"
        account.last_error = exc.message[:500]
        db.flush()
        return False
    for key, value in values.items():
        setattr(account, key, value)
    account.state = "connected"
    account.last_error = None
    db.flush()
    return True


def check_connection(db: Session, account: SocialAccount) -> bool:
    """Read the profile with the token; update avatar / username; set the state."""
    account.last_check_at = utcnow()
    if account.platform not in PUBLISH_PLATFORMS:
        return account.state == "connected"
    try:
        profile = get_publisher(db, account).fetch_profile()
    except ApiError as exc:
        account.state = "expired" if exc.status == 401 else "error"
        account.last_error = exc.message[:500]
        db.flush()
        return False
    account.state = "connected"
    account.last_error = None
    if profile.get("avatar_url"):
        account.avatar_url = profile["avatar_url"][:1000]
    if profile.get("username"):
        account.username = str(profile["username"])[:160]
    if profile.get("external_id") and not account.external_id:
        account.external_id = str(profile["external_id"])
    if profile.get("name") and not account.name:
        account.name = str(profile["name"])[:160]
    db.flush()
    return True


def find_existing(db: Session, workspace_id: int, platform: str, external_id: str | None) -> SocialAccount | None:
    if not external_id:
        return None
    return db.scalar(select(SocialAccount).where(SocialAccount.workspace_id == workspace_id,
                                                 SocialAccount.platform == platform,
                                                 SocialAccount.external_id == str(external_id)))


def upsert_from_oauth(db: Session, workspace_id: int, values_list: list[dict], *, check_limit) -> list[SocialAccount]:
    """Create or update the accounts returned by an OAuth exchange (``check_limit()`` runs before each creation)."""
    accounts = []
    for values in values_list:
        values = {k: v for k, v in values.items() if v is not None}
        existing = find_existing(db, workspace_id, values["platform"], values.get("external_id"))
        if existing is None:
            check_limit()
            existing = SocialAccount(workspace_id=workspace_id, platform=values["platform"],
                                     name=(values.get("name") or values["platform"])[:160])
            db.add(existing)
        extra = dict(existing.extra or {})
        extra.update(values.pop("extra", {}) or {})
        for key, value in values.items():
            if key in ("name", "username"):
                value = str(value)[:160]
            setattr(existing, key, value)
        existing.extra = extra
        existing.active = True
        existing.state = "connected"
        existing.last_error = None
        existing.last_check_at = utcnow()
        db.flush()
        accounts.append(existing)
    return accounts


def refresh_due_tokens(db: Session, workspace_id: int | None = None, days: int = 3) -> int:
    """Renew tokens expiring within ``days`` days; flag the ones that cannot be renewed."""
    query = select(SocialAccount).where(SocialAccount.token_expires_at.is_not(None),
                                        SocialAccount.token_expires_at <= utcnow() + timedelta(days=days),
                                        SocialAccount.active.is_(True),
                                        SocialAccount.access_token.is_not(None))
    if workspace_id:
        query = query.where(SocialAccount.workspace_id == workspace_id)
    renewed = 0
    for account in db.scalars(query).all():
        try:
            renewed += apply_refresh(db, account)
        except Exception:  # never let one account stop the others
            _logger.exception("token refresh failed for account %s", account.id)
    return renewed


def sync_audience(db: Session, accounts: list[SocialAccount]) -> int:
    """Store today's follower count for each account (one AccountStat row per day)."""
    day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    updated = 0
    for account in accounts:
        if account.platform not in PUBLISH_PLATFORMS or account.state not in USABLE_STATES or not account.active:
            continue
        try:
            audience = get_publisher(db, account).fetch_audience()
        except ApiError as exc:
            mark_failed(account, exc)
            continue
        except Exception:
            _logger.exception("audience sync failed for account %s", account.id)
            continue
        if "followers" not in audience:
            continue
        followers = int(audience["followers"] or 0)
        account.followers = followers
        account.followers_updated_at = utcnow()
        stat = db.scalar(select(AccountStat).where(AccountStat.account_id == account.id, AccountStat.day == day))
        if stat:
            stat.followers = followers
        else:
            db.add(AccountStat(workspace_id=account.workspace_id, account_id=account.id, day=day, followers=followers))
        updated += 1
    db.flush()
    return updated
