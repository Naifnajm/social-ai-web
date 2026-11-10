"""Text generation API used by every feature — CONTRACT (the AI builder implements the bodies).

Other features call only these functions (and mock them in tests with ``monkeypatch.setattr``):

    from app.modules.ai import service as ai
    text = ai.generate_text(db, ws_id, system="You write captions…", user="Brief…", purpose="post caption")
    data = ai.generate_json(db, ws_id, system=..., user=..., purpose="inbox triage")  # dict, robust parsing
    ai.has_provider(db, ws_id, "text")
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.i18n import _


@dataclass
class Usage:
    provider_id: int | None
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0


def has_provider(db: Session, workspace_id: int, capability: str = "text") -> bool:
    raise NotImplementedError


def generate_text(db: Session, workspace_id: int, system: str, user: str, *, model_id: int | None = None,
                  provider_id: int | None = None, purpose: str = "", max_tokens: int | None = None,
                  user_id: int | None = None) -> str:
    """Return the model's text answer. Records an AIUsage row (cost). Raises AppError when no provider is set."""
    text, _usage = generate_text_with_usage(db, workspace_id, system, user, model_id=model_id,
                                            provider_id=provider_id, purpose=purpose, max_tokens=max_tokens,
                                            user_id=user_id)
    return text


def generate_text_with_usage(db: Session, workspace_id: int, system: str, user: str, *, model_id: int | None = None,
                             provider_id: int | None = None, purpose: str = "", max_tokens: int | None = None,
                             user_id: int | None = None) -> tuple[str, Usage]:
    raise AppError(_("No AI provider is set up yet. Add one in Settings › AI providers."), code="no_ai_provider")


def generate_json(db: Session, workspace_id: int, system: str, user: str, **kwargs) -> dict:
    """Ask for a JSON object and parse it robustly (code fences, extra text). Raises AppError on failure."""
    raise NotImplementedError
