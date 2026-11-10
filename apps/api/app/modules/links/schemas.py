"""Schemas of the links & conversions API."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

ConversionKind = Literal["order", "lead", "signup", "other"]


class LinkOut(BaseModel):
    id: int
    code: str
    short_url: str
    url: str
    destination: str
    kind: str
    label: str | None = None
    post_id: int | None = None
    post_name: str | None = None
    platform: str | None = None
    campaign_id: int | None = None
    campaign_name: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    clicks: int
    conversions: int = 0
    revenue: float = 0.0
    last_click_at: datetime | None = None
    created_at: datetime


class LinkIn(BaseModel):
    url: HttpUrl
    label: str | None = Field(default=None, max_length=160)
    campaign_id: int | None = None
    utm_source: str | None = Field(default=None, max_length=60, description="Network or place (e.g. instagram, bio)")
    utm_campaign: str | None = Field(default=None, max_length=200)


class LinkUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=160)


class ResultRow(BaseModel):
    key: str
    label: str
    color: str | None = None
    clicks: int = 0
    conversions: int = 0
    orders: int = 0
    leads: int = 0
    revenue: float = 0.0


class TopPost(BaseModel):
    id: int
    name: str
    platforms: list[str]
    clicks: int
    conversions: int
    revenue: float
    thumb_url: str | None = None
    published_at: datetime | None = None


class DayPoint(BaseModel):
    date: str
    clicks: int
    conversions: int
    revenue: float


class Totals(BaseModel):
    clicks: int = 0
    conversions: int = 0
    orders: int = 0
    leads: int = 0
    revenue: float = 0.0
    conversion_rate: float = 0.0


class SummaryOut(BaseModel):
    days: int
    currency: str
    enabled: bool
    totals: Totals
    previous: Totals
    by_platform: list[ResultRow]
    by_campaign: list[ResultRow]
    top_posts: list[TopPost]
    daily: list[DayPoint]


class ConversionIn(BaseModel):
    kind: ConversionKind = "order"
    value: float = Field(default=0.0, ge=0, le=100_000_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    external_id: str | None = Field(default=None, max_length=120, description="Order / lead number (deduplication)")
    code: str | None = Field(default=None, max_length=16, description="Short-link code (sref) of the click")
    utm_source: str | None = Field(default=None, max_length=120)
    utm_medium: str | None = Field(default=None, max_length=120)
    utm_campaign: str | None = Field(default=None, max_length=200)
    post_id: int | None = None
    product_id: int | None = None
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=300)


class ConversionOut(BaseModel):
    id: int
    kind: str
    value: float
    currency: str | None = None
    external_id: str | None = None
    occurred_at: datetime
    source: str
    post_id: int | None = None
    post_name: str | None = None
    platform: str | None = None
    campaign_id: int | None = None
    campaign_name: str | None = None
    product_id: int | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    note: str | None = None


class LinkSettings(BaseModel):
    enabled: bool = True
    retag: bool = False
    add_ref: bool = True
    base_url: str | None = None


class LinkSettingsOut(LinkSettings):
    default_base_url: str
    public_key: str
    has_secret: bool
    snippet: str
    pixel_url: str
    server_url: str


class SecretOut(BaseModel):
    secret: str


class PostLinksOut(BaseModel):
    post_id: int
    links: list[LinkOut]
    clicks: int
    conversions: int
    revenue: float
    currency: str


class PeriodQuery(BaseModel):
    start: date | None = None
    end: date | None = None
