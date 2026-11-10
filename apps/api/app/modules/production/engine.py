"""Execution engine of Production boards.

* ``run(db, board, node_ids, downstream, force)`` queues blocks; ``advance(board_id)`` (a background job) runs
  every ready block in topological order. Unchanged blocks (same settings + inputs, see ``input_hash``) reuse
  their result for free unless ``force`` is set.
* AI images / video / voice go through ``app.modules.ai.media.start_job`` with
  ``callback="app.modules.production.engine.on_media_job"``: videos finish later, the callback records the
  result and continues the board.
* Text goes through ``app.modules.ai.service.generate_text_with_usage``; brand templates through
  ``app.modules.templates.frame``; posts through ``app.modules.social.service``.
"""
import hashlib
import json
import logging
import re
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import db as core_db
from app.core.errors import ApiError, AppError, Forbidden, NotFound
from app.core.i18n import _, set_locale
from app.core.models import Media
from app.core.notify import notify
from app.core.storage import read_media, save_media
from app.modules.ai import media as ai_media
from app.modules.ai import service as ai_service
from app.modules.ai.models import AIModel, MediaJob
from app.modules.brand.models import BrandKit
from app.modules.social import service as social
from app.modules.social.models import Post, PostMedia, SocialAccount
from app.modules.templates import frame
from app.modules.workspaces.models import ROLE_RANK, Membership, Role, Workspace

from . import media_tools
from .catalog import (
    CAPABILITY,
    HASH_FIELDS,
    NETWORK_FORMATS,
    NETWORK_VIDEO_FORMATS,
    OUTPUT,
    PORTS,
    kind_label,
)
from .models import Board, Edge, Node, Output

_logger = logging.getLogger(__name__)

CALLBACK = "app.modules.production.engine.on_media_job"
VAR_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
LLM_SYSTEM = ("You are a creative assistant producing social media content (scripts, captions, prompts). "
              "Follow the instruction precisely. Output only the result, no preamble, no quotes, no markdown.")
_UNSET = object()
# blocks being executed right now (a media callback fired synchronously must not re-enter the board)
_EXECUTING: ContextVar[frozenset] = ContextVar("production_executing", default=frozenset())


# ---------------------------------------------------------------------------- graph
class BoardGraph:
    """Active blocks and links of a board, loaded once, with graph helpers."""

    def __init__(self, db: Session, board: Board):
        self.db = db
        self.board = board
        nodes = db.scalars(select(Node).where(Node.board_id == board.id, Node.active.is_(True))
                           .order_by(Node.id)).all()
        self.nodes: dict[int, Node] = {n.id: n for n in nodes}
        edges = db.scalars(select(Edge).where(Edge.board_id == board.id, Edge.active.is_(True))
                           .order_by(Edge.id)).all()
        self.edges = [e for e in edges if e.source_id in self.nodes and e.target_id in self.nodes]
        self._kit = _UNSET
        self._media: dict[int, Media | None] = {}

    @property
    def kit(self) -> BrandKit | None:
        if self._kit is _UNSET:
            kit = self.db.get(BrandKit, self.board.brand_kit_id) if self.board.brand_kit_id else None
            self._kit = kit if kit and kit.workspace_id == self.board.workspace_id else None
        return self._kit

    def media(self, media_id: int | None) -> Media | None:
        if not media_id:
            return None
        if media_id not in self._media:
            media = self.db.get(Media, media_id)
            self._media[media_id] = media if media and media.workspace_id == self.board.workspace_id else None
        return self._media[media_id]

    def in_edges(self, node: Node) -> list[Edge]:
        return [e for e in self.edges if e.target_id == node.id]

    def upstream(self, node: Node) -> list[Node]:
        return list({e.source_id: self.nodes[e.source_id] for e in self.in_edges(node)}.values())

    def downstream(self, node: Node) -> list[Node]:
        return list({e.target_id: self.nodes[e.target_id] for e in self.edges if e.source_id == node.id}.values())

    def ancestors(self, node: Node) -> list[Node]:
        result: dict[int, Node] = {}
        todo = [node]
        while todo:
            for up in self.upstream(todo.pop()):
                if up.id not in result:
                    result[up.id] = up
                    todo.append(up)
        return list(result.values())

    def descendants(self, node: Node) -> list[Node]:
        result: dict[int, Node] = {}
        todo = [node]
        while todo:
            for down in self.downstream(todo.pop()):
                if down.id not in result:
                    result[down.id] = down
                    todo.append(down)
        return list(result.values())

    def topological(self) -> list[Node]:
        """Blocks ordered so every block comes after its inputs (left to right on ties)."""
        incoming: dict[int, int] = defaultdict(int)
        for edge in self.edges:
            incoming[edge.target_id] += 1
        ready = sorted((n for n in self.nodes.values() if not incoming[n.id]), key=lambda n: (n.x, n.y, n.id))
        order = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for down in self.downstream(node):
                incoming[down.id] -= 1
                if not incoming[down.id]:
                    ready.append(down)
        return order


