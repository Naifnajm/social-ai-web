"""Board editing operations and the canvas payload (graph) of Production. Every function receives objects that
the router already checked to belong to the workspace; ids coming from the client are checked here."""
import base64
import binascii
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.core.models import Media
from app.core.storage import save_media
from app.modules.ai.models import AIModel, AIProvider, MediaJob
from app.modules.auth.models import User
from app.modules.brand.models import BrandKit
from app.modules.social import service as social
from app.modules.social.models import Post, SocialAccount
from app.modules.templates import frame
from app.modules.workspaces.models import Membership, Role, Workspace

from . import engine, media_tools
from .catalog import (
    AUDIO_MODES,
    BUSY_STATES,
    FORMATS,
    KINDS,
    OUTPUT,
    PORTS,
    PUBLISH_MODES,
    STYLES,
    kind_label,
    kinds_payload,
    templates,
)
from .engine import BoardGraph
from .models import Board, Edge, Group, Node, Output

PARAM_FIELDS = ("name", "x", "y", "prompt", "text_value", "provider_id", "model_id", "aspect", "style", "seconds",
                "audio_mode", "variations", "formats", "fit_mode", "caption_position", "caption_size",
                "caption_language", "template_ref", "approver_id", "account_ids", "publish_mode", "publish_at")
COPY_FIELDS = ("kind", "name", "prompt", "text_value", "provider_id", "model_id", "aspect", "style", "seconds",
               "audio_mode", "design", "variations", "formats", "fit_mode", "caption_position", "caption_size",
               "caption_language", "template_ref", "approver_id", "account_ids", "publish_mode", "publish_at",
               "output_text", "output_media_id", "cost")
GROUP_COLORS = ("#71717a", "#2563eb", "#db2777", "#059669", "#ea580c", "#7c3aed")


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------- lookups (workspace-checked)
def get_board(db: Session, workspace_id: int, board_id: int) -> Board:
    board = db.get(Board, board_id)
    if not board or board.workspace_id != workspace_id:
        raise NotFound(_("Board not found."), code="board_not_found")
    return board


def get_node(db: Session, workspace_id: int, node_id: int, active: bool = True) -> Node:
    node = db.get(Node, node_id)
    if not node or node.workspace_id != workspace_id or (active and not node.active):
        raise NotFound(_("Block not found."), code="node_not_found")
    return node


def get_group(db: Session, workspace_id: int, group_id: int) -> Group:
    group = db.get(Group, group_id)
    if not group or group.workspace_id != workspace_id:
        raise NotFound(_("Group not found."), code="group_not_found")
    return group


def _owned(db: Session, model, workspace_id: int, item_id: int | None, message: str):
    if not item_id:
        return None
    item = db.get(model, item_id)
    if not item or item.workspace_id != workspace_id:
        raise NotFound(message, code="not_found")
    return item


def get_media(db: Session, workspace_id: int, media_id: int) -> Media:
    return _owned(db, Media, workspace_id, media_id, _("File not found."))


# ---------------------------------------------------------------------------- serialization
def media_ref(media: Media | None) -> dict | None:
    if not media:
        return None
    return {"id": media.id, "filename": media.filename, "mimetype": media.mimetype, "kind": media.kind,
            "url": "/api/media/%d/file" % media.id, "width": media.width, "height": media.height}


def output_dict(g: BoardGraph, node: Node, output: Output) -> dict:
    return {"id": output.id, "run": output.run_no, "aspect": output.aspect, "cost": round(output.cost or 0, 4),
            "text": (output.text or "")[:400] or None, "model": output.model_label, "created_at": output.created_at,
            "media": media_ref(g.media(output.media_id)),
            "selected": bool(output.media_id and output.media_id == node.output_media_id
                             or (not output.media_id and output.text and output.text == node.output_text))}


