"""AI endpoints: provider management (admin), model price lists, pickers & estimates, "Write with AI",
media generation jobs, transcription, usage & costs."""
from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.deps import Ctx, workspace_ctx
from app.core.errors import AppError, NotFound
from app.core.http import ApiError
from app.core.i18n import _
from app.core.models import Media
from app.modules.auth.models import User
from app.modules.workspaces.models import Role

from . import catalog, media, pricing, prompts
from . import providers as prov
from . import service as ai
from .balance import supports_balance
from .models import AIModel, AIProvider, AIUsage, MediaJob
from .schemas import (
    BalanceOut,
    CatalogEntry,
    CatalogModel,
    CostRow,
    DayRow,
    EstimateIn,
    EstimateOut,
    JobCheckIn,
    JobMedia,
    MediaJobIn,
    MediaJobOut,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    PickerOut,
    ProviderBudget,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
    StatusOut,
    SuggestVisualIn,
    SuggestVisualOut,
    TestResult,
    TranscribeIn,
    TranscribeOut,
    UsageOut,
    UsagePage,
    UsageSummary,
    Wallet,
    WriteIn,
    WriteOut,
)

router = APIRouter(prefix="/ai", tags=["ai"])


# ------------------------------------------------------------------ helpers
def provider_out(db, provider: AIProvider, spent_map: dict | None = None) -> ProviderOut:
    if spent_map is None:
        spent_map = prov.spent_by_provider(db, provider.workspace_id)
    month, total = spent_map.get(provider.id, (0.0, 0.0))
    meta = catalog.info(provider.provider_type)
    count = db.scalar(select(func.count(AIModel.id)).where(AIModel.provider_id == provider.id,
                                                           AIModel.workspace_id == provider.workspace_id)) or 0
    return ProviderOut(
        id=provider.id, name=provider.name, provider_type=provider.provider_type, type_label=meta["label"],
        capabilities=catalog.ordered_caps(provider.provider_type), has_key=bool(provider.api_key),
        base_url=provider.base_url, text_model=provider.text_model, image_model=provider.image_model,
        video_model=provider.video_model, audio_model=provider.audio_model, voice=provider.voice,
        max_tokens=provider.max_tokens or 4000, is_default=provider.is_default, active=provider.active,
        state=provider.state, last_error=provider.last_error, tested_at=provider.tested_at,
        available_models=provider.available_models or [], key_url=meta.get("key_url"),
        balance_supported=supports_balance(provider.provider_type), balance=provider.balance,
        balance_unit=provider.balance_unit, balance_checked_at=provider.balance_checked_at,
        monthly_budget=provider.monthly_budget, spent_month=round(month, 4), spent_total=round(total, 4),
        wallet=Wallet(**prov.wallet(db, provider, month)), models_count=count, sequence=provider.sequence)


def model_out(model: AIModel) -> ModelOut:
    out = ModelOut.model_validate(model)
    out.price_label = pricing.price_label(model)
    return out


def job_out(db, job: MediaJob) -> MediaJobOut:
    provider = db.get(AIProvider, job.provider_id) if job.provider_id else None
    file = db.get(Media, job.media_id) if job.media_id else None
    title = (job.prompt or "").strip().splitlines()[0][:60] if job.prompt else job.kind
    return MediaJobOut(
        id=job.id, kind=job.kind, state=job.state, progress=job.progress or 0, prompt=job.prompt, title=title,
        aspect=job.aspect, style=job.style, seconds=job.seconds, audio_mode=job.audio_mode, voice=job.voice,
        provider_id=job.provider_id, provider=provider.name if provider else None, model_name=job.model_name,
        input_media_ids=job.input_media_ids or [], media_id=job.media_id,
        media=JobMedia(id=file.id, filename=file.filename, mimetype=file.mimetype, url=f"/api/media/{file.id}/file",
                       width=file.width, height=file.height, duration=file.duration) if file else None,
        error=job.error, notice=job.notice, cost=round(job.cost or 0.0, 4), created_at=job.created_at,
        updated_at=job.updated_at)


