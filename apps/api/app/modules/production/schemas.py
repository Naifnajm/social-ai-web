"""Request / response schemas of the Production API (the canvas on the web, boards on mobile)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Aspect = Literal["1:1", "4:5", "9:16", "16:9"]


# ---------------------------------------------------------------------------- shared pieces
class MediaRef(BaseModel):
    id: int
    filename: str
    mimetype: str
    kind: str
    url: str
    width: int | None = None
    height: int | None = None


class Estimate(BaseModel):
    cost: float = 0.0
    model: str | None = None


class RunEstimate(BaseModel):
    cost: float = 0.0
    reused: int = 0
    blocks: int = 0


class OutputOut(BaseModel):
    id: int
    run: int
    aspect: str | None = None
    cost: float = 0.0
    text: str | None = None
    model: str | None = None
    created_at: datetime | None = None
    media: MediaRef | None = None
    selected: bool = False


class NodeOut(BaseModel):
    id: int
    board_id: int
    kind: str
    name: str
    x: float
    y: float
    group_id: int | None = None
    prompt: str = ""
    text_value: str = ""
    provider_id: int | None = None
    model_id: int | None = None
    model_label: str | None = None
    aspect: str = "1:1"
    style: str | None = None
    seconds: int = 8
    audio_mode: str = "speech"
    design: dict | None = None
    variations: int = 1
    formats: list[str] = []
    fit_mode: str = "blur"
    caption_position: str = "bottom"
    caption_size: str = "m"
    caption_language: str = ""
    template_ref: str | None = None
    approval_state: str | None = None
    approval_comment: str | None = None
    approver_id: int | None = None
    approver_name: str | None = None
    can_approve: bool = False
    account_ids: list[int] = []
    publish_mode: str = "draft"
    publish_at: datetime | None = None
    state: str = "idle"
    progress: int = 0
    error: str | None = None
    notice: str | None = None
    output_text: str | None = None
    output: MediaRef | None = None
    outputs: list[OutputOut] = []
    run_no: int = 0
    post_id: int | None = None
    post_state: str | None = None
    out_type: str | None = None
    cost: float = 0.0
    estimate: Estimate | None = None
    fresh: bool = False


class EdgeOut(BaseModel):
    id: int
    source: int
    target: int
    port: str
    type: str | None = None


class ConnectOut(EdgeOut):
    replaced: list[int] = []


class GroupOut(BaseModel):
    id: int
    name: str
    color: str
    nodes: list[int] = []


class Variable(BaseModel):
    key: str = Field(max_length=60)
    value: str = Field(default="", max_length=2000)


class LinkedPost(BaseModel):
    id: int
    name: str | None = None
    state: str


class BoardOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    template: str | None = None
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    variables: list[Variable] = []
    used_variables: list[str] = []
    brand_kit_id: int | None = None
    post: LinkedPost | None = None
    cover_url: str | None = None
    updated_at: datetime | None = None


class BoardCard(BaseModel):
    id: int
    name: str
    template: str | None = None
    node_count: int = 0
    output_count: int = 0
    status: Literal["idle", "running", "failed"] = "idle"
    cover_url: str | None = None
    updated_at: datetime | None = None


class TemplateOut(BaseModel):
    key: str
    name: str
    icon: str
    description: str
    blocks: int


class PortOut(BaseModel):
    key: str
    label: str
    accepts: list[str]
    multi: bool


class KindOut(BaseModel):
    key: str
    label: str
    output: str | None = None
    accepts: list[str] = []
    generative: bool = False
    ports: list[PortOut] = []


class Choice(BaseModel):
    id: int
    name: str


class AccountChoice(Choice):
    platform: str
    state: str
    avatar_url: str | None = None


class TemplateChoice(BaseModel):
    value: str  # "template:<id>" | "set:<id>"
    label: str


class PickerModel(BaseModel):
    id: int
    name: str
    label: str
    price: str | None = None
    default: bool = False


class PickerGroup(BaseModel):
    provider_id: int
    provider: str
    models: list[PickerModel] = []


class BrandDesign(BaseModel):
    """What the design editor needs: brand name, logo and colours."""

    id: int | None = None
    name: str
    logo_url: str | None = None
    color: str = "#111111"
    color2: str = "#71717a"
    text_color: str = "#ffffff"
    font: str = "system-ui"


class GraphOut(BaseModel):
    board: BoardOut
    nodes: list[NodeOut]
    edges: list[EdgeOut]
    groups: list[GroupOut]
    kinds: list[KindOut] = []
    brand_kits: list[Choice] = []
    accounts: list[AccountChoice] = []
    members: list[Choice] = []
    brand_templates: list[TemplateChoice] = []
    pickers: dict[str, list[PickerGroup]] = {}
    brand: BrandDesign | None = None
    styles: list[str] = []
    aspects: list[str] = []
    audio_modes: list[str] = []
    publish_modes: list[str] = []
    ffmpeg: bool = False
    subtitles: bool = False
    busy: bool = False
    run_all: RunEstimate = RunEstimate()


# ---------------------------------------------------------------------------- requests
class BoardCreate(BaseModel):
    template: str = "blank"
    name: str | None = Field(default=None, max_length=200)


class BoardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    zoom: float | None = Field(default=None, ge=0.05, le=4)
    pan_x: float | None = None
    pan_y: float | None = None
    brand_kit_id: int | None = None  # 0 clears it


class FromPostIn(BaseModel):
    post_id: int


class FromMediaIn(BaseModel):
    media_id: int
    text: str | None = None


class NodeParams(BaseModel):
    """Editable parameters of a block (only the given ones are changed)."""

    name: str | None = Field(default=None, max_length=160)
    x: float | None = None
    y: float | None = None
    prompt: str | None = None
    text_value: str | None = None
    provider_id: int | None = None
    model_id: int | None = None
    aspect: Aspect | None = None
    style: str | None = None
    seconds: int | None = Field(default=None, ge=1, le=120)
    audio_mode: Literal["speech", "sfx", "music"] | None = None
    variations: int | None = Field(default=None, ge=1, le=4)
    formats: list[Aspect] | None = None
    fit_mode: Literal["blur", "crop"] | None = None
    caption_position: Literal["bottom", "center", "top"] | None = None
    caption_size: Literal["s", "m", "l"] | None = None
    caption_language: str | None = Field(default=None, max_length=10)
    template_ref: str | None = Field(default=None, max_length=40)
    approver_id: int | None = None
    account_ids: list[int] | None = None
    publish_mode: Literal["draft", "now", "best", "at"] | None = None
    publish_at: datetime | None = None


class NodeCreate(NodeParams):
    kind: str
    x: float = 0
    y: float = 0


class PositionsIn(BaseModel):
    positions: dict[int, tuple[float, float]]


class ConnectIn(BaseModel):
    source_id: int
    target_id: int
    port: str | None = None


class ItemsIn(BaseModel):
    node_ids: list[int] = []
    edge_ids: list[int] = []


class ItemsOut(BaseModel):
    """What was deleted — send it back to /restore to undo."""

    node_ids: list[int] = []
    edge_ids: list[int] = []


class PasteIn(BaseModel):
    node_ids: list[int]
    dx: float = 40
    dy: float = 40


class PasteOut(BaseModel):
    nodes: list[NodeOut]
    edges: list[EdgeOut]


class GroupIn(BaseModel):
    node_ids: list[int]
    name: str | None = Field(default=None, max_length=120)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, max_length=9)
    node_ids: list[int] | None = None


class VariablesIn(BaseModel):
    variables: list[Variable] = Field(default_factory=list, max_length=50)


class BatchIn(BaseModel):
    rows: list[dict[str, str]] = Field(default_factory=list)


class BatchBoard(BaseModel):
    id: int
    name: str


class RunIn(BaseModel):
    node_ids: list[int] | None = None
    downstream: bool = True
    force: bool = False


class UploadIn(BaseModel):
    media_id: int


class SelectOutputIn(BaseModel):
    output_id: int


class ApprovalIn(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class DesignIn(BaseModel):
    png: str = Field(description="The rendered design, base64 PNG (data URL prefix allowed).")
    layers: dict = Field(default_factory=dict)


class StudioOut(BaseModel):
    post_id: int
