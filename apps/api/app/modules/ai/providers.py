"""AI providers of a workspace: defaults from the catalog, model price list, routing by capability, spending,
budgets, wallets, connection tests and balances. Used by the router, ``service.py`` and ``media.py``.

Every function takes the workspace id and only ever touches rows of that workspace.
"""
from datetime import UTC, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.core.http import ApiError
from app.core.i18n import _
from app.modules.billing import limits

from . import catalog, pricing
from .balance import fetch_balance, supports_balance
from .models import AIModel, AIProvider, AIUsage


def utcnow() -> datetime:
    return datetime.now(UTC)


def month_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ------------------------------------------------------------------ lookups
def get_provider(db: Session, workspace_id: int, provider_id: int) -> AIProvider:
    provider = db.get(AIProvider, provider_id)
    if not provider or provider.workspace_id != workspace_id:
        raise NotFound(_("AI provider not found."), code="not_found")
    return provider


def get_model(db: Session, workspace_id: int, model_id: int) -> AIModel:
    model = db.get(AIModel, model_id)
    if not model or model.workspace_id != workspace_id:
        raise NotFound(_("AI model not found."), code="not_found")
    return model


def list_providers(db: Session, workspace_id: int, capability: str | None = None, active_only: bool = False):
    query = select(AIProvider).where(AIProvider.workspace_id == workspace_id).order_by(
        AIProvider.is_default.desc(), AIProvider.sequence, AIProvider.id)
    if active_only:
        query = query.where(AIProvider.active.is_(True))
    if capability:
        query = query.where(AIProvider.provider_type.in_(catalog.types_for(capability)))
    return list(db.scalars(query))


def provider_models(db: Session, provider: AIProvider, capability: str | None = None, active_only: bool = True):
    query = select(AIModel).where(AIModel.workspace_id == provider.workspace_id,
                                  AIModel.provider_id == provider.id).order_by(AIModel.sequence, AIModel.id)
    if capability:
        query = query.where(AIModel.capability == capability)
    if active_only:
        query = query.where(AIModel.active.is_(True))
    return list(db.scalars(query))


def find_model(db: Session, provider: AIProvider, name: str, capability: str) -> AIModel | None:
    return db.scalar(select(AIModel).where(AIModel.workspace_id == provider.workspace_id,
                                           AIModel.provider_id == provider.id, AIModel.name == name,
                                           AIModel.capability == capability).order_by(AIModel.active.desc(),
                                                                                      AIModel.id).limit(1))


def default_model_name(provider: AIProvider, capability: str) -> str:
    field = catalog.MODEL_FIELD.get(capability)
    value = getattr(provider, field) if field else None
    return value or catalog.default_model(provider.provider_type, capability)


# ------------------------------------------------------------------ create / defaults / seeding
def catalog_defaults(provider_type: str) -> dict:
    meta = catalog.info(provider_type)
    models = meta.get("models", {})
    return {
        "name": meta["label"].split(" (")[0],
        "text_model": models.get("text") or None,
        "image_model": models.get("image") or None,
        "video_model": models.get("video") or None,
        "audio_model": models.get("audio") or None,
        "voice": meta.get("voice") or None,
        "max_tokens": meta.get("max_tokens", 4000),
    }


def create_provider(db: Session, workspace_id: int, values: dict) -> AIProvider:
    provider_type = values.get("provider_type") or "openai"
    if provider_type not in catalog.CATALOG:
        raise AppError(_("Unknown AI provider type."), code="bad_provider_type")
    data = catalog_defaults(provider_type)
    data.update({k: v for k, v in values.items() if v is not None and v != ""})
    data["provider_type"] = provider_type
    if not data.get("base_url"):
        data["base_url"] = None
    if catalog.info(provider_type).get("needs_base_url") and not data.get("base_url"):
        raise AppError(_("Please set the Base URL of this provider."), code="base_url_required")
    want_default = bool(data.pop("is_default", False))
    provider = AIProvider(workspace_id=workspace_id, **data)
    db.add(provider)
    db.flush()
    can_text = catalog.can(provider_type, catalog.TEXT)
    if can_text and (want_default or not default_text_provider(db, workspace_id, exclude_id=provider.id)):
        set_default(db, provider)
    seed_models(db, provider)
    return provider


