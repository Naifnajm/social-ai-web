"""Reading what already exists on Meta: past conversations, past posts with their comments, and posts scheduled in
Meta's own tools (Business Suite / the Page's scheduler).

Everything is idempotent (re-running only adds what is new) and read-only towards Meta. Old messages never wake the
assistant (``service.bot_wanted`` ignores anything older than a few hours). Posts go to ``ExternalPost``, never to
``Post``: the publishing scheduler publishes every ``Post`` that is due and would post these a second time.
"""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.http import ApiError
from app.modules.social.models import ExternalPost, PostTarget, SocialAccount

from . import service, sources
from .messaging import get_messenger
from .text import parse_dt, utcnow

_logger = logging.getLogger(__name__)
MEDIA_TYPES = {"image": "image", "photo": "image", "video": "video", "carousel_album": "carousel"}


def _media_type(item: dict) -> str:
    raw = str(item.get("media_type") or item.get("status_type") or "").lower()
    for key, value in MEDIA_TYPES.items():
        if key in raw:
            return value
    return "text" if item.get("message") and not item.get("full_picture") else "image" if item.get("full_picture") \
        else "text"


def _upsert(db: Session, account: SocialAccount, item: dict, kind: str) -> tuple[ExternalPost, bool]:
    external_id = str(item["id"])
    row = db.scalar(select(ExternalPost).where(ExternalPost.account_id == account.id,
                                               ExternalPost.external_id == external_id))
    created = row is None
    if created:
        row = ExternalPost(workspace_id=account.workspace_id, account_id=account.id, platform=account.platform,
                           external_id=external_id)
        db.add(row)
    row.kind = kind
    row.text = item.get("message") or item.get("caption")
    row.permalink = (item.get("permalink_url") or item.get("permalink") or "")[:1000] or None
    row.media_url = (item.get("full_picture") or item.get("media_url") or item.get("thumbnail_url") or "")[:2000] \
        or None
    row.media_type = _media_type(item)
    if kind == "scheduled":
        row.scheduled_at = parse_dt(item.get("scheduled_publish_time"))
        row.published_at = None
    else:
        row.published_at = parse_dt(item.get("created_time") or item.get("timestamp"))
        row.scheduled_at = None
    if item.get("comments_count") is not None:
        row.comments_count = int(item["comments_count"] or 0)
    row.synced_at = utcnow()
    db.flush()
    return row, created


def sync_scheduled(db: Session, account: SocialAccount) -> int:
    """Mirror the posts scheduled on Meta's side (Facebook Pages). Rows that are no longer scheduled (published or
    deleted there) are dropped; published ones come back through the history import. Returns how many are scheduled."""
    if account.platform != "facebook":
        return 0
    seen: set[str] = set()
    for item in get_messenger(account).iter_posts("scheduled", 50):
        if item.get("id"):
            _upsert(db, account, item, "scheduled")
            seen.add(str(item["id"]))
    for row in db.scalars(select(ExternalPost).where(ExternalPost.account_id == account.id,
                                                     ExternalPost.kind == "scheduled")):
        if row.external_id not in seen:
            db.delete(row)
    db.flush()
    return len(seen)


def sync_all_scheduled(db: Session) -> dict:
    accounts = db.scalars(select(SocialAccount).where(
        SocialAccount.platform == "facebook", SocialAccount.active.is_(True),
        SocialAccount.access_token.is_not(None), SocialAccount.state.in_(("connected", "draft")))).all()
    done, errors = 0, []
    for account in accounts:
        try:
            with db.begin_nested():
                done += sync_scheduled(db, account)
        except ApiError as exc:
            errors.append("%s: %s" % (account.name, exc.message))
    return {"scheduled": done, "errors": errors}


def import_history(db: Session, account: SocialAccount, *, days: int = 90, max_threads: int = 100,
                   max_posts: int = 50) -> dict:
    """Past conversations (``max_threads``, last 50 messages each), past posts with their comments and, for
    Facebook, the posts scheduled on Meta. Each part is independent: one failing does not stop the others."""
    if account.platform not in ("facebook", "instagram"):
        raise ApiError("History import works for Facebook Pages and Instagram accounts.")
    result = {"messages": 0, "comments": 0, "posts": 0, "scheduled": 0, "errors": [], "notes": []}
    messenger = get_messenger(account)
    since = utcnow() - timedelta(days=max(1, min(days, 730)))

    def step(label, fn):
        try:
            with db.begin_nested():
                fn()
        except ApiError as exc:
            result["errors"].append("%s: %s" % (label, sources._meta_poll_error(account, label, exc)))

    def messages():
        for thread in messenger.iter_conversations(max_threads):
            if thread.get("updated_time") and parse_dt(thread["updated_time"]) < since:
                break  # newest first: everything after is older
            result["messages"] += sources.import_thread(db, account, thread)

    def posts():
        importer = sources.import_facebook_comments if account.platform == "facebook" \
            else sources.import_instagram_comments
        for item in messenger.iter_posts("published", max_posts):
            when = parse_dt(item.get("created_time") or item.get("timestamp"))
            if when < since:
                break
            made_here = db.scalar(select(PostTarget.id).where(PostTarget.account_id == account.id,
                                                              PostTarget.external_id == str(item["id"])).limit(1))
            if made_here is None:  # posts made from this platform are already in the calendar
                _row, created = _upsert(db, account, item, "published")
                result["posts"] += int(created)
            post = service.post_info(db, account, item["id"])
            post.update(url=post.get("url") or item.get("permalink_url") or item.get("permalink"),
                        text=item.get("message") or item.get("caption"))
            result["comments"] += importer(db, account, messenger, post)

    def scheduled():
        result["scheduled"] = sync_scheduled(db, account)
        if account.platform == "instagram":
            result["notes"].append("Instagram does not expose posts scheduled in Meta's tools through its API.")

    step("messages", messages)
    step("posts", posts)
    step("scheduled", scheduled)
    return result
