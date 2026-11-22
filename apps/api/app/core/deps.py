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
# while a platform administrator views the app as someone: the administrator's own refresh token, to come back
IMPERSONATION_RETURN_COOKIE = "sai_imp_return"

# While viewing as someone, an administrator cannot touch the person's credentials, account or connected access.
IMPERSONATION_BLOCKED = ("/api/auth/password", "/api/auth/email", "/api/auth/2fa", "/api/auth/logout-everywhere",
                         "/api/account/export", "/api/account/delete", "/api/account/workspaces", "/api/account/2fa",
                         "/api/account/avatar", "/api/connect/keys", "/api/connect/authorize", "/api/admin")
# Paths a person who must choose a new password can still use (the rest answers "password_change_required").
PASSWORD_CHANGE_ALLOWED = ("/api/auth/",)


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
    request.state.impersonator_id = None
    if payload.get("imp"):
        _impersonation(request, db, user, payload)
    elif user.must_change_password and not request.url.path.startswith(PASSWORD_CHANGE_ALLOWED):
        raise Forbidden(_("Choose a new password to continue."), code="password_change_required")
    set_locale(user.locale)
    return user


def _impersonation(request: Request, db: Session, user: User, payload: dict) -> None:
    """A platform administrator viewing the app as ``user``: check the administrator is still one, refuse what the
    view may not do, and record every change it makes under the administrator's name."""
    admin = db.get(User, int(payload["imp"]))
    if (not admin or not admin.is_active or not admin.is_superadmin or admin.token_version != payload.get("imp_ver")
            or user.is_superadmin):
        raise Unauthorized(_("Your session has expired. Please sign in again."), code="unauthenticated")
    request.state.impersonator_id = admin.id
    request.state.impersonation_expires = payload.get("exp")
    path = request.url.path
    if request.method == "DELETE" or path.startswith(IMPERSONATION_BLOCKED):
        raise Forbidden(_("This is not possible while you view the app as someone else."),
                        code="impersonation_forbidden")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        from app.modules.users.service import audit
        audit(db, user.id, "impersonation.action", actor_id=admin.id, impersonator_id=admin.id,
              summary=f"{request.method} {path}"[:500], request=request)


def impersonator_id(request: Request) -> int | None:
    """The platform administrator viewing the app as the signed-in user, if any (after ``current_user``)."""
    return getattr(request.state, "impersonator_id", None)


def not_impersonating(request: Request, user: User = Depends(current_user)) -> User:
    """The signed-in user, refused while an administrator views the app as them."""
    if impersonator_id(request):
        raise Forbidden(_("This is not possible while you view the app as someone else."),
                        code="impersonation_forbidden")
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


def superadmin(request: Request, user: User = Depends(current_user)) -> User:
    if not user.is_superadmin or impersonator_id(request):
        raise Forbidden(_("Platform administrators only."), code="forbidden")
    return user
