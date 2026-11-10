"""Posts: content per network, validation, targets (one per account), publishing engine, scheduling, approvals.

Publishing never sends a post twice to the same account: each ``PostTarget`` is *claimed* atomically
(``pending`` → ``sending``) before the network is called, and every result is committed right away.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import AppError, Forbidden, NotFound
from app.core.http import ApiError
from app.core.i18n import _
from app.core.models import Media
from app.core.notify import notify, notify_role
from app.modules.workspaces.models import ROLE_RANK, Membership, Role
from app.modules.workspaces.settings import get_setting

from . import hooks
from .accounts import aware, can_publish, mark_failed
from .models import PUBLISH_PLATFORMS, Post, PostMedia, PostTarget, SocialAccount
from .platforms import PLATFORM_LABELS, STORY_PLATFORMS, get_publisher, kind_of, publisher_class

_logger = logging.getLogger(__name__)

ACTIONS = ("draft", "publish", "schedule", "best_time")
PUBLISH_AS = ("feed", "story", "feed_story")
EDITABLE_STATES = ("draft", "to_approve", "scheduled", "failed", "partial")
DELETABLE_STATES = ("draft", "to_approve", "scheduled", "failed")
APPROVALS_SETTING = "approvals.required"
# Changing one of these after approval withdraws the approval (for members who need one).
CONTENT_FIELDS = ("content", "variants", "media_ids", "story_media_ids", "platform_media", "account_ids",
                  "publish_as")
SENDING_TIMEOUT = timedelta(minutes=30)


class InvalidPost(AppError):
    def __init__(self, problems: list[dict]):
        detail = problems[0]["message"] if len(problems) == 1 else _("The post cannot be published yet: {first}",
                                                                     first=problems[0]["message"])
        super().__init__(detail, code="invalid_post", problems=problems)


# ------------------------------------------------------------------ content helpers
def text_for(post: Post, platform: str) -> str:
    return (((post.variants or {}).get(platform)) or post.content or "").strip()


def _media_rows(db: Session, workspace_id: int, ids: list[int]) -> list[Media]:
    if not ids:
        return []
    rows = {m.id: m for m in db.scalars(select(Media).where(Media.id.in_(ids), Media.workspace_id == workspace_id))}
    return [rows[i] for i in ids if i in rows]


def feed_media(db: Session, post: Post) -> list[Media]:
    ids = [link.media_id for link in post.media_links if link.role != "story"]
    return _media_rows(db, post.workspace_id, ids)


def story_media(db: Session, post: Post) -> list[Media]:
    ids = [link.media_id for link in post.media_links if link.role == "story"]
    media = _media_rows(db, post.workspace_id, ids) or feed_media(db, post)
    return [m for m in media if kind_of(m) in ("image", "video")]


def media_for(db: Session, post: Post, platform: str) -> list[Media]:
    ids = (post.platform_media or {}).get(platform)
    if ids:
        media = _media_rows(db, post.workspace_id, [int(i) for i in ids])
        if media:
            return media
    return feed_media(db, post)


def post_platforms(post: Post) -> list[str]:
    return sorted({a.platform for a in post.accounts})


def default_name(content: str | None) -> str | None:
    lines = (content or "").strip().splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    return first[:60] + ("…" if len(first) > 60 else "")


def media_type_of(media: list[Media]) -> str:
    kinds = [kind_of(m) for m in media]
    if "video" in kinds:
        return "video"
    if "audio" in kinds:
        return "audio"
    if len(kinds) > 1:
        return "carousel"
    return "image" if kinds else "text"


def hashtag_count(text: str) -> int:
    return len(re.findall(r"(?:^|\s)#\w", text or ""))


# ------------------------------------------------------------------ writing posts
def _check_accounts(db: Session, workspace_id: int, ids: list[int]) -> list[SocialAccount]:
    ids = list(dict.fromkeys(int(i) for i in ids or []))
    if not ids:
        return []
    accounts = {a.id: a for a in db.scalars(select(SocialAccount).where(SocialAccount.id.in_(ids),
                                                                         SocialAccount.workspace_id == workspace_id))}
    missing = [i for i in ids if i not in accounts]
    if missing:
        raise NotFound(_("Account not found."), code="account_not_found")
    for account in accounts.values():
        if account.platform not in PUBLISH_PLATFORMS:
            raise AppError(_("{name} is used by the inbox only and cannot publish posts.", name=account.name),
                           code="inbox_only_account")
    return [accounts[i] for i in ids]


def _check_media(db: Session, workspace_id: int, ids: list[int] | None) -> list[int]:
    ids = list(dict.fromkeys(int(i) for i in ids or []))
    if not ids:
        return []
    found = set(db.scalars(select(Media.id).where(Media.id.in_(ids), Media.workspace_id == workspace_id)))
    if len(found) != len(ids):
        raise NotFound(_("File not found."), code="media_not_found")
    return ids


def _check_ref(db: Session, model, workspace_id: int, ref_id: int | None, message: str) -> int | None:
    if not ref_id:
        return None
    row = db.get(model, ref_id)
    if row is None or row.workspace_id != workspace_id:
        raise NotFound(message)
    return ref_id


def content_signature(post: Post) -> str:
    return json.dumps([post.content or "", post.variants or {}, post.platform_media or {}, post.publish_as,
                       sorted((link.media_id, link.role, link.position) for link in post.media_links),
                       sorted(a.id for a in post.accounts)], sort_keys=True, default=str)


def apply_fields(db: Session, post: Post, data: dict) -> None:
    """Write composer fields on a post (ids are checked against the workspace)."""
    from app.modules.planning.models import Campaign, ContentPillar

    ws = post.workspace_id
    if "content" in data:
        post.content = data["content"] or ""
    if "name" in data:
        post.name = (data["name"] or "").strip()[:200] or None
    if "variants" in data:
        variants = {k: v.strip() for k, v in (data["variants"] or {}).items()
                    if k in PUBLISH_PLATFORMS and isinstance(v, str) and v.strip()}
        post.variants = variants or None
    if "platform_media" in data:
        platform_media = {}
        for platform, ids in (data["platform_media"] or {}).items():
            if platform in PUBLISH_PLATFORMS and ids:
                platform_media[platform] = _check_media(db, ws, ids)
        post.platform_media = platform_media or None
    if "publish_as" in data and data["publish_as"]:
        if data["publish_as"] not in PUBLISH_AS:
            raise AppError(_("Unknown publishing format."), code="bad_publish_as")
        post.publish_as = data["publish_as"]
    if "account_ids" in data:
        post.accounts = _check_accounts(db, ws, data["account_ids"] or [])
    if "media_ids" in data or "story_media_ids" in data:
        feed_ids = (_check_media(db, ws, data["media_ids"]) if "media_ids" in data
                    else [link.media_id for link in post.media_links if link.role != "story"])
        story_ids = (_check_media(db, ws, data["story_media_ids"]) if "story_media_ids" in data
                     else [link.media_id for link in post.media_links if link.role == "story"])
        post.media_links = ([PostMedia(media_id=mid, position=i, role="feed") for i, mid in enumerate(feed_ids)]
                            + [PostMedia(media_id=mid, position=i, role="story") for i, mid in enumerate(story_ids)])
    if "campaign_id" in data:
        post.campaign_id = _check_ref(db, Campaign, ws, data["campaign_id"], _("Campaign not found."))
    if "pillar_id" in data:
        post.pillar_id = _check_ref(db, ContentPillar, ws, data["pillar_id"], _("Content pillar not found."))
    for key in ("planned_date", "scheduled_at"):
        if key in data:
            value = data[key]
            if isinstance(value, datetime) and value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            setattr(post, key, value)
    for key in ("ai_brief", "source_ref", "brand_template_id"):
        if key in data:
            setattr(post, key, data[key])
    if not post.name and post.content:
        post.name = default_name(post.content)
    db.flush()


def update_post(db: Session, post: Post, user_id: int | None, data: dict) -> Post:
    if post.state not in EDITABLE_STATES:
        raise AppError(_("A post that is being published or already published cannot be changed."),
                       code="not_editable")
    before = content_signature(post)
    apply_fields(db, post, data)
    db.flush()
    if post.approved_by_id and approval_required(db, post.workspace_id, user_id) \
            and content_signature(post) != before:
        post.approved_by_id = None
        post.approved_at = None
        if post.state == "scheduled":
            send_for_approval(db, post, user_id, "schedule")
    return post


# ------------------------------------------------------------------ validation
def problems(db: Session, post: Post) -> list[dict]:
    """Everything that would make publishing fail, per network (messages in the user's language)."""
    out: list[dict] = []

    def add(message, platform=None, account_id=None):
        out.append({"platform": platform, "account_id": account_id, "message": message})

    if not post.accounts:
        add(_("Choose at least one account to publish on."))
        return out
    feed = feed_media(db, post)
    stories = story_media(db, post)
    for account in post.accounts:
        if not can_publish(account):
            add(_("{name} cannot publish posts.", name=account.name), account.platform, account.id)
        elif not account.access_token:
            add(_("“{name}” is not connected yet.", name=account.name), account.platform, account.id)
        elif account.state == "expired":
            add(_("“{name}” needs to be reconnected.", name=account.name), account.platform, account.id)
    for media in feed:
        if kind_of(media) not in ("image", "video", "audio"):
            add(_("“{name}” is not an image, video or audio file.", name=media.filename))
    if post.publish_as in ("story", "feed_story"):
        if not stories:
            add(_("A story needs an image or a video."))
        if post.publish_as == "story":
            for platform in post_platforms(post):
                if platform not in STORY_PLATFORMS:
                    add(_("{network} has no stories: only Instagram and Facebook Pages do.",
                          network=PLATFORM_LABELS[platform]), platform)
            return out
    if not (post.content or "").strip() and not feed and not post.variants and not post.platform_media:
        add(_("The post is empty."))
        return out
    for platform in post_platforms(post):
        cls = publisher_class(platform)
        for template, values in cls.rule_problems(text_for(post, platform), media_for(db, post, platform)):
            add(_(template, **values), platform)
    seen, unique = set(), []
    for item in out:
        key = (item["platform"], item["message"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def check_ready(db: Session, post: Post) -> None:
    found = problems(db, post)
    if found:
        raise InvalidPost(found)


# ------------------------------------------------------------------ approvals
def member_role(db: Session, workspace_id: int, user_id: int | None) -> Role | None:
    if user_id is None:
        return None
    role = db.scalar(select(Membership.role).where(Membership.workspace_id == workspace_id,
                                                   Membership.user_id == user_id))
    return Role(role) if role else None


def approvals_enabled(db: Session, workspace_id: int) -> bool:
    return bool(get_setting(db, workspace_id, APPROVALS_SETTING, False))


def can_approve(db: Session, workspace_id: int, user_id: int | None) -> bool:
    if user_id is None:  # system / automation
        return True
    role = member_role(db, workspace_id, user_id)
    return role is not None and ROLE_RANK[role] >= ROLE_RANK[Role.approver]


def approval_required(db: Session, workspace_id: int, user_id: int | None) -> bool:
    """True when this member may not publish or schedule without an approver."""
    return approvals_enabled(db, workspace_id) and not can_approve(db, workspace_id, user_id)


def send_for_approval(db: Session, post: Post, user_id: int | None, action: str) -> Post:
    post.state = "to_approve"
    post.requested_action = action
    post.approval_requested_by_id = user_id
    post.approval_requested_at = utcnow()
    post.approved_by_id = None
    post.approved_at = None
    sync_targets(db, post)
    db.flush()
    title = _("Post waiting for approval: {name}", name=post.name or _("Untitled"))
    notify_role(db, post.workspace_id, Role.approver, kind="post.approval", title=title,
                body=(post.content or "")[:180], link=f"/approvals?post={post.id}")
    return post


def approve(db: Session, post: Post, user_id: int) -> Post:
    if not can_approve(db, post.workspace_id, user_id):
        raise Forbidden(_("Only approvers can approve posts."), code="forbidden")
    if post.state != "to_approve":
        raise AppError(_("This post is not waiting for approval."), code="not_to_approve")
    check_ready(db, post)
    post.approved_by_id = user_id
    post.approved_at = utcnow()
    post.approval_note = None
    requester = post.approval_requested_by_id
    if post.requested_action == "schedule" and post.scheduled_at and aware(post.scheduled_at) > utcnow():
        _schedule(db, post)
    else:
        start_publishing(db, post)
    if requester and requester != user_id:
        notify(db, post.workspace_id, [requester], kind="post.approved",
               title=_("Your post was approved: {name}", name=post.name or _("Untitled")), link=f"/posts?post={post.id}")
    return post


def request_changes(db: Session, post: Post, user_id: int, note: str | None) -> Post:
    if not can_approve(db, post.workspace_id, user_id):
        raise Forbidden(_("Only approvers can request changes."), code="forbidden")
    if post.state not in ("to_approve", "scheduled"):
        raise AppError(_("This post is not waiting for approval."), code="not_to_approve")
    requester = post.approval_requested_by_id or post.author_id
    post.state = "draft"
    post.approved_by_id = None
    post.approved_at = None
    post.approval_note = (note or "").strip() or None
    db.flush()
    if requester and requester != user_id:
        notify(db, post.workspace_id, [requester], kind="post.changes_requested",
               title=_("Changes requested: {name}", name=post.name or _("Untitled")), body=post.approval_note or "",
               link=f"/studio?post={post.id}")
    return post


# ------------------------------------------------------------------ targets & state
def sync_targets(db: Session, post: Post) -> list[PostTarget]:
    """One target per selected account; keep the ones already published."""
    wanted = {a.id: a for a in post.accounts}
    for target in list(post.targets):
        if target.account_id not in wanted and target.state not in ("posted", "sending"):
            post.targets.remove(target)
    have = {t.account_id for t in post.targets}
    for account_id, account in wanted.items():
        if account_id not in have:
            post.targets.append(PostTarget(workspace_id=post.workspace_id, account_id=account_id,
                                           platform=account.platform, state="pending"))
    db.flush()
    return list(post.targets)


def update_state(db: Session, post: Post) -> None:
    current = {a.id for a in post.accounts}
    targets = [t for t in post.targets if t.account_id in current]
    states = {t.state for t in targets}
    story_failed = post.publish_as == "feed_story" and any(t.story_state == "failed" for t in targets)
    if "sending" in states:
        return
    if states and states <= {"posted"}:
        post.state = "partial" if story_failed else "posted"
    elif "posted" in states:
        post.state = "partial"
    elif "failed" in states:
        post.state = "failed"
    if post.state in ("posted", "partial"):
        post.published_at = post.published_at or utcnow()
    db.flush()


def _schedule(db: Session, post: Post) -> None:
    post.state = "scheduled"
    sync_targets(db, post)
    if post.scheduled_at and not post.planned_date:
        post.planned_date = post.scheduled_at
    db.flush()


def start_publishing(db: Session, post: Post) -> None:
    """Mark the post as publishing and hand it to the background worker."""
    from app.core.jobs import enqueue

    post.state = "publishing"
    for target in sync_targets(db, post):
        if target.state == "failed":
            target.state, target.error = "pending", None
        if post.publish_as in ("story", "feed_story") and target.story_state == "failed":
            target.story_state, target.story_error = "pending", None
    db.flush()
    db.commit()  # the worker reads the post from its own session
    enqueue("app.modules.social.tasks.publish_post", post.id)


def _run_limit_checks(db: Session, workspace_id: int) -> None:
    from app.modules.billing import limits

    limits.check(db, workspace_id, "posts_month")
    for check in hooks.POST_LIMIT_CHECKS:
        check(db, workspace_id)


def submit(db: Session, post: Post, user_id: int | None, *, action: str, when: datetime | None = None) -> Post:
    if action not in ACTIONS:
        raise AppError(_("Unknown action."), code="bad_action")
    if post.state == "publishing":
        raise AppError(_("This post is being published right now."), code="publishing")
    if post.state == "posted":
        raise AppError(_("This post is already published."), code="already_posted")
    if action == "draft":
        if post.state in ("scheduled", "to_approve"):
            post.state = "draft"
            post.requested_action = None
        db.flush()
        return post
    if action == "best_time":
        from .analytics import next_best_slots

        slots = next_best_slots(db, post.workspace_id, post_platforms(post), count=1)
        when, action = slots[0]["at"], "schedule"
    if action == "schedule":
        when = when or post.scheduled_at
        if when is None:
            raise AppError(_("Choose the date and time to publish."), code="no_date")
        when = aware(when)
        if when < utcnow() - timedelta(minutes=1):
            raise AppError(_("The publishing date is in the past."), code="date_in_past")
        post.scheduled_at = when
    check_ready(db, post)
    if post.state != "partial":
        _run_limit_checks(db, post.workspace_id)
    wants_review = False
    for check in hooks.BEFORE_SUBMIT:
        if check(db, post, user_id, action) == "to_approve":
            wants_review = True
    needs_review = wants_review or (approval_required(db, post.workspace_id, user_id) and not post.approved_by_id)
    if needs_review:
        return send_for_approval(db, post, user_id, action)
    if action == "schedule":
        _schedule(db, post)
    else:
        start_publishing(db, post)
    return post


def retry(db: Session, post: Post, user_id: int | None) -> Post:
    """Send again only what failed (feed and/or story); never what is already published."""
    if post.state not in ("failed", "partial"):
        raise AppError(_("Only failed posts can be retried."), code="not_failed")
    if approval_required(db, post.workspace_id, user_id) and not post.approved_by_id:
        raise Forbidden(_("Posts need an approval before they are published."), code="approval_required")
    start_publishing(db, post)
    return post


# ------------------------------------------------------------------ engine (background job)
def _claim(db: Session, target: PostTarget, column: str) -> bool:
    col = getattr(PostTarget, column)
    result = db.execute(update(PostTarget).where(PostTarget.id == target.id, col == "pending")
                        .values({column: "sending"}).execution_options(synchronize_session=False))
    db.commit()
    db.refresh(target)
    return result.rowcount == 1


def _apply_text_filters(db: Session, post: Post, account: SocialAccount, text: str) -> str:
    for text_filter in hooks.TEXT_FILTERS:
        try:
            text = text_filter(db, post, account, text)
        except Exception:
            _logger.exception("text filter %r failed", text_filter)
    return text


def _publish_feed(db: Session, post: Post, target: PostTarget) -> None:
    account = target.account
    text = _apply_text_filters(db, post, account, text_for(post, account.platform))
    media = media_for(db, post, account.platform)
    try:
        if not account.active or not account.access_token:
            raise ApiError(f"“{account.name}” is not connected.")
        publisher = get_publisher(db, account)
        publisher.check(text, media)
        result = publisher.publish(text, media)
    except ApiError as exc:
        target.state, target.error = "failed", exc.message
        mark_failed(account, exc)
        return
    except Exception as exc:  # never let one network break the others
        _logger.exception("publishing target %s failed", target.id)
        target.state, target.error = "failed", f"Unexpected error: {exc}"
        return
    target.state = "posted"
    target.media_type = media_type_of(media)
    target.text_length = len(text or "")
    target.hashtag_count = hashtag_count(text)
    target.external_id = (result.get("external_id") or None)
    target.external_url = (result.get("url") or None)
    target.error = None
    target.published_at = utcnow()


def _publish_story(db: Session, post: Post, target: PostTarget) -> None:
    account = target.account
    story_only = post.publish_as == "story"
    if account.platform not in STORY_PLATFORMS:
        message = f"{PLATFORM_LABELS[account.platform]} has no stories: only Instagram and Facebook Pages do."
        target.story_state, target.story_error = "skipped", message
        if story_only:
            target.state, target.error = "failed", message
        return
    try:
        result = get_publisher(db, account).publish_story(story_media(db, post))
    except ApiError as exc:
        target.story_state, target.story_error = "failed", exc.message
        if story_only:
            target.state, target.error = "failed", exc.message
        mark_failed(account, exc)
        return
    except Exception as exc:
        _logger.exception("story for target %s failed", target.id)
        message = f"Unexpected error: {exc}"
        target.story_state, target.story_error = "failed", message
        if story_only:
            target.state, target.error = "failed", message
        return
    target.story_state = "posted"
    target.story_external_id = result.get("external_id") or None
    target.story_url = result.get("url") or None
    target.story_error = None
    if story_only:
        target.state = "posted"
        target.media_type = "story"
        target.error = None
        target.external_id = (result.get("external_id") or "").split(",")[0] or None
        target.external_url = result.get("url") or None
        target.published_at = utcnow()


def run_publish(db: Session, post_id: int) -> Post | None:
    post = db.get(Post, post_id)
    if post is None or post.state != "publishing":
        return post
    published_now = False
    for target in list(post.targets):
        if post.publish_as != "story" and target.state == "pending" and _claim(db, target, "state"):
            _publish_feed(db, post, target)
            published_now |= target.state == "posted"
            db.commit()
        if post.publish_as in ("story", "feed_story"):
            if target.story_state in (None, "failed") and target.story_external_id is None:
                target.story_state = "pending"
                db.commit()
            if target.story_state == "pending" and _claim(db, target, "story_state"):
                if post.publish_as == "story" and target.state == "pending":
                    target.state = "sending"
                _publish_story(db, post, target)
                published_now |= target.state == "posted"
                db.commit()
    db.refresh(post)
    if any(t.state == "sending" or t.story_state == "sending" for t in post.targets):
        return post  # another worker is still sending one of the networks
    update_state(db, post)
    db.commit()
    if published_now:
        for callback in hooks.AFTER_PUBLISH:
            try:
                callback(db, post)
            except Exception:
                _logger.exception("after-publish hook %r failed", callback)
    failed = [t for t in post.targets if t.state == "failed" or t.story_state == "failed"]
    if failed and post.author_id:
        networks = ", ".join(sorted({PLATFORM_LABELS.get(t.platform, t.platform) for t in failed}))
        notify(db, post.workspace_id, [post.author_id], kind="post.failed",
               title=_("“{name}” could not be published on {networks}.", name=post.name or _("Untitled"),
                       networks=networks),
               body="\n".join(t.error or t.story_error or "" for t in failed)[:500], link=f"/posts?post={post.id}")
    db.commit()
    return post


def release_stuck_targets(db: Session) -> int:
    """Targets left in ``sending`` by a crashed worker: mark them failed (never re-sent automatically)."""
    limit = utcnow() - SENDING_TIMEOUT
    stuck = db.scalars(select(PostTarget).where(PostTarget.state == "sending", PostTarget.updated_at < limit)).all()
    for target in stuck:
        target.state = "failed"
        target.error = "Interrupted while sending. Check the network before retrying, it may already be published."
    stories = db.scalars(select(PostTarget).where(PostTarget.story_state == "sending",
                                                  PostTarget.updated_at < limit)).all()
    for target in stories:
        target.story_state = "failed"
        target.story_error = "Interrupted while sending. Check the network before retrying."
    for post_id in {t.post_id for t in [*stuck, *stories]}:
        post = db.get(Post, post_id)
        if post and post.state == "publishing":
            update_state(db, post)
    db.flush()
    return len(stuck) + len(stories)


def claim_due_posts(db: Session, limit: int = 50) -> list[int]:
    """Scheduled posts whose time has come → ``publishing`` (atomic: two schedulers never claim the same post)."""
    due = db.scalars(select(Post.id).where(Post.state == "scheduled", Post.scheduled_at <= utcnow())
                     .order_by(Post.scheduled_at).limit(limit)).all()
    claimed = []
    for post_id in due:
        result = db.execute(update(Post).where(Post.id == post_id, Post.state == "scheduled")
                            .values(state="publishing").execution_options(synchronize_session=False))
        if result.rowcount == 1:
            claimed.append(post_id)
    if claimed:
        db.commit()
        for post in db.scalars(select(Post).where(Post.id.in_(claimed))):
            db.refresh(post)
            sync_targets(db, post)
            for target in post.targets:
                if target.state == "failed":
                    target.state, target.error = "pending", None
        db.commit()
    return claimed
