"""Root-mounted endpoints of the connect feature: OAuth metadata and endpoints (``oauth.py``) and the MCP server."""
from fastapi import APIRouter

from . import oauth
from .mcp import mcp_app

router = APIRouter(include_in_schema=False)
router.include_router(oauth.router)
router.add_route("/mcp", mcp_app, methods=["GET", "POST", "DELETE"], include_in_schema=False)
