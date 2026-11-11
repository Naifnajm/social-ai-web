"""Stravica Social API — FastAPI application.

Run: ``uv run uvicorn app.main:app --reload``  ·  API docs at /api/docs
"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core import registry
from app.core.config import settings
from app.core.errors import ApiError, AppError, api_error_handler, app_error_handler
from app.core.hardening import API_HEADERS
from app.core.i18n import pick_locale, set_locale

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    registry.load_models()
    # The interactive API docs describe every endpoint: useful in development, not something to publish.
    public_docs = settings.env != "prod"
    app = FastAPI(title=settings.app_name, version="1.0.0", docs_url="/api/docs" if public_docs else None,
                  redoc_url=None, openapi_url="/api/openapi.json" if public_docs else None)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(ApiError, api_error_handler)

    @app.middleware("http")
    async def locale_middleware(request: Request, call_next):
        set_locale(pick_locale(request.headers.get("accept-language")))
        response = await call_next(request)
        for name, value in API_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/api/health", tags=["system"])
    def health():
        return {"status": "ok", "app": settings.app_name}

    for module in registry.load("router"):
        app.include_router(module.router, prefix="/api")
    for module in registry.load("public"):
        app.include_router(module.router)
    registry.load("tasks")
    return app


app = create_app()
