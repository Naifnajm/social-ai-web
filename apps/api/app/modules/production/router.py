"""Production API: boards, blocks, links, groups, variables, runs, approvals and the design editor.

Reading needs any role; editing and running need an editor; approving needs the chosen approver or an admin.
While a run is busy the canvas polls ``GET /production/boards/{id}?light=true``.
"""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.deps import Ctx, workspace_ctx
from app.core.errors import NotFound
from app.core.i18n import _
from app.modules.brand.models import BrandKit
from app.modules.workspaces.models import Role

from . import engine, service
from .catalog import kinds_payload, templates
from .engine import BoardGraph
from .models import Board
from .schemas import (
    ApprovalIn,
    BatchBoard,
    BatchIn,
    BoardCard,
    BoardCreate,
    BoardUpdate,
    ConnectIn,
    ConnectOut,
    DesignIn,
    EdgeOut,
    FromMediaIn,
    FromPostIn,
    GraphOut,
    GroupIn,
    GroupOut,
    GroupUpdate,
    ItemsIn,
    ItemsOut,
    KindOut,
    NodeCreate,
    NodeOut,
    NodeParams,
    PasteIn,
    PasteOut,
    PickerGroup,
    PositionsIn,
    RunEstimate,
    RunIn,
    SelectOutputIn,
    StudioOut,
    TemplateOut,
    UploadIn,
    VariablesIn,
)

router = APIRouter(prefix="/production", tags=["production"])
viewer = workspace_ctx()
editor = workspace_ctx(Role.editor)


def _graph(ctx: Ctx, board: Board, light: bool = False) -> dict:
    return service.graph(ctx.db, ctx.workspace, board, user_id=ctx.user.id, role=ctx.role, light=light)


def _node_out(ctx: Ctx, board: Board, node) -> dict:
    return service.node_dict(BoardGraph(ctx.db, board), node, user_id=ctx.user.id, role=ctx.role)


def _start(db: Session, board_ids: list[int]) -> None:
    """Commit what the request queued, then advance the boards in the background."""
    db.commit()
    for board_id in board_ids:
        engine.schedule(board_id)
    db.expire_all()


def _board_of(ctx: Ctx, node) -> Board:
    return service.get_board(ctx.db, ctx.workspace.id, node.board_id)


# ---------------------------------------------------------------------------- catalog
@router.get("/templates", response_model=list[TemplateOut])
def list_templates(ctx: Ctx = Depends(viewer)):
    return [{"key": key, "name": t["name"], "icon": t["icon"], "description": t["description"],
             "blocks": len(t["nodes"])} for key, t in templates().items()]


@router.get("/kinds", response_model=list[KindOut])
def list_kinds(ctx: Ctx = Depends(viewer)):
    return kinds_payload()


@router.get("/pickers", response_model=dict[str, list[PickerGroup]])
def list_pickers(ctx: Ctx = Depends(viewer)):
    """Models per capability grouped by provider (same shape as the AI feature's pickers)."""
    return service.pickers(ctx.db, ctx.workspace.id)


# ---------------------------------------------------------------------------- boards
@router.get("/boards", response_model=list[BoardCard])
def list_boards(ctx: Ctx = Depends(viewer)):
    return service.board_cards(ctx.db, ctx.workspace.id)


@router.post("/boards", response_model=BoardCard, status_code=201)
def create_board(data: BoardCreate, ctx: Ctx = Depends(editor)):
    board = service.create_board(ctx.db, ctx.workspace.id, ctx.user.id, data.template, data.name)
    return next(c for c in service.board_cards(ctx.db, ctx.workspace.id) if c["id"] == board.id)


@router.post("/boards/from-post", response_model=BoardCard, status_code=201)
def board_from_post(data: FromPostIn, ctx: Ctx = Depends(editor)):
    board = service.from_post(ctx.db, ctx.workspace.id, ctx.user.id, data.post_id)
    return next(c for c in service.board_cards(ctx.db, ctx.workspace.id) if c["id"] == board.id)


@router.post("/boards/from-media", response_model=BoardCard, status_code=201)
def board_from_media(data: FromMediaIn, ctx: Ctx = Depends(editor)):
    board = service.from_media(ctx.db, ctx.workspace.id, ctx.user.id, data.media_id, data.text)
    return next(c for c in service.board_cards(ctx.db, ctx.workspace.id) if c["id"] == board.id)


@router.get("/boards/{board_id}", response_model=GraphOut, response_model_exclude_none=False)
def get_graph(board_id: int, light: bool = False, ctx: Ctx = Depends(viewer)):
    return _graph(ctx, service.get_board(ctx.db, ctx.workspace.id, board_id), light)


