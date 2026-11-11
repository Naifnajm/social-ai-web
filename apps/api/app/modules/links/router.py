"""Links & conversions API: tracked links, results (clicks / sales per post, network, campaign), conversions,
tracking settings (pixel key, server key)."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.modules.planning.models import Campaign
from app.modules.planning.service import workspace_tz
from app.modules.social.models import Post
from app.modules.social.platforms import PLATFORM_LABELS
from app.modules.workspaces.models import Role
from app.modules.workspaces.settings import get_setting, set_setting

from . import service as svc
from .models import Conversion, TrackedLink
from .schemas import (ConversionIn, ConversionOut, LinkIn, LinkOut, LinkSettings, LinkSettingsOut, LinkUpdate,
                      PostLinksOut, ResultRow, SecretOut, SummaryOut, TopPost, Totals)

router = APIRouter(prefix="/links", tags=["links"])


def _names(ctx: Ctx, post_ids: set, campaign_ids: set) -> tuple[dict, dict]:
    posts = {p.id: p.name or "" for p in ctx.db.scalars(select(Post).where(
        Post.id.in_(post_ids), Post.workspace_id == ctx.workspace.id))} if post_ids else {}
    campaigns = {c.id: c for c in ctx.db.scalars(select(Campaign).where(
        Campaign.id.in_(campaign_ids), Campaign.workspace_id == ctx.workspace.id))} if campaign_ids else {}
    return posts, campaigns


def links_out(ctx: Ctx, links: list[TrackedLink]) -> list[LinkOut]:
    base = svc.short_base(ctx.db, ctx.workspace.id)
    add_ref = bool(get_setting(ctx.db, ctx.workspace.id, "links.add_ref", True))
    posts, campaigns = _names(ctx, {link.post_id for link in links if link.post_id},
                              {link.campaign_id for link in links if link.campaign_id})
    results: dict = {}
    if links:
        rows = ctx.db.execute(
            select(Conversion.link_id, func.count(Conversion.id), func.coalesce(func.sum(Conversion.value), 0.0))
            .where(Conversion.workspace_id == ctx.workspace.id, Conversion.link_id.in_([link.id for link in links]))
            .group_by(Conversion.link_id))
        results = {link_id: (count, float(value)) for link_id, count, value in rows}
    out = []
    for link in links:
        count, value = results.get(link.id, (0, 0.0))
        campaign = campaigns.get(link.campaign_id)
        out.append(LinkOut(
            id=link.id, code=link.code, short_url=f"{base}/r/{link.code}", url=link.url,
            destination=svc.destination(link, add_ref), kind=link.kind, label=link.label, post_id=link.post_id,
            post_name=posts.get(link.post_id), platform=link.platform, campaign_id=link.campaign_id,
            campaign_name=campaign.name if campaign else None, utm_source=link.utm_source,
            utm_medium=link.utm_medium, utm_campaign=link.utm_campaign, clicks=link.clicks or 0,
            conversions=count, revenue=round(value, 2), last_click_at=link.last_click_at,
            created_at=link.created_at))
    return out


def get_link(ctx: Ctx, link_id: int) -> TrackedLink:
    link = ctx.db.get(TrackedLink, link_id)
    if not link or link.workspace_id != ctx.workspace.id:
        raise NotFound(_("Link not found."))
    return link


def _check_campaign(ctx: Ctx, campaign_id: int | None) -> None:
    if campaign_id:
        campaign = ctx.db.get(Campaign, campaign_id)
        if not campaign or campaign.workspace_id != ctx.workspace.id:
            raise NotFound(_("Campaign not found."))


def _check_post(ctx: Ctx, post_id: int | None) -> Post | None:
    if not post_id:
        return None
    post = ctx.db.get(Post, post_id)
    if not post or post.workspace_id != ctx.workspace.id:
        raise NotFound(_("This post no longer exists."))
    return post


# ---------------------------------------------------------------------------------------------- results
def _totals(row: dict | None) -> Totals:
    row = row or {}
    clicks = row.get("clicks", 0)
    conversions = row.get("conversions", 0)
    return Totals(clicks=clicks, conversions=conversions, orders=row.get("orders", 0), leads=row.get("leads", 0),
                  revenue=row.get("revenue", 0.0),
                  conversion_rate=round(100.0 * conversions / clicks, 2) if clicks else 0.0)


@router.get("/summary", response_model=SummaryOut)
def summary(days: int = 30, ctx: Ctx = Depends(workspace_ctx())):
    days = max(1, min(days, 365))
    start, end = svc.period_bounds(days)
    ws = ctx.workspace.id
    totals = svc.results_by(ctx.db, ws, "all", start=start, end=end).get("all")
    previous = svc.results_by(ctx.db, ws, "all", start=start - (end - start), end=start).get("all")
    by_platform = svc.results_by(ctx.db, ws, "platform", start=start, end=end)
    by_campaign = svc.results_by(ctx.db, ws, "campaign", start=start, end=end)
    by_post = svc.results_by(ctx.db, ws, "post", start=start, end=end)
    post_names, campaigns = _names(ctx, set(by_post), set(by_campaign))
    top_ids = sorted(by_post, key=lambda pid: (by_post[pid]["revenue"], by_post[pid]["clicks"]), reverse=True)[:8]
    posts = {p.id: p for p in ctx.db.scalars(select(Post).where(Post.id.in_(top_ids), Post.workspace_id == ws)
                                             .options(selectinload(Post.media_links)))} if top_ids else {}
    platforms_of: dict = {}
    for post_id, platform in ctx.db.execute(select(TrackedLink.post_id, TrackedLink.platform).where(
            TrackedLink.workspace_id == ws, TrackedLink.post_id.in_(top_ids))) if top_ids else []:
        platforms_of.setdefault(post_id, set()).add(platform)
    top = []
    for pid in top_ids:
        post = posts.get(pid)
        if not post:
            continue
        row = by_post[pid]
        media = sorted(post.media_links, key=lambda m: m.position)
        top.append(TopPost(id=pid, name=post.name or "", platforms=sorted(p for p in platforms_of.get(pid, ()) if p),
                           clicks=row["clicks"], conversions=row["conversions"], revenue=row["revenue"],
                           thumb_url=f"/api/media/{media[0].media_id}/file" if media else None,
                           published_at=post.published_at))
    return SummaryOut(
        days=days, currency=ctx.workspace.currency, enabled=svc.is_enabled(ctx.db, ws),
        totals=_totals(totals), previous=_totals(previous),
        by_platform=sorted([ResultRow(key=k, label=PLATFORM_LABELS.get(k, k), **_totals(v).model_dump(
            exclude={"conversion_rate"})) for k, v in by_platform.items()], key=lambda r: (-r.revenue, -r.clicks)),
        by_campaign=sorted([ResultRow(key=str(k), label=campaigns[k].name, color=campaigns[k].color,
                                      **_totals(v).model_dump(exclude={"conversion_rate"}))
                            for k, v in by_campaign.items() if k in campaigns],
                           key=lambda r: (-r.revenue, -r.clicks)),
        top_posts=top,
        daily=svc.daily_series(ctx.db, ws, start, end, workspace_tz(ctx.workspace)),
    )


# ---------------------------------------------------------------------------------------------- links
@router.get("", response_model=list[LinkOut])
def list_links(post_id: int | None = None, campaign_id: int | None = None, platform: str | None = None,
               kind: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0,
               ctx: Ctx = Depends(workspace_ctx())):
    query = select(TrackedLink).where(TrackedLink.workspace_id == ctx.workspace.id)
    if post_id:
        query = query.where(TrackedLink.post_id == post_id)
    if campaign_id:
        query = query.where(TrackedLink.campaign_id == campaign_id)
    if platform:
        query = query.where(TrackedLink.platform == platform)
    if kind:
        query = query.where(TrackedLink.kind == kind)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(TrackedLink.url.ilike(like) | TrackedLink.label.ilike(like) | TrackedLink.code.ilike(like)
                            | TrackedLink.utm_campaign.ilike(like))
    links = ctx.db.scalars(query.order_by(TrackedLink.clicks.desc(), TrackedLink.id.desc())
                           .offset(max(offset, 0)).limit(min(max(limit, 1), 500))).all()
    return links_out(ctx, list(links))


@router.post("", response_model=LinkOut, status_code=201)
def create_link(body: LinkIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    _check_campaign(ctx, body.campaign_id)
    link = svc.create_manual_link(ctx.db, ctx.workspace.id, str(body.url), label=body.label,
                                  campaign_id=body.campaign_id, utm_source=body.utm_source,
                                  utm_campaign=body.utm_campaign)
    return links_out(ctx, [link])[0]


@router.patch("/{link_id}", response_model=LinkOut)
def update_link(link_id: int, body: LinkUpdate, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    link = get_link(ctx, link_id)
    link.label = (body.label or "").strip() or None
    ctx.db.flush()
    return links_out(ctx, [link])[0]


@router.delete("/{link_id}", status_code=204)
def delete_link(link_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    link = get_link(ctx, link_id)
    if link.kind != "manual":
        raise AppError(_("Links of published posts cannot be deleted: they would stop working."), code="in_use")
    ctx.db.delete(link)
    ctx.db.flush()
    return Response(status_code=204)


@router.get("/posts/{post_id}", response_model=PostLinksOut)
def post_links(post_id: int, ctx: Ctx = Depends(workspace_ctx())):
    post = _check_post(ctx, post_id)
    links = ctx.db.scalars(select(TrackedLink).where(TrackedLink.workspace_id == ctx.workspace.id,
                                                     TrackedLink.post_id == post.id).order_by(TrackedLink.id)).all()
    totals = svc.results_by(ctx.db, ctx.workspace.id, "post", post_ids=[post.id]).get(post.id) or {}
    return PostLinksOut(post_id=post.id, links=links_out(ctx, list(links)), clicks=totals.get("clicks", 0),
                        conversions=totals.get("conversions", 0), revenue=totals.get("revenue", 0.0),
                        currency=ctx.workspace.currency)


# ---------------------------------------------------------------------------------------------- conversions
def conversions_out(ctx: Ctx, rows: list[Conversion]) -> list[ConversionOut]:
    posts, campaigns = _names(ctx, {c.post_id for c in rows if c.post_id}, {c.campaign_id for c in rows if c.campaign_id})
    return [ConversionOut(
        id=c.id, kind=c.kind, value=c.value, currency=c.currency or ctx.workspace.currency, external_id=c.external_id,
        occurred_at=c.occurred_at, source=c.source, post_id=c.post_id, post_name=posts.get(c.post_id),
        platform=c.platform, campaign_id=c.campaign_id,
        campaign_name=campaigns[c.campaign_id].name if c.campaign_id in campaigns else None,
        product_id=c.product_id, utm_source=c.utm_source, utm_medium=c.utm_medium, utm_campaign=c.utm_campaign,
        note=c.note) for c in rows]


@router.get("/conversions", response_model=list[ConversionOut])
def list_conversions(days: int = 90, kind: str | None = None, post_id: int | None = None,
                     campaign_id: int | None = None, limit: int = 100, ctx: Ctx = Depends(workspace_ctx())):
    start, _end = svc.period_bounds(days)
    query = select(Conversion).where(Conversion.workspace_id == ctx.workspace.id, Conversion.occurred_at >= start)
    if kind:
        query = query.where(Conversion.kind == kind)
    if post_id:
        query = query.where(Conversion.post_id == post_id)
    if campaign_id:
        query = query.where(Conversion.campaign_id == campaign_id)
    rows = ctx.db.scalars(query.order_by(Conversion.occurred_at.desc()).limit(min(max(limit, 1), 500))).all()
    return conversions_out(ctx, list(rows))


@router.post("/conversions", response_model=ConversionOut, status_code=201)
def add_conversion(body: ConversionIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Report an order / lead (from your shop, CRM or by hand) with its click code or UTM tags."""
    _check_post(ctx, body.post_id)
    if body.product_id:
        from app.modules.products.models import Product
        product = ctx.db.get(Product, body.product_id)
        if not product or product.workspace_id != ctx.workspace.id:
            raise NotFound(_("Product not found."))
    conversion = svc.record_conversion(
        ctx.db, ctx.workspace.id, kind=body.kind, value=body.value, currency=body.currency,
        external_id=body.external_id, code=body.code, utm_source=body.utm_source, utm_medium=body.utm_medium,
        utm_campaign=body.utm_campaign, post_id=body.post_id, occurred_at=body.occurred_at,
        source="manual" if not (body.code or body.utm_source) else "api", note=body.note, product_id=body.product_id)
    return conversions_out(ctx, [conversion])[0]