def node_dict(g: BoardGraph, node: Node, *, with_estimate: bool = True, user_id: int | None = None,
              role: Role | None = None, labels: dict | None = None) -> dict:
    db = g.db
    outputs = db.scalars(select(Output).where(Output.node_id == node.id).order_by(Output.id.desc()).limit(24)).all()
    progress = node.progress or 0
    if node.state == "running" and node.run_job_ids:
        running = db.scalars(select(MediaJob.progress).where(MediaJob.id.in_(node.run_job_ids),
                                                             MediaJob.state == "running")).all()
        if running:
            progress = int(sum(running) / len(running))
    labels = labels if labels is not None else {}
    model_label = None
    if node.model_id:
        model_label = labels.get(("model", node.model_id))
        if model_label is None:
            model = db.get(AIModel, node.model_id)
            model_label = model.label if model else None
    approver = engine.approver_id(g, node) if node.kind == "approval" else None
    approver_name = None
    if approver:
        approver_name = labels.get(("user", approver))
        if approver_name is None:
            user = db.get(User, approver)
            approver_name = user.name if user else None
    post_state = None
    if node.post_id:
        post = db.get(Post, node.post_id)
        post_state = post.state if post and post.workspace_id == node.workspace_id else None
    est = engine.estimate(g, node) if with_estimate else None
    return {
        "id": node.id, "board_id": node.board_id, "kind": node.kind, "name": node.name or kind_label(node.kind),
        "x": node.x, "y": node.y, "group_id": node.group_id, "prompt": node.prompt or "",
        "text_value": node.text_value or "", "provider_id": node.provider_id, "model_id": node.model_id,
        "model_label": model_label, "aspect": node.aspect or "1:1", "style": node.style, "seconds": node.seconds or 8,
        "audio_mode": node.audio_mode or "speech", "design": node.design, "variations": engine.variations(node),
        "formats": [f for f in (node.formats or "").split(",") if f], "fit_mode": node.fit_mode or "blur",
        "caption_position": node.caption_position or "bottom", "caption_size": node.caption_size or "m",
        "caption_language": node.caption_language or "", "template_ref": node.template_ref,
        "approval_state": node.approval_state, "approval_comment": node.approval_comment,
        "approver_id": node.approver_id, "approver_name": approver_name,
        "can_approve": bool(node.kind == "approval" and user_id and role and
                            engine.can_approve(db, g, node, user_id, role)),
        "account_ids": list(node.account_ids or []), "publish_mode": node.publish_mode or "draft",
        "publish_at": node.publish_at, "state": node.state, "progress": progress, "error": node.error,
        "notice": node.notice, "output_text": node.output_text, "output": media_ref(g.media(node.output_media_id)),
        "outputs": [output_dict(g, node, o) for o in outputs], "run_no": node.run_no or 0, "post_id": node.post_id,
        "post_state": post_state, "out_type": engine.out_type(g, node), "cost": round(node.cost or 0, 4),
        "estimate": {"cost": float(est.get("cost") or 0), "model": est.get("model")} if est else None,
        "fresh": node.state == "done" and node.done_hash == engine.input_hash(g, node),
    }


def edge_dict(g: BoardGraph, edge: Edge) -> dict:
    source = g.nodes.get(edge.source_id)
    return {"id": edge.id, "source": edge.source_id, "target": edge.target_id, "port": edge.target_port or "",
            "type": engine.out_type(g, source) if source else None}


def group_dict(db: Session, group: Group) -> dict:
    nodes = db.scalars(select(Node.id).where(Node.group_id == group.id, Node.active.is_(True)).order_by(Node.id))
    return {"id": group.id, "name": group.name, "color": group.color or "#71717a", "nodes": list(nodes)}


def board_dict(g: BoardGraph) -> dict:
    board, db = g.board, g.db
    post = db.get(Post, board.post_id) if board.post_id else None
    return {"id": board.id, "name": board.name, "description": board.description, "template": board.template,
            "zoom": board.zoom or 1.0, "pan_x": board.pan_x or 0.0, "pan_y": board.pan_y or 0.0,
            "variables": [v for v in board.variables or [] if isinstance(v, dict)],
            "used_variables": engine.used_variables(g), "brand_kit_id": board.brand_kit_id,
            "post": {"id": post.id, "name": post.name, "state": post.state}
            if post and post.workspace_id == board.workspace_id else None,
            "cover_url": "/api/media/%d/file" % board.cover_media_id if board.cover_media_id else None,
            "updated_at": board.updated_at}


