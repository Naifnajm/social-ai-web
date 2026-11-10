"""Request / response schemas of the AI feature (they define the OpenAPI used by the web and mobile apps)."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Capability = Literal["text", "image", "video", "audio", "stt"]
MediaKind = Literal["image", "video", "audio"]
AudioMode = Literal["speech", "sfx", "music"]
Aspect = Literal["1:1", "4:5", "9:16", "16:9"]
Unit = Literal["tokens", "image", "second", "1k_chars", "minute", "free"]


# ------------------------------------------------------------------ catalog
class CatalogModel(BaseModel):
    name: str
    label: str
    capability: Capability
    unit: Unit
    price_in: float = 0
    price_out: float = 0
    price: float = 0
    price_label: str = ""


class CatalogEntry(BaseModel):
    type: str
    label: str
    capabilities: list[Capability]
    engine: str | None = None
    base_url: str = ""
    needs_base_url: bool = False
    no_key: bool = False
    key_url: str | None = None
    default_models: dict[str, str] = {}
    voice: str | None = None
    max_tokens: int = 4000
    balance_supported: bool = False
    models: list[CatalogModel] = []


# ------------------------------------------------------------------ providers
class Wallet(BaseModel):
    kind: Literal["balance", "budget", "spent"]
    amount: float
    unit: str = "USD"
    spent: float = 0
    budget: float | None = None


class ProviderOut(BaseModel):
    id: int
    name: str
    provider_type: str
    type_label: str
    capabilities: list[Capability]
    has_key: bool
    base_url: str | None = None
    text_model: str | None = None
    image_model: str | None = None
    video_model: str | None = None
    audio_model: str | None = None
    voice: str | None = None
    max_tokens: int
    is_default: bool
    active: bool
    state: str
    last_error: str | None = None
    tested_at: datetime | None = None
    available_models: list[str] = []
    key_url: str | None = None
    balance_supported: bool
    balance: float | None = None
    balance_unit: str | None = None
    balance_checked_at: datetime | None = None
    monthly_budget: float | None = None
    spent_month: float = 0
    spent_total: float = 0
    wallet: Wallet
    models_count: int = 0
    sequence: int = 10


class ProviderCreate(BaseModel):
    provider_type: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, max_length=900)
    base_url: str | None = Field(default=None, max_length=500)
    text_model: str | None = Field(default=None, max_length=120)
    image_model: str | None = Field(default=None, max_length=120)
    video_model: str | None = Field(default=None, max_length=120)
    audio_model: str | None = Field(default=None, max_length=120)
    voice: str | None = Field(default=None, max_length=120)
    max_tokens: int | None = Field(default=None, ge=64, le=200000)
    monthly_budget: float | None = Field(default=None, ge=0)
    is_default: bool = False


class ProviderUpdate(BaseModel):
    """Only the fields sent are changed. ``api_key``: a new key replaces the old one, ``""`` removes it."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    api_key: str | None = Field(default=None, max_length=900)
    base_url: str | None = Field(default=None, max_length=500)
    text_model: str | None = Field(default=None, max_length=120)
    image_model: str | None = Field(default=None, max_length=120)
    video_model: str | None = Field(default=None, max_length=120)
    audio_model: str | None = Field(default=None, max_length=120)
    voice: str | None = Field(default=None, max_length=120)
    max_tokens: int | None = Field(default=None, ge=64, le=200000)
    monthly_budget: float | None = Field(default=None, ge=0)
    is_default: bool | None = None
    active: bool | None = None
    sequence: int | None = None


class TestResult(BaseModel):
    ok: bool
    message: str
    models: list[str] = []
    warning: str | None = None
    provider: ProviderOut


class BalanceOut(BaseModel):
    ok: bool
    message: str
    provider: ProviderOut


# ------------------------------------------------------------------ models (price list)
class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    name: str
    label: str
    capability: Capability
    unit: Unit
    price_in: float
    price_out: float
    price: float
    price_label: str = ""
    active: bool
    sequence: int


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=160)
    capability: Capability = "text"
    unit: Unit = "tokens"
    price_in: float = Field(default=0, ge=0)
    price_out: float = Field(default=0, ge=0)
    price: float = Field(default=0, ge=0)
    active: bool = True
    sequence: int = 50


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=160)
    capability: Capability | None = None
    unit: Unit | None = None
    price_in: float | None = Field(default=None, ge=0)
    price_out: float | None = Field(default=None, ge=0)
    price: float | None = Field(default=None, ge=0)
    active: bool | None = None
    sequence: int | None = None


# ------------------------------------------------------------------ pickers / estimates
class PickerModel(BaseModel):
    id: int
    name: str
    label: str
    unit: Unit
    price: float
    price_in: float
    price_out: float
    price_label: str
    default: bool


class PickerGroup(BaseModel):
    provider_id: int
    provider: str
    provider_type: str
    is_default: bool
    has_key: bool
    state: str
    models: list[PickerModel]
    wallet: Wallet


class PickerOut(BaseModel):
    capability: Capability
    groups: list[PickerGroup]


