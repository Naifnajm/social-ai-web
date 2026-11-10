import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.i18n import _

from .models import Invitation, Membership, Role, Workspace

INVITATION_DAYS = 7
WORKSPACE_CREATED_HOOKS: list = []  # callables(db, workspace) — e.g. billing starts a trial, seeds defaults


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:50]
    return text or "workspace"


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug = base
    while db.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def create_workspace(db: Session, name: str, owner, locale: str | None = None) -> Workspace:
    workspace = Workspace(name=name, slug=unique_slug(db, name), locale=locale or owner.locale,
                          timezone=owner.timezone)
    db.add(workspace)
    db.flush()
    db.add(Membership(user_id=owner.id, workspace_id=workspace.id, role=Role.owner))
    owner.last_workspace_id = workspace.id
    db.flush()
    for hook in WORKSPACE_CREATED_HOOKS:
        hook(db, workspace)
    return workspace


def invite(db: Session, workspace: Workspace, email: str, role: str, invited_by) -> Invitation:
    if role == Role.owner:
        raise AppError(_("Ownership cannot be given by invitation."), code="bad_role")
    invitation = Invitation(workspace_id=workspace.id, email=email.lower(), role=role, token=secrets.token_urlsafe(24),
                            invited_by_id=invited_by.id,
                            expires_at=datetime.now(timezone.utc) + timedelta(days=INVITATION_DAYS))
    db.add(invitation)
    db.flush()
    return invitation


def accept_invitation(db: Session, token: str, user) -> Membership:
    invitation = db.scalar(select(Invitation).where(Invitation.token == token))
    if not invitation or invitation.accepted_at or invitation.expires_at < datetime.now(timezone.utc):
        raise AppError(_("This invitation is no longer valid."), code="bad_invitation")
    if invitation.email.lower() != user.email.lower():
        raise AppError(_("This invitation was sent to another e-mail address."), code="bad_invitation")
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id,
                                                    Membership.workspace_id == invitation.workspace_id))
    if not membership:
        membership = Membership(user_id=user.id, workspace_id=invitation.workspace_id, role=invitation.role)
        db.add(membership)
    invitation.accepted_at = datetime.now(timezone.utc)
    user.last_workspace_id = invitation.workspace_id
    db.flush()
    return membership


def owners_count(db: Session, workspace_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Membership).where(
        Membership.workspace_id == workspace_id, Membership.role == Role.owner)) or 0