def pickers(db: Session, workspace_id: int) -> dict[str, list[dict]]:
    """Models per capability grouped by provider (fallback when the AI feature's /api/ai/pickers is absent)."""
    providers = db.scalars(select(AIProvider).where(AIProvider.workspace_id == workspace_id,
                                                    AIProvider.active.is_(True))
                           .order_by(AIProvider.sequence, AIProvider.id)).all()
    models = db.scalars(select(AIModel).where(AIModel.workspace_id == workspace_id, AIModel.active.is_(True))
                        .order_by(AIModel.sequence, AIModel.id)).all()
    defaults = {"text": "text_model", "image": "image_model", "video": "video_model", "audio": "audio_model"}
    result: dict[str, list[dict]] = {}
    for capability, field in defaults.items():
        groups = []
        for provider in providers:
            options = [{"id": m.id, "name": m.name, "label": m.label or m.name,
                        "price": _price_label(m), "default": m.name == getattr(provider, field)}
                       for m in models if m.provider_id == provider.id and m.capability == capability]
            if options:
                groups.append({"provider_id": provider.id, "provider": provider.name, "models": options})
        result[capability] = groups
    return result


def _price_label(model: AIModel) -> str | None:
    if model.unit == "tokens" and (model.price_in or model.price_out):
        return "$%g / $%g per 1M" % (model.price_in, model.price_out)
    if model.unit == "free":
        return _("Free")
    if model.price:
        unit = {"image": _("image"), "second": _("second"), "1k_chars": _("1k characters"),
                "minute": _("minute")}.get(model.unit, model.unit)
        return "$%g / %s" % (model.price, unit)
    return None


def brand_design(db: Session, workspace: Workspace, kit: BrandKit | None) -> dict:
    if kit:
        return {"id": kit.id, "name": kit.name,
                "logo_url": "/api/media/%d/file" % kit.logo_media_id if kit.logo_media_id else None,
                "color": kit.color_primary or "#111111", "color2": kit.color_secondary or "#71717a",
                "text_color": kit.color_text or "#ffffff", "font": kit.font_family or "system-ui"}
    return {"id": None, "name": workspace.name,
            "logo_url": "/api/media/%d/file" % workspace.logo_media_id if workspace.logo_media_id else None,
            "color": "#111111", "color2": "#71717a", "text_color": "#ffffff", "font": "system-ui"}


def template_choices(db: Session, workspace_id: int) -> list[dict]:
    """Brand templates for the Template block (provided by the templates feature when it offers ``choices``)."""
    choices = getattr(frame, "choices", None)
    if not choices:
        return []
    try:
        result = []
        for choice in choices(db, workspace_id) or []:
            value = choice.get("value") or choice.get("key")
            label = choice.get("label") or choice.get("name") or value
            if value and str(value).partition(":")[0] in ("template", "set"):
                result.append({"value": str(value), "label": str(label)})
        return result
    except Exception:  # the templates feature is optional for the canvas
        return []