def apply_vars(board: Board, text: str | None) -> str | None:
    if not text or "{{" not in text:
        return text
    values = {str(v.get("key") or "").strip(): str(v.get("value") or "") for v in (board.variables or [])
              if isinstance(v, dict) and str(v.get("key") or "").strip()}
    return VAR_RE.sub(lambda m: values.get(m.group(1).strip(), m.group(0)), text)


def used_variables(g: BoardGraph) -> list[str]:
    names: list[str] = []
    for node in g.nodes.values():
        for text in (node.prompt, node.text_value):
            for match in VAR_RE.finditer(text or ""):
                if match.group(1).strip() not in names:
                    names.append(match.group(1).strip())
    return names


def media_kind(media: Media | None) -> str:
    return (media.mimetype or "").split("/")[0] if media else ""


def output_types(g: BoardGraph, node: Node) -> set[str]:
    """Data types this block produces (an upload depends on its file, formats/approval on their inputs)."""
    out = OUTPUT[node.kind]
    if out != "media":
        return {out} if out else set()
    kind = media_kind(g.media(node.output_media_id))
    if kind in ("image", "video", "audio"):
        return {kind}
    if node.kind in ("reframe", "approval"):
        types: set[str] = set()
        for up in g.upstream(node):
            types |= output_types(g, up)
        allowed = {t for port in PORTS[node.kind] for t in port[2]}
        return (types & allowed) or set(allowed)
    return {"image", "video", "audio"}


def out_type(g: BoardGraph, node: Node) -> str | None:
    types = output_types(g, node)
    return sorted(types)[0] if len(types) == 1 else ("media" if types else None)


def inputs(g: BoardGraph, node: Node) -> tuple[list[str], list[Media]]:
    """Texts and media coming from the linked blocks (an approval block passes its content through)."""
    texts: list[str] = []
    media: list[Media] = []
    for up in g.upstream(node):
        if up.kind == "approval":
            up_texts, up_media = inputs(g, up)
            texts += up_texts
            media += [m for m in up_media if m not in media]
            continue
        if OUTPUT[up.kind] == "text":
            if (up.output_text or "").strip():
                texts.append(up.output_text.strip())
        else:
            item = g.media(up.output_media_id)
            if item and item not in media:
                media.append(item)
    return texts, media


def refresh_text_state(g: BoardGraph, node: Node) -> None:
    if node.kind != "text":
        return
    ok = bool((node.text_value or "").strip())
    node.output_text = apply_vars(g.board, node.text_value) if ok else None
    node.state = "done" if ok else "failed"
    node.error = None if ok else _("Write some text.")
    node.progress = 100 if ok else 0


def has_result(node: Node) -> bool:
    if node.kind == "post":
        return bool(node.post_id)
    if node.kind == "approval":
        return node.approval_state == "approved"
    return bool(node.output_media_id or node.output_text)


def input_hash(g: BoardGraph, node: Node) -> str:
    """Fingerprint of everything that decides this block's result."""
    links = []
    for edge in g.in_edges(node):
        up = g.nodes[edge.source_id]
        links.append([edge.target_port or "", up.id, up.output_media_id, up.output_text or "", up.done_hash or ""])
    kit = g.kit
    values = {f: getattr(node, f) for f in HASH_FIELDS}
    data = [values, apply_vars(g.board, node.prompt or ""), node.provider_id, node.model_id,
            sorted(node.account_ids or []), links,
            [kit.id, kit.llm_profile(), kit.visual_hint(), kit.voice] if kit else None]
    if node.kind == "upload":
        data.append(node.output_media_id)
    if node.kind == "template" and node.template_ref and hasattr(frame, "fingerprint"):
        try:  # a template edited since the last run gives a new result
            data.append(frame.fingerprint(g.db, g.board.workspace_id, node.template_ref))
        except Exception:  # pragma: no cover - optional hook of the templates feature
            pass
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------------------- plan & estimates
def plan(g: BoardGraph, node_ids: list[int] | None = None, downstream: bool = True,
         force: bool = False) -> tuple[list[Node], set[int]]:
    """Blocks a run would execute: ``(selection, dirty ids)``. Unchanged results are reused."""
    roots = [g.nodes[i] for i in node_ids or [] if i in g.nodes] if node_ids else list(g.nodes.values())
    selection: dict[int, Node] = {n.id: n for n in roots}
    if downstream:
        for node in roots:
            selection.update({d.id: d for d in g.descendants(node)})
    for node in list(selection.values()):
        selection.update({a.id: a for a in g.ancestors(node) if a.state != "done"})
    forced = {n.id for n in roots} if force and node_ids else set()
    dirty = {n.id for n in selection.values() if n.kind != "text" and (
        n.id in forced or n.state != "done" or not has_result(n) or n.done_hash != input_hash(g, n))}
    for node_id in list(dirty):
        dirty |= {d.id for d in g.descendants(g.nodes[node_id]) if d.id in selection}
    ordered = [n for n in g.topological() if n.id in selection]
    return ordered, dirty


