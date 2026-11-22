"""/api/connect — what the web app needs: the consent page (request details, the user's decision), connected apps
(list, disconnect) and personal API keys (create once-shown, list, revoke)."""
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.deps import Ctx, current_user, workspace_ctx
from app.core.errors import AppError, Forbidden, NotFound
from app.core.i18n import _
from app.modules.auth.models import User
from app.modules.billing import limits
from app.modules.workspaces.models import Membership, Role, Workspace

from . import auth, oauth
from .models import ApiKey, OAuthClient, OAuthGrant

router = APIRouter(prefix="/connect", tags=["connect"])

SENSITIVE = ("publish", "inbox")


def scope_options(keys, selected=()) -> list[dict]:
    return [{"key": k, "label": _(auth.SCOPE_LABELS[k]), "selected": k in selected, "sensitive": k in SENSITIVE}
            for k in auth.clean_scopes(keys)]


@router.get("/info")
def info(ctx: Ctx = Depends(workspace_ctx())):
    """The MCP server URL to paste in Claude / ChatGPT, and what this workspace may do."""
    return {"mcp_url": auth.mcp_url(), "issuer": auth.issuer(), "scopes": scope_options(auth.SCOPES),
            "plan_ok": limits.feature(ctx.db, ctx.workspace.id, "mcp"), "can_manage_keys": ctx.can(Role.admin),
            "key_days": list(auth.API_KEY_DAYS)}


# ----------------------------------------------------------------------------------------------- consent page
def _request(db: Session, secret: str):
    req = oauth.find_request(db, secret)
    if not req:
        raise NotFound(_("This sign-in request has expired. Start connecting again from the app you were using."),
                       code="request_expired")
    return req


def _workspaces(db: Session, user: User) -> list[dict]:
    rows = db.execute(select(Membership, Workspace).join(Workspace, Workspace.id == Membership.workspace_id)
                      .where(Membership.user_id == user.id).order_by(Workspace.name)).all()
    return [{"id": ws.id, "name": ws.name, "role": m.role, "active": ws.status == "active",
             "plan_ok": ws.status == "active" and limits.feature(db, ws.id, "mcp")} for m, ws in rows]


@router.get("/authorize/request")
def authorize_request(request: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req = _request(db, request)
    client: OAuthClient = req.client
    redirect = urlparse(req.redirect_uri)
    return {
        "client": {"name": client.client_name, "verified_host": oauth.client_display_host(client),
                   "client_uri": client.client_uri, "redirect_host": redirect.hostname,
                   "redirect_uri": req.redirect_uri, "loopback_only": oauth.only_loopback(client),
                   "kind": client.kind},
        "scopes": scope_options(req.scopes, req.preselected),
        "workspaces": _workspaces(db, user),
        "current_workspace_id": user.last_workspace_id,
        "user": {"name": user.name, "email": user.email},
        "expires_at": req.expires_at,
    }


class DecisionIn(BaseModel):
    request: str = Field(min_length=10, max_length=200)
    approve: bool
    workspace_id: int | None = None
    scopes: list[str] = Field(default_factory=list, max_length=10)


@router.post("/authorize/decision")
def authorize_decision(body: DecisionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req = _request(db, body.request)
    if not body.approve:
        return {"redirect_url": oauth.decide(db, req, user_id=user.id, workspace_id=None, scopes=[], approve=False)}
    if not body.workspace_id:
        raise AppError(_("Choose a workspace."), code="no_workspace")
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id,
                                                    Membership.workspace_id == body.workspace_id))
    workspace = db.get(Workspace, body.workspace_id)
    if not membership or not workspace:
        raise Forbidden(_("You are not a member of this workspace."), code="forbidden")
    if workspace.status != "active":
        raise Forbidden(_("This workspace is suspended."), code="workspace_suspended")
    limits.require(db, workspace.id, "mcp")
    scopes = auth.clean_scopes(["read", *[s for s in body.scopes if s in (req.scopes or [])]])
    url = oauth.decide(db, req, user_id=user.id, workspace_id=workspace.id, scopes=scopes, approve=True)
    return {"redirect_url": url}


