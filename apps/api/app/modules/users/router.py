"""Accounts: the person's account center (``/api/account``) and Platform admin › Users (``/api/admin/users``)."""
from fastapi import APIRouter

from .account import router as account_router
from .admin import router as admin_router

router = APIRouter()
router.include_router(account_router)
router.include_router(admin_router)
