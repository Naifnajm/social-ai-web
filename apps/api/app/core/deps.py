"""Request dependencies: the signed-in user and the active workspace with the user's role.

Typical endpoint::

    @router.get("/posts")
    def list_posts(ctx: Ctx = Depends(workspace_ctx())):          # any member
        return ctx.db.scalars(select(Post).where(Post.workspace_id == ctx.workspace.id)).all()

    @router.post("/accounts")
    def add_account(..., ctx: Ctx = Depends(workspace_ctx(Role.admin))):  # admins and owners only
"""
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.workspaces.models import ROLE_RANK, Membership, Role, Workspace

from .db import get_db
from .errors import AppError, Forbidden
from .i18n import _, set_locale
from .security import decode_token

ACCESS_COOKIE = "sai_access"
REFRESH_COOKIE = "sai_refresh"


class Unauthorized(AppError):
    status_code = 401


@dataclass
class Ctx:
    db: Session
    user: User
    workspace: Workspace
    role: Role

    def can(self, role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]

    def require(self, role: Role) -> None:
        if not self.can(role):
            raise Forbidden(_("You don't have the rights to do this."), code="forbidden")


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(ACCESS_COOKIE)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token_from(request)
    payload = decode_token(token, "access") if token else None
    if not payload:
        raise Unauthorized(_("Please sign in."), code="unauthenticated")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or user.token_version != payload.get("ver"):
        raise Unauthorized(_("Your session has expired. Please sign in again."), code="unauthenticated")
    set_locale(user.locale)
    return user


def workspace_ctx(min_role: Role = Role.viewer):
    """Dependency factory: resolves the workspace from the ``X-Workspace`` header (id) or the user's last one."""

    def dependency(user: User = Depends(current_user), db: Session = Depends(get_db),
                   x_workspace: str | None = Header(default=None)) -> Ctx:
        wanted = int(x_workspace) if x_workspace and x_workspace.isdigit() else user.last_workspace_id
        query = select(Membership).where(Membership.user_id == user.id)
        membership = None
        if wanted:
            membership = db.scalar(query.where(Membership.workspace_id == wanted))
        if not membership:
            membership = db.scalar(query.order_by(Membership.id))
        if not membership:
            raise Forbidden(_("You are not a member of any workspace."), code="no_workspace")
        workspace = membership.workspace
        if workspace.status != "active" and not user.is_superadmin:
            raise Forbidden(_("This workspace is suspended."), code="workspace_suspended")
        if user.last_workspace_id != workspace.id:
            user.last_workspace_id = workspace.id
        ctx = Ctx(db=db, user=user, workspace=workspace, role=Role(membership.role))
        ctx.require(min_role)
        return ctx

    return dependency


def superadmin(user: User = Depends(current_user)) -> User:
    if not user.is_superadmin:
        raise Forbidden(_("Platform administrators only."), code="forbidden")
    return user
