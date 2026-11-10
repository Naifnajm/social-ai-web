"""Brand kits: logo (a media id), colours, font, tone, rules, hashtags, visual style and voice."""
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.deps import Ctx, workspace_ctx
from app.core.errors import NotFound
from app.core.i18n import _
from app.core.models import Media
from app.modules.workspaces.models import Role

from . import identity, service
from .models import EMOJI_STYLES, LANGUAGE_STYLES, BrandKit

router = APIRouter(prefix="/brand-kits", tags=["brand kits"])

# CSS font stacks offered for kits; the web app loads the named Arabic families for previews.
FONTS = ["system-ui", "'IBM Plex Sans Arabic', sans-serif", "'Cairo', sans-serif", "'Tajawal', sans-serif",
         "'Almarai', sans-serif", "'Readex Pro', sans-serif", "'Alexandria', sans-serif",
         "'Noto Kufi Arabic', sans-serif", "'Changa', sans-serif", "'Noto Naskh Arabic', serif", "'Amiri', serif",
         "Tahoma, sans-serif", "Arial, sans-serif", "Georgia, serif", "'Times New Roman', serif",
         "'Courier New', monospace"]
COLOR_FIELDS = ("color_primary", "color_secondary", "color_text", "color_accent", "color_background")
NULLABLE = ("logo_media_id", "tagline", "tone", "guidelines", "hashtags", "visual_style", "voice", "color_accent",
            "color_background", "font_heading", "description", "industry", "audience", "personality",
            "language_style", "emoji_style", "cta", "banned_words", "sample_posts", "website")
COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _color(value):
    if value is not None and not COLOR.match(value):
        raise ValueError("colour must be like #112233")
    return value


def _code(value, field: str):
    allowed = LANGUAGE_STYLES if field == "language_style" else EMOJI_STYLES
    if value is not None and value not in allowed:
        raise ValueError(f"must be one of: {', '.join(allowed)}")
    return value


class BrandKitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    logo_media_id: int | None = None
    logo_url: str | None = None
    color_primary: str
    color_secondary: str
    color_text: str
    font_family: str
    tagline: str | None = None
    tone: str | None = None
    guidelines: str | None = None
    hashtags: str | None = None
    visual_style: str | None = None
    voice: str | None = None
    color_accent: str | None = None
    color_background: str | None = None
    font_heading: str | None = None
    description: str | None = None
    industry: str | None = None
    audience: str | None = None
    personality: str | None = None
    language_style: str | None = None
    emoji_style: str | None = None
    cta: str | None = None
    banned_words: str | None = None
    sample_posts: str | None = None
    website: str | None = None
    is_default: bool
    active: bool


class BrandKitIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    logo_media_id: int | None = None
    color_primary: str = "#111111"
    color_secondary: str = "#71717a"
    color_text: str = "#ffffff"
    font_family: str = Field(default="system-ui", max_length=80)
    tagline: str | None = Field(default=None, max_length=200)
    tone: str | None = Field(default=None, max_length=4000)
    guidelines: str | None = Field(default=None, max_length=8000)
    hashtags: str | None = Field(default=None, max_length=500)
    visual_style: str | None = Field(default=None, max_length=4000)
    voice: str | None = Field(default=None, max_length=120)
    color_accent: str | None = None
    color_background: str | None = None
    font_heading: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    industry: str | None = Field(default=None, max_length=120)
    audience: str | None = Field(default=None, max_length=1000)
    personality: str | None = Field(default=None, max_length=300)
    language_style: str | None = None
    emoji_style: str | None = None
    cta: str | None = Field(default=None, max_length=200)
    banned_words: str | None = Field(default=None, max_length=2000)
    sample_posts: str | None = Field(default=None, max_length=6000)
    website: str | None = Field(default=None, max_length=300)
    is_default: bool = False
    active: bool = True

    _colors = field_validator(*COLOR_FIELDS)(_color)
    _codes = field_validator("language_style", "emoji_style")(lambda v, info: _code(v, info.field_name))


class BrandKitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    logo_media_id: int | None = None
    color_primary: str | None = None
    color_secondary: str | None = None
    color_text: str | None = None
    font_family: str | None = Field(default=None, max_length=80)
    tagline: str | None = Field(default=None, max_length=200)
    tone: str | None = Field(default=None, max_length=4000)
    guidelines: str | None = Field(default=None, max_length=8000)
    hashtags: str | None = Field(default=None, max_length=500)
    visual_style: str | None = Field(default=None, max_length=4000)
    voice: str | None = Field(default=None, max_length=120)
    color_accent: str | None = None
    color_background: str | None = None
    font_heading: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    industry: str | None = Field(default=None, max_length=120)
    audience: str | None = Field(default=None, max_length=1000)
    personality: str | None = Field(default=None, max_length=300)
    language_style: str | None = None
    emoji_style: str | None = None
    cta: str | None = Field(default=None, max_length=200)
    banned_words: str | None = Field(default=None, max_length=2000)
    sample_posts: str | None = Field(default=None, max_length=6000)
    website: str | None = Field(default=None, max_length=300)
    is_default: bool | None = None
    active: bool | None = None

    _colors = field_validator(*COLOR_FIELDS)(_color)
    _codes = field_validator("language_style", "emoji_style")(lambda v, info: _code(v, info.field_name))


