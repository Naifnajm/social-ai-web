"""Text generation API used by every feature — CONTRACT (implemented by the AI feature).

Other features call only these functions (and mock them in tests with ``monkeypatch.setattr``):

    from app.modules.ai import service as ai
    text = ai.generate_text(db, ws_id, system="You write captions…", user="Brief…", purpose="post caption")
    data = ai.generate_json(db, ws_id, system=..., user=..., purpose="inbox triage")  # dict, robust parsing
    ai.has_provider(db, ws_id, "text")

Errors: ``AppError`` code ``no_ai_provider`` (nothing set up), ``ai_budget_exceeded`` (HTTP 402, monthly budget of
the provider used up), ``ai_bad_json`` (generate_json could not parse the answer); ``LimitReached`` from billing;
``ApiError`` when the provider itself fails (the message is readable; the API turns it into HTTP 502).
Every successful call records an ``AIUsage`` row with its approximate cost.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.i18n import _

from . import catalog, pricing
from . import providers as prov
from .prompts import parse_json


@dataclass
class Usage:
    provider_id: int | None
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    provider: str = ""
    usage_id: int | None = None


def has_provider(db: Session, workspace_id: int, capability: str = "text") -> bool:
    """True when an active provider of the workspace can do ``capability`` (text, image, video, audio, stt)."""
    return bool(prov.list_providers(db, workspace_id, capability, active_only=True))


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
    from .clients import get_client

    provider, model, model_name = prov.resolve(db, workspace_id, catalog.TEXT, model_id=model_id,
                                               provider_id=provider_id)
    estimated = pricing.estimate(model, (system or "") + (user or ""), 0, max_tokens or provider.max_tokens)[0] \
        if model else 0.0
    prov.check_spend(db, provider, estimated)
    client = get_client(provider, model=model_name or None, max_tokens=max_tokens)
    text = client.generate(system or "", user or "")
    tokens_in, tokens_out = client.last_usage
    if not tokens_in and not tokens_out:  # provider did not report usage: estimate it
        tokens_in = int(len((system or "") + (user or "")) / pricing.CHARS_PER_TOKEN)
        tokens_out = int(len(text) / pricing.CHARS_PER_TOKEN)
    usage = prov.record_usage(db, provider, client.model, catalog.TEXT, tokens_in=tokens_in, tokens_out=tokens_out,
                              purpose=purpose or (user or "")[:80], user_id=user_id)
    return text, Usage(provider_id=provider.id, model=client.model, tokens_in=tokens_in, tokens_out=tokens_out,
                       cost=usage.cost, provider=provider.name, usage_id=usage.id)


JSON_INSTRUCTION = ("\n\nAnswer with ONLY one valid JSON object (no code fence, no comments, no text before or "
                    "after it).")


def generate_json(db: Session, workspace_id: int, system: str, user: str, **kwargs) -> dict:
    """Ask for a JSON object and parse it robustly (code fences, extra text). Raises AppError on failure.

    A JSON array answer is returned as ``{"items": [...]}``.
    """
    system = (system or "").rstrip()
    if "json" not in system.lower():
        system += JSON_INSTRUCTION
    text = generate_text(db, workspace_id, system, user, **kwargs)
    data = parse_json(text)
    if isinstance(data, list):
        return {"items": data}
    if not isinstance(data, dict):
        raise AppError(_("The AI answer could not be read. Please try again."), code="ai_bad_json")
    return data