@router.delete("/conversions/{conversion_id}", status_code=204)
def delete_conversion(conversion_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    conversion = ctx.db.get(Conversion, conversion_id)
    if not conversion or conversion.workspace_id != ctx.workspace.id:
        raise NotFound(_("Conversion not found."))
    ctx.db.delete(conversion)
    ctx.db.flush()
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------- settings
def _settings_out(ctx: Ctx) -> LinkSettingsOut:
    ws = ctx.workspace.id
    key = svc.public_key(ctx.db, ws)
    api = settings.public_api_url.rstrip("/")
    snippet = (f'<script async src="{api}/r/t.js?k={key}"></script>\n'
               '<script>\n'
               '  // on your "thank you" page, after an order:\n'
               '  window.stravicaQ = window.stravicaQ || [];\n'
               '  window.stravicaQ.push({ value: 199.00, currency: "%s", id: "ORDER-1001", kind: "order" });\n'
               '</script>') % ctx.workspace.currency
    return LinkSettingsOut(
        enabled=svc.is_enabled(ctx.db, ws), retag=bool(get_setting(ctx.db, ws, "links.retag", False)),
        add_ref=bool(get_setting(ctx.db, ws, "links.add_ref", True)), base_url=get_setting(ctx.db, ws, "links.base_url"),
        default_base_url=settings.public_api_url.rstrip("/"), public_key=key,
        has_secret=bool(get_setting(ctx.db, ws, "links.secret_hash")), snippet=snippet,
        pixel_url=f"{api}/r/conv?k={key}&value=199&currency={ctx.workspace.currency}&id=ORDER-1001",
        server_url=f"{api}/r/conv")


@router.get("/settings", response_model=LinkSettingsOut)
def get_link_settings(ctx: Ctx = Depends(workspace_ctx())):
    return _settings_out(ctx)


@router.put("/settings", response_model=LinkSettingsOut)
def put_link_settings(body: LinkSettings, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ws = ctx.workspace.id
    base = (body.base_url or "").strip().rstrip("/")
    if base and not base.startswith(("https://", "http://")):
        raise AppError(_("Enter a full web address starting with https://"), code="bad_url")
    set_setting(ctx.db, ws, "links.enabled", body.enabled)
    set_setting(ctx.db, ws, "links.retag", body.retag)
    set_setting(ctx.db, ws, "links.add_ref", body.add_ref)
    set_setting(ctx.db, ws, "links.base_url", base or None)
    return _settings_out(ctx)


@router.post("/settings/rotate-key", response_model=LinkSettingsOut)
def rotate_public_key(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    set_setting(ctx.db, ctx.workspace.id, "links.public_key", None)
    return _settings_out(ctx)


@router.post("/settings/secret", response_model=SecretOut)
def create_secret(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """A new server key for shops / CRMs (shown once). Replaces the previous one."""
    return SecretOut(secret=svc.new_secret(ctx.db, ctx.workspace.id))


@router.delete("/settings/secret", status_code=204)
def delete_secret(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    set_setting(ctx.db, ctx.workspace.id, "links.secret_hash", None)
    return Response(status_code=204)

