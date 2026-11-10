"""Request / response schemas of the planning API (campaigns, pillars, planner, evergreen)."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

HEX = r"^#[0-9a-fA-F]{6}$"
CampaignState = Literal["planned", "running", "finished"]


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    tagline: str | None = Field(default=None, max_length=200)
    goal: str | None = None
    date_start: date | None = None
    date_end: date | None = None
    color: str | None = Field(default=None, pattern=HEX)
    state: CampaignState | None = None
    budget: float | None = Field(default=None, ge=0)
    owner_id: int | None = None
    auto_state: bool = True
    target_posts: int | None = Field(default=None, ge=0, le=10000)


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    tagline: str | None = Field(default=None, max_length=200)
    goal: str | None = None
    date_start: date | None = None
    date_end: date | None = None
    color: str | None = Field(default=None, pattern=HEX)
    state: CampaignState | None = None
    budget: float | None = Field(default=None, ge=0)
    owner_id: int | None = None
    auto_state: bool | None = None
    archived: bool | None = None
    target_posts: int | None = Field(default=None, ge=0, le=10000)


class CampaignStats(BaseModel):
    post_count: int = 0
    published_count: int = 0
    scheduled_count: int = 0
    draft_count: int = 0
    impressions: int = 0
    reach: int = 0
    engagements: int = 0
    engagement_rate: float = 0.0
    video_views: int = 0
    progress: float = 0.0
    clicks: int = 0
    conversions: int = 0
    revenue: float = 0.0


class CampaignOut(BaseModel):
    id: int
    name: str
    tagline: str | None = None
    goal: str | None = None
    date_start: date | None = None
    date_end: date | None = None
    color: str
    state: CampaignState
    budget: float | None = None
    owner_id: int | None = None
    owner_name: str | None = None
    auto_state: bool = True
    archived: bool = False
    target_posts: int | None = None
    days_left: int | None = None
    stats: CampaignStats


class NetworkRow(BaseModel):
    platform: str
    posts: int
    impressions: int
    engagements: int
    engagement_rate: float
    clicks: int = 0
    revenue: float = 0.0


class Ref(BaseModel):
    id: int
    name: str
    color: str


class MediaRef(BaseModel):
    id: int
    kind: str
    url: str


class PlannerPost(BaseModel):
    id: int
    name: str
    preview: str
    state: str
    day: str | None = None
    time: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    platforms: list[str]
    account_ids: list[int]
    media: MediaRef | None = None
    media_count: int = 0
    campaign: Ref | None = None
    pillar: Ref | None = None
    author: str = ""
    evergreen: bool = False
    recycled: bool = False
    movable: bool = False


class CampaignDetail(CampaignOut):
    networks: list[NetworkRow]
    posts: list[PlannerPost]
    currency: str


class PillarIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str | None = Field(default=None, pattern=HEX)
    description: str | None = None
    target_share: int = Field(default=25, ge=0, le=100)
    active: bool = True


class PillarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, pattern=HEX)
    description: str | None = None
    target_share: int | None = Field(default=None, ge=0, le=100)
    active: bool | None = None


class PillarOut(BaseModel):
    id: int
    name: str
    color: str
    description: str | None = None
    target_share: int
    position: int
    active: bool
    published_30: int = Field(description="Posts published in the last 30 days")
    share_30: float = Field(description="% of the posts published in the last 30 days")
    planned_30: int = Field(description="Posts planned for the next 30 days")
    planned_share_30: float
    gap: float = Field(description="Published share minus target (negative: post more of this pillar)")


class PillarOrder(BaseModel):
    ids: list[int]


class BestHint(BaseModel):
    weekday: int = Field(description="0 = Monday")
    time: str | None = None
    top: bool = False
    source: str = "benchmark"


class BestSlot(BaseModel):
    at: datetime
    local: str
    weekday: int
    time: str
    source: str


class AccountRef(BaseModel):
    id: int
    name: str
    platform: str
    avatar_url: str | None = None


class CampaignRef(BaseModel):
    id: int
    name: str
    color: str
    state: str
    date_start: date | None = None
    date_end: date | None = None


class PlannerOut(BaseModel):
    start: date
    end: date
    today: date
    timezone: str
    posts: list[PlannerPost]
    unplanned: list[PlannerPost]
    best: list[BestHint]
    best_slots: list[BestSlot]
    accounts: list[AccountRef]
    campaigns: list[CampaignRef]
    pillars: list[PillarOut]


class MoveIn(BaseModel):
    day: date
    time: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")


class ScheduleIn(BaseModel):
    day: date
    time: str = Field(pattern=r"^\d{1,2}:\d{2}$")


class PostPlanUpdate(BaseModel):
    campaign_id: int | None = None
    pillar_id: int | None = None
    clear_campaign: bool = False
    clear_pillar: bool = False


class BestTimesOut(BaseModel):
    by_weekday: list[BestHint]
    slots: list[BestSlot]


class EvergreenIn(BaseModel):
    evergreen: bool
    interval_days: int = Field(default=30, ge=1, le=365)
    until: date | None = None
    rewrite: bool = False


class EvergreenOut(BaseModel):
    post: PlannerPost
    evergreen: bool
    interval_days: int
    until: date | None = None
    rewrite: bool
    recycle_count: int
    last_recycled_at: datetime | None = None
    next_recycle_at: datetime | None = None
    waiting_copy: bool = False


class RecycleOut(BaseModel):
    post_id: int
    copy_id: int
    state: str
