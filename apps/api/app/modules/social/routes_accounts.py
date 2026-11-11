"""/api/accounts — connected social accounts (OAuth or token), tests, follower sync, disconnect."""
import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.db import utcnow
from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.i18n import _
from app.modules.billing import limits
from app.modules.workspaces.models import Role

from . import accounts as service
from . import oauth
from .models import PUBLISH_PLATFORMS, OAuthSession, SocialAccount
from .platforms import PLATFORM_LABELS
from .schemas import (AccountCreate, AccountOut, AccountUpdate, ConnectionResult, OAuthAppIn, OAuthSetupOut,
                      OAuthStartIn, OAuthStartOut, PlatformOption, SyncResult)
from .platforms.pinterest import board_of
from .platforms.tiktok import PRIVACY_LEVELS

router = APIRouter(prefix="/accounts", tags=["accounts"])


def account_out(account: SocialAccount) -> AccountOut:
    extra = account.extra or {}
    oauth_app = extra.get("oauth_app")
    return AccountOut(
        id=account.id, name=account.name, platform=account.platform,
        platform_label=PLATFORM_LABELS.get(account.platform, account.platform), username=account.username,
        external_id=account.external_id, avatar_url=account.avatar_url, state=account.state,
        last_error=account.last_error, last_check_at=account.last_check_at, followers=account.followers or 0,
        followers_updated_at=account.followers_updated_at, token_expires_at=account.token_expires_at,
        has_token=bool(account.access_token), can_refresh=bool(account.refresh_token) or account.platform == "threads",
        active=account.active, inbox_only=account.platform not in PUBLISH_PLATFORMS,
        can_publish=service.can_publish(account) and bool(account.access_token),
        connected_with="oauth" if oauth_app else "token",
        oauth_app=oauth_app if oauth_app in ("workspace", "platform") else None,
        privacy_level=extra.get("privacy_level") if account.platform == "tiktok" else None,
        board_id=board_of(extra) if account.platform == "pinterest" else None,
        boards=extra.get("boards") if account.platform == "pinterest" else None,
        created_at=account.created_at,
    )


def get_account(ctx: Ctx, account_id: int) -> SocialAccount:
    account = ctx.db.get(SocialAccount, account_id)
    if not account or account.workspace_id != ctx.workspace.id:
        raise NotFound(_("Account not found."))
    return account


@router.get("", response_model=list[AccountOut])
def list_accounts(include_inactive: bool = False, ctx: Ctx = Depends(workspace_ctx())):
    """All accounts of the workspace. WhatsApp numbers (inbox) are listed with ``inbox_only``."""
    query = select(SocialAccount).where(SocialAccount.workspace_id == ctx.workspace.id)
    if not include_inactive:
        query = query.where(SocialAccount.active.is_(True))
    rows = ctx.db.scalars(query).all()
    order = {p: i for i, p in enumerate((*PUBLISH_PLATFORMS, "whatsapp"))}
    return [account_out(a) for a in sorted(rows, key=lambda a: (order.get(a.platform, 99), a.name.lower()))]


@router.get("/platforms", response_model=list[PlatformOption])
def platforms(ctx: Ctx = Depends(workspace_ctx())):
    """How each network connects (one-click OAuth when an app is configured, else guided setup or token)."""
    out = []
    for key in PUBLISH_PLATFORMS:
        if key == "telegram":
            out.append(PlatformOption(key=key, label=PLATFORM_LABELS[key], method="token",
                                      help=_(oauth.MANUAL_HELP[key])))
            continue
        _id, _secret, source = oauth.credentials(ctx.db, ctx.workspace.id, key)
        out.append(PlatformOption(key=key, label=PLATFORM_LABELS[key], method="oauth",
                                  oauth_platform=oauth.oauth_key(key), configured=bool(source),
                                  source=source or None, help=_(oauth.MANUAL_HELP[key])))
    return out


