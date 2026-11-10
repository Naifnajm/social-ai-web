"""Request / response schemas of the inbox API (also the contract of the mobile app)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

State = Literal["open", "pending", "done"]
Kind = Literal["dm", "comment"]
Channel = Literal["dm", "public", "private"]
Intent = Literal["question", "order", "complaint", "lead", "praise", "spam", "other"]
Sentiment = Literal["positive", "neutral", "negative"]
BotMode = Literal["off", "suggest", "auto"]
Folder = Literal["all", "unassigned", "mine", "pending", "done"]


class UserRef(BaseModel):
    id: int
    name: str
    avatar_url: str | None = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: int = 0


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: int = Field(default=0, ge=0, le=11)


class ConversationRow(BaseModel):
    id: int
    account_id: int
    account_name: str
    platform: str
    kind: Kind
    name: str
    handle: str | None = None
    avatar_url: str | None = None
    snippet: str | None = None
    last_message_at: datetime | None = None
    unread: bool
    state: State
    intent: Intent | None = None
    sentiment: Sentiment | None = None
    assignee: UserRef | None = None
    tags: list[TagOut] = []
    has_suggestion: bool = False
    bot_paused: bool = False
    is_hidden: bool = False


class FolderCounts(BaseModel):
    all: int = 0
    unassigned: int = 0
    mine: int = 0
    pending: int = 0
    unread: int = 0


class ConversationPage(BaseModel):
    items: list[ConversationRow]
    next_cursor: str | None = None
    counts: FolderCounts


class AttachmentOut(BaseModel):
    id: int
    filename: str
    mimetype: str
    url: str


class MessageOut(BaseModel):
    id: int
    direction: Literal["in", "out"]
    channel: Channel
    author: str | None = None
    body: str
    sent_at: datetime
    is_bot: bool
    user: UserRef | None = None
    state: Literal["received", "suggested", "sent", "failed"]
    error: str | None = None
    confidence: int = 0
    note: str | None = None
    hidden: bool = False
    trigger: str | None = None
    attachments: list[AttachmentOut] = []


class WindowOut(BaseModel):
    """Meta / WhatsApp 24-hour reply window of a DM."""

    limited: bool
    open: bool
    hours_left: float
    human_agent: bool


class PostRef(BaseModel):
    url: str | None = None
    preview: str | None = None
    post_id: int | None = None


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    handle: str | None = None
    phone: str | None = None
    email: str | None = None
    note: str | None = None
    conversations: int = 0


class ContactUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    note: str | None = None


class ThreadOut(ConversationRow):
    external_user_id: str | None = None
    messages: list[MessageOut]
    suggestion: MessageOut | None = None
    contact: ContactOut | None = None
    post: PostRef | None = None
    note: str | None = None
    handover_reason: str | None = None
    bot_error: str | None = None
    window: WindowOut
    bot_mode: BotMode
    can_private: bool
    can_hide: bool
    can_like: bool
    first_inbound_at: datetime | None = None


class SendIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    channel: Channel = "dm"


class SendOut(BaseModel):
    message: MessageOut
    thread: ThreadOut


class SuggestionSendIn(BaseModel):
    body: str | None = Field(default=None, max_length=5000)  # edited text; None = as suggested


class HideIn(BaseModel):
    hide: bool = True


class ConversationUpdate(BaseModel):
    """Only the fields sent are changed (``assignee_id: null`` un-assigns)."""

    state: State | None = None
    assignee_id: int | None = None
    tag_ids: list[int] | None = None
    bot_paused: bool | None = None
    note: str | None = Field(default=None, max_length=5000)
    intent: Intent | None = None
    sentiment: Sentiment | None = None
    unread: bool | None = None


class UnreadOut(BaseModel):
    unread: int
    pending: int


class SyncOut(BaseModel):
    new: int
    errors: list[str]


# ------------------------------------------------------------------ canned replies / knowledge / triggers
class CannedIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)
    shortcut: str | None = Field(default=None, max_length=40, pattern=r"^/?[\w\-]*$")
    sequence: int = 10
    active: bool = True


class CannedOut(CannedIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class KnowledgeIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=20000)
    sequence: int = 10
    active: bool = True


class KnowledgeOut(KnowledgeIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class TriggerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    keywords: str = Field(min_length=1, max_length=500)
    public_reply: str | None = Field(default=None, max_length=2000)
    dm_text: str | None = Field(default=None, max_length=2000)
    account_ids: list[int] = []
    post_id: int | None = None
    active: bool = True
    sequence: int = 10


class TriggerOut(TriggerIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hit_count: int = 0


# ------------------------------------------------------------------ accounts & settings
class BotSettings(BaseModel):
    mode: BotMode = "suggest"
    comment_mode: BotMode = "suggest"
    hide_offensive: bool = False
    private_reply: bool = True
    confidence: int = Field(default=75, ge=0, le=100)
    when: Literal["always", "office_hours", "outside_hours"] = "always"
    hour_from: float = Field(default=9.0, ge=0, le=24)
    hour_to: float = Field(default=17.0, ge=0, le=24)
    brand_kit_id: int | None = None
    instructions: str = Field(default="", max_length=4000)


class BotSettingsPatch(BaseModel):
    mode: BotMode | None = None
    comment_mode: BotMode | None = None
    hide_offensive: bool | None = None
    private_reply: bool | None = None
    confidence: int | None = Field(default=None, ge=0, le=100)
    when: Literal["always", "office_hours", "outside_hours"] | None = None
    hour_from: float | None = Field(default=None, ge=0, le=24)
    hour_to: float | None = Field(default=None, ge=0, le=24)
    brand_kit_id: int | None = None
    instructions: str | None = Field(default=None, max_length=4000)


class InboxAccountOut(BaseModel):
    id: int
    name: str
    platform: str
    username: str | None = None
    avatar_url: str | None = None
    state: str
    inbox_enabled: bool
    bot: BotSettings
    webhook_kind: Literal["meta", "telegram", "twilio"] | None = None
    webhook_url: str | None = None  # admins only
    telegram_webhook_active: bool = False
    last_sync_at: datetime | None = None
    sync_error: str | None = None
    whatsapp_provider: Literal["cloud", "twilio"] | None = None
    whatsapp_number: str | None = None
    has_token: bool = False
    open_conversations: int = 0


class InboxAccountUpdate(BaseModel):
    inbox_enabled: bool | None = None
    bot: BotSettingsPatch | None = None


class WhatsAppAccountIn(BaseModel):
    """Cloud API: ``phone_number_id`` + ``access_token``. Twilio: ``twilio_account_sid`` + ``twilio_auth_token``
    + ``whatsapp_number`` (your sender)."""

    name: str = Field(min_length=1, max_length=160)
    provider: Literal["cloud", "twilio"] = "cloud"
    phone_number_id: str | None = Field(default=None, max_length=64)
    access_token: str | None = Field(default=None, max_length=4000)
    whatsapp_number: str | None = Field(default=None, max_length=32)
    twilio_account_sid: str | None = Field(default=None, max_length=64)
    twilio_auth_token: str | None = Field(default=None, max_length=200)
    verify: bool = True


class WhatsAppAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    phone_number_id: str | None = Field(default=None, max_length=64)
    access_token: str | None = Field(default=None, max_length=4000)
    whatsapp_number: str | None = Field(default=None, max_length=32)
    twilio_account_sid: str | None = Field(default=None, max_length=64)
    twilio_auth_token: str | None = Field(default=None, max_length=200)


class AccountCheckOut(BaseModel):
    ok: bool
    state: str
    error: str | None = None


class InboxSettingsOut(BaseModel):
    handover_message: str = ""
    private_ack: str = ""
    human_agent_tag: bool = False
    create_contacts: bool = True
    company_info: str = ""
    meta_webhook_url: str
    platform_meta_app: bool  # the platform's Meta app receives the webhooks
    meta_app_id: str | None = None  # the workspace's own Meta app (optional)
    has_meta_app_secret: bool = False
    meta_verify_token: str | None = None


class InboxSettingsIn(BaseModel):
    handover_message: str | None = Field(default=None, max_length=1000)
    private_ack: str | None = Field(default=None, max_length=500)
    human_agent_tag: bool | None = None
    create_contacts: bool | None = None
    company_info: str | None = Field(default=None, max_length=4000)
    meta_app_id: str | None = Field(default=None, max_length=64)
    meta_app_secret: str | None = Field(default=None, max_length=200)  # write only; "" clears


class InboxMeta(BaseModel):
    """Static data of the inbox screen."""

    accounts: list[InboxAccountOut]
    platforms: list[str]
    members: list[UserRef]
    tags: list[TagOut]
    canned: list[CannedOut]
    has_provider: bool
    user_id: int
    can_reply: bool
    can_manage: bool


class PlatformStat(BaseModel):
    platform: str
    conversations: int
    dm: int
    comment: int
    pending: int


class InboxStats(BaseModel):
    days: int
    conversations: int
    open: int
    pending: int
    done: int
    unread: int
    received: int
    replies: int
    bot_replies: int
    bot_share: float
    avg_first_response_minutes: float
    sentiment: dict[str, int]
    intents: dict[str, int]
    by_platform: list[PlatformStat]
