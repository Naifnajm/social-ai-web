"""Product catalogue API (lightweight) and the "announce new product" automation."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select

from app.core.deps import Ctx, workspace_ctx
from app.core.errors import NotFound
from app.core.i18n import _
from app.core.jobs import enqueue
from app.core.models import Media
from app.modules.social.models import Post, SocialAccount
from app.modules.workspaces.models import Role
from app.modules.workspaces.settings import set_setting

from . import service as svc
from .models import Product

router = APIRouter(prefix="/products", tags=["products"])


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    image_media_id: int | None = None
    url: HttpUrl | None = None
    sku: str | None = Field(default=None, max_length=80)
    active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    image_media_id: int | None = None
    url: HttpUrl | None = None
    sku: str | None = Field(default=None, max_length=80)
    active: bool | None = None


class ProductOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    price: float | None = None
    currency: str
    price_label: str
    image_media_id: int | None = None
    image_url: str | None = None
    url: str | None = None
    sku: str | None = None
    active: bool
    announced_post_id: int | None = None
    announced_post_state: str | None = None
    announced_at: datetime | None = None
    created_at: datetime


class AnnounceIn(BaseModel):
    mode: Literal["draft", "best_time"] | None = None
    account_ids: list[int] | None = None
    force: bool = False


class AnnounceOut(BaseModel):
    post_id: int
    state: str
    content: str
    studio_url: str


class ProductSettings(BaseModel):
    auto_announce: bool = False
    account_ids: list[int] = []
    caption: Literal["ai", "template"] = "ai"
    template: str = Field(default=svc.DEFAULT_TEMPLATE, max_length=2000)
    mode: Literal["draft", "best_time"] = "draft"
    design: str = Field(default="", max_length=40, description='Brand design: "template:<id>" or "set:<id>"')
    campaign_id: int | None = None


def get_product(ctx: Ctx, product_id: int) -> Product:
    product = ctx.db.get(Product, product_id)
    if not product or product.workspace_id != ctx.workspace.id:
        raise NotFound(_("Product not found."))
    return product


def _check_media(ctx: Ctx, media_id: int | None) -> None:
    if media_id:
        media = ctx.db.get(Media, media_id)
        if not media or media.workspace_id != ctx.workspace.id:
            raise NotFound(_("File not found."))


def product_out(ctx: Ctx, products: list[Product]) -> list[ProductOut]:
    ids = {p.announced_post_id for p in products if p.announced_post_id}
    states = dict(ctx.db.execute(select(Post.id, Post.state).where(Post.id.in_(ids))).all()) if ids else {}
    return [ProductOut(
        id=p.id, name=p.name, description=p.description, price=p.price, currency=p.currency or ctx.workspace.currency,
        price_label=svc.price_text(p, ctx.workspace), image_media_id=p.image_media_id,
        image_url=f"/api/media/{p.image_media_id}/file" if p.image_media_id else None, url=p.url, sku=p.sku,
        active=p.active, announced_post_id=p.announced_post_id if p.announced_post_id in states else None,
        announced_post_state=states.get(p.announced_post_id), announced_at=p.announced_at,
        created_at=p.created_at) for p in products]


@router.get("/settings", response_model=ProductSettings)
def get_product_settings(ctx: Ctx = Depends(workspace_ctx())):
    return ProductSettings(**svc.product_settings(ctx.db, ctx.workspace.id))


@router.put("/settings", response_model=ProductSettings)
def put_product_settings(body: ProductSettings, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    valid = set(ctx.db.scalars(select(SocialAccount.id).where(SocialAccount.workspace_id == ctx.workspace.id,
                                                              SocialAccount.id.in_(body.account_ids or [0]))))
    if set(body.account_ids) - valid:
        raise NotFound(_("Account not found."))
    if body.campaign_id:
        from app.modules.planning.models import Campaign
        campaign = ctx.db.get(Campaign, body.campaign_id)
        if not campaign or campaign.workspace_id != ctx.workspace.id:
            raise NotFound(_("Campaign not found."))
    for key, value in body.model_dump().items():
        set_setting(ctx.db, ctx.workspace.id, f"products.{key}", value)
    return ProductSettings(**svc.product_settings(ctx.db, ctx.workspace.id))


@router.get("", response_model=list[ProductOut])
def list_products(q: str | None = None, active: bool | None = None, ctx: Ctx = Depends(workspace_ctx())):
    query = select(Product).where(Product.workspace_id == ctx.workspace.id)
    if q and q.strip():
        query = query.where(Product.name.ilike(f"%{q.strip()}%") | Product.sku.ilike(f"%{q.strip()}%"))
    if active is not None:
        query = query.where(Product.active.is_(active))
    return product_out(ctx, list(ctx.db.scalars(query.order_by(Product.id.desc()).limit(500))))


@router.post("", response_model=ProductOut, status_code=201)
def create_product(body: ProductIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    _check_media(ctx, body.image_media_id)
    data = body.model_dump()
    data["url"] = str(body.url) if body.url else None
    data["currency"] = (body.currency or "").upper() or None
    product = Product(workspace_id=ctx.workspace.id, **data)
    ctx.db.add(product)
    ctx.db.flush()
    if product.active and svc.product_settings(ctx.db, ctx.workspace.id)["auto_announce"]:
        ctx.db.commit()  # the background job reads the product from its own session
        enqueue("app.modules.products.tasks.announce_product", product.id, ctx.user.id)
    return product_out(ctx, [product])[0]


@router.get("/{product_id}", response_model=ProductOut)
def one_product(product_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return product_out(ctx, [get_product(ctx, product_id)])[0]


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, body: ProductUpdate, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    product = get_product(ctx, product_id)
    data = body.model_dump(exclude_unset=True)
    if "image_media_id" in data:
        _check_media(ctx, data["image_media_id"])
    if "url" in data:
        data["url"] = str(data["url"]) if data["url"] else None
    if data.get("currency"):
        data["currency"] = data["currency"].upper()
    for key, value in data.items():
        setattr(product, key, value)
    ctx.db.flush()
    return product_out(ctx, [product])[0]


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    ctx.db.delete(get_product(ctx, product_id))
    ctx.db.flush()
    return Response(status_code=204)


@router.post("/{product_id}/announce", response_model=AnnounceOut)
def announce_product(product_id: int, body: AnnounceIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    product = get_product(ctx, product_id)
    if body.account_ids:
        valid = set(ctx.db.scalars(select(SocialAccount.id).where(SocialAccount.workspace_id == ctx.workspace.id,
                                                                  SocialAccount.id.in_(body.account_ids))))
        if set(body.account_ids) - valid:
            raise NotFound(_("Account not found."))
    post = svc.announce(ctx.db, ctx.workspace, product, ctx.user.id, mode=body.mode, account_ids=body.account_ids,
                        force=body.force)
    return AnnounceOut(post_id=post.id, state=post.state, content=post.content or "",
                       studio_url=f"/studio?post={post.id}")
