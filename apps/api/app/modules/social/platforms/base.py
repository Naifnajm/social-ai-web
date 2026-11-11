"""Common interface of every social network publisher.

``publish(text, media)`` returns ``{"external_id": str, "url": str}``; ``media`` is a list of core ``Media`` rows.
``fetch_profile()`` returns ``{"name", "username", "avatar_url", "external_id"?}``.
``fetch_metrics(targets)`` returns ``{target_id: {impressions, reach, likes, comments, shares, saves, clicks,
video_views}}``; ``fetch_audience()`` returns ``{"followers": int}`` (or ``{}``).

Messages raised as :class:`ApiError` are English; :func:`app.core.i18n._` translates the known ones when shown.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.http import ApiError, call
from app.core.storage import public_url, read_media

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.core.models import Media

    from ..models import SocialAccount

PLATFORM_LABELS = {
    "facebook": "Facebook", "instagram": "Instagram", "linkedin": "LinkedIn", "x": "X", "tiktok": "TikTok",
    "threads": "Threads", "telegram": "Telegram", "whatsapp": "WhatsApp",
    "youtube": "YouTube", "pinterest": "Pinterest", "google_business": "Google Business Profile",
}


def kind_of(media) -> str:
    return (media.mimetype or "application/octet-stream").split("/")[0]


class BasePublisher:
    platform = ""
    max_chars = 0
    max_images = 10
    requires_media = False
    supports_text_only = True
    supports_images = True
    supports_video = True
    supports_audio = False
    supports_story = False

    def __init__(self, db: Session, account: SocialAccount, token: str | None = None):
        from ..accounts import valid_token  # late import: accounts imports the publishers registry

        self.db = db
        self.account = account
        self.token = token if token is not None else valid_token(db, account)

    # -- helpers ------------------------------------------------------------
    @property
    def label(self) -> str:
        return PLATFORM_LABELS.get(self.platform, self.platform)

    def _call(self, method, url, operation, **kwargs):
        return call(method, url, service="social", operation=f"{self.label}: {operation}",
                    workspace_id=self.account.workspace_id, ref=("social_account", self.account.id), **kwargs)

    def _setting(self, key: str, default):
        from app.modules.workspaces.settings import get_setting
        return get_setting(self.db, self.account.workspace_id, f"social.{key}", default) or default

    @staticmethod
    def _bytes(media: Media) -> bytes:
        return read_media(media)

    def _public_url(self, media: Media) -> str:
        """A URL the network's servers download the file from (Instagram, Threads, TikTok)."""
        base = settings.public_api_url or ""
        if not base.startswith("https://") or "localhost" in base or "127.0.0.1" in base:
            raise ApiError(f"{self.label} downloads media from this server, which must be reachable over public "
                           f"HTTPS (current address: {base}).")
        return public_url(media)

    @staticmethod
    def split(media: list) -> tuple[list, list, list]:
        kinds: dict[str, list] = {"image": [], "video": [], "audio": []}
        for item in media:
            kinds.setdefault(kind_of(item), []).append(item)
        return kinds["image"], kinds["video"], kinds["audio"]

    @classmethod
    def rule_problems(cls, text: str, media: list) -> list[tuple[str, dict]]:
        """Rule violations as ``(English template with {named} placeholders, values)`` — translated by callers."""
        label = PLATFORM_LABELS.get(cls.platform, cls.platform)
        images, videos, audios = cls.split(media)
        out: list[tuple[str, dict]] = []
        if videos and not cls.supports_video:
            out.append(("{network} cannot publish videos from here.", {"network": label}))
        if audios and not cls.supports_audio:
            out.append(("{network} does not accept audio posts. Use the voice-over in a video, or post it on "
                        "Telegram.", {"network": label}))
        if images and not cls.supports_images:
            out.append(("{network} publishes videos only.", {"network": label}))
        if cls.requires_media and not media:
            needs = ("{network} needs an image or a video." if cls.supports_images and cls.supports_video
                     else "{network} needs a video." if cls.supports_video else "{network} needs an image.")
            out.append((needs, {"network": label}))
        if cls.max_chars and len(text or "") > cls.max_chars:
            out.append(("Text is too long for {network} ({length} / {max} characters).",
                        {"network": label, "length": len(text), "max": cls.max_chars}))
        if cls.supports_images and len(images) > cls.max_images:
            out.append(("{network} accepts one image per post." if cls.max_images == 1
                        else "{network} accepts at most {count} images.", {"network": label, "count": cls.max_images}))
        if len(videos) > 1 or len(audios) > 1:
            out.append(("{network} accepts one video or one audio file per post.", {"network": label}))
        if (videos or audios) and len(media) > 1:
            out.append(("A post can have several images, or one video, or one audio file.", {}))
        if not (text or "").strip() and not media:
            out.append(("The post is empty.", {}))
        return out

    @classmethod
    def problems(cls, text: str, media: list) -> list[str]:
        """Rule violations in English (used just before sending)."""
        return [template.format(**values) for template, values in cls.rule_problems(text, media)]

    def check(self, text: str, media: list) -> None:
        problems = self.problems(text, media)
        if problems:
            raise ApiError(problems[0])

    def publish(self, text: str, media: list) -> dict:
        images, videos, audios = self.split(media)
        if videos:
            return self.publish_video(text, videos[0])
        if audios:
            return self.publish_audio(text, audios[0])
        return self.publish_images(text, images)

    # -- to implement ---------------------------------------------------------
    def publish_images(self, text: str, images: list) -> dict:
        """Text-only when ``images`` is empty."""
        raise NotImplementedError

    def publish_video(self, text: str, video) -> dict:
        raise ApiError(f"{self.label} cannot publish videos from here.")

    def publish_audio(self, text: str, audio) -> dict:
        raise ApiError(f"{self.label} does not accept audio posts.")

    def publish_story(self, media: list) -> dict:
        raise ApiError(f"{self.label} has no stories: only Instagram and Facebook Pages do.")

    def fetch_metrics(self, targets: list) -> dict:
        return {}

    def fetch_audience(self) -> dict:
        return {}

    def fetch_profile(self) -> dict:
        raise NotImplementedError
