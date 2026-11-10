"""AI providers of a workspace (bring-your-own-key), model price list, usage/costs and media generation jobs.

These tables are shared by every feature. The AI builder owns the services in this package; other features
only call the functions documented in ``app/modules/ai/service.py`` and ``app/modules/ai/media.py``.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedString
from app.core.db import Base, WorkspaceMixin

CAPABILITIES = ("text", "image", "video", "audio", "stt")


class AIProvider(WorkspaceMixin, Base):
    __tablename__ = "ai_providers"

    name: Mapped[str] = mapped_column(String(120))
    provider_type: Mapped[str] = mapped_column(String(40))  # openai, anthropic, gemini, elevenlabs… (see catalog)
    api_key: Mapped[str | None] = mapped_column(EncryptedString(1000))
    base_url: Mapped[str | None] = mapped_column(String(500))
    text_model: Mapped[str | None] = mapped_column(String(120))
    image_model: Mapped[str | None] = mapped_column(String(120))
    video_model: Mapped[str | None] = mapped_column(String(120))
    audio_model: Mapped[str | None] = mapped_column(String(120))
    voice: Mapped[str | None] = mapped_column(String(120))
    max_tokens: Mapped[int] = mapped_column(Integer, default=4000)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # default for text
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(20), default="draft")  # draft | ok | error
    last_error: Mapped[str | None] = mapped_column(Text)
    balance: Mapped[float | None] = mapped_column(Float)
    balance_unit: Mapped[str | None] = mapped_column(String(20))
    balance_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monthly_budget: Mapped[float | None] = mapped_column(Float)
    sequence: Mapped[int] = mapped_column(Integer, default=10)
    available_models: Mapped[list | None] = mapped_column(JSON)  # ids returned by the last connection test
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIModel(WorkspaceMixin, Base):
    """A model a provider offers, with its list price (used for estimates and costs)."""

    __tablename__ = "ai_models"

    provider_id: Mapped[int] = mapped_column(ForeignKey("ai_providers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))  # model id at the provider
    label: Mapped[str] = mapped_column(String(160))
    capability: Mapped[str] = mapped_column(String(10), default="text")
    unit: Mapped[str] = mapped_column(String(20), default="tokens")  # tokens | image | second | 1k_chars | minute | free
    price_in: Mapped[float] = mapped_column(Float, default=0.0)  # $ per 1M input tokens
    price_out: Mapped[float] = mapped_column(Float, default=0.0)  # $ per 1M output tokens
    price: Mapped[float] = mapped_column(Float, default=0.0)  # $ per unit for non-token units
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sequence: Mapped[int] = mapped_column(Integer, default=10)


class AIUsage(WorkspaceMixin, Base):
    """One AI call and its approximate cost (feeds budgets, plan credits and the cost dashboards)."""

    __tablename__ = "ai_usage"

    provider_id: Mapped[int | None] = mapped_column(ForeignKey("ai_providers.id", ondelete="SET NULL"), index=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("ai_models.id", ondelete="SET NULL"))
    model_name: Mapped[str | None] = mapped_column(String(120))
    capability: Mapped[str] = mapped_column(String(10), default="text")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[float] = mapped_column(Float, default=0.0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    purpose: Mapped[str | None] = mapped_column(String(160))  # "inbox reply", "post caption", "board 12 / node 4"…
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class MediaJob(WorkspaceMixin, Base):
    """An AI image / video / audio generation. Images and audio usually finish at once; video is polled."""

    __tablename__ = "media_jobs"

    kind: Mapped[str] = mapped_column(String(10))  # image | video | audio
    prompt: Mapped[str] = mapped_column(Text)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("ai_providers.id", ondelete="SET NULL"))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("ai_models.id", ondelete="SET NULL"))
    model_name: Mapped[str | None] = mapped_column(String(120))
    aspect: Mapped[str] = mapped_column(String(5), default="1:1")
    style: Mapped[str | None] = mapped_column(String(30))
    seconds: Mapped[int] = mapped_column(Integer, default=8)
    audio_mode: Mapped[str] = mapped_column(String(10), default="speech")  # speech | sfx | music
    voice: Mapped[str | None] = mapped_column(String(120))
    input_media_ids: Mapped[list | None] = mapped_column(JSON)  # reference images / image to animate
    state: Mapped[str] = mapped_column(String(10), default="running", index=True)  # running | done | failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    external_job: Mapped[str | None] = mapped_column(String(255))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    error: Mapped[str | None] = mapped_column(Text)
    notice: Mapped[str | None] = mapped_column(String(500))
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    # who to tell when it finishes: dotted path of a function(db, job) + free context (e.g. {"node_id": 4})
    callback: Mapped[str | None] = mapped_column(String(200))
    callback_context: Mapped[dict | None] = mapped_column(JSON)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
