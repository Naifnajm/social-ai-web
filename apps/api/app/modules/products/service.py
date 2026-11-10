"""Announce products on social media: caption (AI or template), branded image, post through the contract."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import ApiError, AppError
from app.core.i18n import _
from app.core.models import Media
from app.modules.social import service as social
from app.modules.social.models import Post, SocialAccount
from app.modules.workspaces.models import Workspace
from app.modules.workspaces.settings import get_setting

from .models import Product

_logger = logging.getLogger(__name__)
DEFAULT_TEMPLATE = "✨ {name}\n{description}\n{price}\n{url}"
LANGUAGES = {"ar": "Arabic", "en": "English", "nl": "Dutch"}


def product_settings(db: Session, workspace_id: int) -> dict:
    return {
        "auto_announce": bool(get_setting(db, workspace_id, "products.auto_announce", False)),
        "account_ids": [int(x) for x in get_setting(db, workspace_id, "products.account_ids", []) or []
                        if str(x).isdigit()],
        "caption": get_setting(db, workspace_id, "products.caption", "ai") or "ai",
        "template": get_setting(db, workspace_id, "products.template", DEFAULT_TEMPLATE) or DEFAULT_TEMPLATE,
        "mode": get_setting(db, workspace_id, "products.mode", "draft") or "draft",
        "design": get_setting(db, workspace_id, "products.design", "") or "",
        "campaign_id": get_setting(db, workspace_id, "products.campaign_id"),
    }


def price_text(product: Product, workspace: Workspace) -> str:
    if not product.price:
        return ""
    amount = f"{product.price:,.2f}".rstrip("0").rstrip(".")
    return f"{amount} {product.currency or workspace.currency}"


def template_caption(product: Product, workspace: Workspace, template: str) -> str:
    values = {"name": product.name, "description": (product.description or "")[:400],
              "price": price_text(product, workspace), "url": product.url or ""}
    text = template or DEFAULT_TEMPLATE
    for key, value in values.items():
        text = text.replace("{%s}" % key, value or "")
    return "\n".join(line for line in text.splitlines() if line.strip()).strip()


def ai_caption(db: Session, workspace: Workspace, product: Product, platforms: list[str],
               user_id: int | None = None) -> str:
    from app.modules.ai import service as ai
    language = LANGUAGES.get(workspace.locale, "Arabic")
    system = ("You write one social media post announcing a new product. Make people want it; mention the price "
              "if given. Do not invent features. If a link is given, put it at the end exactly as given. "
              f"Write in {language}. Networks: {', '.join(platforms) or 'any'}. "
              "Answer with the post text only, no quotes and no explanations.")
    user = (f"Product: {product.name}\nDescription: {(product.description or '-')[:1500]}\n"
            f"Price: {price_text(product, workspace) or '-'}\nLink: {product.url or '-'}")
    text = (ai.generate_text(db, workspace.id, system, user, purpose="product post", user_id=user_id) or "").strip()
    if not text:
        raise AppError(_("The AI returned an empty caption."), code="empty_caption")
    return text.strip("\"'“”«» \n")


def caption_for(db: Session, workspace: Workspace, product: Product, conf: dict, platforms: list[str],
                user_id: int | None = None) -> str:
    if conf["caption"] == "ai":
        try:
            return ai_caption(db, workspace, product, platforms, user_id)
        except (AppError, ApiError, NotImplementedError) as exc:
            _logger.info("AI caption for product %s failed, using the template: %s", product.id, exc)
    return template_caption(product, workspace, conf["template"])


def image_for(db: Session, workspace: Workspace, product: Product, conf: dict) -> int | None:
    """The product image, framed with the brand template when one is chosen (never fails the post)."""
    media = db.get(Media, product.image_media_id) if product.image_media_id else None
    if not media or media.workspace_id != workspace.id:
        return None
    if conf["design"]:
        try:
            from app.modules.templates import frame
            framed = frame.compose_for_post(db, workspace.id, conf["design"], media.id,
                                            text=price_text(product, workspace) or None)
            if framed is not None and getattr(framed, "id", None):
                return framed.id
        except Exception:  # NotImplementedError until the templates feature exists, or a design error
            _logger.info("brand template not applied to product %s", product.id, exc_info=True)
    return media.id


def announce(db: Session, workspace: Workspace, product: Product, user_id: int | None, *, mode: str | None = None,
             account_ids: list[int] | None = None, force: bool = False) -> Post:
    """Create the post announcing ``product`` (once; ``force`` makes a new one). Returns the post."""
    if product.announced_post_id and not force:
        existing = db.get(Post, product.announced_post_id)
        if existing and existing.workspace_id == workspace.id:
            return existing
    conf = product_settings(db, workspace.id)
    wanted = account_ids if account_ids is not None else conf["account_ids"]
    accounts = db.scalars(select(SocialAccount).where(
        SocialAccount.workspace_id == workspace.id, SocialAccount.id.in_(wanted or [0]),
        SocialAccount.active.is_(True))).all()
    platforms = sorted({a.platform for a in accounts})
    text = caption_for(db, workspace, product, conf, platforms, user_id)
    media_id = image_for(db, workspace, product, conf)
    campaign_id = conf["campaign_id"]
    if campaign_id:
        from app.modules.planning.models import Campaign
        campaign = db.get(Campaign, campaign_id)
        campaign_id = campaign.id if campaign and campaign.workspace_id == workspace.id else None
    post = social.create_post(db, workspace.id, user_id, content=text, media_ids=[media_id] if media_id else [],
                              account_ids=[a.id for a in accounts],
                              name=_("New product: {name}", name=product.name)[:200], campaign_id=campaign_id,
                              source_ref=f"product:{product.id}")
    product.announced_post_id = post.id
    product.announced_at = utcnow()
    db.flush()
    if (mode or conf["mode"]) == "best_time" and accounts:
        try:
            social.submit(db, post, user_id, action="best_time")
        except AppError as exc:
            _logger.info("product post %s kept as a draft: %s", post.id, exc.detail)
    return post
