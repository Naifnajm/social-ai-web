"""Errors returned to clients as ``{"detail": "...", "code": "..."}`` (detail already translated)."""
from fastapi import Request
from fastapi.responses import JSONResponse


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


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "code": exc.code, **exc.extra}, status_code=exc.status_code)


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse({"detail": exc.message, "code": "external_api"}, status_code=502)