def graph(db: Session, workspace: Workspace, board: Board, *, user_id: int | None = None, role: Role | None = None,
          light: bool = False) -> dict:
    """Everything the canvas needs. ``light`` (polling while a run is busy) skips choices and estimates."""
    g = BoardGraph(db, board)
    labels: dict = {}
    model_ids = {n.model_id for n in g.nodes.values() if n.model_id}
    if model_ids:
        labels.update({("model", m.id): m.label for m in db.scalars(select(AIModel).where(AIModel.id.in_(model_ids)))})
    payload = {
        "board": board_dict(g),
        "nodes": [node_dict(g, n, with_estimate=not light, user_id=user_id, role=role, labels=labels)
                  for n in g.nodes.values()],
        "edges": [edge_dict(g, e) for e in g.edges],
        "groups": [group_dict(db, grp) for grp in db.scalars(select(Group).where(Group.board_id == board.id)
                                                            .order_by(Group.id))],
        "busy": any(n.state in BUSY_STATES for n in g.nodes.values()),
    }
    if light:
        return payload
    members = db.execute(select(User.id, User.name).join(Membership, Membership.user_id == User.id)
                         .where(Membership.workspace_id == workspace.id).order_by(User.name)).all()
    accounts = db.scalars(select(SocialAccount).where(SocialAccount.workspace_id == workspace.id,
                                                      SocialAccount.active.is_(True),
                                                      SocialAccount.platform != "whatsapp")
                          .order_by(SocialAccount.platform, SocialAccount.name)).all()
    kits = db.scalars(select(BrandKit).where(BrandKit.workspace_id == workspace.id, BrandKit.active.is_(True))
                      .order_by(BrandKit.name)).all()
    payload.update({
        "kinds": kinds_payload(),
        "brand_kits": [{"id": k.id, "name": k.name} for k in kits],
        "accounts": [{"id": a.id, "name": a.name, "platform": a.platform, "state": a.state,
                      "avatar_url": a.avatar_url} for a in accounts],
        "members": [{"id": m.id, "name": m.name} for m in members],
        "brand_templates": template_choices(db, workspace.id),
        "pickers": pickers(db, workspace.id),
        "brand": brand_design(db, workspace, g.kit),
        "styles": list(STYLES), "aspects": list(FORMATS), "audio_modes": list(AUDIO_MODES),
        "publish_modes": list(PUBLISH_MODES),
        "ffmpeg": media_tools.ffmpeg_available(), "subtitles": media_tools.subtitles_available(),
        "run_all": engine.estimate_run(g),
    })
    return payload


def board_cards(db: Session, workspace_id: int, limit: int = 100) -> list[dict]:
    boards = db.scalars(select(Board).where(Board.workspace_id == workspace_id)
                        .order_by(Board.updated_at.desc(), Board.id.desc()).limit(limit)).all()
    if not boards:
        return []
    ids = [b.id for b in boards]
    rows = db.execute(select(Node.board_id, Node.state, Node.output_media_id).where(
        Node.board_id.in_(ids), Node.active.is_(True))).all()
    stats: dict[int, dict] = {i: {"nodes": 0, "outputs": 0, "states": set()} for i in ids}
    for board_id, state, media_id in rows:
        stats[board_id]["nodes"] += 1
        stats[board_id]["outputs"] += 1 if media_id else 0
        stats[board_id]["states"].add(state)
    cards = []
    for board in boards:
        states = stats[board.id]["states"]
        cards.append({"id": board.id, "name": board.name, "template": board.template,
                      "node_count": stats[board.id]["nodes"], "output_count": stats[board.id]["outputs"],
                      "status": "running" if states & {"queued", "running", "waiting"} else
                      "failed" if "failed" in states else "idle",
                      "cover_url": "/api/media/%d/file" % board.cover_media_id if board.cover_media_id else None,
                      "updated_at": board.updated_at})
    return cards


# ---------------------------------------------------------------------------- boards
def create_node(db: Session, board: Board, kind: str, x: float = 0, y: float = 0, **values) -> Node:
    if kind not in KINDS:
        raise AppError(_("Unknown block type."), code="bad_kind")
    node = Node(workspace_id=board.workspace_id, board_id=board.id, kind=kind, x=x, y=y, state="idle")
    db.add(node)
    apply_params(db, board, node, values)
    if not node.name:
        node.name = kind_label(kind)
    db.flush()
    if kind == "text":
        engine.refresh_text_state(BoardGraph(db, board), node)
    return node