def estimate(g: BoardGraph, node: Node) -> dict | None:
    """Approximate cost of running this block now: ``{"cost": $, "model": "..."}`` or None."""
    capability = CAPABILITY.get(node.kind)
    if not capability:
        return None
    texts = [(up.output_text or up.text_value or up.prompt or "") for up in g.upstream(node)
             if OUTPUT[up.kind] == "text"]
    if node.kind == "audio" and node.audio_mode == "speech":
        prompt = "\n".join(texts) or node.prompt or ""
    else:
        prompt = "\n".join([node.prompt or "", *texts])
    try:
        result = ai_media.estimate(g.db, g.board.workspace_id, capability, apply_vars(g.board, prompt) or "",
                                   seconds=node.seconds if node.kind in ("video", "audio") else 0,
                                   audio_mode=node.audio_mode, model_id=node.model_id, provider_id=node.provider_id)
    except Exception:  # the AI feature may not be configured yet: no estimate
        return None
    if not isinstance(result, dict):
        return None
    count = variations(node)
    if count > 1 and result.get("cost"):
        result = dict(result, cost=round(float(result["cost"]) * count, 6))
    return result


def estimate_run(g: BoardGraph, node_ids: list[int] | None = None, downstream: bool = True,
                 force: bool = False) -> dict:
    selection, dirty = plan(g, node_ids, downstream, force)
    cost = sum(float((estimate(g, g.nodes[i]) or {}).get("cost") or 0) for i in dirty if g.nodes[i].kind in CAPABILITY)
    reused = len([n for n in selection if n.kind in CAPABILITY and n.id not in dirty])
    return {"cost": round(cost, 4), "reused": reused, "blocks": len(dirty)}


def variations(node: Node) -> int:
    return max(1, min(4, node.variations or 1))


# ---------------------------------------------------------------------------- running
def run(db: Session, board: Board, node_ids: list[int] | None = None, downstream: bool = True,
        force: bool = False) -> int:
    """Queue blocks for execution (call ``schedule(board.id)`` after committing). Returns the queued count."""
    g = BoardGraph(db, board)
    selection, _dirty = plan(g, node_ids, downstream, force)
    queued = 0
    for node in selection:
        if node.state in ("queued", "running"):
            continue
        if node.kind == "text":
            refresh_text_state(g, node)
            continue
        node.state, node.error, node.notice, node.progress, node.force_run = "queued", None, None, 0, False
        if force and node_ids and node.id in node_ids:
            node.force_run = True
        queued += 1
    db.flush()
    return queued


def schedule(board_id: int) -> None:
    """Advance the board in the background (inline when SAI_JOBS_SYNC is on)."""
    from app.core.jobs import enqueue
    enqueue("app.modules.production.engine.advance", board_id)


@contextmanager
def _job_session():
    """Like ``core.jobs.session_scope`` but resolves the session factory at call time (tests swap it)."""
    db = core_db.SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def advance(board_id: int, budget: int = 50) -> None:
    """Background job: run the ready blocks of a board."""
    with _job_session() as db:
        board = db.get(Board, board_id)
        if board:
            use_workspace_locale(db, board)
            step(db, board, budget)


def use_workspace_locale(db: Session, board: Board) -> None:
    """Messages written by background work (errors, notices) use the workspace language."""
    workspace = db.get(Workspace, board.workspace_id)
    if workspace:
        set_locale(workspace.locale)


def step(db: Session, board: Board, budget: int = 50) -> None:
    executed = 0
    while executed < budget:
        g = BoardGraph(db, board)
        node = _next_ready(db, g)
        if node is None:
            break
        execute(db, g, node)
        db.commit()
        executed += 1
    g = BoardGraph(db, board)
    for node in g.topological():  # blocks whose inputs failed cannot run
        if node.state == "queued" and any(up.state == "failed" for up in g.upstream(node)):
            node.state, node.error = "failed", _("An input block failed.")
    db.flush()


def _next_ready(db: Session, g: BoardGraph) -> Node | None:
    db.flush()
    for node in g.topological():
        if node.state != "queued" or not all(up.state == "done" for up in g.upstream(node)):
            continue
        # lock the row so a second worker (periodic task, another run) does not execute it twice
        row = db.execute(select(Node.id).where(Node.id == node.id, Node.state == "queued")
                         .with_for_update(skip_locked=True)).first()
        if row:
            return node
    return None