def update_provider(db: Session, provider: AIProvider, values: dict) -> AIProvider:
    reset = {"api_key", "base_url", "text_model"} & set(values)
    want_default = values.pop("is_default", None)
    for key, value in values.items():
        if key == "base_url":
            value = value or None
        setattr(provider, key, value)
    if reset:
        provider.state, provider.last_error = "draft", None
    if want_default:
        set_default(db, provider)
    elif want_default is False and provider.is_default:
        provider.is_default = False
    if not provider.active and provider.is_default:
        provider.is_default = False
        _promote_default(db, provider.workspace_id)
    db.flush()
    return provider


def delete_provider(db: Session, provider: AIProvider) -> None:
    workspace_id, was_default = provider.workspace_id, provider.is_default
    db.delete(provider)
    db.flush()
    if was_default:
        _promote_default(db, workspace_id)


def _promote_default(db: Session, workspace_id: int) -> None:
    candidates = [p for p in list_providers(db, workspace_id, catalog.TEXT, active_only=True) if not p.is_default]
    if candidates and not default_text_provider(db, workspace_id):
        candidates[0].is_default = True
        db.flush()


def set_default(db: Session, provider: AIProvider) -> None:
    if not catalog.can(provider.provider_type, catalog.TEXT):
        raise AppError(_("Only a provider that writes text can be the default."), code="not_text_provider")
    for other in db.scalars(select(AIProvider).where(AIProvider.workspace_id == provider.workspace_id,
                                                     AIProvider.is_default.is_(True), AIProvider.id != provider.id)):
        other.is_default = False
    provider.is_default = True
    provider.active = True
    db.flush()


def default_text_provider(db: Session, workspace_id: int, exclude_id: int | None = None) -> AIProvider | None:
    query = select(AIProvider).where(AIProvider.workspace_id == workspace_id, AIProvider.is_default.is_(True),
                                     AIProvider.active.is_(True),
                                     AIProvider.provider_type.in_(catalog.types_for(catalog.TEXT)))
    if exclude_id:
        query = query.where(AIProvider.id != exclude_id)
    return db.scalar(query.limit(1))


def seed_models(db: Session, provider: AIProvider) -> list[AIModel]:
    """Create the catalog models of a provider that are missing (prices are approximate list prices)."""
    existing = {(m.name, m.capability) for m in provider_models(db, provider, active_only=False)}
    created = []
    for seq, (name, cap, unit, p_in, p_out, price, label) in enumerate(pricing.entries(provider.provider_type)):
        if (name, cap) in existing:
            continue
        model = AIModel(workspace_id=provider.workspace_id, provider_id=provider.id, name=name, label=label,
                        capability=cap, unit=unit, price_in=p_in, price_out=p_out, price=price, sequence=seq)
        db.add(model)
        created.append(model)
    db.flush()
    return created


# ------------------------------------------------------------------ routing
CAPABILITY_ERROR = {
    "text": "Add an AI provider that can write text: {names}.",
    "image": "Add an AI provider that can create images: {names}.",
    "video": "Add an AI provider that can create videos: {names}.",
    "audio": "Add an AI provider that can create voice and sound: {names}.",
    "stt": "Add an AI provider that can transcribe speech: {names}.",
}


def provider_for(db: Session, workspace_id: int, capability: str, provider_id: int | None = None) -> AIProvider:
    """The provider asked for (if it can do it), else the default / first active one that can."""
    if provider_id:
        provider = get_provider(db, workspace_id, provider_id)
        if provider.active and catalog.can(provider.provider_type, capability):
            return provider
    if capability == catalog.TEXT:
        default = default_text_provider(db, workspace_id)
        if default:
            return default
    providers = list_providers(db, workspace_id, capability, active_only=True)
    if not providers:
        names = ", ".join(meta["label"] for meta in catalog.CATALOG.values() if capability in meta["caps"])
        code = "no_ai_provider" if capability == catalog.TEXT else "no_media_provider"
        if capability == catalog.TEXT:
            raise AppError(_("No AI provider is set up yet. Add one in Settings › AI providers."), code=code)
        raise AppError(_(CAPABILITY_ERROR.get(capability, CAPABILITY_ERROR["image"]), names=names), code=code)
    return providers[0]