@router.post("", response_model=ConnectionResult, status_code=201)
def connect_with_token(body: AccountCreate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Manual connection: paste a token (and the page / channel id). The connection is tested right away."""
    if body.platform == "telegram" and not (body.external_id or "").strip():
        raise AppError(_("Enter the channel (@name or -100…)."), code="missing_external_id")
    if body.platform in ("facebook", "instagram", "google_business") and not (body.external_id or "").strip():
        raise AppError(_("Enter the account or page ID."), code="missing_external_id")
    account = service.find_existing(ctx.db, ctx.workspace.id, body.platform, (body.external_id or "").strip() or None)
    if account is None:
        limits.check(ctx.db, ctx.workspace.id, "social_accounts")
        account = SocialAccount(workspace_id=ctx.workspace.id, platform=body.platform,
                                name=(body.name or PLATFORM_LABELS[body.platform]).strip()[:160])
        ctx.db.add(account)
    account.access_token = body.access_token.strip()
    account.external_id = (body.external_id or "").strip() or account.external_id
    if body.name:
        account.name = body.name.strip()[:160]
    if body.username:
        account.username = body.username.strip().lstrip("@")[:160]
    extra = dict(account.extra or {})
    extra.pop("oauth_app", None)
    if body.platform == "tiktok":
        extra["privacy_level"] = body.privacy_level if body.privacy_level in PRIVACY_LEVELS else "SELF_ONLY"
    account.extra = extra
    account.refresh_token = None
    account.token_expires_at = None
    account.active = True
    account.state = "draft"
    ctx.db.flush()
    ok = service.check_connection(ctx.db, account)
    return ConnectionResult(ok=ok, account=account_out(account),
                            message=None if ok else account.last_error)


@router.get("/oauth/setup/{platform}", response_model=OAuthSetupOut)
def oauth_setup(platform: str, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Everything the Connect dialog needs to guide the first-time developer-app setup."""
    key = oauth.oauth_key(platform)
    guide = oauth.SETUP_GUIDES.get(key)
    if not guide:
        raise AppError(_("This platform connects with a token."), code="token_only")
    own_id, own_secret = oauth.workspace_credentials(ctx.db, ctx.workspace.id, key)
    _cid, _sec, source = oauth.credentials(ctx.db, ctx.workspace.id, key)
    return OAuthSetupOut(
        platform=key, requested=platform, brand=guide["brand"], portal_url=guide["portal_url"],
        id_label=_(guide["id_label"]), secret_label=_(guide["secret_label"]), steps=[_(s) for s in guide["steps"]],
        note=_(guide["note"]) if guide.get("note") else None, redirect_uri=oauth.redirect_uri(),
        configured=bool(source), source=source or None, own_app=bool(own_id and own_secret), client_id=own_id,
    )


def _start(ctx: Ctx, platform: str) -> OAuthStartOut:
    key = oauth.oauth_key(platform)
    if key not in oauth.PLATFORMS:
        raise AppError(_("This platform connects with a token."), code="token_only")
    client_id, _secret, source = oauth.credentials(ctx.db, ctx.workspace.id, key)
    if not client_id:
        raise AppError(_("Set up the {brand} app first, or connect with an access token.",
                         brand=oauth.SETUP_GUIDES[key]["brand"]), code="oauth_not_configured")
    session = OAuthSession(workspace_id=ctx.workspace.id, state_token=secrets.token_urlsafe(32), platform=key,
                           code_verifier=oauth.new_verifier(), user_id=ctx.user.id, app_source=source,
                           locale=ctx.user.locale or "ar")
    ctx.db.add(session)
    ctx.db.flush()
    return OAuthStartOut(url=oauth.authorize_url(ctx.db, ctx.workspace.id, key, session.state_token,
                                                 session.code_verifier, client_id))


@router.post("/oauth/start", response_model=OAuthStartOut)
def oauth_start(body: OAuthStartIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Returns the consent URL of the network; the browser goes there and comes back to ``/oauth/callback``."""
    return _start(ctx, body.platform)


@router.put("/oauth/apps/{platform}", response_model=OAuthStartOut | None)
def save_oauth_app(platform: str, body: OAuthAppIn, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Store the workspace's own developer-app keys (secret encrypted), then (optionally) start the login."""
    key = oauth.oauth_key(platform)
    if key not in oauth.PLATFORMS:
        raise AppError(_("This platform connects with a token."), code="token_only")
    client_id, secret = body.client_id.strip(), body.client_secret.strip()
    if not client_id or not secret:
        raise AppError(_("Please fill in both keys."), code="missing_keys")
    oauth.save_workspace_credentials(ctx.db, ctx.workspace.id, key, client_id, secret)
    return _start(ctx, key) if body.connect else None


@router.delete("/oauth/apps/{platform}", status_code=204)
def delete_oauth_app(platform: str, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Forget the workspace's own app (the platform-wide app, if any, is used again)."""
    oauth.save_workspace_credentials(ctx.db, ctx.workspace.id, oauth.oauth_key(platform), None, None)


@router.get("/{account_id}", response_model=AccountOut)
def one(account_id: int, ctx: Ctx = Depends(workspace_ctx())):
    return account_out(get_account(ctx, account_id))


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountUpdate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    account = get_account(ctx, account_id)
    data = body.model_dump(exclude_unset=True)
    for key in ("name", "username", "external_id"):
        if data.get(key):
            setattr(account, key, data[key].strip().lstrip("@") if key == "username" else data[key].strip())
    if data.get("access_token"):
        account.access_token = data["access_token"].strip()
        account.refresh_token = None
        account.token_expires_at = None
        account.state = "draft"
        account.last_error = None
    if "privacy_level" in data and account.platform == "tiktok":
        if data["privacy_level"] not in PRIVACY_LEVELS:
            raise AppError(_("Unknown TikTok privacy level."), code="bad_privacy")
        account.extra = dict(account.extra or {}, privacy_level=data["privacy_level"])
    if data.get("board_id") and account.platform == "pinterest":
        if data["board_id"] not in {b.get("id") for b in (account.extra or {}).get("boards") or []}:
            raise AppError(_("This board is not in the account. Test the connection to read the boards again."),
                           code="bad_board")
        account.extra = dict(account.extra or {}, board_id=data["board_id"])
    if data.get("active") is not None:
        if data["active"] and not account.active:
            limits.check(ctx.db, ctx.workspace.id, "social_accounts")
        account.active = data["active"]
    ctx.db.flush()
    return account_out(account)


@router.post("/{account_id}/test", response_model=ConnectionResult)
def test_connection(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    account = get_account(ctx, account_id)
    if account.platform not in PUBLISH_PLATFORMS:
        raise AppError(_("This account is managed in the inbox settings."), code="inbox_only_account")
    ok = service.check_connection(ctx.db, account)
    return ConnectionResult(ok=ok, account=account_out(account),
                            message=_("“{name}” is connected.", name=account.name) if ok else account.last_error)


@router.post("/{account_id}/refresh-token", response_model=ConnectionResult)
def refresh_token(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    account = get_account(ctx, account_id)
    ok = service.apply_refresh(ctx.db, account)
    return ConnectionResult(ok=ok, account=account_out(account), message=None if ok else account.last_error)


@router.post("/{account_id}/sync", response_model=SyncResult)
def sync_account(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Followers (+ today's daily snapshot) and the statistics of its recent posts."""
    from .analytics import sync_metrics

    account = get_account(ctx, account_id)
    followers = service.sync_audience(ctx.db, [account])
    posts = sync_metrics(ctx.db, ctx.workspace.id, account_ids=[account.id])
    return SyncResult(posts=posts, accounts=followers)


@router.delete("/{account_id}", status_code=204)
def disconnect(account_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Disconnect: tokens are erased and the account is hidden; published results and statistics are kept."""
    account = get_account(ctx, account_id)
    if account.platform not in PUBLISH_PLATFORMS:
        raise AppError(_("This account is managed in the inbox settings."), code="inbox_only_account")
    account.access_token = None
    account.refresh_token = None
    account.token_expires_at = None
    account.active = False
    account.state = "disconnected"
    account.last_error = None
    account.last_check_at = utcnow()
