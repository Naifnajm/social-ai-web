"""Publishing feature API: accounts, Studio composer, posts, approvals and performance."""
from fastapi import APIRouter

from .routes_accounts import router as accounts_router
from .routes_analytics import router as analytics_router
from .routes_posts import router as posts_router

router = APIRouter()
router.include_router(accounts_router)
router.include_router(posts_router)
router.include_router(analytics_router)
