"""AI media generators (image, video, voice, sound) — one client class per provider type."""
from app.core.http import ApiError

from .. import catalog
from .base import ASPECTS, BaseMediaClient, MediaInput, download  # noqa: F401
from .gemini_media import GeminiMediaClient
from .openai_media import (
    AzureOpenAIMediaClient,
    OpenAICompatibleImageClient,
    OpenAIMediaClient,
)
from .specialists import (
    ElevenLabsClient,
    LumaClient,
    ReplicateClient,
    RunwayClient,
    StabilityClient,
)

CLIENTS = {
    "openai": OpenAIMediaClient,
    "azure_openai": AzureOpenAIMediaClient,
    "gemini": GeminiMediaClient,
    "xai": OpenAICompatibleImageClient,
    "together": OpenAICompatibleImageClient,
    "stability": StabilityClient,
    "replicate": ReplicateClient,
    "runway": RunwayClient,
    "luma": LumaClient,
    "elevenlabs": ElevenLabsClient,
}


def get_media_client(provider, model: str | None = None, capability: str | None = None) -> BaseMediaClient:
    cls = CLIENTS.get(provider.provider_type)
    if not cls:
        raise ApiError("%s does not create images, video or voice." % catalog.info(provider.provider_type)["label"])
    return cls(provider, model=model, capability=capability)
