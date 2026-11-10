"""AI media generation API used by other features — CONTRACT (the AI builder implements the bodies).

    from app.modules.ai import media as ai_media
    job = ai_media.start_job(db, ws_id, "image", "A cozy cafe…", aspect="4:5", inputs=[media_id],
                             callback="app.modules.production.engine.on_media_job", callback_context={"node_id": 4})
    # image/audio jobs are usually done when start_job returns (job.state == "done", job.media_id set);
    # video jobs stay "running" and are polled by a periodic task; the callback is called when they finish.
    ai_media.estimate(db, ws_id, "video", prompt, seconds=8, model_id=None) -> {"cost": 0.8, "model": "..."}
"""
from sqlalchemy.orm import Session

from .models import MediaJob


def start_job(db: Session, workspace_id: int, kind: str, prompt: str, *, provider_id: int | None = None,
              model_id: int | None = None, aspect: str = "1:1", style: str | None = None, seconds: int = 8,
              audio_mode: str = "speech", voice: str | None = None, inputs: list[int] | None = None,
              callback: str | None = None, callback_context: dict | None = None,
              user_id: int | None = None) -> MediaJob:
    raise NotImplementedError


def estimate(db: Session, workspace_id: int, kind: str, prompt: str = "", *, seconds: int = 0,
             audio_mode: str = "speech", model_id: int | None = None, provider_id: int | None = None) -> dict:
    raise NotImplementedError


def transcribe(db: Session, workspace_id: int, media_id: int, language: str | None = None) -> dict:
    """Speech-to-text with timestamps: {"segments": [{"start","end","text"}], "duration": s, "cost": $}."""
    raise NotImplementedError
