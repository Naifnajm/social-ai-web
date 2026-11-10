"""OAuth callback: the network sends the browser back here after consent; we store the accounts and return to
the web app (Settings › Accounts)."""
import logging
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, utcnow
from app.core.errors import AppError
from app.core.http import ApiError
from app.core.i18n import _, set_locale
from app.modules.billing import limits
from app.modules.workspaces.models import ROLE_RANK, Membership, Role

from . import accounts as account_service
from . import oauth
from .models import OAuthSession

router = APIRouter(tags=["public"])
_logger = logging.getLogger(__name__)
RETURN_PATH = "/settings/accounts"
SESSION_TTL = timedelta(hours=1)


def _back(locale: str, **params) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return RedirectResponse(f"{settings.web_url.rstrip('/')}/{locale}{RETURN_PATH}?{query}", status_code=303)


@router.get(oauth.CALLBACK_PATH, include_in_schema=False)
def oauth_callback(state: str | None = None, code: str | None = None, error: str | None = None,
                   error_description: str | None = None, db: Session = Depends(get_db)):
    session = db.scalar(select(OAuthSession).where(OAuthSession.state_token == (state or "")[:80])) if state else None
    locale = session.locale if session else settings.default_locale
    set_locale(locale)
    if session is None or session.created_at < utcnow() - SESSION_TTL:
        if session is not None:
            db.delete(session)
        return _back(locale, error=_("This connection link has expired. Please start again."))
    platform, verifier, source = session.platform, session.code_verifier, session.app_source
    workspace_id, user_id = session.workspace_id, session.user_id
    db.delete(session)  # single use
    db.flush()
    if error or not code:
        return _back(locale, error=error_description or error or _("Access was not granted."))
    role = db.scalar(select(Membership.role).where(Membership.workspace_id == workspace_id,
                                                   Membership.user_id == user_id))
    if not role or ROLE_RANK[Role(role)] < ROLE_RANK[Role.admin]:
        return _back(locale, error=_("Only admins can connect accounts."))
    try:
        values = oauth.exchange(db, workspace_id, platform, code, verifier, source)
        accounts = account_service.upsert_from_oauth(
            db, workspace_id, values, check_limit=lambda: limits.check(db, workspace_id, "social_accounts"))
    except ApiError as exc:
        db.rollback()
        return _back(locale, error=exc.message)
    except AppError as exc:
        db.rollback()
        return _back(locale, error=exc.detail)
    except Exception:
        db.rollback()
        _logger.exception("OAuth callback failed")
        return _back(locale, error=_("Unexpected error while connecting the account. See the API logs."))
    return _back(locale, connected=len(accounts), platform=platform)
