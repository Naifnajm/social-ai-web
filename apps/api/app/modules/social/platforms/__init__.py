"""Publishers per network + the rules the composer uses for live counters and warnings."""
from .base import PLATFORM_LABELS, BasePublisher, kind_of
from .google import GoogleBusinessPublisher, YouTubePublisher
from .linkedin import LinkedInPublisher
from .meta import FacebookPublisher, InstagramPublisher, ThreadsPublisher
from .pinterest import PinterestPublisher
from .telegram import TelegramPublisher
from .tiktok import TikTokPublisher
from .x import XPublisher

PUBLISHERS: dict[str, type[BasePublisher]] = {
    "facebook": FacebookPublisher,
    "instagram": InstagramPublisher,
    "threads": ThreadsPublisher,
    "linkedin": LinkedInPublisher,
    "x": XPublisher,
    "tiktok": TikTokPublisher,
    "telegram": TelegramPublisher,
    "youtube": YouTubePublisher,
    "pinterest": PinterestPublisher,
    "google_business": GoogleBusinessPublisher,
}
STORY_PLATFORMS = tuple(key for key, cls in PUBLISHERS.items() if cls.supports_story)


def publisher_class(platform: str) -> type[BasePublisher]:
    return PUBLISHERS[platform]


def get_publisher(db, account, token: str | None = None) -> BasePublisher:
    return PUBLISHERS[account.platform](db, account, token)


def platform_rules() -> dict:
    return {
        key: {
            "label": PLATFORM_LABELS[key],
            "max_chars": cls.max_chars,
            "max_images": cls.max_images,
            "requires_media": cls.requires_media,
            "images": cls.supports_images,
            "video": cls.supports_video,
            "audio": cls.supports_audio,
            "story": cls.supports_story,
        }
        for key, cls in PUBLISHERS.items()
    }


__all__ = ["PUBLISHERS", "STORY_PLATFORMS", "PLATFORM_LABELS", "get_publisher", "kind_of", "platform_rules",
           "publisher_class"]