def _job(ctx: Ctx, job_id: int) -> MediaJob:
    job = ctx.db.get(MediaJob, job_id)
    if not job or job.workspace_id != ctx.workspace.id:
        raise NotFound(_("Generation not found."), code="not_found")
    return job


# ------------------------------------------------------------------ catalog & status
@router.get("/catalog", response_model=list[CatalogEntry])
def get_catalog(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    entries = []
    for key, meta in catalog.CATALOG.items():
        models = [CatalogModel(name=n, label=lbl, capability=cap, unit=unit, price_in=p_in, price_out=p_out,
                               price=price, price_label=pricing.price_label(
                                   AIModel(unit=unit, price_in=p_in, price_out=p_out, price=price)))
                  for n, cap, unit, p_in, p_out, price, lbl in pricing.entries(key)]
        entries.append(CatalogEntry(
            type=key, label=meta["label"], capabilities=catalog.ordered_caps(key), engine=meta.get("engine"),
            base_url=meta.get("base_url") or "", needs_base_url=bool(meta.get("needs_base_url")),
            no_key=bool(meta.get("no_key")), key_url=meta.get("key_url"),
            default_models={k: v for k, v in meta.get("models", {}).items() if v}, voice=meta.get("voice"),
            max_tokens=meta.get("max_tokens", 4000), balance_supported=supports_balance(key), models=models))
    return entries


@router.get("/status", response_model=StatusOut)
def status(ctx: Ctx = Depends(workspace_ctx())):
    default = prov.default_text_provider(ctx.db, ctx.workspace.id)
    caps = {c: ai.has_provider(ctx.db, ctx.workspace.id, c) for c in catalog.CAPS_ORDER}
    return StatusOut(**caps, default_provider=default.name if default else None)


# ------------------------------------------------------------------ providers (admin)
@router.get("/providers", response_model=list[ProviderOut])
def list_providers(ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    spent_map = prov.spent_by_provider(ctx.db, ctx.workspace.id)
    return [provider_out(ctx.db, p, spent_map) for p in prov.list_providers(ctx.db, ctx.workspace.id)]


@router.post("/providers", response_model=ProviderOut, status_code=201)
def create_provider(data: ProviderCreate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    provider = prov.create_provider(ctx.db, ctx.workspace.id, data.model_dump())
    return provider_out(ctx.db, provider)


@router.get("/providers/{provider_id}", response_model=ProviderOut)
def get_provider(provider_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    return provider_out(ctx.db, prov.get_provider(ctx.db, ctx.workspace.id, provider_id))


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: int, data: ProviderUpdate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    provider = prov.get_provider(ctx.db, ctx.workspace.id, provider_id)
    values = data.model_dump(exclude_unset=True)
    for key in ("name", "max_tokens", "active", "sequence"):
        if key in values and values[key] is None:
            values.pop(key)
    if "api_key" in values:
        values["api_key"] = (values["api_key"] or "").strip() or None
    prov.update_provider(ctx.db, provider, values)
    return provider_out(ctx.db, provider)


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    prov.delete_provider(ctx.db, prov.get_provider(ctx.db, ctx.workspace.id, provider_id))


@router.post("/providers/{provider_id}/test", response_model=TestResult)
def test_provider(provider_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    provider = prov.get_provider(ctx.db, ctx.workspace.id, provider_id)
    result = prov.test_connection(ctx.db, provider)
    return TestResult(**result, provider=provider_out(ctx.db, provider))


@router.post("/providers/{provider_id}/try", response_model=TestResult)
def try_provider(provider_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Quick sanity check that text generation really works (costs a few tokens)."""
    provider = prov.get_provider(ctx.db, ctx.workspace.id, provider_id)
    if not catalog.can(provider.provider_type, catalog.TEXT):
        raise AppError(_("This provider does not write text."), code="not_text_provider")
    try:
        text = ai.generate_text(ctx.db, ctx.workspace.id, "You are a helpful assistant.",
                                "Reply with one short friendly sentence confirming you work.",
                                provider_id=provider.id, purpose=_("Provider test"), max_tokens=provider.max_tokens,
                                user_id=ctx.user.id)
    except ApiError as exc:
        provider.state, provider.last_error = "error", exc.message[:1000]
        return TestResult(ok=False, message=exc.message, provider=provider_out(ctx.db, provider))
    provider.state, provider.last_error = "ok", None
    return TestResult(ok=True, message=text[:300], provider=provider_out(ctx.db, provider))


@router.post("/providers/{provider_id}/default", response_model=ProviderOut)
def set_default(provider_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    provider = prov.get_provider(ctx.db, ctx.workspace.id, provider_id)
    prov.set_default(ctx.db, provider)
    return provider_out(ctx.db, provider)


@router.post("/providers/{provider_id}/balance", response_model=BalanceOut)
def refresh_balance(provider_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    provider = prov.get_provider(ctx.db, ctx.workspace.id, provider_id)
    try:
        result = prov.refresh_balance(ctx.db, provider)
    except ApiError as exc:
        return BalanceOut(ok=False, message=exc.message, provider=provider_out(ctx.db, provider))
    amount = pricing.fmt(round(result["amount"], 2))
    return BalanceOut(ok=True, message=_("Balance: {amount} {unit}", amount=amount, unit=result["unit"]),
                      provider=provider_out(ctx.db, provider))


# ------------------------------------------------------------------ model price list (admin)
@router.get("/providers/{provider_id}/models", response_model=list[ModelOut])
def list_models(provider_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    provider = prov.get_provider(ctx.db, ctx.workspace.id, provider_id)
    return [model_out(m) for m in prov.provider_models(ctx.db, provider, active_only=False)]


@router.post("/providers/{provider_id}/models", response_model=ModelOut, status_code=201)
def create_model(provider_id: int, data: ModelCreate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    provider = prov.get_provider(ctx.db, ctx.workspace.id, provider_id)
    if prov.find_model(ctx.db, provider, data.name.strip(), data.capability):
        raise AppError(_("This model is already in the list."), code="duplicate_model")
    values = data.model_dump()
    values["name"] = values["name"].strip()
    values["label"] = (values.get("label") or "").strip() or values["name"]
    model = AIModel(workspace_id=ctx.workspace.id, provider_id=provider.id, **values)
    ctx.db.add(model)
    ctx.db.flush()
    return model_out(model)


@router.post("/providers/{provider_id}/models/load-catalog", response_model=list[ModelOut])
def load_catalog_models(provider_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    """Add the catalog models that are missing from the provider's price list (existing prices are kept)."""
    provider = prov.get_provider(ctx.db, ctx.workspace.id, provider_id)
    prov.seed_models(ctx.db, provider)
    return [model_out(m) for m in prov.provider_models(ctx.db, provider, active_only=False)]


@router.patch("/models/{model_id}", response_model=ModelOut)
def update_model(model_id: int, data: ModelUpdate, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    model = prov.get_model(ctx.db, ctx.workspace.id, model_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(model, key, value.strip() if isinstance(value, str) else value)
    ctx.db.flush()
    return model_out(model)


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: int, ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    ctx.db.delete(prov.get_model(ctx.db, ctx.workspace.id, model_id))


# ------------------------------------------------------------------ pickers & estimates (editor)
@router.get("/pickers", response_model=PickerOut)
def pickers(capability: str = Query("text", pattern="^(text|image|video|audio|stt)$"),
            ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    return PickerOut(capability=capability, groups=prov.picker(ctx.db, ctx.workspace.id, capability))


@router.post("/estimate", response_model=EstimateOut)
def estimate(data: EstimateIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    if data.model_id:
        prov.get_model(ctx.db, ctx.workspace.id, data.model_id)
    if data.provider_id:
        prov.get_provider(ctx.db, ctx.workspace.id, data.provider_id)
    return prov.estimate_task(ctx.db, ctx.workspace.id, data.capability, prompt=data.prompt, seconds=data.seconds,
                              audio_mode=data.audio_mode, model_id=data.model_id, provider_id=data.provider_id)


# ------------------------------------------------------------------ text
def _platforms(ctx: Ctx, data: WriteIn) -> list[str]:
    platforms = [p for p in data.platforms if p in prompts.PLATFORM_LIMITS]
    if data.account_ids:
        from app.modules.social.models import SocialAccount
        rows = ctx.db.scalars(select(SocialAccount.platform).where(SocialAccount.workspace_id == ctx.workspace.id,
                                                                   SocialAccount.id.in_(data.account_ids)))
        platforms += list(rows)
    return sorted(set(platforms))


def _brand_profile(ctx: Ctx, brand_kit_id: int | None) -> str:
    from app.modules.brand import service as brand
    kit = brand.get_kit(ctx.db, ctx.workspace.id, brand_kit_id) if brand_kit_id \
        else brand.default_kit(ctx.db, ctx.workspace.id)
    return kit.llm_profile() if kit else ""


@router.post("/text", response_model=WriteOut)
def write(data: WriteIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Composer "Write with AI": brief (+ tone, language, length, platforms…) → ready-to-publish text."""
    if not data.brief.strip() and not data.current_text.strip():
        raise AppError(_("Describe what the post is about."), code="empty_brief")
    platforms = _platforms(ctx, data)
    profile = _brand_profile(ctx, data.brand_kit_id)
    tailor = data.preset == "post" and data.tailor and len(platforms) > 1
    if data.preset == "post" and not data.system:
        system, user = prompts.build_prompts(profile, data.brief, data.tone, data.language, data.length, platforms,
                                             hashtags=data.hashtags, emojis=data.emojis, tailor=tailor,
                                             current_text=data.current_text)
    else:
        system = data.system or prompts.PRESETS.get(data.preset) or prompts.PRESETS["free"]
        if profile:
            system += "\n\nBrand profile and voice to respect:\n%s" % profile
        if data.language and data.language != "auto":
            system += "\nWrite in %s." % prompts.LANGUAGES.get(data.language, data.language)
        user = data.brief
        if data.current_text:
            user = "%s\n\n<<<\n%s\n>>>" % (user or "Improve this text.", data.current_text)
    purpose = {"post": _("Post caption"), "reply": _("Reply"), "ideas": _("Post ideas"), "hashtags": _("Hashtags"),
               "rewrite": _("Rewrite")}.get(data.preset) or _("AI text")
    text, usage = ai.generate_text_with_usage(ctx.db, ctx.workspace.id, system, user, model_id=data.model_id,
                                              provider_id=data.provider_id, purpose="%s: %s" % (
                                                  purpose, (data.brief or data.current_text)[:100]),
                                              user_id=ctx.user.id)
    main, variants = prompts.parse_answer(text, tailor=tailor, platforms=platforms)
    return WriteOut(text=main, variants=variants, provider=usage.provider, model=usage.model,
                    cost=round(usage.cost, 6), tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)


@router.post("/suggest-visual", response_model=SuggestVisualOut)
def suggest_visual(data: SuggestVisualIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Turn a post text into a strong prompt for an image or video model."""
    system = prompts.VISUAL_SYSTEM.format(kind="video" if data.kind == "video" else "image")
    if data.kind == "video":
        system += " Describe camera movement and what happens in 5-8 seconds."
    if data.brand_kit_id:
        from app.modules.brand import service as brand
        hint = brand.get_kit(ctx.db, ctx.workspace.id, data.brand_kit_id).visual_hint()
        if hint:
            system += " Respect the brand: %s" % hint
    text, usage = ai.generate_text_with_usage(ctx.db, ctx.workspace.id, system, "Social media post:\n%s" % data.text,
                                              model_id=data.model_id, purpose=_("Visual prompt"), user_id=ctx.user.id)
    return SuggestVisualOut(prompt=prompts.clean(text), cost=round(usage.cost, 6))


# ------------------------------------------------------------------ media jobs
@router.post("/media", response_model=MediaJobOut, status_code=201)
def start_media(data: MediaJobIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    if data.model_id:
        prov.get_model(ctx.db, ctx.workspace.id, data.model_id)
    job = media.start_job(ctx.db, ctx.workspace.id, data.kind, data.prompt, provider_id=data.provider_id,
                          model_id=data.model_id, aspect=data.aspect, style=data.style, seconds=data.seconds,
                          audio_mode=data.audio_mode, voice=data.voice, inputs=data.input_media_ids,
                          user_id=ctx.user.id, brand_kit_id=data.brand_kit_id)
    return job_out(ctx.db, job)


@router.get("/jobs", response_model=list[MediaJobOut])
def list_jobs(kind: str | None = Query(None, pattern="^(image|video|audio)$"),
              state: str | None = Query(None, pattern="^(running|done|failed)$"),
              limit: int = Query(30, ge=1, le=200), ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    query = select(MediaJob).where(MediaJob.workspace_id == ctx.workspace.id).order_by(MediaJob.id.desc()).limit(limit)
    if kind:
        query = query.where(MediaJob.kind == kind)
    if state:
        query = query.where(MediaJob.state == state)
    return [job_out(ctx.db, j) for j in ctx.db.scalars(query)]


@router.post("/jobs/check", response_model=list[MediaJobOut])
def check_jobs(data: JobCheckIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    """Called by the UI every few seconds while something is being created: polls the due jobs."""
    ids = list(dict.fromkeys(data.ids))
    media.poll_due(ctx.db, ctx.workspace.id, job_ids=ids, limit=len(ids) or 1)
    jobs = ctx.db.scalars(select(MediaJob).where(MediaJob.workspace_id == ctx.workspace.id,
                                                 MediaJob.id.in_(ids)).order_by(MediaJob.id)) if ids else []
    return [job_out(ctx.db, j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=MediaJobOut)
def get_job(job_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    return job_out(ctx.db, _job(ctx, job_id))


@router.post("/jobs/{job_id}/retry", response_model=MediaJobOut)
def retry_job(job_id: int, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    job = _job(ctx, job_id)
    provider = ctx.db.get(AIProvider, job.provider_id) if job.provider_id else None
    if provider and job.state == "failed":
        quote = prov.estimate_task(ctx.db, ctx.workspace.id, job.kind, prompt=job.prompt, seconds=job.seconds,
                                   audio_mode=job.audio_mode, model_id=job.model_id, provider_id=provider.id)
        prov.check_spend(ctx.db, provider, quote["cost"])
    return job_out(ctx.db, media.retry(ctx.db, job))


@router.post("/transcribe", response_model=TranscribeOut)
def transcribe(data: TranscribeIn, ctx: Ctx = Depends(workspace_ctx(Role.editor))):
    return media.transcribe(ctx.db, ctx.workspace.id, data.media_id, data.language, provider_id=data.provider_id,
                            model_id=data.model_id, user_id=ctx.user.id)


# ------------------------------------------------------------------ usage & costs (admin)
def _range(ctx: Ctx, date_from: date | None, date_to: date | None) -> tuple[date, date, datetime, datetime, str]:
    tz_name = ctx.workspace.timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz, tz_name = ZoneInfo("UTC"), "UTC"
    today = datetime.now(tz).date()
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=29))
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    start = datetime.combine(date_from, time.min, tz).astimezone(UTC)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tz).astimezone(UTC)
    return date_from, date_to, start, end, tz_name


@router.get("/usage", response_model=UsagePage)
def usage(provider_id: int | None = None, capability: str | None = None, date_from: date | None = None,
          date_to: date | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
          ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    _df, _dt, start, end, _tz = _range(ctx, date_from, date_to)
    where = [AIUsage.workspace_id == ctx.workspace.id, AIUsage.created_at >= start, AIUsage.created_at < end]
    if provider_id:
        where.append(AIUsage.provider_id == provider_id)
    if capability:
        where.append(AIUsage.capability == capability)
    total = ctx.db.scalar(select(func.count(AIUsage.id)).where(*where)) or 0
    rows = ctx.db.execute(select(AIUsage, AIProvider.name, User.name)
                          .outerjoin(AIProvider, AIProvider.id == AIUsage.provider_id)
                          .outerjoin(User, User.id == AIUsage.user_id)
                          .where(*where).order_by(AIUsage.created_at.desc(), AIUsage.id.desc()).limit(limit)
                          .offset(offset)).all()
    items = [UsageOut(id=u.id, created_at=u.created_at, provider_id=u.provider_id, provider=pname,
                      model_name=u.model_name, capability=u.capability, tokens_in=u.tokens_in, tokens_out=u.tokens_out,
                      units=u.units, cost=u.cost, purpose=u.purpose, user_id=u.user_id, user_name=uname)
             for u, pname, uname in rows]
    return UsagePage(items=items, total=total)


@router.get("/usage/summary", response_model=UsageSummary)
def usage_summary(date_from: date | None = None, date_to: date | None = None,
                  ctx: Ctx = Depends(workspace_ctx(Role.admin))):
    date_from, date_to, start, end, tz_name = _range(ctx, date_from, date_to)
    db, ws_id = ctx.db, ctx.workspace.id
    where = [AIUsage.workspace_id == ws_id, AIUsage.created_at >= start, AIUsage.created_at < end]
    total_cost, total_calls = db.execute(select(func.coalesce(func.sum(AIUsage.cost), 0.0), func.count(AIUsage.id))
                                         .where(*where)).one()

    def grouped(column, label_column=None, outer=None):
        cols = [column, label_column] if label_column is not None else [column]
        query = select(*cols, func.sum(AIUsage.cost), func.count(AIUsage.id)).where(*where)
        if outer is not None:
            query = query.outerjoin(*outer)
        query = query.group_by(*cols).order_by(func.sum(AIUsage.cost).desc())
        return db.execute(query).all()

    by_provider = [CostRow(key=str(pid or 0), label=name or _("Removed provider"), cost=round(cost or 0, 6), calls=n)
                   for pid, name, cost, n in grouped(AIUsage.provider_id, AIProvider.name,
                                                     (AIProvider, AIProvider.id == AIUsage.provider_id))]
    by_model = [CostRow(key=name or "", label=name or "—", cost=round(cost or 0, 6), calls=n)
                for name, cost, n in grouped(AIUsage.model_name)]
    by_capability = [CostRow(key=cap, label=cap, cost=round(cost or 0, 6), calls=n)
                     for cap, cost, n in grouped(AIUsage.capability)]
    local_day = func.date(func.timezone(tz_name, AIUsage.created_at))
    days = {d: (cost, n) for d, cost, n in db.execute(
        select(local_day, func.sum(AIUsage.cost), func.count(AIUsage.id)).where(*where).group_by(local_day)).all()}
    by_day, cursor = [], date_from
    while cursor <= date_to and len(by_day) < 400:
        cost, n = days.get(cursor, (0.0, 0))
        by_day.append(DayRow(day=cursor, cost=round(cost or 0, 6), calls=n or 0))
        cursor += timedelta(days=1)
    month_key = func.to_char(func.timezone(tz_name, AIUsage.created_at), "YYYY-MM")
    year_ago = prov.month_start() - timedelta(days=365)
    by_month = [CostRow(key=k, label=k, cost=round(cost or 0, 6), calls=n) for k, cost, n in db.execute(
        select(month_key, func.sum(AIUsage.cost), func.count(AIUsage.id))
        .where(AIUsage.workspace_id == ws_id, AIUsage.created_at >= year_ago).group_by(month_key)
        .order_by(month_key)).all()]
    spent_map = prov.spent_by_provider(db, ws_id)
    budgets = [ProviderBudget(provider_id=p.id, provider=p.name, spent_month=round(spent_map.get(p.id, (0, 0))[0], 4),
                              monthly_budget=p.monthly_budget,
                              wallet=Wallet(**prov.wallet(db, p, spent_map.get(p.id, (0.0, 0.0))[0])))
               for p in prov.list_providers(db, ws_id)]
    month_cost = prov.spent(db, ws_id, since=prov.month_start())
    return UsageSummary(date_from=date_from, date_to=date_to, total_cost=round(total_cost or 0, 6),
                        total_calls=total_calls or 0, month_cost=round(month_cost, 6), by_provider=by_provider,
                        by_model=by_model, by_capability=by_capability, by_day=by_day, by_month=by_month,
                        budgets=budgets)
