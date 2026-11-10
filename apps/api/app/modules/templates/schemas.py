"""Request/response schemas of the brand templates API (also used by the mobile app through OpenAPI)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.files.router import MediaOut

TemplateFormat = Literal["post_4x5", "post_1x1", "story_9x16", "landscape_16x9"]
Category = Literal["offers", "product", "event", "quote", "other"]
LogoPosition = Literal["top_left", "top_right", "bottom_left", "bottom_right"]
PhotoFit = Literal["cover", "contain"]
TextAlign = Literal["auto", "left", "center", "right"]
PublishAs = Literal["feed", "story", "feed_story"]
Color = str  # "#rrggbb"

PCT = {"ge": 0, "le": 100}


class TemplateFields(BaseModel):
    """Editable fields of a brand template (all optional: used for create, update and live preview)."""

    name: str | None = Field(default=None, max_length=120)
    sequence: int | None = None
    active: bool | None = None
    set_id: int | None = None
    brand_kit_id: int | None = None
    category: Category | None = None
    format: TemplateFormat | None = None
    frame_media_id: int | None = None
    background_color: Color | None = Field(default=None, max_length=9)
    box_x: float | None = Field(default=None, **PCT)
    box_y: float | None = Field(default=None, **PCT)
    box_w: float | None = Field(default=None, gt=0, le=100)
    box_h: float | None = Field(default=None, gt=0, le=100)
    photo_fit: PhotoFit | None = None
    text_enabled: bool | None = None
    text_x: float | None = Field(default=None, **PCT)
    text_y: float | None = Field(default=None, **PCT)
    text_w: float | None = Field(default=None, gt=0, le=100)
    text_h: float | None = Field(default=None, gt=0, le=100)
    text_size: int | None = Field(default=None, ge=10, le=400)
    text_color: Color | None = Field(default=None, max_length=9)
    text_bg_color: Color | None = Field(default=None, max_length=9)
    text_align: TextAlign | None = None
    text_bold: bool | None = None
    text_max_lines: int | None = Field(default=None, ge=1, le=8)
    text_default: str | None = Field(default=None, max_length=200)
    logo_enabled: bool | None = None
    logo_position: LogoPosition | None = None
    logo_size: float | None = Field(default=None, ge=3, le=60)


class TemplateCreate(TemplateFields):
    name: str = Field(min_length=1, max_length=120)


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sequence: int
    active: bool
    set_id: int | None
    set_name: str | None = None
    brand_kit_id: int | None
    category: str
    format: TemplateFormat
    aspect: str
    width: int
    height: int
    frame_media_id: int | None
    frame_has_window: bool
    background_color: str | None
    box_x: float
    box_y: float
    box_w: float
    box_h: float
    photo_fit: PhotoFit
    text_enabled: bool
    text_x: float
    text_y: float
    text_w: float
    text_h: float
    text_size: int
    text_color: str
    text_bg_color: str | None
    text_align: TextAlign
    text_bold: bool
    text_max_lines: int
    text_default: str | None
    logo_enabled: bool
    logo_position: LogoPosition
    logo_size: float
    preview_media_id: int | None
    preview_url: str
    usage_count: int
    created_at: datetime
    updated_at: datetime


class TemplateSetIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sequence: int | None = None
    active: bool | None = None
    category: Category | None = None
    brand_kit_id: int | None = None


class TemplateSetCreate(TemplateSetIn):
    name: str = Field(min_length=1, max_length=120)


class TemplateSetOut(BaseModel):
    id: int
    name: str
    sequence: int
    active: bool
    category: str
    brand_kit_id: int | None
    post_template_id: int | None
    story_template_id: int | None
    templates: list[TemplateOut]
    usage_count: int


class Detection(BaseModel):
    box_x: float
    box_y: float
    box_w: float
    box_h: float
    frame_has_window: bool
    format: TemplateFormat
    width: int
    height: int


class FrameUploadOut(BaseModel):
    media: MediaOut
    detection: Detection


class RenderPreviewIn(TemplateFields):
    """Unsaved template values (an editor's live preview). ``template_id`` = start from a saved template."""

    template_id: int | None = None
    text: str | None = Field(default=None, max_length=300)
    media_id: int | None = None  # a real photo instead of the sample


class BrandKitBrief(BaseModel):
    id: int
    name: str
    color_primary: str
    logo_media_id: int | None
    is_default: bool


class TemplateBrief(BaseModel):
    id: int
    name: str
    format: TemplateFormat
    aspect: str
    role: Literal["post", "story"]
    text_enabled: bool
    text_default: str
    preview_url: str
    preview_media_id: int | None


class TemplateChoice(BaseModel):
    """A template set (``key`` = "set:ID") or a template without a set ("template:ID")."""

    key: str
    name: str
    category: str
    templates: list[TemplateBrief]
    usage: int


class QuickAccount(BaseModel):
    id: int
    name: str
    platform: str
    username: str | None
    avatar_url: str | None
    state: str
    can_story: bool


class BestSlot(BaseModel):
    at: datetime
    label: str


class QuickData(BaseModel):
    choices: list[TemplateChoice]
    accounts: list[QuickAccount]
    recent: list[MediaOut]
    story_platforms: list[str]
    best_slots: list[BestSlot]
    has_ai: bool
    ffmpeg: bool
    can_manage: bool


class QuickPreviewIn(BaseModel):
    choice: str = Field(description='"set:ID" or "template:ID"')
    media_ids: list[int] = Field(min_length=1, max_length=20)
    text: str | None = Field(default=None, max_length=300)


class QuickPreviewItem(BaseModel):
    role: Literal["post", "story"]
    template_id: int
    aspect: str
    src: str = Field(description="data:image/jpeg;base64,… (max 540 px)")


class QuickPreviewOut(BaseModel):
    media_id: int
    video: bool
    error: str | None
    items: list[QuickPreviewItem]


class QuickPublishIn(BaseModel):
    choice: str = Field(description='"set:ID" or "template:ID"')
    media_ids: list[int] = Field(min_length=1, max_length=20)
    text: str | None = Field(default=None, max_length=300, description="Text drawn on the image")
    content: str = Field(default="", max_length=5000, description="Caption")
    account_ids: list[int] = []
    publish_as: PublishAs = "feed"
    grouping: Literal["single", "carousel"] = "single"
    mode: Literal["draft", "now", "best_time", "schedule"] = "draft"
    scheduled_at: datetime | None = None


class PostResultLine(BaseModel):
    account_id: int
    account: str
    platform: str
    state: str
    url: str
    error: str
    story_state: str
    story_error: str


class PostResult(BaseModel):
    id: int
    name: str
    state: str
    scheduled_at: datetime | None
    results: list[PostResultLine]


class QuickPublishOut(BaseModel):
    mode: str
    posts: list[PostResult]


class TelegramSettings(BaseModel):
    """Publishing from the Telegram bot: send a photo with ``/post offers Caption…``."""

    publishers: list[str] = Field(default=[], description="Telegram user ids or @usernames allowed to publish")
    mode: Literal["draft", "publish", "best_time"] = "draft"
    publish_as: PublishAs = "feed"
    default_set_id: int | None = None
    account_ids: list[int] = []
    ai_caption: bool = False