def apply_params(db: Session, board: Board, node: Node, values: dict) -> None:
    ws = board.workspace_id
    values = {k: v for k, v in values.items() if k in PARAM_FIELDS}
    if "provider_id" in values and values["provider_id"]:
        _owned(db, AIProvider, ws, values["provider_id"], _("AI provider not found."))
    if "model_id" in values:
        model = _owned(db, AIModel, ws, values["model_id"], _("AI model not found."))
        if model:
            values["provider_id"] = model.provider_id
    if values.get("approver_id"):
        engine.check_member(db, ws, values["approver_id"])
    if "account_ids" in values:
        ids = list(dict.fromkeys(int(i) for i in values["account_ids"] or []))
        if ids:
            found = set(db.scalars(select(SocialAccount.id).where(SocialAccount.id.in_(ids),
                                                                  SocialAccount.workspace_id == ws)))
            if found != set(ids):
                raise NotFound(_("Account not found."), code="account_not_found")
        values["account_ids"] = ids
    if "formats" in values:
        formats = [f for f in values["formats"] or [] if f in FORMATS]
        values["formats"] = ",".join(dict.fromkeys(formats))
    if "style" in values and values["style"] and values["style"] not in STYLES:
        values["style"] = None
    if "variations" in values:
        values["variations"] = max(1, min(4, int(values["variations"] or 1)))
    if "template_ref" in values:
        ref = (values["template_ref"] or "").strip()
        kind, _sep, value = ref.partition(":")
        values["template_ref"] = ref if kind in ("template", "set") and value.isdigit() else None
    if "name" in values:
        values["name"] = (values["name"] or "").strip() or kind_label(node.kind)
    for key, value in values.items():
        setattr(node, key, value)
    if node.kind == "design" and "aspect" in values and node.design:
        node.design = dict(node.design, aspect=values["aspect"])


def update_node(db: Session, board: Board, node: Node, values: dict) -> Node:
    apply_params(db, board, node, values)
    db.flush()
    if node.kind == "text" and "text_value" in values:
        engine.refresh_text_state(BoardGraph(db, board), node)
    return node


def create_board(db: Session, workspace_id: int, user_id: int, key: str = "blank", name: str | None = None) -> Board:
    catalog = templates()
    template = catalog.get(key) or catalog["blank"]
    board = Board(workspace_id=workspace_id, user_id=user_id, name=(name or "").strip() or template["name"],
                  template=key if key in catalog else "blank")
    db.add(board)
    db.flush()
    nodes = []
    for spec in template["nodes"]:
        values = dict(spec)
        kind = values.pop("kind")
        # media-first cards are wide and tall: give them room
        x, y = values.pop("x", 0) * 1.25, values.pop("y", 0) * 1.6
        nodes.append(create_node(db, board, kind, x, y, **values))
    for source, target in template["edges"]:
        connect(db, board, nodes[source].id, nodes[target].id)
    return board


def _copy_node(db: Session, board: Board, src: Node, dx: float = 0, dy: float = 0) -> Node:
    values = {f: getattr(src, f) for f in COPY_FIELDS}
    has_output = bool(src.output_media_id or src.output_text)
    node = Node(workspace_id=board.workspace_id, board_id=board.id, x=src.x + dx, y=src.y + dy,
                state="done" if has_output and src.kind not in ("post", "approval") else "idle", **values)
    if src.kind == "approval":
        node.output_media_id, node.output_text = None, None
    db.add(node)
    db.flush()
    if has_output and src.kind not in ("approval", "post"):
        output = Output(workspace_id=board.workspace_id, node_id=node.id, run_no=0, media_id=src.output_media_id,
                        text=src.output_text, cost=0.0)
        db.add(output)
    return node


def duplicate_board(db: Session, board: Board, name: str, user_id: int | None = None) -> Board:
    new = Board(workspace_id=board.workspace_id, user_id=user_id or board.user_id, name=name[:200],
                description=board.description, template=board.template, cover_media_id=board.cover_media_id,
                zoom=board.zoom, pan_x=board.pan_x, pan_y=board.pan_y,
                variables=[dict(v) for v in board.variables or []], brand_kit_id=board.brand_kit_id)
    db.add(new)
    db.flush()
    g = BoardGraph(db, board)
    mapping = {src.id: _copy_node(db, new, src) for src in g.nodes.values()}
    for edge in g.edges:
        db.add(Edge(workspace_id=board.workspace_id, board_id=new.id, source_id=mapping[edge.source_id].id,
                    target_id=mapping[edge.target_id].id, target_port=edge.target_port))
    db.flush()
    new_graph = BoardGraph(db, new)
    for node in new_graph.nodes.values():
        engine.refresh_text_state(new_graph, node)
    db.flush()
    return new


