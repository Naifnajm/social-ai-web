"""Errors returned to clients as ``{"detail": "...", "code": "..."}`` (detail already translated).

A failure on our side (anything unexpected, or an external API that failed) also carries ``"ref"``: a short
reference the person can give to support. The failure is stored under that reference (``ErrorEvent``).
"""
import logging
import secrets
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

_logger = logging.getLogger(__name__)
MAX_DETAIL = 12000


class AppError(Exception):
    status_code = 400

    def __init__(self, detail: str, code: str = "error", status_code: int | None = None, **extra):
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.extra = extra
        if status_code:
            self.status_code = status_code


class NotFound(AppError):
    status_code = 404


class Forbidden(AppError):
    status_code = 403


class LimitReached(AppError):
    """A plan limit (accounts, posts, AI credits…) is reached."""

    status_code = 402


class ApiError(Exception):
    """Failure of an external API (AI provider, social network). ``message`` is user-readable."""

    def __init__(self, message: str, status: int | None = None, payload=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload


def request_ref(request: Request) -> str:
    """The reference of this request (made on first use; also sent as the ``X-Request-ID`` header)."""
    ref = getattr(request.state, "ref", None)
    if not ref:
        ref = request.state.ref = secrets.token_hex(4).upper()
    return ref


def _who(request: Request) -> tuple[int | None, int | None]:
    """``(user id, workspace id)`` of the request when they can be read without the database."""
    from .security import decode_token
    user_id = workspace_id = None
    try:
        auth = request.headers.get("authorization") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else request.cookies.get("sai_access")
        payload = decode_token(token, "access") if token else None
        user_id = int(payload["sub"]) if payload else None
        header = request.headers.get("x-workspace") or ""
        workspace_id = int(header) if header.isdigit() else None
    except Exception:  # noqa: BLE001 — never fail while reporting a failure
        pass
    return user_id, workspace_id


def record_error(request: Request, *, status: int, code: str, message: str, detail: str | None = None) -> str:
    """Store the failure under the request's reference, in its own transaction. Returns the reference."""
    ref = request_ref(request)
    user_id, workspace_id = _who(request)
    try:
        from . import db as core_db
        from .models import ErrorEvent
        with core_db.SessionLocal() as db:
            if workspace_id is not None:
                from app.modules.workspaces.models import Workspace
                if db.get(Workspace, workspace_id) is None:
                    workspace_id = None
            db.add(ErrorEvent(ref=ref, status=status, code=code[:40], method=request.method[:10],
                              path=str(request.url.path)[:500], message=(message or "")[:2000],
                              detail=(detail or None) and detail[-MAX_DETAIL:], user_id=user_id,
                              workspace_id=workspace_id))
            db.commit()
    except Exception:  # noqa: BLE001
        _logger.exception("could not store error %s", ref)
    return ref


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "code": exc.code, **exc.extra}, status_code=exc.status_code)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    ref = record_error(request, status=502, code="external_api", message=exc.message,
                       detail=str(exc.payload) if exc.payload else None)
    return JSONResponse({"detail": exc.message, "code": "external_api", "ref": ref}, status_code=502,
                        headers={"X-Request-ID": ref})


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything nobody handled: the person gets a plain sentence and a reference; the traceback stays with us."""
    from .i18n import _
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    ref = record_error(request, status=500, code="server_error", message=f"{type(exc).__name__}: {exc}", detail=detail)
    _logger.error("unexpected error %s on %s %s", ref, request.method, request.url.path, exc_info=exc)
    return JSONResponse({"detail": _("Something went wrong on our side. Our team can see what happened under "
                                     "reference {ref}.", ref=ref), "code": "server_error", "ref": ref},
                        status_code=500, headers={"X-Request-ID": ref})