class BrandOptions(BaseModel):
    fonts: list[str]
    language_styles: list[str]
    emoji_styles: list[str]


class BrandBrief(BaseModel):
    """What the AI needs to draft an identity; ``palette`` = colours taken from the logo, most used first."""
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    industry: str | None = Field(default=None, max_length=120)
    audience: str | None = Field(default=None, max_length=1000)
    website: str | None = Field(default=None, max_length=300)
    language_style: str | None = None
    palette: list[str] = Field(default_factory=list, max_length=8)

    _codes = field_validator("language_style")(lambda v, info: _code(v, info.field_name))


class BrandDraft(BaseModel):
    """An AI-drafted identity: the form is filled with it, nothing is saved until the kit is."""
    color_primary: str
    color_secondary: str
    color_text: str
    font_family: str
    color_accent: str | None = None
    color_background: str | None = None
    font_heading: str | None = None
    tagline: str | None = None
    description: str | None = None
    audience: str | None = None
    personality: str | None = None
    tone: str | None = None
    language_style: str | None = None
    emoji_style: str | None = None
    cta: str | None = None
    guidelines: str | None = None
    banned_words: str | None = None
    hashtags: str | None = None
    visual_style: str | None = None
    sample_posts: str | None = None


def kit_out(kit: BrandKit) -> BrandKitOut:
    out = BrandKitOut.model_validate(kit)
    out.logo_url = f"/api/media/{kit.logo_media_id}/file" if kit.logo_media_id else None
    return out


def _check_logo(ctx: Ctx, media_id: int | None) -> None:
    if media_id is None:
        return
    media = ctx.db.get(Media, media_id)
    if not media or media.workspace_id != ctx.workspace.id or media.kind != "image":
        raise NotFound(_("File not found."))


@router.get("", response_model=list[BrandKitOut])
def list_kits(active_only: bool = False, ctx: Ctx = Depends(workspace_ctx())):
    return [kit_out(k) for k in service.list_kits(ctx.db, ctx.workspace.id, active_only)]


@router.get("/options", response_model=BrandOptions)
def options(ctx: Ctx = Depends(workspace_ctx())):
    return BrandOptions(fonts=FONTS, language_styles=list(LANGUAGE_STYLES), emoji_styles=list(EMOJI_STYLES))


@router.post("/generate", response_model=BrandDraft)
def generate(data: BrandBrief, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Draft a full identity with the workspace's text AI (uses AI credit; nothing is saved)."""
    return identity.generate(ctx.db, ctx.workspace.id, data.model_dump(), fonts=FONTS, user_id=ctx.user.id)


@router.get("/default", response_model=BrandKitOut | None)
def default(ctx: Ctx = Depends(workspace_ctx())):
    kit = service.default_kit(ctx.db, ctx.workspace.id)
    return kit_out(kit) if kit else None


@router.post("", response_model=BrandKitOut, status_code=201)
def create(data: BrandKitIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    _check_logo(ctx, data.logo_media_id)
    values = data.model_dump()
    want_default = values.pop("is_default")
    kit = BrandKit(workspace_id=ctx.workspace.id, **values)
    ctx.db.add(kit)
    ctx.db.flush()
    if want_default or not any(k.is_default for k in service.list_kits(ctx.db, ctx.workspace.id) if k.id != kit.id):
        service.set_default(ctx.db, kit)
    return kit_out(kit)


@router.get("/{kit_id}", response_model=BrandKitOut)
def one(kit_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return kit_out(service.get_kit(ctx.db, ctx.workspace.id, kit_id))


@router.patch("/{kit_id}", response_model=BrandKitOut)
def update(kit_id: int, data: BrandKitUpdate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    kit = service.get_kit(ctx.db, ctx.workspace.id, kit_id)
    values = data.model_dump(exclude_unset=True)
    if "logo_media_id" in values:
        _check_logo(ctx, values["logo_media_id"])
    want_default = values.pop("is_default", None)
    for key, value in values.items():
        if value is None and key not in NULLABLE:
            continue
        setattr(kit, key, value)
    if want_default:
        service.set_default(ctx.db, kit)
    elif want_default is False:
        kit.is_default = False
    if not kit.active:
        kit.is_default = False
    ctx.db.flush()
    return kit_out(kit)


@router.post("/{kit_id}/default", response_model=BrandKitOut)
def make_default(kit_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    kit = service.get_kit(ctx.db, ctx.workspace.id, kit_id)
    service.set_default(ctx.db, kit)
    return kit_out(kit)


@router.delete("/{kit_id}", status_code=204)
def delete(kit_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    kit = service.get_kit(ctx.db, ctx.workspace.id, kit_id)
    was_default = kit.is_default
    ctx.db.delete(kit)
    ctx.db.flush()
    if was_default:
        rest = service.list_kits(ctx.db, ctx.workspace.id, active_only=True)
        if rest:
            service.set_default(ctx.db, rest[0])
