"""AI media generation API used by other features — CONTRACT (implemented by the AI feature).

    from app.modules.ai import media as ai_media
    job = ai_media.start_job(db, ws_id, "image", "A cozy cafe…", aspect="4:5", inputs=[media_id],
                             callback="app.modules.production.engine.on_media_job", callback_context={"node_id": 4})
    # image/audio jobs are usually done when start_job returns (job.state == "done", job.media_id set);
    # video jobs stay "running" and are polled by a periodic task; the callback is called when they finish.
    ai_media.estimate(db, ws_id, "video", prompt, seconds=8, model_id=None) -> {"cost": 0.8, "model": "..."}
    # shot={"lens": "85", "light": "golden_hour", …} adds camera settings (camera.py); the brand guard
    # (brand/guard.py) applies the picked kit, or the default kit when its guard is strict.
    ai_media.transcribe(db, ws_id, media_id, language="ar") -> {"segments": [...], "duration": 12.3, "cost": 0.001}

The callback is a dotted path to ``fn(db, job)``; it is called once when the job is ``done`` or ``failed`` — also
when that happens immediately inside ``start_job``. Errors inside a callback are logged and never fail the job.
``start_job`` raises ``AppError`` before creating anything when no provider can do the kind
(``no_media_provider``), the prompt is empty, or the monthly budget is used up (``ai_budget_exceeded``).
Provider failures do not raise: the job is returned with ``state == "failed"`` and ``error`` set.
"""
import importlib
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.core.http import ApiError
from app.core.i18n import _, set_locale
from app.core.models import Media
from app.core.storage import public_url, read_media, save_media

from . import catalog
from . import providers as prov
from .generators import ASPECTS, MediaInput, download, get_media_client
from .models import AIProvider, MediaJob

_logger = logging.getLogger(__name__)

KINDS = ("image", "video", "audio")
AUDIO_MODES = ("speech", "sfx", "music")
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4",
              "video/quicktime": "mov", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav"}
DEFAULT_MIME = {"image": "image/png", "video": "video/mp4", "audio": "audio/mpeg"}
POLL_EVERY = timedelta(seconds=10)
CALLBACK_PATH = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+$")
TIMEOUT = timedelta(hours=2)

