"""/api/analytics — Performance dashboard, manual refresh and the AI strategy report."""
from fastapi import APIRouter, Depends

from app.core.deps import Ctx, workspace_ctx
from app.core.errors import NotFound
from app.core.i18n import _
from app.modules.workspaces.models import Role

from . import analytics
from .models import PUBLISH_PLATFORMS, SocialAccount
from .schemas import AIReportIn, AIReportOut, DashboardOut, SyncResult

router = APIRouter(prefix="/analytics", tags=["performance"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(days: int = 30, platform: str | None = None, account_id: int | None = None,
              ctx: Ctx = Depends(workspace_ctx())):
    if platform and platform not in PUBLISH_PLATFORMS:
        platform = None
    if account_id:
        account = ctx.db.get(SocialAccount, account_id)
        if not account or account.workspace_id != ctx.workspace.id:
            raise NotFound(_("Account not found."))
    return analytics.dashboard(ctx.db, ctx.workspace.id, days, platform, account_id)


@router.post("/refresh", response_model=SyncResult)
def refresh(platform: str | None = None, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Pull fresh statistics and follower counts now."""
    return analytics.refresh(ctx.db, ctx.workspace.id, platform if platform in PUBLISH_PLATFORMS else None)


@router.post("/ai-report", response_model=AIReportOut)
def ai_report(body: AIReportIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    return analytics.ai_report(ctx.db, ctx.workspace.id, body.days, body.platform, user_id=ctx.user.id)
