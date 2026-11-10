"""Brand kits for other features:

    from app.modules.brand import service as brand
    kit = brand.default_kit(db, ws_id)            # BrandKit | None (the default, else the first active one)
    kit = brand.get_kit(db, ws_id, kit_id)        # NotFound when it is not in the workspace
    kit.llm_profile()  /  kit.visual_hint()  /  brand.design(kit)   # text for prompts, design dict for templates
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.i18n import _

from .models import BrandKit


def get_kit(db: Session, workspace_id: int, kit_id: int) -> BrandKit:
    kit = db.get(BrandKit, kit_id)
    if not kit or kit.workspace_id != workspace_id:
        raise NotFound(_("Brand kit not found."), code="not_found")
    return kit


def list_kits(db: Session, workspace_id: int, active_only: bool = False) -> list[BrandKit]:
    query = select(BrandKit).where(BrandKit.workspace_id == workspace_id).order_by(BrandKit.is_default.desc(),
                                                                                   BrandKit.name, BrandKit.id)
    if active_only:
        query = query.where(BrandKit.active.is_(True))
    return list(db.scalars(query))


def default_kit(db: Session, workspace_id: int) -> BrandKit | None:
    kits = list_kits(db, workspace_id, active_only=True)
    return kits[0] if kits else None


def set_default(db: Session, kit: BrandKit) -> None:
    for other in db.scalars(select(BrandKit).where(BrandKit.workspace_id == kit.workspace_id,
                                                   BrandKit.is_default.is_(True), BrandKit.id != kit.id)):
        other.is_default = False
    kit.is_default = True
    kit.active = True
    db.flush()


def design(kit: BrandKit) -> dict:
    """What templates / production need to draw with the brand."""
    return {"id": kit.id, "name": kit.name, "logo_media_id": kit.logo_media_id,
            "color": kit.color_primary or "#111111", "color2": kit.color_secondary or "#71717a",
            "text_color": kit.color_text or "#ffffff", "font": kit.font_family or "system-ui",
            "accent": kit.color_accent or kit.color_secondary or "#71717a",
            "font_heading": kit.font_heading or kit.font_family or "system-ui"}