STYLE_PROMPTS = {
    "photo": "Photorealistic, natural light, high detail, professional photography.",
    "illustration": "Modern digital illustration, clean shapes, vibrant colors.",
    "3d": "Polished 3D render, soft studio lighting, depth of field.",
    "minimal": "Minimal flat design, plenty of empty space, simple palette.",
    "cinematic": "Cinematic wide shot, dramatic lighting, film color grading.",
    "product": "Studio product photography on a clean background, soft shadows, sharp focus.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def full_prompt(job: MediaJob) -> str:
    parts = [job.prompt]
    if job.kind in ("image", "video") and job.style and job.style in STYLE_PROMPTS:
        parts.append("Style: %s" % STYLE_PROMPTS[job.style])
    if job.kind in ("image", "video"):
        from . import camera
        parts.append(camera.describe(job.shot, job.kind))
    return "\n\n".join(p for p in parts if p)


# ------------------------------------------------------------------ public contract
def start_job(db: Session, workspace_id: int, kind: str, prompt: str, *, provider_id: int | None = None,
              model_id: int | None = None, aspect: str = "1:1", style: str | None = None, seconds: int = 8,
              audio_mode: str = "speech", voice: str | None = None, inputs: list[int] | None = None,
              callback: str | None = None, callback_context: dict | None = None,
              user_id: int | None = None, brand_kit_id: int | None = None, shot: dict | None = None) -> MediaJob:
    if kind not in KINDS:
        raise AppError(_("Unknown media type."), code="bad_kind")
    prompt = (prompt or "").strip()
    if not prompt:
        raise AppError(_("Describe what you want to create."), code="empty_prompt")
    audio_mode = audio_mode if audio_mode in AUDIO_MODES else "speech"
    aspect = aspect if aspect in ASPECTS else "1:1"
    seconds = max(1, min(int(seconds or 8), 300))
    input_ids = _check_inputs(db, workspace_id, inputs)
    if callback and not CALLBACK_PATH.match(callback):
        raise AppError(_("Invalid callback."), code="bad_callback")
    from app.modules.brand import guard
    kit = guard.kit_for(db, workspace_id, brand_kit_id)  # the picked kit, or the default one when it is strict
    camera_shot = None
    if kind in ("image", "video"):
        prompt, camera_shot = guard.visual(kit, kind, prompt, shot)
    elif kind == "audio" and audio_mode == "speech" and not voice and kit and kit.voice:
        voice = kit.voice

    provider, model, model_name = prov.resolve(db, workspace_id, kind, model_id=model_id, provider_id=provider_id)
    quote = prov.estimate_task(db, workspace_id, kind, prompt=prompt, seconds=seconds, audio_mode=audio_mode,
                               model_id=model.id if model else None, provider_id=provider.id)
    prov.check_spend(db, provider, quote["cost"], user_id)

    job = MediaJob(workspace_id=workspace_id, kind=kind, prompt=prompt, provider_id=provider.id, shot=camera_shot,
                   brand_kit_id=kit.id if kit else None,
                   model_id=model.id if model else None, model_name=model_name or None, aspect=aspect,
                   style=style or None, seconds=seconds, audio_mode=audio_mode, voice=voice or None,
                   input_media_ids=input_ids or None, state="running", progress=0, callback=callback,
                   callback_context=callback_context, user_id=user_id)
    db.add(job)
    db.flush()
    run(db, job)
    return job


def sound_provider(db: Session, workspace_id: int, mode: str, provider_id: int | None = None) -> AIProvider | None:
    """A provider that can really make ``mode`` ("music" / "sfx"): the one asked for when it can, else the first
    of the workspace's own providers that can, else the platform's (e.g. ElevenLabs). None when nobody can."""
    from .generators import CLIENTS
    flag = "supports_music" if mode == "music" else "supports_sfx"
    able = lambda p: p is not None and getattr(CLIENTS.get(p.provider_type), flag, False)  # noqa: E731
    if provider_id:
        asked = db.get(AIProvider, provider_id)
        if asked and asked.workspace_id == workspace_id and asked.active and able(asked):
            return asked
    for provider in prov.list_providers(db, workspace_id, "audio", active_only=True):
        if able(provider):
            return provider
    types = tuple(t for t, cls in CLIENTS.items() if getattr(cls, flag, False))
    managed = prov.platform_provider(db, workspace_id, "audio", types=types)
    return managed if able(managed) else None


def sound_possible(db: Session, workspace_id: int, mode: str, provider_id: int | None = None) -> bool:
    """Like ``sound_provider`` but read-only (no platform provider row is created): for previews and estimates."""
    from app.modules.billing import platform

    from .generators import CLIENTS
    flag = "supports_music" if mode == "music" else "supports_sfx"
    able = lambda t: getattr(CLIENTS.get(t), flag, False)  # noqa: E731
    if provider_id:
        asked = db.get(AIProvider, provider_id)
        if asked and asked.workspace_id == workspace_id and asked.active and able(asked.provider_type):
            return True
    if any(able(p.provider_type) for p in prov.list_providers(db, workspace_id, "audio", active_only=True)):
        return True
    return any(able(t) and catalog.can(t, "audio") and platform.ai_key(db, t) for t in platform.AI_PROVIDERS)


def estimate(db: Session, workspace_id: int, kind: str, prompt: str = "", *, seconds: int = 0,
             audio_mode: str = "speech", model_id: int | None = None, provider_id: int | None = None) -> dict:
    """``{"cost", "detail", "model", "model_id", "provider", "provider_id", "wallet", "known"}``."""
    return prov.estimate_task(db, workspace_id, kind, prompt=prompt, seconds=seconds, audio_mode=audio_mode,
                              model_id=model_id, provider_id=provider_id)


def transcribe(db: Session, workspace_id: int, media_id: int, language: str | None = None, *,
               provider_id: int | None = None, model_id: int | None = None, purpose: str = "",
               user_id: int | None = None) -> dict:
    """Speech-to-text with timestamps: {"segments": [{"start","end","text"}], "duration": s, "cost": $,
    "text": "...", "model": "whisper-1", "provider": "OpenAI"}."""
    from .generators.compose import extract_audio
    from .generators.transcribe import transcribe as run_stt

    media = db.get(Media, media_id)
    if not media or media.workspace_id != workspace_id:
        raise NotFound(_("File not found."))
    if media.kind not in ("audio", "video"):
        raise AppError(_("Only audio and video files can be transcribed."), code="bad_type")
    provider, model, model_name = prov.resolve(db, workspace_id, catalog.STT, model_id=model_id,
                                               provider_id=provider_id)
    if model and media.duration:
        prov.check_spend(db, provider, media.duration / 60.0 * (model.price or 0), user_id)
    else:
        prov.check_spend(db, provider, 0.0)
    content, mimetype = read_media(media), media.mimetype
    if media.kind == "video":
        content, mimetype = extract_audio(content, mimetype), "audio/mpeg"
    segments, duration, used_model, text = run_stt(provider, content, mimetype, language, model=model_name or None)
    usage = prov.record_usage(db, provider, used_model, catalog.STT, seconds=duration,
                              purpose=purpose or _("Transcription of {name}", name=media.filename), user_id=user_id)
    if not media.duration and duration:
        media.duration = duration
    return {"segments": segments, "duration": duration, "cost": usage.cost, "text": text, "model": used_model,
            "provider": provider.name}


# ------------------------------------------------------------------ running & polling
def run(db: Session, job: MediaJob) -> None:
    """Ask the provider. Images/audio usually finish now; video keeps running and is polled."""
    try:
        provider = db.get(AIProvider, job.provider_id) if job.provider_id else None
        if not provider:
            raise ApiError(_("The AI provider of this job was removed."))
        client = get_media_client(provider, model=job.model_name, capability=job.kind)
        if job.voice:
            client.voice = job.voice
        refs = _inputs(db, job)
        notice = None
        if job.kind == "image":
            if refs and not client.supports_image_edit:
                notice = _("{provider} cannot use a reference image; created from the prompt only.",
                           provider=provider.name)
                refs = []
            result = client.image(full_prompt(job), job.aspect, refs=refs or None)
        elif job.kind == "audio":
            if job.audio_mode in ("sfx", "music"):
                supported = client.supports_music if job.audio_mode == "music" else client.supports_sfx
                if not supported:
                    what = _("music") if job.audio_mode == "music" else _("sound effects")
                    raise ApiError(_("{provider} cannot create {what}.", provider=provider.name, what=what))
                result = client.sound(job.prompt, job.audio_mode, job.seconds)
            else:
                result = client.audio(job.prompt)
        else:
            image = refs[0] if refs else None
            if image and not client.supports_image_to_video:
                notice = _("{provider} cannot animate an image; created from the prompt only.",
                           provider=provider.name)
                image = None
            result = client.video_start(full_prompt(job), job.aspect, job.seconds, image=image)
        if notice:
            job.notice = notice[:500]
        _handle(db, job, provider, result)
    except (ApiError, AppError) as exc:
        _fail(db, job, getattr(exc, "message", None) or getattr(exc, "detail", None) or str(exc))
    except Exception:  # never leave a job running forever because of a bug or a corrupt file
        _logger.exception("AI media job %s failed", job.id)
        _fail(db, job, _("Unexpected error while creating the file."))


def poll(db: Session, job: MediaJob) -> MediaJob:
    """Check a running provider job (video, slow models) once."""
    if job.state != "running":
        return job
    if job.external_job:
        try:
            provider = db.get(AIProvider, job.provider_id) if job.provider_id else None
            if not provider:
                raise ApiError(_("The AI provider of this job was removed."))
            client = get_media_client(provider, model=job.model_name, capability=job.kind)
            _handle(db, job, provider, client.video_poll(job.external_job))
        except (ApiError, AppError) as exc:
            _fail(db, job, getattr(exc, "message", None) or getattr(exc, "detail", None) or str(exc))
        except Exception:
            _logger.exception("polling AI media job %s failed", job.id)
            job.next_check_at = _now() + POLL_EVERY * 3
    created = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=UTC)
    if job.state == "running" and created < _now() - TIMEOUT:
        _fail(db, job, _("Timed out after 2 hours."))
    db.flush()
    return job


