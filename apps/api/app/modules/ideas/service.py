"""Ideas service: make a batch, edit, approve (schedule through the normal publishing and approval flow),
reject, expire. Settings live in workspace settings under ``ideas.*``."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import AppError
from app.core.i18n import _
from app.core.models import Media
from app.modules.social.models import PUBLISH_PLATFORMS, SocialAccount
from app.modules.workspaces.models import Workspace
from app.modules.workspaces.settings import get_setting

from . import context as ctx_mod
from . import generator, slides
from .models import ContentIdea

DEFAULTS = {"daily": True, "count": 3, "language": None, "hour": 7}
REJECT_REASONS = ("not_relevant", "not_our_tone", "already_done", "bad_timing", "other")
EXPIRE_AFTER = timedelta(days=4)


def settings(db: Session, workspace: Workspace) -> dict:
    out = {key: get_setting(db, workspace.id, f"ideas.{key}", value) for key, value in DEFAULTS.items()}
    out["language"] = out["language"] or workspace.locale
    return out


def _accounts(db: Session, workspace_id: int, platforms: list[str] | None = None) -> list[SocialAccount]:
    stmt = select(SocialAccount).where(SocialAccount.workspace_id == workspace_id, SocialAccount.active.is_(True),
                                       SocialAccount.platform.in_(PUBLISH_PLATFORMS))
    if platforms:
        stmt = stmt.where(SocialAccount.platform.in_(platforms))
    return list(db.scalars(stmt.order_by(SocialAccount.id)))


def _text_only_ok(platform: str) -> bool:
    from app.modules.social.platforms import PUBLISHERS
    cls = PUBLISHERS.get(platform)
    return bool(cls and cls.supports_text_only and not cls.requires_media)


def _has_image(db: Session, product_id: int | None) -> bool:
    if not product_id:
        return False
    from app.modules.products.models import Product
    product = db.get(Product, product_id)
    return bool(product and product.image_media_id)


def _taken_slots(db: Session, workspace_id: int) -> set[str]:
    rows = db.scalars(select(ContentIdea.suggested_at).where(ContentIdea.workspace_id == workspace_id,
                                                             ContentIdea.state == "new",
                                                             ContentIdea.suggested_at.is_not(None)))
    return {r.isoformat() for r in rows}


def generate(db: Session, workspace: Workspace, user_id: int | None = None, *, count: int | None = None,
             language: str | None = None, focus: str | None = None, formats: list[str] | None = None) -> list[ContentIdea]:
    conf = settings(db, workspace)
    count = max(1, min(int(count or conf["count"]), 6))
    language = language or conf["language"]
    context = ctx_mod.build(db, workspace)
    items, by_ai = generator.generate(db, workspace, context, count, language, focus=focus, user_id=user_id)
    if formats:
        items = [i for i in items if i["format"] in formats] or items
    taken = _taken_slots(db, workspace.id)
    slots = [s for s in context.get("slots") or [] if s["at"].isoformat() not in taken]
    created = []
    for index, item in enumerate(items):
        platforms = list(context.get("platforms") or [])
        if item["format"] == "video":
            platforms = [p for p in platforms if p in generator.VIDEO_PLATFORMS] or platforms
        elif item["format"] == "post" and not _has_image(db, item.get("product_id")):
            platforms = [p for p in platforms if _text_only_ok(p)] or platforms
        slot = slots[index] if index < len(slots) else (slots[-1] if slots else None)
        reasons = list(item.get("reasons") or [])
        if slot:
            reasons.append({"kind": "best_time", "label": _("Your audience is most active {when}",
                                                            when=slot.get("label") or "")})
        idea = ContentIdea(
            workspace_id=workspace.id, state="new", format=item["format"], language=language, title=item["title"],
            reasons=reasons, caption=item["caption"], variants=item.get("variants"),
            hashtags=item.get("hashtags") or [], slides=item.get("slides") or [], video=item.get("video"),
            platforms=platforms, account_ids=[a.id for a in _accounts(db, workspace.id, platforms)],
            suggested_at=slot["at"] if slot else None, slot_label=(slot or {}).get("label"),
            pillar_id=item.get("pillar_id"), product_id=item.get("product_id"), ai_written=by_ai,
            created_by_id=user_id)
        db.add(idea)
        created.append(idea)
    db.flush()
    return created


def full_caption(idea: ContentIdea, text: str | None = None) -> str:
    body = (text if text is not None else idea.caption or "").rstrip()
    tags = " ".join(t for t in idea.hashtags or [] if t not in body)
    return f"{body}\n\n{tags}".strip() if tags else body


def render_slides(db: Session, workspace: Workspace, idea: ContentIdea, user_id: int | None = None) -> list[Media]:
    if idea.format != "carousel" or not idea.slides:
        return []
    brand = ctx_mod._brand(db, workspace)
    image = None
    if idea.product_id:
        from app.modules.products.models import Product
        product = db.get(Product, idea.product_id)
        image = product.image_media_id if product else None
    media = slides.render_carousel(db, workspace.id, idea.slides, brand, product_image_id=image, user_id=user_id,
                                   name=f"idea-{idea.id}")
    idea.media_ids = [m.id for m in media]
    db.flush()
    return media


def approve(db: Session, workspace: Workspace, idea: ContentIdea, user_id: int, *, mode: str = "suggested",
            when: datetime | None = None, account_ids: list[int] | None = None) -> dict:
    """mode: suggested (the idea's time) | best_time | schedule (``when``) | draft (studio, not scheduled)."""
    from app.modules.social import service as social

    if idea.state != "new":
        raise AppError(_("This idea was already handled."), code="idea_done")
    accounts = account_ids if account_ids is not None else idea.account_ids
    if mode != "draft" and not accounts:
        raise AppError(_("Choose at least one account to publish on."), code="idea_no_account")
    media_ids: list[int] = []
    if idea.format == "carousel":
        media_ids = [m.id for m in render_slides(db, workspace, idea, user_id)]
    elif idea.product_id:
        from app.modules.products.models import Product
        product = db.get(Product, idea.product_id)
        if product and product.image_media_id:
            media_ids = [product.image_media_id]
    skipped: list[str] = []
    if not media_ids and accounts and idea.format != "video":  # a text post cannot go to Instagram, TikTok…
        rows = db.scalars(select(SocialAccount).where(SocialAccount.id.in_(accounts))).all()
        keep = [a.id for a in rows if _text_only_ok(a.platform)]
        skipped = [a.name for a in rows if a.id not in keep]
        if not keep and mode != "draft":
            raise AppError(_("These accounts need a photo or a video. Add one in the studio, or choose other "
                             "accounts."), code="idea_needs_media")
        accounts = keep
    if idea.format == "video":
        mode = "draft"  # the video still has to be made: the post waits in the studio with the script as brief
    brief = None
    if idea.video:
        scenes = "\n".join(f"{i + 1}. {s.get('visual')} — {s.get('text')}" for i, s in enumerate(idea.video.get("scenes") or []))
        brief = f"{idea.video.get('hook')}\n{scenes}\n{idea.video.get('voiceover') or ''}".strip()
    post = social.create_post(db, workspace.id, user_id, content=full_caption(idea), media_ids=media_ids,
                              account_ids=accounts or [], variants=idea.variants, name=idea.title[:120],
                              pillar_id=idea.pillar_id, source_ref=f"idea:{idea.id}", ai_brief=brief)
    if mode == "draft":
        idea.state = "draft"
    else:
        at = when if mode == "schedule" else idea.suggested_at if mode == "suggested" else None
        if mode == "schedule" and not when:
            raise AppError(_("Choose a date and time."), code="idea_no_time")
        if at and at <= utcnow() + timedelta(minutes=5):
            at = None
        social.submit(db, post, user_id, action="schedule" if at else "best_time", when=at)
        idea.state = "scheduled"
    idea.post_id = post.id
    db.flush()
    url = f"/studio?post={post.id}" if idea.state == "draft" else (
        f"/approvals?post={post.id}" if post.state == "to_approve" else f"/planner?post={post.id}")
    return {"post_id": post.id, "post_state": post.state, "scheduled_at": post.scheduled_at, "url": url,
            "skipped_accounts": skipped}


def expire(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    rows = db.scalars(select(ContentIdea).where(ContentIdea.state == "new",
                                                ContentIdea.created_at < now - EXPIRE_AFTER)).all()
    for idea in rows:
        idea.state = "expired"
    db.flush()
    return len(rows)