def from_post(db: Session, workspace_id: int, user_id: int, post_id: int) -> Board:
    """Open a post in Production: its text and media become blocks wired to a Post block that updates it."""
    post = _owned(db, Post, workspace_id, post_id, _("This post no longer exists."))
    board = Board(workspace_id=workspace_id, user_id=user_id, post_id=post.id, template="post",
                  name=_("Edit: {name}", name=post.name or _("post"))[:200])
    db.add(board)
    db.flush()
    post_node = create_node(db, board, "post", 900, 80, name=_("Post"),
                            account_ids=[a.id for a in post.accounts])
    post_node.post_id = post.id
    if (post.content or "").strip():
        text = create_node(db, board, "text", 40, 40, name=_("Caption"), text_value=post.content)
        connect(db, board, text.id, post_node.id)
    for index, link in enumerate(post.media_links):
        media = db.get(Media, link.media_id)
        if media and media.workspace_id == workspace_id:
            upload = _upload_node(db, board, media, 40, 300 + index * 360)
            connect(db, board, upload.id, post_node.id)
    return board


def from_media(db: Session, workspace_id: int, user_id: int, media_id: int, text: str | None = None) -> Board:
    """Send one image, video or audio (e.g. from the Studio composer) to a new board."""
    media = get_media(db, workspace_id, media_id)
    board = Board(workspace_id=workspace_id, user_id=user_id, name=_("Edit: {name}", name=media.filename)[:200])
    db.add(board)
    db.flush()
    _upload_node(db, board, media, 60, 80)
    if (text or "").strip():
        create_node(db, board, "text", 60, 460, name=_("Text"), text_value=text)
    return board


def _upload_node(db: Session, board: Board, media: Media, x: float, y: float) -> Node:
    node = create_node(db, board, "upload", x, y, name=media.filename[:160])
    set_upload(db, board, node, media)
    g = BoardGraph(db, board)
    node.run_hash = engine.input_hash(g, node)
    node.done_hash = node.run_hash
    return node


def set_upload(db: Session, board: Board, node: Node, media: Media | None) -> Node:
    if node.kind != "upload":
        raise AppError(_("Files can only be added to an Upload block."), code="not_upload")
    if media and media.kind not in ("image", "video", "audio"):
        raise AppError(_("Only images, videos and audio files can be used."), code="bad_type")
    node.output_media_id = media.id if media else None
    node.state = "done" if media else "idle"
    node.error = None
    node.progress = 100 if media else 0
    if media and (not node.name or node.name == kind_label("upload")):
        node.name = media.filename[:160]
    db.flush()
    if media:
        g = BoardGraph(db, board)
        engine.add_output(g, node, media)
        node.done_hash = engine.input_hash(g, node)
        if media.kind == "image" and not board.cover_media_id:
            board.cover_media_id = media.id
    return node


def save_design(db: Session, board: Board, node: Node, png: str, layers: dict, user_id: int) -> Node:
    """The browser renders the design (it shapes Arabic text perfectly) and sends the PNG."""
    if node.kind != "design":
        raise AppError(_("Only a Design block has a design."), code="not_design")
    data = png.split(",", 1)[1] if png.startswith("data:") else png
    try:
        content = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise AppError(_("The design image is invalid."), code="bad_png")
    if not content.startswith(b"\x89PNG") or len(content) > 25 * 1024 * 1024:
        raise AppError(_("The design image is invalid."), code="bad_png")
    media = save_media(db, board.workspace_id, content, "production-design-%d.png" % node.id, "image/png",
                       source="production", user_id=user_id)
    g = BoardGraph(db, board)
    g._media[media.id] = media
    node.design = layers or None
    if layers.get("aspect") in FORMATS:
        node.aspect = layers["aspect"]
    node.run_no = (node.run_no or 0) + 1
    node.error, node.notice = None, None
    engine.add_output(g, node, media)
    node.state, node.progress = "done", 100
    node.done_hash = node.run_hash = engine.input_hash(g, node)
    db.flush()
    return node


