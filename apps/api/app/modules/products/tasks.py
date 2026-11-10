"""Background job: announce a new product (the "auto announce" setting)."""
import logging

from app.core.jobs import session_scope
from app.modules.workspaces.models import Workspace

from . import service
from .models import Product

_logger = logging.getLogger(__name__)


def announce_product(product_id: int, user_id: int | None = None) -> int | None:
    with session_scope() as db:
        product = db.get(Product, product_id)
        if not product or not product.active or product.announced_post_id:
            return None
        workspace = db.get(Workspace, product.workspace_id)
        try:
            post = service.announce(db, workspace, product, user_id)
        except Exception:
            _logger.exception("announcing product %s failed", product_id)
            return None
        return post.id
