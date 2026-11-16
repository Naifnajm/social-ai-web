"""Ideas of the day API. Everyone can read; editors generate, edit, approve and reject."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import LOCALES, _
from app.modules.billing import limits
from app.modules.social.models import Post, SocialAccount
from app.modules.workspaces.models import Role
from app.modules.workspaces.settings import set_setting

from . import service as svc
from .models import ContentIdea

router = APIRouter(prefix="/ideas", tags=["ideas"])
Language = Literal["ar", "en", "nl", "de", "fr"]


class GenerateIn(BaseModel):
    count: int | None = Field(default=None, ge=1, le=6)
    language: Language | None = None
    focus: str | None = Field(default=None, max_length=300)
    formats: list[Literal["post", "carousel", "video"]] | None = None


class Slide(BaseModel):
    title: str = Field(default="", max_length=120)
    body: str = Field(default="", max_length=400)


class Scene(BaseModel):
    visual: str = Field(default="", max_length=300)
    text: str = Field(default="", max_length=200)


class Video(BaseModel):
    hook: str = Field(default="", max_length=300)
    duration: int = Field(default=30, ge=5, le=180)
    scenes: list[Scene] = []
    voiceover: str = Field(default="", max_length=2000)


class IdeaPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    caption: str | None = Field(default=None, max_length=5000)
    variants: dict[str, str] | None = None
    hashtags: list[str] | None = Field(default=None, max_length=10)
    slides: list[Slide] | None = Field(default=None, max_length=10)
    video: Video | None = None
    suggested_at: datetime | None = None
    account_ids: list[int] | None = None


class ApproveIn(BaseModel):
    mode: Literal["suggested", "best_time", "schedule", "draft"] = "suggested"
    when: datetime | None = None
    account_ids: list[int] | None = None


class RejectIn(BaseModel):
    reason: Literal["not_relevant", "not_our_tone", "already_done", "bad_timing", "other"] = "other"


class SettingsIn(BaseModel):
    daily: bool = True
    count: int = Field(default=3, ge=1, le=6)
    language: Language | None = None
    hour: int = Field(default=7, ge=0, le=23)


def _idea(ctx: Ctx, idea_id: int) -> ContentIdea:
    idea = ctx.db.get(ContentIdea, idea_id)
    if not idea or idea.workspace_id != ctx.workspace.id:
        raise NotFound(_("Idea not found."))
    return idea


def idea_out(ctx: Ctx, idea: ContentIdea) -> dict:
    post = ctx.db.get(Post, idea.post_id) if idea.post_id else None
    return {
        "id": idea.id, "state": idea.state, "format": idea.format, "language": idea.language, "title": idea.title,
        "reasons": idea.reasons or [], "caption": idea.caption, "variants": idea.variants or {},
        "hashtags": idea.hashtags or [], "slides": idea.slides or [], "video": idea.video,
        "platforms": idea.platforms or [], "account_ids": idea.account_ids or [],
        "suggested_at": idea.suggested_at, "slot_label": idea.slot_label, "pillar_id": idea.pillar_id,
        "product_id": idea.product_id, "media_ids": idea.media_ids or [],
        "media_urls": [f"/api/media/{m}/file" for m in idea.media_ids or []],
        "ai_written": idea.ai_written, "edited": idea.edited, "created_at": idea.created_at,
        "rejected_reason": idea.rejected_reason,
        "post": {"id": post.id, "state": post.state, "scheduled_at": post.scheduled_at} if post else None,
    }


@router.get("")
def list_ideas(state: Literal["new", "handled", "all"] = "new", limit: int = Query(default=30, ge=1, le=100),
               ctx: Ctx = Depends(workspace_ctx())):
    stmt = select(ContentIdea).where(ContentIdea.workspace_id == ctx.workspace.id)
    if state == "new":
        stmt = stmt.where(ContentIdea.state == "new")
    elif state == "handled":
        stmt = stmt.where(ContentIdea.state.in_(("scheduled", "draft", "rejected")))
    rows = ctx.db.scalars(stmt.order_by(ContentIdea.created_at.desc(), ContentIdea.id).limit(limit))
    return [idea_out(ctx, i) for i in rows]


@router.get("/settings")
def get_settings(ctx: Ctx = Depends(workspace_ctx())):
    accounts = ctx.db.scalars(select(SocialAccount).where(SocialAccount.workspace_id == ctx.workspace.id,
                                                          SocialAccount.active.is_(True))).all()
    from app.modules.ai import service as ai
    from app.modules.social.publishing import approval_required
    return {**svc.settings(ctx.db, ctx.workspace), "languages": list(LOCALES),
            "approvals_required": approval_required(ctx.db, ctx.workspace.id, ctx.user.id),
            "has_ai": ai.has_provider(ctx.db, ctx.workspace.id, "text"),
            "accounts": [{"id": a.id, "name": a.name, "platform": a.platform, "avatar_url": a.avatar_url}
                         for a in accounts if a.platform != "whatsapp"]}


@router.put("/settings")
def put_settings(body: SettingsIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    for key, value in body.model_dump().items():
        set_setting(ctx.db, ctx.workspace.id, f"ideas.{key}", value)
    return get_settings(ctx)


@router.post("/generate")
def generate(body: GenerateIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    limits.require(ctx.db, ctx.workspace.id, "ai_studio")
    ideas = svc.generate(ctx.db, ctx.workspace, ctx.user.id, count=body.count, language=body.language,
                         focus=body.focus, formats=body.formats)
    return [idea_out(ctx, i) for i in ideas]


@router.get("/{idea_id}")
def one_idea(idea_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return idea_out(ctx, _idea(ctx, idea_id))


@router.patch("/{idea_id}")
def update_idea(idea_id: int, body: IdeaPatch, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    idea = _idea(ctx, idea_id)
    if idea.state != "new":
        raise AppError(_("This idea was already handled."), code="idea_done")
    data = body.model_dump(exclude_unset=True)
    if data.get("account_ids"):
        valid = set(ctx.db.scalars(select(SocialAccount.id).where(SocialAccount.workspace_id == ctx.workspace.id,
                                                                  SocialAccount.id.in_(data["account_ids"]))))
        if set(data["account_ids"]) - valid:
            raise NotFound(_("Account not found."))
    if "hashtags" in data and data["hashtags"] is not None:
        data["hashtags"] = ["#" + t.strip().lstrip("#").replace(" ", "_") for t in data["hashtags"] if t.strip()]
    for key, value in data.items():
        setattr(idea, key, value)
    if {"slides"} & data.keys():
        idea.media_ids = []  # the rendered slides no longer match
    idea.edited = True
    ctx.db.flush()
    return idea_out(ctx, idea)


@router.post("/{idea_id}/slides")
def render_slides(idea_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Render the carousel slides as images (the same ones that will be published)."""
    idea = _idea(ctx, idea_id)
    svc.render_slides(ctx.db, ctx.workspace, idea, ctx.user.id)
    return idea_out(ctx, idea)


@router.post("/{idea_id}/approve")
def approve(idea_id: int, body: ApproveIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    idea = _idea(ctx, idea_id)
    if body.account_ids:
        valid = set(ctx.db.scalars(select(SocialAccount.id).where(SocialAccount.workspace_id == ctx.workspace.id,
                                                                  SocialAccount.id.in_(body.account_ids))))
        if set(body.account_ids) - valid:
            raise NotFound(_("Account not found."))
    result = svc.approve(ctx.db, ctx.workspace, idea, ctx.user.id, mode=body.mode, when=body.when,
                         account_ids=body.account_ids)
    return {**result, "idea": idea_out(ctx, idea)}


@router.post("/{idea_id}/reject")
def reject(idea_id: int, body: RejectIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    idea = _idea(ctx, idea_id)
    if idea.state != "new":
        raise AppError(_("This idea was already handled."), code="idea_done")
    idea.state, idea.rejected_reason = "rejected", body.reason
    ctx.db.flush()
    return idea_out(ctx, idea)
