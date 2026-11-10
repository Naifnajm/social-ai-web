"""Media library API (on top of the core ``/api/media`` upload): search, filters, tags, favourites, usage,
safe delete and "use in Studio"."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError

from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, Forbidden, NotFound
from app.core.i18n import _
from app.core.models import Media
from app.core.storage import delete_media_file
from app.modules.social import service as social
from app.modules.social.models import Post, PostMedia
from app.modules.workspaces.models import Role

router = APIRouter(prefix="/library", tags=["library"])
KINDS = ("image", "video", "audio")


class LibraryItem(BaseModel):
    id: int
    filename: str
    mimetype: str
    kind: str
    size: int
    source: str
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    tags: list[str]
    favorite: bool
    used: int = Field(description="Number of posts (and products) using this file")
    author: str | None = None
    created_by_id: int | None = None
    created_at: datetime
    url: str
    thumb_url: str


class TagCount(BaseModel):
    name: str
    count: int


class LibraryPage(BaseModel):
    items: list[LibraryItem]
    total: int
    tags: list[TagCount]
    counts: dict[str, int] = Field(description="Files per kind (image, video, audio) for the current filters")


class LibraryUpdate(BaseModel):
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    tags: list[str] | None = None
    favorite: bool | None = None


class UsagePost(BaseModel):
    id: int
    name: str
    state: str
    date: datetime | None = None


class UsageOut(BaseModel):
    posts: list[UsagePost]
    products: list[dict]
    total: int


class TagRename(BaseModel):
    old: str = Field(min_length=1, max_length=40)
    new: str = Field(min_length=1, max_length=40)


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    action: Literal["delete", "favorite", "unfavorite", "add_tag", "remove_tag"]
    tag: str | None = Field(default=None, max_length=40)


class BulkOut(BaseModel):
    done: list[int]
    skipped: list[int]


class UseOut(BaseModel):
    post_id: int
    studio_url: str


def clean_tags(names: list[str]) -> list[str]:
    seen, out = set(), []
    for name in names or []:
        name = " ".join((name or "").split())[:40]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out[:20]


def get_item(ctx: Ctx, media_id: int) -> Media:
    media = ctx.db.get(Media, media_id)
    if not media or media.workspace_id != ctx.workspace.id:
        raise NotFound(_("File not found."))
    return media


def usage_counts(ctx: Ctx, ids: list[int]) -> dict[int, int]:
    """``{media id: number of posts (+ products) using it}`` — post media and per-network media."""
    usage = dict.fromkeys(ids, 0)
    if not ids:
        return usage
    rows = ctx.db.execute(select(PostMedia.media_id, func.count(func.distinct(PostMedia.post_id)))
                          .join(Post, Post.id == PostMedia.post_id)
                          .where(Post.workspace_id == ctx.workspace.id, PostMedia.media_id.in_(ids))
                          .group_by(PostMedia.media_id))
    for media_id, count in rows:
        usage[media_id] += count
    wanted = set(ids)
    direct = {(pid, mid) for pid, mid in ctx.db.execute(
        select(PostMedia.post_id, PostMedia.media_id).join(Post, Post.id == PostMedia.post_id)
        .where(Post.workspace_id == ctx.workspace.id, PostMedia.media_id.in_(ids)))}
    for post_id, platform_media in ctx.db.execute(select(Post.id, Post.platform_media).where(
            Post.workspace_id == ctx.workspace.id, Post.platform_media.is_not(None))):
        found = {int(i) for values in (platform_media or {}).values() for i in (values or []) if str(i).isdigit()}
        for media_id in found & wanted:
            if (post_id, media_id) not in direct:
                usage[media_id] += 1
    from app.modules.products.models import Product
    for media_id, count in ctx.db.execute(select(Product.image_media_id, func.count()).where(
            Product.workspace_id == ctx.workspace.id, Product.image_media_id.in_(ids)).group_by(Product.image_media_id)):
        usage[media_id] += count
    return usage


def items_out(ctx: Ctx, medias: list[Media]) -> list[LibraryItem]:
    from app.modules.auth.models import User
    usage = usage_counts(ctx, [m.id for m in medias])
    authors = {u.id: u.name for u in ctx.db.scalars(select(User).where(
        User.id.in_({m.created_by_id for m in medias if m.created_by_id})))} if medias else {}
    return [LibraryItem(
        id=m.id, filename=m.filename, mimetype=m.mimetype, kind=m.kind, size=m.size or 0, source=m.source,
        width=m.width, height=m.height, duration=m.duration, tags=list(m.tags or []), favorite=bool(m.favorite),
        used=usage.get(m.id, 0), author=authors.get(m.created_by_id), created_by_id=m.created_by_id,
        created_at=m.created_at, url=f"/api/media/{m.id}/file",
        thumb_url=f"/api/media/{m.id}/file" if m.kind == "image" else "") for m in medias]


def _filtered(ctx: Ctx, q: str | None, source: str | None, tag: str | None, favorite: bool | None,
              unused: bool | None):
    query = select(Media).where(Media.workspace_id == ctx.workspace.id,
                                or_(*[Media.mimetype.startswith(f"{k}/") for k in KINDS]))
    if q and q.strip():
        query = query.where(Media.filename.ilike(f"%{q.strip()}%"))
    if source:
        query = query.where(Media.source == source)
    if tag:
        query = query.where(cast(Media.tags, JSONB).contains([tag]))
    if favorite:
        query = query.where(Media.favorite.is_(True))
    if unused:
        used_ids = select(PostMedia.media_id)
        query = query.where(Media.id.not_in(used_ids))
    return query


def tag_counts(ctx: Ctx) -> list[TagCount]:
    counts: dict[str, int] = {}
    for (tags,) in ctx.db.execute(select(Media.tags).where(Media.workspace_id == ctx.workspace.id,
                                                           Media.tags.is_not(None))):
        for name in tags or []:
            counts[name] = counts.get(name, 0) + 1
    return [TagCount(name=n, count=c) for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]


@router.get("/media", response_model=LibraryPage)
def search(q: str | None = None, kind: str | None = None, source: str | None = None, tag: str | None = None,
           favorite: bool | None = None, unused: bool | None = None,
           sort: Literal["new", "old", "name", "size"] = "new", offset: int = 0, limit: int = 60,
           ctx: Ctx = Depends(workspace_ctx())):
    base = _filtered(ctx, q, source, tag, favorite, unused)
    query = base.where(Media.mimetype.startswith(f"{kind}/")) if kind in KINDS else base
    order = {"new": (Media.created_at.desc(), Media.id.desc()), "old": (Media.created_at, Media.id),
             "name": (func.lower(Media.filename), Media.id), "size": (Media.size.desc(), Media.id.desc())}[sort]
    total = ctx.db.scalar(select(func.count()).select_from(query.subquery())) or 0
    medias = ctx.db.scalars(query.order_by(*order).offset(max(offset, 0)).limit(min(max(limit, 1), 200))).all()
    counts = {k: 0 for k in KINDS}
    for kind_name, count in ctx.db.execute(_kind_counts(base)):
        if kind_name in counts:
            counts[kind_name] = count
    return LibraryPage(items=items_out(ctx, list(medias)), total=total, tags=tag_counts(ctx), counts=counts)


def _kind_counts(base):
    sub = base.subquery()
    kind = func.split_part(sub.c.mimetype, "/", 1)
    return select(kind, func.count()).group_by(kind)


@router.get("/media/{media_id}", response_model=LibraryItem)
def one(media_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return items_out(ctx, [get_item(ctx, media_id)])[0]


@router.patch("/media/{media_id}", response_model=LibraryItem)
def update(media_id: int, body: LibraryUpdate, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    media = get_item(ctx, media_id)
    if body.filename is not None:
        media.filename = body.filename.strip()[:255]
    if body.tags is not None:
        media.tags = clean_tags(body.tags)
    if body.favorite is not None:
        media.favorite = body.favorite
    ctx.db.flush()
    return items_out(ctx, [media])[0]


@router.post("/media/{media_id}/favorite", response_model=LibraryItem)
def toggle_favorite(media_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    media = get_item(ctx, media_id)
    media.favorite = not media.favorite
    ctx.db.flush()
    return items_out(ctx, [media])[0]


@router.get("/media/{media_id}/usage", response_model=UsageOut)
def usage(media_id: int, ctx: Ctx = Depends(workspace_ctx())):
    media = get_item(ctx, media_id)
    direct = set(ctx.db.scalars(select(PostMedia.post_id).join(Post, Post.id == PostMedia.post_id).where(
        Post.workspace_id == ctx.workspace.id, PostMedia.media_id == media.id)))
    for post_id, platform_media in ctx.db.execute(select(Post.id, Post.platform_media).where(
            Post.workspace_id == ctx.workspace.id, Post.platform_media.is_not(None))):
        if any(str(media.id) == str(i) for values in (platform_media or {}).values() for i in (values or [])):
            direct.add(post_id)
    posts = ctx.db.scalars(select(Post).where(Post.id.in_(direct)).order_by(Post.id.desc())).all() if direct else []
    from app.modules.products.models import Product
    products = ctx.db.scalars(select(Product).where(Product.workspace_id == ctx.workspace.id,
                                                    Product.image_media_id == media.id)).all()
    return UsageOut(
        posts=[UsagePost(id=p.id, name=p.name or "", state=p.state,
                         date=p.published_at or p.scheduled_at or p.planned_date) for p in posts],
        products=[{"id": p.id, "name": p.name} for p in products], total=len(posts) + len(products))


def _can_delete(ctx: Ctx, media: Media) -> None:
    if not ctx.can(Role.admin) and media.created_by_id != ctx.user.id:
        raise Forbidden(_("Only the person who added this file or an administrator can delete it."),
                        code="forbidden")


def _delete(ctx: Ctx, media: Media) -> None:
    used = usage_counts(ctx, [media.id])[media.id]
    if used:
        raise AppError(_("This file is used by {count} post(s) or product(s) and cannot be deleted.", count=used),
                       code="in_use", status_code=409)
    try:
        with ctx.db.begin_nested():
            ctx.db.delete(media)
            ctx.db.flush()
    except IntegrityError:  # referenced by another feature (brand template, production board…)
        raise AppError(_("This file is still used elsewhere (templates or production) and cannot be deleted."),
                       code="in_use", status_code=409)
    delete_media_file(media)


@router.delete("/media/{media_id}", status_code=204)
def delete(media_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    media = get_item(ctx, media_id)
    _can_delete(ctx, media)
    _delete(ctx, media)
    return Response(status_code=204)


@router.post("/media/bulk", response_model=BulkOut)
def bulk(body: BulkIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    medias = ctx.db.scalars(select(Media).where(Media.workspace_id == ctx.workspace.id,
                                                Media.id.in_(body.ids))).all()
    if len(medias) != len(set(body.ids)):
        raise NotFound(_("File not found."))
    tag = clean_tags([body.tag or ""])
    if body.action in ("add_tag", "remove_tag") and not tag:
        raise AppError(_("Enter a tag."), code="no_tag")
    done, skipped = [], []
    for media in medias:
        if body.action == "delete":
            try:
                _can_delete(ctx, media)
                _delete(ctx, media)
                done.append(media.id)
            except AppError:
                skipped.append(media.id)
            continue
        if body.action in ("favorite", "unfavorite"):
            media.favorite = body.action == "favorite"
        elif body.action == "add_tag":
            media.tags = clean_tags(list(media.tags or []) + tag)
        else:
            media.tags = [t for t in (media.tags or []) if t.lower() != tag[0].lower()]
        done.append(media.id)
    ctx.db.flush()
    return BulkOut(done=done, skipped=skipped)


@router.get("/tags", response_model=list[TagCount])
def tags(ctx: Ctx = Depends(workspace_ctx())):
    return tag_counts(ctx)


@router.post("/tags/rename", response_model=list[TagCount])
def rename_tag(body: TagRename, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    old, new = body.old.strip().lower(), clean_tags([body.new])
    for media in ctx.db.scalars(select(Media).where(Media.workspace_id == ctx.workspace.id,
                                                    Media.tags.is_not(None))):
        if any(t.lower() == old for t in media.tags or []):
            media.tags = clean_tags([new[0] if t.lower() == old else t for t in media.tags])
    ctx.db.flush()
    return tag_counts(ctx)


@router.delete("/tags/{name}", response_model=list[TagCount])
def delete_tag(name: str, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    for media in ctx.db.scalars(select(Media).where(Media.workspace_id == ctx.workspace.id,
                                                    Media.tags.is_not(None))):
        if any(t.lower() == name.lower() for t in media.tags or []):
            media.tags = [t for t in media.tags if t.lower() != name.lower()]
    ctx.db.flush()
    return tag_counts(ctx)


@router.post("/media/{media_id}/use", response_model=UseOut)
def use_in_studio(media_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Start a draft post with this file (then open it in the Studio)."""
    media = get_item(ctx, media_id)
    post = social.create_post(ctx.db, ctx.workspace.id, ctx.user.id, content="", media_ids=[media.id],
                              name=media.filename.rsplit(".", 1)[0][:200], source_ref=f"library:{media.id}")
    return UseOut(post_id=post.id, studio_url=f"/studio?post={post.id}")