def resolve(db: Session, workspace_id: int, capability: str, *, model_id: int | None = None,
            provider_id: int | None = None) -> tuple[AIProvider, AIModel | None, str]:
    """(provider, model row or None, model name) for a task. A model id wins over a provider id."""
    model = None
    if model_id:
        model = get_model(db, workspace_id, model_id)
        if model.capability != capability:
            model = None
        else:
            provider_id = model.provider_id
    provider = provider_for(db, workspace_id, capability, provider_id)
    if model and model.provider_id != provider.id:
        model = None
    name = model.name if model else default_model_name(provider, capability)
    if not model and name:
        model = find_model(db, provider, name, capability)
    return provider, model, name


# ------------------------------------------------------------------ money
def spent(db: Session, workspace_id: int, provider_id: int | None = None, since: datetime | None = None) -> float:
    query = select(func.coalesce(func.sum(AIUsage.cost), 0.0)).where(AIUsage.workspace_id == workspace_id)
    if provider_id:
        query = query.where(AIUsage.provider_id == provider_id)
    if since:
        query = query.where(AIUsage.created_at >= since)
    return float(db.scalar(query) or 0.0)


def spent_by_provider(db: Session, workspace_id: int) -> dict[int, tuple[float, float]]:
    """{provider_id: (spent this month, spent in total)}."""
    start = month_start()
    rows = db.execute(select(AIUsage.provider_id, func.sum(AIUsage.cost),
                             func.sum(func.coalesce(AIUsage.cost, 0.0)).filter(AIUsage.created_at >= start))
                      .where(AIUsage.workspace_id == workspace_id, AIUsage.provider_id.is_not(None))
                      .group_by(AIUsage.provider_id)).all()
    return {pid: (float(month or 0.0), float(total or 0.0)) for pid, total, month in rows}


def wallet(db: Session, provider: AIProvider, spent_month: float | None = None) -> dict:
    """What to show next to a model picker: the real balance, the budget left, or the spending."""
    if spent_month is None:
        spent_month = spent(db, provider.workspace_id, provider.id, month_start())
    if provider.balance_checked_at and provider.balance is not None:
        return {"kind": "balance", "amount": round(provider.balance, 2), "unit": provider.balance_unit or "USD",
                "spent": round(spent_month, 2), "budget": None}
    if provider.monthly_budget:
        return {"kind": "budget", "amount": round(provider.monthly_budget - spent_month, 2), "unit": "USD",
                "budget": provider.monthly_budget, "spent": round(spent_month, 2)}
    return {"kind": "spent", "amount": round(spent_month, 2), "unit": "USD", "spent": round(spent_month, 2),
            "budget": None}


def check_spend(db: Session, provider: AIProvider, cost: float) -> None:
    """Refuse a task that would exceed the provider's monthly budget; ask billing for platform credits."""
    if provider.monthly_budget:
        used = spent(db, provider.workspace_id, provider.id, month_start())
        if used >= provider.monthly_budget - 1e-9 or used + (cost or 0) > provider.monthly_budget + 1e-9:
            raise AppError(
                _("The monthly AI budget of “{provider}” is used up (${spent} of ${budget}). Raise the budget in "
                  "Settings › AI providers or wait until next month.", provider=provider.name,
                  spent=pricing.fmt(round(used, 2)), budget=pricing.fmt(provider.monthly_budget)),
                code="ai_budget_exceeded", status_code=402)
    # The workspace's own keys (bring-your-own-key) never consume the plan's AI credits; the check still blocks
    # workspaces whose trial ended or whose payment is overdue. Platform-paid AI must pass its real cost here.
    limits.check(db, provider.workspace_id, "ai_credits", amount=0)


def record_usage(db: Session, provider: AIProvider | None, model_name: str | None, capability: str, *,
                 tokens_in: int = 0, tokens_out: int = 0, units: float = 0, chars: int = 0, seconds: float = 0,
                 purpose: str = "", user_id: int | None = None, cost: float | None = None,
                 workspace_id: int | None = None) -> AIUsage:
    model = find_model(db, provider, model_name, capability) if provider and model_name else None
    if cost is None:
        cost = pricing.cost_of(model, tokens_in, tokens_out, units, chars, seconds) if model else 0.0
    usage = AIUsage(workspace_id=workspace_id or provider.workspace_id, provider_id=provider.id if provider else None,
                    model_id=model.id if model else None, model_name=(model_name or "")[:120] or None,
                    capability=capability, tokens_in=int(tokens_in or 0), tokens_out=int(tokens_out or 0),
                    units=float(units or chars or seconds or 0), cost=round(float(cost or 0.0), 6),
                    purpose=(purpose or "")[:160] or None, user_id=user_id)
    db.add(usage)
    db.flush()
    return usage