@router.patch("/boards/{board_id}", response_model=GraphOut)
def update_board(board_id: int, data: BoardUpdate, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    values = data.model_dump(exclude_unset=True)
    if "brand_kit_id" in values:
        kit_id = values.pop("brand_kit_id") or None
        if kit_id:
            kit = ctx.db.get(BrandKit, kit_id)
            if not kit or kit.workspace_id != ctx.workspace.id:
                raise NotFound(_("Brand kit not found."), code="kit_not_found")
        board.brand_kit_id = kit_id
    for key, value in values.items():
        if value is not None:
            setattr(board, key, value.strip() if isinstance(value, str) and key == "name" else value)
    ctx.db.flush()
    return _graph(ctx, board)


@router.put("/boards/{board_id}/view", status_code=204)
def save_view(board_id: int, data: BoardUpdate, ctx: Ctx = Depends(editor)):
    """Zoom and pan of the canvas (saved quietly, no graph returned)."""
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    for key in ("zoom", "pan_x", "pan_y"):
        value = getattr(data, key)
        if value is not None:
            setattr(board, key, value)
    return Response(status_code=204)


@router.delete("/boards/{board_id}", status_code=204)
def delete_board(board_id: int, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    ctx.db.delete(board)
    return Response(status_code=204)


@router.post("/boards/{board_id}/duplicate", response_model=BoardCard, status_code=201)
def duplicate_board(board_id: int, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    copy = service.duplicate_board(ctx.db, board, _("{name} (copy)", name=board.name), ctx.user.id)
    return next(c for c in service.board_cards(ctx.db, ctx.workspace.id) if c["id"] == copy.id)


# ---------------------------------------------------------------------------- blocks
@router.post("/boards/{board_id}/nodes", response_model=NodeOut, status_code=201)
def add_node(board_id: int, data: NodeCreate, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    values = data.model_dump(exclude_unset=True, exclude={"kind", "x", "y"})
    node = service.create_node(ctx.db, board, data.kind, data.x, data.y, **values)
    return _node_out(ctx, board, node)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
def update_node(node_id: int, data: NodeParams, ctx: Ctx = Depends(editor)):
    node = service.get_node(ctx.db, ctx.workspace.id, node_id)
    board = _board_of(ctx, node)
    service.update_node(ctx.db, board, node, data.model_dump(exclude_unset=True))
    return _node_out(ctx, board, node)


@router.post("/boards/{board_id}/positions", status_code=204)
def save_positions(board_id: int, data: PositionsIn, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    g = BoardGraph(ctx.db, board)
    for node_id, (x, y) in data.positions.items():
        if node_id in g.nodes:
            g.nodes[node_id].x, g.nodes[node_id].y = float(x), float(y)
    return Response(status_code=204)


@router.post("/nodes/{node_id}/upload", response_model=NodeOut)
def set_upload(node_id: int, data: UploadIn, ctx: Ctx = Depends(editor)):
    node = service.get_node(ctx.db, ctx.workspace.id, node_id)
    board = _board_of(ctx, node)
    service.set_upload(ctx.db, board, node, service.get_media(ctx.db, ctx.workspace.id, data.media_id))
    return _node_out(ctx, board, node)


@router.post("/nodes/{node_id}/select-output", response_model=NodeOut)
def select_output(node_id: int, data: SelectOutputIn, ctx: Ctx = Depends(editor)):
    node = service.get_node(ctx.db, ctx.workspace.id, node_id)
    board = _board_of(ctx, node)
    service.select_output(ctx.db, board, node, data.output_id)
    return _node_out(ctx, board, node)


@router.post("/nodes/{node_id}/design", response_model=NodeOut)
def save_design(node_id: int, data: DesignIn, ctx: Ctx = Depends(editor)):
    node = service.get_node(ctx.db, ctx.workspace.id, node_id)
    board = _board_of(ctx, node)
    service.save_design(ctx.db, board, node, data.png, data.layers, ctx.user.id)
    return _node_out(ctx, board, node)


@router.post("/nodes/{node_id}/send-to-studio", response_model=StudioOut)
def send_to_studio(node_id: int, ctx: Ctx = Depends(editor)):
    node = service.get_node(ctx.db, ctx.workspace.id, node_id)
    return {"post_id": service.send_to_studio(ctx.db, _board_of(ctx, node), node, ctx.user.id)}


@router.post("/nodes/{node_id}/approve", response_model=GraphOut)
def approve(node_id: int, data: ApprovalIn, ctx: Ctx = Depends(viewer)):
    node = service.get_node(ctx.db, ctx.workspace.id, node_id)
    board = _board_of(ctx, node)
    engine.approve(ctx.db, board, node, ctx.user.id, ctx.user.name, ctx.role, data.comment)
    _start(ctx.db, [board.id])
    return _graph(ctx, board)


@router.post("/nodes/{node_id}/reject", response_model=GraphOut)
def reject(node_id: int, data: ApprovalIn, ctx: Ctx = Depends(viewer)):
    node = service.get_node(ctx.db, ctx.workspace.id, node_id)
    board = _board_of(ctx, node)
    engine.reject(ctx.db, board, node, ctx.user.id, ctx.user.name, ctx.role, data.comment)
    return _graph(ctx, board)


# ---------------------------------------------------------------------------- links, undo, paste, groups
@router.post("/boards/{board_id}/edges", response_model=ConnectOut, status_code=201)
def connect(board_id: int, data: ConnectIn, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    return service.connect(ctx.db, board, data.source_id, data.target_id, data.port)


@router.post("/boards/{board_id}/archive", response_model=ItemsOut)
def archive_items(board_id: int, data: ItemsIn, ctx: Ctx = Depends(editor)):
    """Delete blocks / links (undoable with /restore for a day)."""
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    return service.archive_items(ctx.db, board, data.node_ids, data.edge_ids)


@router.post("/boards/{board_id}/restore", response_model=GraphOut)
def restore_items(board_id: int, data: ItemsIn, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    service.restore_items(ctx.db, board, data.node_ids, data.edge_ids)
    return _graph(ctx, board)


@router.post("/boards/{board_id}/paste", response_model=PasteOut)
def paste(board_id: int, data: PasteIn, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    nodes, edges = service.paste_nodes(ctx.db, board, data.node_ids, data.dx, data.dy)
    g = BoardGraph(ctx.db, board)
    return {"nodes": [service.node_dict(g, n, user_id=ctx.user.id, role=ctx.role) for n in nodes],
            "edges": [service.edge_dict(g, e) for e in edges]}


@router.post("/boards/{board_id}/groups", response_model=GroupOut, status_code=201)
def create_group(board_id: int, data: GroupIn, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    return service.group_dict(ctx.db, service.group_nodes(ctx.db, board, data.node_ids, data.name))


@router.patch("/groups/{group_id}", response_model=GroupOut)
def update_group(group_id: int, data: GroupUpdate, ctx: Ctx = Depends(editor)):
    group = service.get_group(ctx.db, ctx.workspace.id, group_id)
    if data.name is not None:
        group.name = data.name.strip()
    if data.color is not None:
        group.color = data.color
    if data.node_ids is not None:
        board = service.get_board(ctx.db, ctx.workspace.id, group.board_id)
        g = BoardGraph(ctx.db, board)
        for node in g.nodes.values():
            if node.id in data.node_ids:
                node.group_id = group.id
            elif node.group_id == group.id:
                node.group_id = None
    ctx.db.flush()
    return service.group_dict(ctx.db, group)


@router.delete("/groups/{group_id}", response_model=list[int])
def ungroup(group_id: int, ctx: Ctx = Depends(editor)):
    """Remove the group frame (the blocks stay). Returns the ids of the blocks that were in it."""
    return service.ungroup(ctx.db, service.get_group(ctx.db, ctx.workspace.id, group_id))


# ---------------------------------------------------------------------------- variables, runs
@router.put("/boards/{board_id}/variables", response_model=GraphOut)
def set_variables(board_id: int, data: VariablesIn, ctx: Ctx = Depends(editor)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    service.set_variables(ctx.db, board, [v.model_dump() for v in data.variables])
    return _graph(ctx, board)


@router.post("/boards/{board_id}/batch", response_model=list[BatchBoard])
def run_batch(board_id: int, data: BatchIn, ctx: Ctx = Depends(editor)):
    """One copy of the board per row of variable values, each one run in the background."""
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    boards = service.run_batch(ctx.db, board, data.rows, ctx.user.id)
    result = [{"id": b.id, "name": b.name} for b in boards]
    _start(ctx.db, [b.id for b in boards])
    return result


@router.get("/boards/{board_id}/estimate", response_model=RunEstimate)
def estimate(board_id: int, node_ids: list[int] | None = Query(default=None), downstream: bool = True,
             force: bool = False, ctx: Ctx = Depends(viewer)):
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    return engine.estimate_run(BoardGraph(ctx.db, board), node_ids, downstream, force)


@router.post("/boards/{board_id}/run", response_model=GraphOut)
def run(board_id: int, data: RunIn, ctx: Ctx = Depends(editor)):
    """Run the board (or the given blocks and what depends on them). Unchanged blocks are reused for free
    unless ``force``; the canvas then polls the board until ``busy`` is false."""
    board = service.get_board(ctx.db, ctx.workspace.id, board_id)
    if data.node_ids:
        for node_id in data.node_ids:
            service.get_node(ctx.db, ctx.workspace.id, node_id)
    engine.run(ctx.db, board, data.node_ids, data.downstream, data.force)
    _start(ctx.db, [board.id])
    return _graph(ctx, board)