def execute(db: Session, g: BoardGraph, node: Node) -> None:
    token = _EXECUTING.set(_EXECUTING.get() | {node.id})
    try:
        current = input_hash(g, node)
        if not node.force_run and node.done_hash == current and has_result(node) and node.kind != "upload":
            node.state, node.progress, node.force_run = "done", 100, False
            node.notice = _("Unchanged — the previous result is reused (no cost).")
            return
        node.state, node.error, node.notice, node.progress, node.force_run = "running", None, None, 0, False
        node.run_no = (node.run_no or 0) + 1
        node.run_hash, node.run_expected, node.run_job_ids = current, 0, []
        db.flush()
        try:
            with db.begin_nested():
                RUNNERS[node.kind](g, node)
        except AppError as exc:
            _fail(node, exc.detail)
        except ApiError as exc:
            _fail(node, exc.message)
        except NotImplementedError:
            _fail(node, _("This feature is not available yet on this platform."))
        except Exception as exc:  # keep the board usable whatever happens
            _logger.exception("production block %s failed", node.id)
            _fail(node, _("Unexpected error: {error}", error=str(exc)[:300]))
        db.flush()
    finally:
        _EXECUTING.reset(token)


def _fail(node: Node, message: str) -> None:
    node.state, node.error, node.progress = "failed", message, 0


# ---------------------------------------------------------------------------- results & versions
def add_output(g: BoardGraph, node: Node, media: Media | None = None, text: str | None = None, cost: float = 0.0,
               job: MediaJob | None = None, aspect: str | None = None, select_it: bool = True,
               model_label: str | None = None, run_no: int | None = None) -> Output:
    db = g.db
    last = db.scalars(select(Output).where(Output.node_id == node.id).order_by(Output.id.desc()).limit(1)).first()
    media_id = media.id if media else None
    if last and last.media_id == media_id and (last.text or None) == (text or None) and not job and media_id:
        output = last  # the same file again (e.g. an upload used twice)
    else:
        if model_label is None and node.model_id:
            model = db.get(AIModel, node.model_id)
            model_label = model.label if model else None
        output = Output(workspace_id=node.workspace_id, node_id=node.id,
                        run_no=node.run_no if run_no is None else run_no, media_id=media_id, text=text or None,
                        cost=cost or 0.0, job_id=job.id if job else None, aspect=aspect, model_label=model_label)
        db.add(output)
        db.flush()
    if select_it:
        select_output(g, node, output)
    return output


def select_output(g: BoardGraph, node: Node, output: Output) -> None:
    node.output_media_id = output.media_id
    if output.text or not output.media_id:
        node.output_text = output.text
    elif node.kind != "captions":
        node.output_text = None
    media = g.media(output.media_id)
    if media_kind(media) == "image":
        g.board.cover_media_id = media.id


def _done_with(g: BoardGraph, node: Node, media: Media | None = None, text=_UNSET, cost: float = 0.0,
               record: bool = True) -> None:
    if record and (media or (text is not _UNSET and text)):
        add_output(g, node, media, None if text is _UNSET else text, cost)
    else:
        if media:
            node.output_media_id = media.id
        if text is not _UNSET:
            node.output_text = text
    node.state, node.progress = "done", 100
    node.done_hash = node.run_hash or input_hash(g, node)


def _store(g: BoardGraph, node: Node, content: bytes, mimetype: str, ext: str, suffix: str = "") -> Media:
    name = "production-%s-%s%s.%s" % (node.kind, node.id, "-" + suffix if suffix else "", ext)
    media = save_media(g.db, node.workspace_id, content, name, mimetype, source="production", user_id=g.board.user_id)
    g._media[media.id] = media
    return media


def _prompt(g: BoardGraph, node: Node) -> str:
    return (apply_vars(g.board, node.prompt or "") or "").strip()


def _prompt_with_inputs(g: BoardGraph, node: Node, texts: list[str]) -> str:
    return "\n\n".join(p for p in [_prompt(g, node), *texts] if p)


def _with_brand(g: BoardGraph, prompt: str) -> str:
    hint = g.kit.visual_hint() if g.kit else ""
    return "%s\n\n%s" % (prompt, hint) if prompt and hint else prompt


