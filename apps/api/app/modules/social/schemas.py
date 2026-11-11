"""Request / response schemas of accounts, posts, approvals and performance (the mobile app uses the same)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.files.router import MediaOut

Platform = Literal["facebook", "instagram", "linkedin", "x", "tiktok", "threads", "telegram", "youtube", "pinterest",
                   "google_business"]
OAuthPlatform = Literal["facebook", "instagram", "linkedin", "x", "tiktok", "threads", "youtube", "pinterest",
                        "google_business"]
PublishAs = Literal["feed", "story", "feed_story"]
SubmitAction = Literal["draft", "publish", "schedule", "best_time"]


# ------------------------------------------------------------------ accounts
class AccountOut(BaseModel):
    id: int
    name: str
    platform: str
    platform_label: str
    username: str | None = None
    external_id: str | None = None
    avatar_url: str | None = None
    state: str
    last_error: str | None = None
    last_check_at: datetime | None = None
    followers: int = 0
    followers_updated_at: datetime | None = None
    token_expires_at: datetime | None = None
    has_token: bool = False
    can_refresh: bool = False
    active: bool = True
    inbox_only: bool = False
    can_publish: bool = False
    connected_with: Literal["oauth", "token"] = "token"
    oauth_app: Literal["workspace", "platform"] | None = None
    privacy_level: str | None = None
    board_id: str | None = None           # Pinterest: where pins go
    boards: list[dict] | None = None      # Pinterest: [{"id", "name"}] to choose from
    created_at: datetime


class AccountCreate(BaseModel):
    """Manual connection with an access token (Telegram bot token, Page token, …)."""

    platform: Platform
    access_token: str = Field(min_length=3, max_length=4000)
    external_id: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=160)
    username: str | None = Field(default=None, max_length=160)
    privacy_level: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    username: str | None = Field(default=None, max_length=160)
    external_id: str | None = Field(default=None, max_length=200)
    access_token: str | None = Field(default=None, max_length=4000)
    privacy_level: str | None = None
    board_id: str | None = Field(default=None, max_length=64)
    active: bool | None = None


class ConnectionResult(BaseModel):
    ok: bool
    account: AccountOut
    message: str | None = None


class SyncResult(BaseModel):
    posts: int = 0
    accounts: int = 0


class PlatformOption(BaseModel):
    key: str
    label: str
    method: Literal["oauth", "token"]
    oauth_platform: str | None = None
    configured: bool = False
    source: Literal["workspace", "platform"] | None = None
    help: str = ""


class OAuthStartIn(BaseModel):
    platform: OAuthPlatform


class OAuthStartOut(BaseModel):
    url: str


class OAuthSetupOut(BaseModel):
    platform: str
    requested: str
    brand: str
    portal_url: str
    id_label: str
    secret_label: str
    steps: list[str]
    note: str | None = None
    redirect_uri: str
    configured: bool
    source: Literal["workspace", "platform"] | None = None
    own_app: bool = False
    client_id: str = ""


class OAuthAppIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str = Field(min_length=1, max_length=500)
    connect: bool = True


# ------------------------------------------------------------------ posts
class PostIn(BaseModel):
    """Composer fields. On PATCH only the fields sent are changed."""

    content: str | None = Field(default=None, max_length=70000)
    name: str | None = Field(default=None, max_length=200)
    variants: dict[str, str] | None = None
    account_ids: list[int] | None = None
    media_ids: list[int] | None = None
    story_media_ids: list[int] | None = None
    platform_media: dict[str, list[int]] | None = None
    publish_as: PublishAs | None = None
    campaign_id: int | None = None
    pillar_id: int | None = None
    planned_date: datetime | None = None
    scheduled_at: datetime | None = None
    ai_brief: str | None = None


class ComposeIn(PostIn):
    """Save the composer (new post when ``post_id`` is empty) and run ``action`` in one call."""

    post_id: int | None = None
    action: SubmitAction = "draft"
    when: datetime | None = None


class SubmitIn(BaseModel):
    action: SubmitAction
    when: datetime | None = None


class ChangesIn(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class Problem(BaseModel):
    platform: str | None = None
    account_id: int | None = None
    message: str


class ValidationOut(BaseModel):
    ok: bool
    problems: list[Problem]


class TargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    account_name: str = ""
    account_avatar: str | None = None
    platform: str
    state: str
    external_id: str | None = None
    external_url: str | None = None
    error: str | None = None
    published_at: datetime | None = None
    media_type: str | None = None
    story_state: str | None = None
    story_url: str | None = None
    story_error: str | None = None
    impressions: int = 0
    reach: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    clicks: int = 0
    video_views: int = 0
    engagements: int = 0
    engagement_rate: float = 0.0
    metrics_updated_at: datetime | None = None


class PostAccount(BaseModel):
    id: int
    name: str
    platform: str
    avatar_url: str | None = None
    username: str | None = None


class PostOut(BaseModel):
    id: int
    name: str | None = None
    content: str = ""
    variants: dict[str, str] = {}
    state: str
    publish_as: str
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    planned_date: datetime | None = None
    created_at: datetime
    updated_at: datetime
    author_id: int | None = None
    author_name: str | None = None
    accounts: list[PostAccount] = []
    account_ids: list[int] = []
    platforms: list[str] = []
    media: list[MediaOut] = []
    story_media: list[MediaOut] = []
    platform_media: dict[str, list[int]] = {}
    campaign_id: int | None = None
    pillar_id: int | None = None
    ai_brief: str | None = None
    source_ref: str | None = None
    requested_action: str | None = None
    approval_requested_by_id: int | None = None
    approval_requested_by_name: str | None = None
    approval_requested_at: datetime | None = None
    approved_by_id: int | None = None
    approved_at: datetime | None = None
    approval_note: str | None = None
    targets: list[TargetOut] = []
    can_edit: bool = False
    can_retry: bool = False
    totals: dict[str, float] = {}


class PostPage(BaseModel):
    items: list[PostOut]
    total: int


class BestSlot(BaseModel):
    at: datetime
    local: str
    label: str
    score: float = 0


class StudioKpis(BaseModel):
    published: int
    scheduled: int
    failed: int
    to_approve: int
    accounts: int


class StudioOut(BaseModel):
    accounts: list[AccountOut]
    rules: dict[str, dict]
    story_platforms: list[str]
    needs_approval: bool
    is_approver: bool
    approvals_enabled: bool
    kpis: StudioKpis
    recent_posts: list[PostOut]
    timezone: str
    can_connect: bool


class ApprovalSettings(BaseModel):
    required: bool


# ------------------------------------------------------------------ performance
class AIReportIn(BaseModel):
    days: int = Field(default=30, ge=1, le=365)
    platform: Platform | None = None


class AIReportOut(BaseModel):
    text: str
    generated_at: datetime


class Tip(BaseModel):
    level: Literal["danger", "warning", "success", "info"]
    icon: str
    title: str
    text: str
    action: str | None = None


class DashboardOut(BaseModel):
    """Performance data (ported from the Odoo dashboard). ``extra`` carries blocks added by other features."""

    period: dict
    platform: str | None = None
    timezone: str
    has_metrics: bool
    kpis: dict[str, float]
    deltas: dict[str, float | None]
    breakdown: list[dict]
    series: list[dict]
    followers_series: list[dict]
    heatmap: list[list[dict]]
    best_slots: list[dict]
    best_source: Literal["own", "benchmark"]
    content: dict[str, list[dict]]
    top_posts: list[dict]
    accounts: list[dict]
    tips: list[Tip]
    last_sync: datetime | None = None
    extra: dict = {}