def select_output(db: Session, board: Board, node: Node, output_id: int) -> Node:
    """Use another version (or variation) of this block — free, nothing is generated."""
    output = db.get(Output, output_id)
    if not output or output.node_id != node.id:
        raise NotFound(_("Version not found."), code="output_not_found")
    g = BoardGraph(db, board)
    engine.select_output(g, node, output)
    if node.state != "done":
        node.state, node.error = "done", None
    if node.kind == "upload":
        node.done_hash = engine.input_hash(g, node)
    db.flush()
    return node


# ---------------------------------------------------------------------------- links
def connect(db: Session, board: Board, source_id: int, target_id: int, port: str | None = None) -> dict:
    """Link the output of a block to a named input port of another (auto-picked when not given)."""
    g = BoardGraph(db, board)
    source, target = g.nodes.get(source_id), g.nodes.get(target_id)
    if not source or not target or source.id == target.id:
        raise AppError(_("These blocks cannot be linked."), code="bad_link")
    out_types = engine.output_types(g, source)
    ports = [p for p in PORTS[target.kind] if not port or p[0] == port]
    match = next((p for p in ports if p[2] & out_types), None)
    if not match:
        raise AppError(_("“{target}” cannot take the output of “{source}”.", target=target.name, source=source.name),
                       code="bad_link")
    if target.id == source.id or target in g.ancestors(source):
        raise AppError(_("This link would create a loop."), code="loop")
    key, _label, _types, multi = match
    existing = [e for e in g.edges if e.target_id == target.id and e.target_port == key]
    same = next((e for e in existing if e.source_id == source.id), None)
    if same:
        return dict(edge_dict(g, same), replaced=[])
    replaced = [] if multi else existing  # a single-input port keeps only the newest link
    for edge in replaced:
        edge.active, edge.archived_at = False, now()
    edge = Edge(workspace_id=board.workspace_id, board_id=board.id, source_id=source.id, target_id=target.id,
                target_port=key)
    db.add(edge)
    db.flush()
    g.edges = [e for e in g.edges if e not in replaced] + [edge]
    return dict(edge_dict(g, edge), replaced=[e.id for e in replaced])


def archive_items(db: Session, board: Board, node_ids: list[int], edge_ids: list[int]) -> dict:
    """Soft delete (so it can be undone). Links of removed blocks go with them."""
    g = BoardGraph(db, board)
    nodes = [g.nodes[i] for i in node_ids if i in g.nodes]
    removed = {n.id for n in nodes}
    edges = [e for e in g.edges if e.id in set(edge_ids) or e.source_id in removed or e.target_id in removed]
    stamp = now()
    for edge in edges:
        edge.active, edge.archived_at = False, stamp
    for node in nodes:
        node.active, node.archived_at, node.group_id = False, stamp, None
    db.flush()
    return {"node_ids": [n.id for n in nodes], "edge_ids": [e.id for e in edges]}


def restore_items(db: Session, board: Board, node_ids: list[int], edge_ids: list[int]) -> None:
    if node_ids:
        for node in db.scalars(select(Node).where(Node.id.in_(node_ids), Node.board_id == board.id)):
            node.active, node.archived_at = True, None
    db.flush()
    if edge_ids:
        active = set(db.scalars(select(Node.id).where(Node.board_id == board.id, Node.active.is_(True))))
        for edge in db.scalars(select(Edge).where(Edge.id.in_(edge_ids), Edge.board_id == board.id)):
            if edge.source_id in active and edge.target_id in active:
                edge.active, edge.archived_at = True, None
    db.flush()


def paste_nodes(db: Session, board: Board, node_ids: list[int], dx: float = 40, dy: float = 40) -> tuple[list, list]:
    """Copy blocks (from this or another board of the workspace) with their settings, results and inner links."""
    sources = db.scalars(select(Node).where(Node.id.in_(node_ids or [0]), Node.workspace_id == board.workspace_id)
                         .order_by(Node.id)).all()
    if not sources:
        raise NotFound(_("Nothing to paste."), code="nothing_to_paste")
    mapping = {src.id: _copy_node(db, board, src, dx, dy) for src in sources}
    edges = db.scalars(select(Edge).where(Edge.source_id.in_(list(mapping)), Edge.target_id.in_(list(mapping)),
                                          Edge.active.is_(True), Edge.workspace_id == board.workspace_id)).all()
    new_edges = []
    for edge in edges:
        new = Edge(workspace_id=board.workspace_id, board_id=board.id, source_id=mapping[edge.source_id].id,
                   target_id=mapping[edge.target_id].id, target_port=edge.target_port)
        db.add(new)
        new_edges.append(new)
    db.flush()
    g = BoardGraph(db, board)
    for node in mapping.values():
        engine.refresh_text_state(g, node)
    db.flush()
    return list(mapping.values()), new_edges


