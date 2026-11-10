"""Background work of Production: advance boards (safety net for runs and video callbacks) and purge
deleted blocks that can no longer be undone."""
import logging

from sqlalchemy import select

from app.core.jobs import periodic

from . import engine
from .engine import BoardGraph
from .models import Board, Node

_logger = logging.getLogger(__name__)


@periodic(seconds=20)
def step_boards() -> None:
    with engine._job_session() as db:
        engine.purge_archived(db)
        # running blocks whose media jobs all finished (a missed callback) are completed here
        for node in db.scalars(select(Node).where(Node.active.is_(True), Node.state == "running",
                                                  Node.kind.in_(("image", "video", "audio")))):
            if not node.run_job_ids:
                continue
            board = db.get(Board, node.board_id)
            try:
                engine.check_run_complete(BoardGraph(db, board), node)
            except Exception:  # pragma: no cover - keep the other boards going
                _logger.exception("production node %s could not be checked", node.id)
        db.commit()
        for board_id in engine.busy_board_ids(db):
            board = db.get(Board, board_id)
            engine.use_workspace_locale(db, board)
            try:
                engine.step(db, board, budget=3)
                db.commit()
            except Exception:  # pragma: no cover
                db.rollback()
                _logger.exception("production board %s failed to advance", board_id)