class EstimateIn(BaseModel):
    capability: Capability = "text"
    prompt: str = ""
    seconds: float = Field(default=0, ge=0, le=7200)
    audio_mode: AudioMode = "speech"
    model_id: int | None = None
    provider_id: int | None = None


class EstimateOut(BaseModel):
    cost: float
    detail: str = ""
    model: str = ""
    model_id: int | None = None
    provider: str = ""
    provider_id: int | None = None
    wallet: Wallet | None = None
    known: bool = False


class StatusOut(BaseModel):
    """Which AI capabilities the workspace can use right now (to show or hide AI buttons)."""

    text: bool
    image: bool
    video: bool
    audio: bool
    stt: bool
    default_provider: str | None = None


# ------------------------------------------------------------------ text
class WriteIn(BaseModel):
    """Composer "Write with AI". ``preset`` = post (default: full post-writing prompt) | reply | ideas | hashtags |
    rewrite | free. ``system`` (optional) replaces the preset's system prompt for free use."""

    brief: str = Field(default="", max_length=8000)
    preset: Literal["post", "reply", "ideas", "hashtags", "rewrite", "free"] = "post"
    system: str | None = Field(default=None, max_length=8000)
    tone: str | None = Field(default="professional", max_length=40)
    language: str | None = Field(default="auto", max_length=10)
    length: Literal["short", "medium", "long"] = "medium"
    hashtags: bool = True
    emojis: bool = True
    platforms: list[str] = []
    account_ids: list[int] = []
    tailor: bool = False
    current_text: str = Field(default="", max_length=20000)
    brand_kit_id: int | None = None
    model_id: int | None = None
    provider_id: int | None = None


class WriteOut(BaseModel):
    text: str
    variants: dict[str, str] = {}
    provider: str
    model: str
    cost: float
    tokens_in: int = 0
    tokens_out: int = 0


class SuggestVisualIn(BaseModel):
    kind: Literal["image", "video"] = "image"
    text: str = Field(min_length=1, max_length=8000)
    brand_kit_id: int | None = None
    model_id: int | None = None


class SuggestVisualOut(BaseModel):
    prompt: str
    cost: float = 0


# ------------------------------------------------------------------ media jobs
class MediaJobIn(BaseModel):
    kind: MediaKind = "image"
    prompt: str = Field(min_length=1, max_length=8000)
    model_id: int | None = None
    provider_id: int | None = None
    aspect: Aspect = "1:1"
    style: Literal["photo", "illustration", "3d", "minimal", "cinematic", "product"] | None = None
    seconds: int = Field(default=8, ge=1, le=300)
    audio_mode: AudioMode = "speech"
    voice: str | None = Field(default=None, max_length=120)
    input_media_ids: list[int] = []
    brand_kit_id: int | None = None


class JobMedia(BaseModel):
    id: int
    filename: str
    mimetype: str
    url: str
    width: int | None = None
    height: int | None = None
    duration: float | None = None


class MediaJobOut(BaseModel):
    id: int
    kind: MediaKind
    state: Literal["running", "done", "failed"]
    progress: int
    prompt: str
    title: str
    aspect: str
    style: str | None = None
    seconds: int
    audio_mode: str
    voice: str | None = None
    provider_id: int | None = None
    provider: str | None = None
    model_name: str | None = None
    input_media_ids: list[int] = []
    media_id: int | None = None
    media: JobMedia | None = None
    error: str | None = None
    notice: str | None = None
    cost: float
    created_at: datetime
    updated_at: datetime


class JobCheckIn(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=100)


class TranscribeIn(BaseModel):
    media_id: int
    language: str | None = Field(default=None, max_length=10)
    provider_id: int | None = None
    model_id: int | None = None


class Segment(BaseModel):
    start: float
    end: float
    text: str


class TranscribeOut(BaseModel):
    segments: list[Segment]
    duration: float
    cost: float
    text: str = ""
    model: str = ""
    provider: str = ""


# ------------------------------------------------------------------ usage & costs
class UsageOut(BaseModel):
    id: int
    created_at: datetime
    provider_id: int | None = None
    provider: str | None = None
    model_name: str | None = None
    capability: str
    tokens_in: int
    tokens_out: int
    units: float
    cost: float
    purpose: str | None = None
    user_id: int | None = None
    user_name: str | None = None


class UsagePage(BaseModel):
    items: list[UsageOut]
    total: int


class CostRow(BaseModel):
    key: str
    label: str
    cost: float
    calls: int


class DayRow(BaseModel):
    day: date
    cost: float
    calls: int


class ProviderBudget(BaseModel):
    provider_id: int
    provider: str
    spent_month: float
    monthly_budget: float | None = None
    wallet: Wallet


class UsageSummary(BaseModel):
    date_from: date
    date_to: date
    total_cost: float
    total_calls: int
    month_cost: float
    by_provider: list[CostRow]
    by_model: list[CostRow]
    by_capability: list[CostRow]
    by_day: list[DayRow]
    by_month: list[CostRow]
    budgets: list[ProviderBudget]
