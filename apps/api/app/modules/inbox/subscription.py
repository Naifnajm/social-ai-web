"""Page → app webhook subscription: the step that makes Meta actually send events.

Registering the callback URL on the Meta app is not enough: every Facebook Page (and the Instagram account linked
to it) must also be subscribed to the app with ``POST /{page-id}/subscribed_apps``. Without it Meta sends nothing,
silently. This module does that when an account is connected (``hooks.AFTER_CONNECT``), checks it every few hours
and lets an admin repair it from the inbox. The result is kept in ``account.extra["webhook"]`` so the screens can
show it.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.http import ApiError, call
from app.modules.social import hooks
from app.modules.social.models import SocialAccount

from . import sources
from .config import inbox_settings

_logger = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com"
WANTED = ("messages", "feed")                              # tried first, together
ESSENTIAL = {"facebook": "feed", "instagram": "messages"}  # without it the account gets no events at all


def _graph() -> str:
    return "%s/%s" % (GRAPH, inbox_settings().meta_graph_version)


def page_of(account: SocialAccount) -> tuple[str | None, str | None]:
    """(page id, page token): a Facebook account is the page; an Instagram account uses its linked page."""
    if account.platform == "facebook":
        return account.external_id, account.access_token
    if account.platform == "instagram":
        return (account.extra or {}).get("page_id"), account.access_token
    return None, None


def _call(account: SocialAccount, method: str, page_id: str, operation: str, **kwargs):
    return call(method, "%s/%s/subscribed_apps" % (_graph(), page_id), service="inbox", operation=operation,
                workspace_id=account.workspace_id, **kwargs)


def subscribed_fields(db: Session, account: SocialAccount) -> list[str]:
    """Live check at Meta: the fields of this account's page that are subscribed for our app."""
    page_id, token = page_of(account)
    data = _call(account, "GET", page_id, "Read page subscription", params={"access_token": token})
    ours = sources.our_meta_app_ids(db, account.workspace_id)
    rows = data.get("data") or []
    mine = [a for a in rows if str(a.get("id")) in ours] if ours else rows
    return sorted({f for a in mine for f in (a.get("subscribed_fields") or [])})


def subscribe(account: SocialAccount) -> tuple[list[str], str | None]:
    """Subscribe the page to our app. Falls back to fewer fields when Meta refuses one of them (for example
    ``messages`` while the app has no Messenger permission), so the others still work.
    Returns (fields now subscribed, last error)."""
    page_id, token = page_of(account)
    error = None
    for fields in (WANTED, ("feed",), ("messages",)):
        try:
            _call(account, "POST", page_id, "Subscribe page to app",
                  data={"subscribed_fields": ",".join(fields), "access_token": token})
        except ApiError as exc:
            error = exc.message
            continue
        return list(fields), (error if len(fields) < len(WANTED) else None)
    return [], (error or "Meta refused the subscription")[:300]


def _store(account: SocialAccount, fields: list[str], error: str | None) -> bool:
    ok = ESSENTIAL.get(account.platform) in fields
    extra = dict(account.extra or {})
    extra["webhook"] = {"ok": ok, "fields": fields, "error": None if ok and not error else (error or "")[:300] or None,
                        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    account.extra = extra
    return ok


def health(account: SocialAccount) -> dict:
    return (account.extra or {}).get("webhook") or {}


def _by_page(accounts: list[SocialAccount]) -> dict[str, list[SocialAccount]]:
    pages: dict[str, list[SocialAccount]] = {}
    for account in accounts:
        page_id, token = page_of(account)
        if page_id and token:
            pages.setdefault(str(page_id), []).append(account)
    return pages


def ensure(db: Session, accounts: list[SocialAccount], *, force: bool = False) -> dict[int, bool]:
    """Make sure the pages of ``accounts`` are subscribed. One set of Graph calls per page: the page's Facebook and
    Instagram accounts share it. Returns {account id: ok}."""
    results: dict[int, bool] = {}
    for _page, group in _by_page(accounts).items():
        fields: list[str] | None = None
        error = None
        try:
            if not force:
                current = subscribed_fields(db, group[0])
                if all(ESSENTIAL.get(a.platform) in current for a in group):
                    fields = current
            if fields is None:
                fields, error = subscribe(group[0])
        except ApiError as exc:
            fields, error = [], exc.message[:300]
        except Exception as exc:  # never let one page stop the others
            _logger.exception("inbox: page subscription failed for account %s", group[0].id)
            fields, error = [], str(exc)[:300]
        for account in group:
            results[account.id] = _store(account, fields, error)
            if not results[account.id]:
                _logger.warning("inbox: account %s is NOT subscribed to the Meta app (%s)", account.id,
                                error or "needed field missing")
    db.flush()
    return results


def ensure_all(db: Session) -> dict:
    accounts = list(db.scalars(select(SocialAccount).where(
        SocialAccount.platform.in_(("facebook", "instagram")), SocialAccount.active.is_(True),
        SocialAccount.access_token.is_not(None), SocialAccount.state.in_(("connected", "draft")))))
    results = ensure(db, accounts)
    return {"checked": len(results), "problems": sum(1 for ok in results.values() if not ok)}


def after_connect(db: Session, accounts: list[SocialAccount]) -> None:
    """OAuth just connected these accounts: subscribe their pages right away (a failure never blocks connecting)."""
    meta = [a for a in accounts if a.platform in ("facebook", "instagram")]
    if meta:
        try:
            ensure(db, meta, force=True)
        except Exception:
            _logger.exception("inbox: could not subscribe the connected pages")


hooks.AFTER_CONNECT.append(after_connect)