# ---------------------------------------------------------------------------- groups
def group_nodes(db: Session, board: Board, node_ids: list[int], name: str | None = None) -> Group:
    g = BoardGraph(db, board)
    nodes = [g.nodes[i] for i in node_ids if i in g.nodes]
    if not nodes:
        raise AppError(_("Select the blocks to group."), code="empty_group")
    count = db.scalar(select(func.count()).select_from(Group).where(Group.board_id == board.id)) or 0
    group = Group(workspace_id=board.workspace_id, board_id=board.id,
                  name=(name or "").strip() or _("Group {number}", number=count + 1),
                  color=GROUP_COLORS[count % len(GROUP_COLORS)])
    db.add(group)
    db.flush()
    for node in nodes:
        node.group_id = group.id
    db.flush()
    return group


def ungroup(db: Session, group: Group) -> list[int]:
    nodes = db.scalars(select(Node).where(Node.group_id == group.id)).all()
    for node in nodes:
        node.group_id = None
    db.delete(group)
    db.flush()
    return [n.id for n in nodes]


# ---------------------------------------------------------------------------- variables & batches
def set_variables(db: Session, board: Board, variables: list[dict]) -> None:
    clean, seen = [], set()
    for v in variables or []:
        key = str(v.get("key") or "").strip()
        if key and key not in seen:
            seen.add(key)
            clean.append({"key": key, "value": str(v.get("value") or "")})
    board.variables = clean
    db.flush()
    g = BoardGraph(db, board)
    for node in g.nodes.values():
        engine.refresh_text_state(g, node)
    db.flush()


def run_batch(db: Session, board: Board, rows: list[dict], user_id: int) -> list[Board]:
    """One copy of the board per row of variable values; each copy is queued (the caller schedules them)."""
    rows = [{str(k).strip(): str(v) for k, v in (row or {}).items() if str(k).strip()} for row in rows or []]
    rows = [row for row in rows if any(v.strip() for v in row.values())]
    if not rows:
        raise AppError(_("Add at least one version."), code="empty_batch")
    if len(rows) > 20:
        raise AppError(_("Up to 20 versions at a time."), code="batch_limit")
    created = []
    current = {v["key"]: v["value"] for v in board.variables or [] if isinstance(v, dict) and v.get("key")}
    for index, row in enumerate(rows, 1):
        label = next((v for v in row.values() if v.strip()), "") or str(index)
        copy = duplicate_board(db, board, "%s · %s" % (board.name, label[:40]), user_id)
        values = dict(current, **row)
        set_variables(db, copy, [{"key": k, "value": v} for k, v in values.items()])
        engine.run(db, copy)
        created.append(copy)
    return created


# ---------------------------------------------------------------------------- Studio
def send_to_studio(db: Session, board: Board, node: Node, user_id: int) -> int:
    """Create a draft post from this block's result (the Studio composer opens it)."""
    if node.kind == "post" and node.post_id:
        post = db.get(Post, node.post_id)
        if post and post.workspace_id == node.workspace_id:
            return post.id
    g = BoardGraph(db, board)
    media = g.media(node.output_media_id)
    if not media and not node.output_text:
        raise AppError(_("Run this block first."), code="no_result")
    media_ids = [media.id] if media and media.kind in ("image", "video", "audio") else []
    content = node.output_text if OUTPUT[node.kind] == "text" and node.output_text else ""
    post = social.create_post(db, board.workspace_id, user_id, content=content or "", media_ids=media_ids,
                              name=board.name, source_ref="board:%d" % board.id)
    return post.id