def estimate_task(db: Session, workspace_id: int, capability: str, *, prompt: str = "", seconds: float = 0,
                  audio_mode: str = "speech", model_id: int | None = None, provider_id: int | None = None) -> dict:
    """Cost estimate shown before running something, plus the wallet of the provider."""
    try:
        provider, model, name = resolve(db, workspace_id, capability, model_id=model_id, provider_id=provider_id)
    except AppError:
        return {"cost": 0.0, "detail": "", "model": "", "model_id": None, "provider": "", "provider_id": None,
                "wallet": None, "known": False}
    base = {"provider": provider.name, "provider_id": provider.id, "wallet": wallet(db, provider)}
    if capability == catalog.AUDIO and audio_mode in ("sfx", "music"):
        rate = pricing.SOUND_PRICE_PER_SECOND.get(provider.provider_type, {}).get(audio_mode, 0)
        secs = seconds or 10
        label = _("Music") if audio_mode == "music" else _("Sound effect")
        return {**base, "cost": round(rate * secs, 4), "detail": "%ss" % pricing.fmt_number(secs), "model": label,
                "model_id": None, "known": bool(rate)}
    if model:
        cost, detail = pricing.estimate(model, prompt, seconds or (8 if capability == catalog.VIDEO else 0),
                                        provider.max_tokens)
        return {**base, "cost": round(cost, 4), "detail": detail, "model": model.label, "model_id": model.id,
                "known": True}
    return {**base, "cost": 0.0, "detail": "", "model": name, "model_id": None, "known": False}


def picker(db: Session, workspace_id: int, capability: str) -> list[dict]:
    """Models for a dropdown, grouped by provider, with price and wallet."""
    spent_map = spent_by_provider(db, workspace_id)
    groups = []
    for provider in list_providers(db, workspace_id, capability, active_only=True):
        default_name = default_model_name(provider, capability)
        options = [{"id": m.id, "name": m.name, "label": m.label, "unit": m.unit, "price": m.price,
                    "price_in": m.price_in, "price_out": m.price_out, "price_label": pricing.price_label(m),
                    "default": m.name == default_name}
                   for m in provider_models(db, provider, capability)]
        groups.append({"provider_id": provider.id, "provider": provider.name, "provider_type": provider.provider_type,
                       "is_default": provider.is_default, "has_key": bool(provider.api_key),
                       "state": provider.state, "models": options,
                       "wallet": wallet(db, provider, spent_map.get(provider.id, (0.0, 0.0))[0])})
    return groups


# ------------------------------------------------------------------ actions
def test_connection(db: Session, provider: AIProvider) -> dict:
    """Light call proving the key works; stores the list of models when the API returns one."""
    from .clients import get_client
    from .generators import get_media_client
    try:
        if catalog.can(provider.provider_type, catalog.TEXT):
            models = get_client(provider).list_models()
        else:
            models = get_media_client(provider).test()
    except ApiError as exc:
        provider.state, provider.last_error, provider.tested_at = "error", exc.message[:1000], utcnow()
        db.flush()
        return {"ok": False, "message": exc.message, "models": [], "warning": None}
    provider.state, provider.last_error, provider.tested_at = "ok", None, utcnow()
    provider.available_models = list(models[:300]) or None
    db.flush()
    warning = None
    if models and catalog.can(provider.provider_type, catalog.TEXT) and provider.text_model \
            and provider.text_model not in models and provider.provider_type not in ("azure_openai",):
        warning = _("Warning: model “{model}” is not in the list.", model=provider.text_model)
    message = _("Connected! {count} models available.", count=len(models)) if models else _("Connected!")
    return {"ok": True, "message": message, "models": list(models[:300]), "warning": warning}


def refresh_balance(db: Session, provider: AIProvider) -> dict:
    if not supports_balance(provider.provider_type):
        raise AppError(_("This provider does not share its balance through the API."), code="balance_unsupported")
    result = fetch_balance(provider)
    provider.balance, provider.balance_unit = result["amount"], result["unit"]
    provider.balance_checked_at = utcnow()
    db.flush()
    return result