# ----------------------------------------------------------------------------------------------- connected apps
class AppOut(BaseModel):
    id: int
    client_name: str
    client_host: str | None = None
    scopes: list[str]
    user_id: int
    user_name: str
    mine: bool
    created_at: datetime
    last_used_at: datetime | None = None


@router.get("/apps", response_model=list[AppOut])
def list_apps(ctx: Ctx = Depends(workspace_ctx())):
    """Apps connected to this workspace: your own, and everyone's for admins."""
    query = select(OAuthGrant, User.name).join(User, User.id == OAuthGrant.user_id).where(
        OAuthGrant.workspace_id == ctx.workspace.id, OAuthGrant.revoked_at.is_(None))
    if not ctx.can(Role.admin):
        query = query.where(OAuthGrant.user_id == ctx.user.id)
    # a grant counts once its code was exchanged (it has tokens)
    from .models import OAuthToken
    query = query.where(OAuthGrant.id.in_(select(OAuthToken.grant_id)))
    out = []
    for grant, user_name in ctx.db.execute(query.order_by(OAuthGrant.created_at.desc())).all():
        client = grant.client
        out.append(AppOut(id=grant.id, client_name=client.client_name if client else "app",
                          client_host=urlparse((client.redirect_uris or [""])[0]).hostname if client else None,
                          scopes=auth.clean_scopes(grant.scopes), user_id=grant.user_id, user_name=user_name,
                          mine=grant.user_id == ctx.user.id, created_at=grant.created_at,
                          last_used_at=grant.last_used_at))
    return out


@router.delete("/apps/{grant_id}", status_code=204)
def disconnect_app(grant_id: int, ctx: Ctx = Depends(workspace_ctx())):
    grant = ctx.db.get(OAuthGrant, grant_id)
    if not grant or grant.workspace_id != ctx.workspace.id or grant.revoked_at:
        raise NotFound(_("This app is not connected."))
    if grant.user_id != ctx.user.id:
        ctx.require(Role.admin)
    auth.revoke_grant(ctx.db, grant)


# ----------------------------------------------------------------------------------------------- API keys
class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[Literal["read", "write", "publish", "inbox"]] = Field(default_factory=lambda: ["read"])
    expires_days: Literal[30, 90, 365] = 90


class KeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    scopes: list[str]
    user_id: int
    user_name: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    expired: bool = False


class KeyCreated(BaseModel):
    key: str  # shown once
    item: KeyOut


def _key_out(key: ApiKey, user_name: str) -> KeyOut:
    return KeyOut(id=key.id, name=key.name, prefix=key.prefix, scopes=auth.clean_scopes(key.scopes),
                  user_id=key.user_id, user_name=user_name, created_at=key.created_at, expires_at=key.expires_at,
                  last_used_at=key.last_used_at, expired=auth.aware(key.expires_at) <= utcnow())


@router.get("/keys", response_model=list[KeyOut])
def list_keys(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    rows = ctx.db.execute(select(ApiKey, User.name).join(User, User.id == ApiKey.user_id)
                          .where(ApiKey.workspace_id == ctx.workspace.id, ApiKey.revoked_at.is_(None))
                          .order_by(ApiKey.created_at.desc())).all()
    return [_key_out(k, name) for k, name in rows]


@router.post("/keys", response_model=KeyCreated, status_code=201)
def create_key(body: KeyIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    limits.require(ctx.db, ctx.workspace.id, "mcp")
    secret = auth.API_KEY_PREFIX + auth.new_secret(30)
    key = ApiKey(workspace_id=ctx.workspace.id, user_id=ctx.user.id, name=body.name.strip(),
                 prefix=secret[:len(auth.API_KEY_PREFIX) + 4], key_hash=auth.sha256(secret),
                 scopes=auth.clean_scopes(["read", *body.scopes]),
                 expires_at=utcnow() + timedelta(days=body.expires_days))
    ctx.db.add(key)
    ctx.db.flush()
    return KeyCreated(key=secret, item=_key_out(key, ctx.user.name))


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    key = ctx.db.get(ApiKey, key_id)
    if not key or key.workspace_id != ctx.workspace.id or key.revoked_at:
        raise NotFound(_("API key not found."))
    key.revoked_at = utcnow()