def poll_due(db: Session, workspace_id: int | None = None, job_ids: list[int] | None = None,
             limit: int = 30) -> int:
    """Poll running jobs whose next check is due. Returns how many were checked."""
    query = select(MediaJob).where(MediaJob.state == "running",
                                   or_(MediaJob.next_check_at.is_(None), MediaJob.next_check_at <= _now()))
    if workspace_id is not None:
        query = query.where(MediaJob.workspace_id == workspace_id)
    if job_ids is not None:
        query = query.where(MediaJob.id.in_(job_ids))
    jobs = list(db.scalars(query.order_by(MediaJob.next_check_at.nulls_first(), MediaJob.id).limit(limit)))
    background = workspace_id is None
    for job in jobs:
        if background:  # messages stored on the job follow the workspace language
            from app.modules.workspaces.models import Workspace
            workspace = db.get(Workspace, job.workspace_id)
            set_locale(workspace.locale if workspace else None)
        poll(db, job)
    return len(jobs)


def retry(db: Session, job: MediaJob) -> MediaJob:
    if job.state != "failed":
        return job
    job.state, job.error, job.external_job, job.progress, job.notice = "running", None, None, 0, None
    job.next_check_at = None
    db.flush()
    run(db, job)
    return job


# ------------------------------------------------------------------ internals
def _check_inputs(db: Session, workspace_id: int, inputs: list[int] | None) -> list[int]:
    ids = []
    for media_id in inputs or []:
        media = db.get(Media, int(media_id))
        if not media or media.workspace_id != workspace_id:
            raise NotFound(_("File not found."))
        ids.append(media.id)
    return ids


