from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import Ctx, current_user, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.core.mail import send_mail
from app.modules.auth.models import User

from .models import Invitation, Membership, Role, Workspace
from .service import accept_invitation, create_workspace, invite, owners_count
from .settings import get_settings_prefix, set_setting

router = APIRouter(tags=["workspaces"])


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    locale: str
    timezone: str
    currency: str
    logo_media_id: int | None = None
    plan_code: str
    status: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    locale: str | None = None
    timezone: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    logo_media_id: int | None = None


class CurrentOut(BaseModel):
    workspace: WorkspaceOut
    role: str


def _member_out(ctx: Ctx, m) -> "MemberOut":
    from app.modules.billing import limits
    return MemberOut(id=m.id, user_id=m.user_id, name=m.user.name, email=m.user.email, role=m.role,
                     avatar_url=m.user.avatar_url, ai_monthly_limit=m.ai_monthly_limit,
                     ai_spent_month=limits.ai_spend_month(ctx.db, ctx.workspace.id, m.user_id))


class MemberOut(BaseModel):
    id: int
    user_id: int
    name: str
    email: str
    role: str
    avatar_url: str | None = None
    ai_monthly_limit: float | None = None   # $ of platform-paid AI per month; None = no personal limit
    ai_spent_month: float = 0.0


class MemberUpdate(BaseModel):
    role: Role
    ai_monthly_limit: float | None = Field(default=None, ge=0, le=100000)   # sent explicitly as null to clear


class InviteIn(BaseModel):
    email: EmailStr
    role: Role = Role.editor


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None = None


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
def new_workspace(data: WorkspaceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return create_workspace(db, data.name.strip(), owner=user)


@router.get("/workspace", response_model=CurrentOut)
def current(ctx: Ctx = Depends(workspace_ctx())):
    return CurrentOut(workspace=WorkspaceOut.model_validate(ctx.workspace), role=ctx.role)


@router.patch("/workspace", response_model=WorkspaceOut)
def update_current(data: WorkspaceUpdate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(ctx.workspace, key, value)
    return ctx.workspace


@router.get("/workspace/members", response_model=list[MemberOut])
def members(ctx: Ctx = Depends(workspace_ctx())):
    rows = ctx.db.scalars(select(Membership).where(Membership.workspace_id == ctx.workspace.id)
                          .order_by(Membership.id)).all()
    return [_member_out(ctx, m) for m in rows]


def _membership(ctx: Ctx, member_id: int) -> Membership:
    membership = ctx.db.get(Membership, member_id)
    if not membership or membership.workspace_id != ctx.workspace.id:
        raise NotFound(_("Member not found."))
    return membership


@router.patch("/workspace/members/{member_id}", response_model=MemberOut)
def update_member(member_id: int, data: MemberUpdate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    membership = _membership(ctx, member_id)
    if Role.owner in (data.role, membership.role) and not ctx.can(Role.owner):
        raise AppError(_("Only an owner can change ownership."), code="forbidden", status_code=403)
    if membership.role == Role.owner and data.role != Role.owner and owners_count(ctx.db, ctx.workspace.id) <= 1:
        raise AppError(_("A workspace needs at least one owner."), code="last_owner")
    membership.role = data.role
    if "ai_monthly_limit" in data.model_fields_set:
        membership.ai_monthly_limit = data.ai_monthly_limit
    return _member_out(ctx, membership)


@router.delete("/workspace/members/{member_id}", status_code=204)
def remove_member(member_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    membership = _membership(ctx, member_id)
    if membership.role == Role.owner and owners_count(ctx.db, ctx.workspace.id) <= 1:
        raise AppError(_("A workspace needs at least one owner."), code="last_owner")
    ctx.db.delete(membership)


@router.get("/workspace/invitations", response_model=list[InvitationOut])
def invitations(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    return ctx.db.scalars(select(Invitation).where(Invitation.workspace_id == ctx.workspace.id,
                                                   Invitation.accepted_at.is_(None)).order_by(Invitation.id.desc())).all()


@router.post("/workspace/invitations", response_model=InvitationOut, status_code=201)
def create_invitation(data: InviteIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    invitation = invite(ctx.db, ctx.workspace, data.email, data.role, ctx.user)
    link = f"{settings.web_url.rstrip('/')}/{ctx.workspace.locale}/invite/{invitation.token}"
    send_mail(invitation.email, _("{name} invited you to {workspace}", name=ctx.user.name, workspace=ctx.workspace.name),
              f"<p>{_('{name} invited you to join {workspace} on {app}.', name=ctx.user.name, workspace=ctx.workspace.name, app=settings.app_name)}</p>"
              f'<p><a href="{link}">{_("Accept the invitation")}</a></p>', text=link)
    return invitation


@router.delete("/workspace/invitations/{invitation_id}", status_code=204)
def revoke_invitation(invitation_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    invitation = ctx.db.get(Invitation, invitation_id)
    if not invitation or invitation.workspace_id != ctx.workspace.id:
        raise NotFound(_("Invitation not found."))
    ctx.db.delete(invitation)


@router.post("/invitations/{token}/accept", response_model=CurrentOut)
def accept(token: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    membership = accept_invitation(db, token, user)
    workspace = db.get(Workspace, membership.workspace_id)
    return CurrentOut(workspace=WorkspaceOut.model_validate(workspace), role=membership.role)


@router.get("/workspace/settings")
def read_settings(prefix: str = "", ctx: Ctx = Depends(workspace_ctx())):
    return get_settings_prefix(ctx.db, ctx.workspace.id, prefix)


@router.put("/workspace/settings")
def write_settings(values: dict, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    for key, value in values.items():
        set_setting(ctx.db, ctx.workspace.id, key, value)
    return get_settings_prefix(ctx.db, ctx.workspace.id, "")