def clean_text(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.strip("`").strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


# ---------------------------------------------------------------------------- block runners
def _run_text(g: BoardGraph, node: Node) -> None:
    refresh_text_state(g, node)


def _run_upload(g: BoardGraph, node: Node) -> None:
    media = g.media(node.output_media_id)
    if not media:
        raise AppError(_("Upload a file in this block."), code="no_file")
    _done_with(g, node, media)


def _run_llm(g: BoardGraph, node: Node) -> None:
    db = g.db
    texts, _media = inputs(g, node)
    instruction = _prompt(g, node) or "Improve this text."
    model = db.get(AIModel, node.model_id) if node.model_id else None
    if model and (model.capability != "text" or model.workspace_id != node.workspace_id):
        model = None
    provider_id = model.provider_id if model else node.provider_id
    kit = g.kit
    system = LLM_SYSTEM + ("\n" + kit.llm_profile() if kit else "")
    user = instruction + ("\n\nInput:\n%s" % "\n\n".join(texts) if texts else "")
    count, total = variations(node), 0.0
    for index in range(count):
        ask = user if count == 1 else "%s\n\n(Version %d of %d — make it clearly different from the others.)" % (
            user, index + 1, count)
        text, usage = ai_service.generate_text_with_usage(
            db, node.workspace_id, system, ask, model_id=model.id if model else None, provider_id=provider_id,
            purpose="Production: %s" % node.name, user_id=g.board.user_id)
        total += float(getattr(usage, "cost", 0) or 0)
        add_output(g, node, text=clean_text(text), cost=float(getattr(usage, "cost", 0) or 0),
                   select_it=index == 0, model_label=getattr(usage, "model", None) or None)
    node.cost = round(total, 6)
    _done_with(g, node, record=False)


def _start_job(g: BoardGraph, node: Node, kind: str, prompt: str, media_inputs: list[Media] | None = None,
               **kwargs) -> None:
    if not (prompt or "").strip():
        raise AppError(_("Write a prompt or link a text block."), code="no_prompt")
    db = g.db
    count = variations(node)
    node.run_expected, node.run_job_ids = count, []
    kit = g.kit
    if kind == "audio" and kit and kit.voice and kwargs.get("audio_mode", "speech") == "speech":
        kwargs["voice"] = kit.voice
    model = db.get(AIModel, node.model_id) if node.model_id else None
    model_id = model.id if model and model.capability == kind and model.workspace_id == node.workspace_id else None
    db.flush()
    partial_error = None
    for _index in range(count):
        try:
            job = ai_media.start_job(
                db, node.workspace_id, kind, prompt, provider_id=node.provider_id, model_id=model_id,
                aspect=node.aspect or "1:1", style=node.style, seconds=node.seconds or 8,
                inputs=[m.id for m in media_inputs or []], callback=CALLBACK,
                callback_context={"node_id": node.id, "run_no": node.run_no}, user_id=g.board.user_id, **kwargs)
        except (AppError, ApiError) as exc:
            if not node.run_job_ids:
                raise
            partial_error = exc.detail if isinstance(exc, AppError) else exc.message
            node.run_expected = len(node.run_job_ids)
            break
        node.run_job_ids = [*(node.run_job_ids or []), job.id]
        if job.state != "running":
            record_job(g, node, job)
    check_run_complete(g, node)
    if partial_error and node.state == "done":
        node.notice = _("{ok} of {total} versions were created: {error}", ok=len(node.run_job_ids), total=count,
                        error=partial_error)


def record_job(g: BoardGraph, node: Node, job: MediaJob, run_no: int | None = None) -> None:
    if job.state != "done" or not job.media_id:
        return
    exists = g.db.scalar(select(Output.id).where(Output.node_id == node.id, Output.job_id == job.id))
    media = g.media(job.media_id)
    if not exists and media:
        add_output(g, node, media, cost=float(job.cost or 0), job=job, select_it=False,
                   model_label=job.model_name, run_no=run_no)


def check_run_complete(g: BoardGraph, node: Node) -> bool:
    """When every media job of the current run has finished, pick the first result. True when finished."""
    db = g.db
    ids = list(node.run_job_ids or [])
    jobs = db.scalars(select(MediaJob).where(MediaJob.id.in_(ids)).order_by(MediaJob.id)).all() if ids else []
    if len(jobs) < (node.run_expected or 0) or any(j.state == "running" for j in jobs):
        node.state = "running"
        return False
    outputs = db.scalars(select(Output).where(Output.node_id == node.id, Output.run_no == node.run_no)
                         .order_by(Output.id)).all()
    notice = next((j.notice for j in jobs if j.notice), None)
    if outputs:
        failed = [j for j in jobs if j.state == "failed"]
        if failed:
            notice = _("{ok} of {total} versions were created: {error}", ok=len(outputs), total=len(jobs),
                       error=failed[0].error or "")
        select_output(g, node, outputs[0])
        node.state, node.progress, node.error, node.notice = "done", 100, None, notice
        node.cost = round(sum(float(j.cost or 0) for j in jobs), 6)
        node.done_hash = node.run_hash
    else:
        _fail(node, (jobs[0].error if jobs else None) or _("Nothing was created."))
    return True


def on_media_job(db: Session, job: MediaJob) -> None:
    """Callback of the AI media jobs: record the result, then continue the board."""
    context = job.callback_context or {}
    node = db.get(Node, context.get("node_id") or 0)
    if not node or node.workspace_id != job.workspace_id:
        return
    board = db.get(Board, node.board_id)
    if node.id not in _EXECUTING.get():
        use_workspace_locale(db, board)
    g = BoardGraph(db, board)
    if context.get("run_no") != node.run_no or job.id not in (node.run_job_ids or []):
        record_job(g, node, job, run_no=context.get("run_no"))  # an older run: keep it in the history only
        db.flush()
        return
    record_job(g, node, job)
    finished = node.state == "running" and check_run_complete(g, node)
    db.flush()
    if finished and node.id not in _EXECUTING.get():
        step(db, board, budget=10)


def _run_image(g: BoardGraph, node: Node) -> None:
    texts, media = inputs(g, node)
    refs = [m for m in media if media_kind(m) == "image"]
    _start_job(g, node, "image", _with_brand(g, _prompt_with_inputs(g, node, texts)), refs)


def _run_video(g: BoardGraph, node: Node) -> None:
    texts, media = inputs(g, node)
    images = [m for m in media if media_kind(m) == "image"][:1]
    prompt = _prompt_with_inputs(g, node, texts)
    if not prompt.strip() and images:
        prompt = "Bring this image to life with subtle natural motion."
    _start_job(g, node, "video", _with_brand(g, prompt), images)


def _run_audio(g: BoardGraph, node: Node) -> None:
    texts, _media = inputs(g, node)
    if (node.audio_mode or "speech") == "speech":
        # the linked text is the script; the block's own prompt is used when nothing is linked
        _start_job(g, node, "audio", "\n\n".join(texts) or _prompt(g, node), audio_mode="speech")
    else:
        _start_job(g, node, "audio", _prompt_with_inputs(g, node, texts), audio_mode=node.audio_mode)


def _run_merge(g: BoardGraph, node: Node) -> None:
    _texts, media = inputs(g, node)
    visual = ([m for m in media if media_kind(m) == "video"] or [m for m in media if media_kind(m) == "image"])[:1]
    audios = [m for m in media if media_kind(m) == "audio"]
    if not visual or not audios:
        raise AppError(_("Link a video (or an image) and an audio block."), code="merge_inputs")
    content = media_tools.merge((read_media(visual[0]), visual[0].mimetype),
                                [(read_media(a), a.mimetype) for a in audios], aspect=node.aspect)
    _done_with(g, node, _store(g, node, content, "video/mp4", "mp4"))


def _run_design(g: BoardGraph, node: Node) -> None:
    media = g.media(node.output_media_id)
    if not media:
        raise AppError(_("Open the design editor and save your design."), code="no_design")
    _done_with(g, node, media)


def upstream_formats(g: BoardGraph, node: Node) -> dict[str, Media]:
    """Per-format results of the Formats / Template blocks feeding this block: ``{aspect: media}``."""
    sets: dict[str, Media] = {}
    for up in g.upstream(node):
        if up.kind == "approval":
            for aspect, media in upstream_formats(g, up).items():
                sets.setdefault(aspect, media)
        elif up.kind in ("reframe", "template") and up.output_media_id:
            current = g.db.scalars(select(Output).where(Output.node_id == up.id,
                                                        Output.media_id == up.output_media_id)
                                   .order_by(Output.id.desc()).limit(1)).first()
            if not current:
                continue
            for out in g.db.scalars(select(Output).where(Output.node_id == up.id, Output.run_no == current.run_no,
                                                         Output.aspect.is_not(None)).order_by(Output.id)):
                media = g.media(out.media_id)
                if media:
                    sets.setdefault(out.aspect, media)
    return sets


POST_STATE_LABELS = {"draft": "Draft", "to_approve": "Waiting for approval", "scheduled": "Scheduled",
                     "publishing": "Publishing", "posted": "Published", "partial": "Partly published",
                     "failed": "Failed"}


def _post_accounts(g: BoardGraph, node: Node, linked: Post | None) -> list[SocialAccount]:
    ids = list(node.account_ids or [])
    if not ids and linked:
        ids = [a.id for a in linked.accounts]
    if not ids:
        return []
    return list(g.db.scalars(select(SocialAccount).where(SocialAccount.id.in_(ids),
                                                         SocialAccount.workspace_id == node.workspace_id)
                             .order_by(SocialAccount.id)))


def _run_post(g: BoardGraph, node: Node) -> None:
    db, board = g.db, g.board
    texts, media = inputs(g, node)
    kinds = {media_kind(m) for m in media}
    if "video" in kinds:  # a post holds one video, or images
        media = [m for m in media if media_kind(m) == "video"][:1]
    elif "image" in kinds:
        media = [m for m in media if media_kind(m) == "image"]
    linked = None
    for post_id in (node.post_id, board.post_id):
        post = db.get(Post, post_id) if post_id else None
        if post and post.workspace_id == node.workspace_id:
            linked = post
            break
    accounts = _post_accounts(g, node, linked)
    mode = node.publish_mode or "draft"
    if mode != "draft" and not accounts:
        raise AppError(_("Choose the accounts to publish on in this Post block."), code="no_accounts")
    if mode == "at" and not node.publish_at:
        raise AppError(_("Choose the publishing date in this Post block."), code="no_date")
    formats = upstream_formats(g, node)
    per_network: dict[str, list[int]] = {}
    if formats:
        is_video = any(media_kind(m) == "video" for m in formats.values())
        for account in accounts:
            prefs = (NETWORK_VIDEO_FORMATS if is_video else NETWORK_FORMATS).get(account.platform, ("1:1",))
            choice = next((formats[a] for a in prefs if a in formats), None)
            if choice:
                per_network[account.platform] = [choice.id]
    content = "\n\n".join(texts)
    if linked and linked.state in ("draft", "failed"):
        post = linked  # the board was opened from this post (or ran before): update the same draft
        post.content = content
        post.platform_media = per_network or None
        post.accounts = accounts or list(post.accounts)
        post.media_links = [PostMedia(media_id=m.id, position=index, role="feed") for index, m in enumerate(media)]
        db.flush()
    else:
        post = social.create_post(db, node.workspace_id, board.user_id, content=content,
                                  media_ids=[m.id for m in media], account_ids=[a.id for a in accounts],
                                  platform_media=per_network or None, name=board.name,
                                  source_ref="board:%d" % board.id)
    node.post_id = post.id
    if not board.post_id:
        board.post_id = post.id
    notice = None
    if mode == "now":
        post = social.submit(db, post, board.user_id, action="publish") or post
        notice = _("Published: {state}", state=_(POST_STATE_LABELS.get(post.state, post.state)))
    elif mode in ("best", "at"):
        if mode == "best":
            post = social.submit(db, post, board.user_id, action="best_time") or post
        else:
            post = social.submit(db, post, board.user_id, action="schedule", when=node.publish_at) or post
        if post.state == "to_approve":
            notice = _("Sent for approval before publishing.")
        else:
            when = post.scheduled_at or node.publish_at
            notice = _("Scheduled for {when}", when=when.strftime("%Y-%m-%d %H:%M") if when else "")
    node.notice = notice
    _done_with(g, node, text=post.name or board.name, record=False)


def _run_reframe(g: BoardGraph, node: Node) -> None:
    _texts, media = inputs(g, node)
    source = next((m for m in media if media_kind(m) in ("image", "video")), None)
    if not source:
        raise AppError(_("Link an image or a video."), code="reframe_input")
    aspects = [a.strip() for a in (node.formats or "").split(",") if a.strip() in media_tools.SIZES]
    aspects = list(dict.fromkeys(aspects)) or ["9:16", "1:1"]
    content = read_media(source)
    is_video = media_kind(source) == "video"
    first = None
    for aspect in aspects:
        if is_video:
            result, mime, ext = media_tools.reframe_video(content, source.mimetype, aspect, node.fit_mode), \
                "video/mp4", "mp4"
        else:
            result, mime, ext = media_tools.reframe_image(content, aspect, node.fit_mode), "image/png", "png"
        stored = _store(g, node, result, mime, ext, suffix=aspect.replace(":", "x"))
        output = add_output(g, node, stored, aspect=aspect, select_it=False)
        first = first or output
    select_output(g, node, first)
    _done_with(g, node, record=False)


def _run_captions(g: BoardGraph, node: Node) -> None:
    _texts, media = inputs(g, node)
    video = next((m for m in media if media_kind(m) == "video"), None)
    speech = next((m for m in media if media_kind(m) == "audio"), None)
    if not video:
        raise AppError(_("Link a video."), code="captions_input")
    if not media_tools.subtitles_available():  # check before paying for speech-to-text
        raise media_tools.MediaToolError(_("This server's ffmpeg cannot draw subtitles (it needs libass)."),
                                         code="no_libass")
    video_bytes = read_media(video)
    audio = speech or _store(g, node, media_tools.extract_audio(video_bytes, video.mimetype), "audio/mpeg", "mp3",
                             suffix="speech")
    result = ai_media.transcribe(g.db, node.workspace_id, audio.id, (node.caption_language or "").strip() or None)
    segments = (result or {}).get("segments") or []
    if not segments:
        raise AppError(_("No speech was found in this video."), code="no_speech")
    srt = media_tools.to_srt(segments)
    content = media_tools.burn_subtitles(video_bytes, video.mimetype, srt, node.caption_position, node.caption_size)
    cost = round(float((result or {}).get("cost") or 0), 6)
    node.cost = cost
    _done_with(g, node, _store(g, node, content, "video/mp4", "mp4"), text=srt, cost=cost)


def approver_id(g: BoardGraph, node: Node) -> int | None:
    return node.approver_id or g.board.user_id


def _run_approval(g: BoardGraph, node: Node) -> None:
    texts, media = inputs(g, node)
    if not texts and not media:
        raise AppError(_("Link the content to review."), code="approval_input")
    if node.approval_state == "approved" and node.approved_hash == node.run_hash:
        node.notice = node.notice
        _done_with(g, node, record=False)
        return
    node.state, node.approval_state, node.approval_comment, node.progress = "waiting", "pending", None, 0
    for down in g.descendants(node):
        if down.state == "queued":
            down.state = "idle"
            down.notice = _("Waiting for approval of “{name}”.", name=node.name)
    reviewer = approver_id(g, node)
    if reviewer:
        notify(g.db, node.workspace_id, [reviewer], kind="production.approval",
               title=_("Approve “{name}”", name=node.name),
               body=_("Review the content of the production board “{board}” before it is published.",
                      board=g.board.name),
               link="/production/%d?node=%d" % (g.board.id, node.id))


def _run_template(g: BoardGraph, node: Node) -> None:
    ref = (node.template_ref or "").strip()
    kind, _sep, value = ref.partition(":")
    if kind not in ("template", "set") or not value.isdigit():
        raise AppError(_("Choose a brand template in this block."), code="no_template")
    texts, media = inputs(g, node)
    photo = next((m for m in media if media_kind(m) == "image"), None)
    if not photo:
        raise AppError(_("Link a photo."), code="template_input")
    text = "\n".join(t for t in texts if t) or (node.text_value or "").strip() or None
    text = apply_vars(g.board, text) if text else None
    results: list[tuple[Media, str | None]] = []
    if kind == "set":
        for story in (False, True):
            framed = frame.compose_for_post(g.db, node.workspace_id, ref, photo.id, text=text, story=story)
            if framed and framed.id not in [m.id for m, _a in results]:
                results.append((framed, media_tools.aspect_of(framed.width, framed.height) or
                                ("9:16" if story else None)))
    else:
        framed = frame.compose(g.db, node.workspace_id, int(value), photo.id, text=text)
        results.append((framed, media_tools.aspect_of(framed.width, framed.height)))
    first = None
    for framed, aspect in results:
        g._media[framed.id] = framed
        output = add_output(g, node, framed, aspect=aspect, select_it=False)
        first = first or output
    if not first:
        raise AppError(_("Nothing was created."), code="nothing")
    select_output(g, node, first)
    _done_with(g, node, record=False)


RUNNERS = {
    "text": _run_text, "upload": _run_upload, "llm": _run_llm, "image": _run_image, "video": _run_video,
    "audio": _run_audio, "merge": _run_merge, "design": _run_design, "post": _run_post, "reframe": _run_reframe,
    "captions": _run_captions, "approval": _run_approval, "template": _run_template,
}


# ---------------------------------------------------------------------------- approvals
def can_approve(db: Session, g: BoardGraph, node: Node, user_id: int, role: Role) -> bool:
    if ROLE_RANK[role] >= ROLE_RANK[Role.admin]:
        return True
    return user_id == approver_id(g, node)


def approve(db: Session, board: Board, node: Node, user_id: int, user_name: str, role: Role,
            comment: str | None = None) -> None:
    g = BoardGraph(db, board)
    if not can_approve(db, g, node, user_id, role):
        raise Forbidden(_("Only the chosen approver or an admin can approve this."), code="not_approver")
    node.approval_state = "approved"
    node.approved_hash = node.run_hash or input_hash(g, node)
    node.approval_comment = comment or None
    node.notice = _("Approved by {name}", name=user_name)
    node.error = None
    run(db, board, [node.id], downstream=True)


def reject(db: Session, board: Board, node: Node, user_id: int, user_name: str, role: Role,
           comment: str | None = None) -> None:
    g = BoardGraph(db, board)
    if not can_approve(db, g, node, user_id, role):
        raise Forbidden(_("Only the chosen approver or an admin can approve this."), code="not_approver")
    node.approval_state, node.state, node.approval_comment = "rejected", "failed", comment or None
    node.error = _("Rejected by {user}: {comment}", user=user_name, comment=comment or _("no comment"))
    db.flush()


def check_member(db: Session, workspace_id: int, user_id: int | None) -> None:
    if user_id and not db.scalar(select(Membership.id).where(Membership.workspace_id == workspace_id,
                                                             Membership.user_id == user_id)):
        raise NotFound(_("This person is not a member of the workspace."), code="not_member")


# ---------------------------------------------------------------------------- housekeeping
def purge_archived(db: Session, older_than: timedelta = timedelta(days=1)) -> int:
    """Blocks and links deleted more than a day ago cannot be undone any more."""
    limit = datetime.now(timezone.utc) - older_than
    edges = db.execute(delete(Edge).where(Edge.active.is_(False), Edge.archived_at < limit)).rowcount or 0
    nodes = db.execute(delete(Node).where(Node.active.is_(False), Node.archived_at < limit)).rowcount or 0
    return edges + nodes


def busy_board_ids(db: Session) -> list[int]:
    return list(db.scalars(select(Node.board_id).where(Node.active.is_(True), Node.state.in_(("queued", "running")))
                           .distinct()))


def default_name(kind: str) -> str:
    return kind_label(kind)