def _inputs(db: Session, job: MediaJob, kinds=("image",)) -> list[MediaInput]:
    refs = []
    for media_id in job.input_media_ids or []:
        media = db.get(Media, media_id)
        if not media or media.workspace_id != job.workspace_id or media.kind not in kinds:
            continue
        refs.append(MediaInput(read_media(media), media.mimetype, media.filename,
                               url_fn=lambda m=media: public_url(m)))
    return refs


def _handle(db: Session, job: MediaJob, provider: AIProvider, result: dict) -> None:
    """Store a ready file, or remember the provider job to poll later."""
    if result.get("seconds"):  # the provider rounded the duration (e.g. Sora: 4/8/12 s)
        job.seconds = int(result["seconds"])
    if result.get("job") and result.get("status", "running") == "running" and not result.get("url"):
        job.external_job, job.state = str(result["job"])[:255], "running"
        job.progress = int(result.get("progress") or 0)
        job.next_check_at = _now() + POLL_EVERY
        db.flush()
        return
    if result.get("status") == "running":
        job.progress = int(result.get("progress") or 0)
        job.next_check_at = _now() + POLL_EVERY
        db.flush()
        return
    content, mimetype = result.get("content"), result.get("mimetype")
    if not content and result.get("url"):
        content, mimetype = download(result["url"], provider, default_mimetype=DEFAULT_MIME[job.kind])
    if not content:
        raise ApiError(_("The provider returned an empty file."))
    mimetype = mimetype or DEFAULT_MIME[job.kind]
    ext = EXTENSIONS.get(mimetype, mimetype.split("/")[-1][:5])
    media = save_media(db, job.workspace_id, content, "ai-%s-%s.%s" % (job.kind, job.id, ext), mimetype,
                       source="ai", user_id=job.user_id)
    if job.kind == "video" or (job.kind == "audio" and job.audio_mode in ("sfx", "music")):
        media.duration = media.duration or float(job.seconds)
    if job.kind == "image" and job.brand_kit_id:
        _brand_check(db, job, content)
    job.media_id, job.state, job.progress, job.error, job.next_check_at = media.id, "done", 100, None, None
    _record_usage(db, job, provider)
    db.flush()
    _finish(db, job)


def _brand_check(db: Session, job: MediaJob, content: bytes) -> None:
    """Colour match of a generated image with the brand palette (a notice when it drifts)."""
    from app.modules.brand import guard
    from app.modules.brand.models import BrandKit
    match = guard.color_match(db.get(BrandKit, job.brand_kit_id), content)
    if not match:
        return
    job.brand_score = match["score"]
    if match["score"] < guard.LOW_MATCH:
        job.notice = _("The colours drift from the brand palette (match {score}%). Try again or adjust the prompt.",
                       score=match["score"])[:500]


def _record_usage(db: Session, job: MediaJob, provider: AIProvider) -> None:
    """Approximate cost of a finished generation (images, seconds of video, characters of speech)."""
    from .pricing import SOUND_PRICE_PER_SECOND
    purpose = (job.prompt or "").strip().splitlines()[0][:80] if job.prompt else job.kind
    if job.kind == "audio" and job.audio_mode in ("sfx", "music"):
        rate = SOUND_PRICE_PER_SECOND.get(provider.provider_type, {}).get(job.audio_mode, 0)
        usage = prov.record_usage(db, provider, job.audio_mode, "audio", seconds=job.seconds,
                                  cost=rate * job.seconds, purpose=purpose, user_id=job.user_id)
    elif job.kind == "image":
        usage = prov.record_usage(db, provider, job.model_name, "image", units=1, purpose=purpose,
                                  user_id=job.user_id)
    elif job.kind == "video":
        usage = prov.record_usage(db, provider, job.model_name, "video", seconds=job.seconds, purpose=purpose,
                                  user_id=job.user_id)
    else:
        usage = prov.record_usage(db, provider, job.model_name, "audio", chars=len(job.prompt or ""),
                                  purpose=purpose, user_id=job.user_id)
    job.cost = usage.charged


def _fail(db: Session, job: MediaJob, message: str) -> None:
    job.state, job.error, job.next_check_at = "failed", (message or "")[:2000], None
    db.flush()
    _finish(db, job)


def _finish(db: Session, job: MediaJob) -> None:
    if not job.callback:
        return
    try:
        module, _sep, name = job.callback.rpartition(".")
        func = getattr(importlib.import_module(module), name)
        func(db, job)
    except Exception:
        _logger.exception("callback %s of AI media job %s failed", job.callback, job.id)
