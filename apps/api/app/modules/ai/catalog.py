"""Catalog of supported AI providers (ported from the Odoo module).

Each entry says which client writes text (``engine``), which media it can generate (``caps``), the official
endpoint, sensible default models and where to get a key. Every default can be changed on the provider row.
"""
from app.core.i18n import lazy

TEXT, IMAGE, VIDEO, AUDIO, STT = "text", "image", "video", "audio", "stt"
MEDIA_KINDS = (IMAGE, VIDEO, AUDIO)
CAPS_ORDER = (TEXT, IMAGE, VIDEO, AUDIO, STT)

# provider fields holding the default model of each capability
MODEL_FIELD = {TEXT: "text_model", IMAGE: "image_model", VIDEO: "video_model", AUDIO: "audio_model"}

CATALOG: dict[str, dict] = {
    # --- the big three -------------------------------------------------------
    "openai": {
        "label": "OpenAI", "engine": "openai", "base_url": "https://api.openai.com/v1",
        "caps": {TEXT, IMAGE, VIDEO, AUDIO, STT},
        "models": {TEXT: "gpt-5-mini", IMAGE: "gpt-image-1", VIDEO: "sora-2", AUDIO: "gpt-4o-mini-tts",
                   STT: "whisper-1"},
        "voice": "alloy", "max_tokens": 4000,
        "key_url": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic Claude", "engine": "anthropic", "base_url": "https://api.anthropic.com/v1",
        "caps": {TEXT},
        # Claude may think before answering: leave room so the post is not cut off.
        "models": {TEXT: "claude-opus-5-5"}, "max_tokens": 16000,
        "key_url": "https://platform.claude.com/settings/keys",
    },
    "gemini": {
        "label": "Google Gemini", "engine": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "caps": {TEXT, IMAGE, VIDEO},
        "models": {TEXT: "gemini-2.5-flash", IMAGE: "gemini-2.5-flash-image", VIDEO: "veo-3.0-generate-001"},
        "max_tokens": 8000,
        "key_url": "https://aistudio.google.com/apikey",
    },
    "azure_openai": {
        "label": "Azure OpenAI", "engine": "azure", "base_url": "https://YOUR-RESOURCE.openai.azure.com/openai/v1",
        "caps": {TEXT, IMAGE, AUDIO},
        "models": {TEXT: "gpt-5-mini", IMAGE: "gpt-image-1", AUDIO: "gpt-4o-mini-tts"},
        "voice": "alloy", "max_tokens": 4000, "needs_base_url": True,
        "key_url": "https://portal.azure.com",
    },
    # --- OpenAI-compatible text APIs ---------------------------------------
    "xai": {
        "label": "xAI Grok", "engine": "openai_compatible", "base_url": "https://api.x.ai/v1",
        "caps": {TEXT, IMAGE}, "models": {TEXT: "grok-4", IMAGE: "grok-2-image"},
        "key_url": "https://console.x.ai",
    },
    "mistral": {
        "label": "Mistral AI", "engine": "openai_compatible", "base_url": "https://api.mistral.ai/v1",
        "caps": {TEXT}, "models": {TEXT: "mistral-large-latest"},
        "key_url": "https://console.mistral.ai/api-keys",
    },
    "deepseek": {
        "label": "DeepSeek", "engine": "openai_compatible", "base_url": "https://api.deepseek.com/v1",
        "caps": {TEXT}, "models": {TEXT: "deepseek-chat"},
        "key_url": "https://platform.deepseek.com/api_keys",
    },
    "qwen": {
        "label": "Alibaba Qwen", "engine": "openai_compatible",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "caps": {TEXT}, "models": {TEXT: "qwen-plus"},
        "key_url": "https://bailian.console.alibabacloud.com",
    },
    "moonshot": {
        "label": "Moonshot Kimi", "engine": "openai_compatible", "base_url": "https://api.moonshot.ai/v1",
        "caps": {TEXT}, "models": {TEXT: "kimi-k2-0905-preview"},
        "key_url": "https://platform.moonshot.ai",
    },
    "cohere": {
        "label": "Cohere", "engine": "openai_compatible", "base_url": "https://api.cohere.ai/compatibility/v1",
        "caps": {TEXT}, "models": {TEXT: "command-a-03-2025"},
        "key_url": "https://dashboard.cohere.com/api-keys",
    },
    "perplexity": {
        "label": "Perplexity", "engine": "openai_compatible", "base_url": "https://api.perplexity.ai",
        "caps": {TEXT}, "models": {TEXT: "sonar"},
        "key_url": "https://www.perplexity.ai/settings/api",
    },
    "groq": {
        "label": "Groq", "engine": "openai_compatible", "base_url": "https://api.groq.com/openai/v1",
        "caps": {TEXT}, "models": {TEXT: "llama-3.3-70b-versatile"},
        "key_url": "https://console.groq.com/keys",
    },
    "together": {
        "label": "Together AI", "engine": "openai_compatible", "base_url": "https://api.together.xyz/v1",
        "caps": {TEXT, IMAGE},
        "models": {TEXT: "meta-llama/Llama-3.3-70B-Instruct-Turbo", IMAGE: "black-forest-labs/FLUX.1-schnell"},
        "key_url": "https://api.together.ai/settings/api-keys",
    },
    "fireworks": {
        "label": "Fireworks AI", "engine": "openai_compatible", "base_url": "https://api.fireworks.ai/inference/v1",
        "caps": {TEXT}, "models": {TEXT: "accounts/fireworks/models/llama-v3p3-70b-instruct"},
        "key_url": "https://fireworks.ai/account/api-keys",
    },
    "openrouter": {
        "label": "OpenRouter (300+ models)", "engine": "openai_compatible", "base_url": "https://openrouter.ai/api/v1",
        "caps": {TEXT}, "models": {TEXT: "openai/gpt-5-mini"},
        "key_url": "https://openrouter.ai/keys",
    },
    "ollama": {
        "label": "Ollama (local)", "engine": "openai_compatible", "base_url": "http://localhost:11434/v1",
        "caps": {TEXT}, "models": {TEXT: "llama3.2"}, "no_key": True,
        "key_url": "https://ollama.com/download",
    },
    "lmstudio": {
        "label": "LM Studio (local)", "engine": "openai_compatible", "base_url": "http://localhost:1234/v1",
        "caps": {TEXT}, "models": {TEXT: ""}, "no_key": True,
        "key_url": "https://lmstudio.ai",
    },
    "custom": {
        "label": "Other OpenAI-compatible API", "engine": "openai_compatible", "base_url": "",
        "caps": {TEXT}, "models": {TEXT: ""}, "needs_base_url": True,
    },
    # --- media specialists --------------------------------------------------
    "stability": {
        "label": "Stability AI", "engine": None, "base_url": "https://api.stability.ai",
        "caps": {IMAGE}, "models": {IMAGE: "core"},
        "key_url": "https://platform.stability.ai/account/keys",
    },
    "replicate": {
        "label": "Replicate (any model)", "engine": None, "base_url": "https://api.replicate.com/v1",
        "caps": {IMAGE, VIDEO, AUDIO},
        "models": {IMAGE: "black-forest-labs/flux-schnell", VIDEO: "minimax/video-01",
                   AUDIO: "minimax/speech-02-turbo"},
        "key_url": "https://replicate.com/account/api-tokens",
    },
    "runway": {
        "label": "Runway", "engine": None, "base_url": "https://api.dev.runwayml.com/v1",
        "caps": {VIDEO}, "models": {VIDEO: "veo3.1_fast"},
        "key_url": "https://dev.runwayml.com",
    },
    "luma": {
        "label": "Luma AI", "engine": None, "base_url": "https://api.lumalabs.ai/dream-machine/v1",
        "caps": {IMAGE, VIDEO}, "models": {IMAGE: "photon-1", VIDEO: "ray-2"},
        "key_url": "https://lumalabs.ai/dream-machine/api/keys",
    },
    "elevenlabs": {
        "label": "ElevenLabs", "engine": None, "base_url": "https://api.elevenlabs.io/v1",
        "caps": {AUDIO, STT}, "models": {AUDIO: "eleven_multilingual_v2", STT: "scribe_v1"},
        "voice": "21m00Tcm4TlvDq8ikWAM",
        "key_url": "https://elevenlabs.io/app/settings/api-keys",
    },
}

CAPABILITY_LABELS = {TEXT: lazy("Text"), IMAGE: lazy("Images"), VIDEO: lazy("Video"), AUDIO: lazy("Voice & sound"),
                     STT: lazy("Speech to text")}


def info(provider_type: str) -> dict:
    return CATALOG.get(provider_type) or CATALOG["custom"]


def caps(provider_type: str) -> set[str]:
    return info(provider_type)["caps"]


def can(provider_type: str, capability: str) -> bool:
    return capability in caps(provider_type)


def types_for(capability: str) -> list[str]:
    return [key for key, meta in CATALOG.items() if capability in meta["caps"]]


def default_model(provider_type: str, capability: str) -> str:
    return info(provider_type).get("models", {}).get(capability) or ""


def ordered_caps(provider_type: str) -> list[str]:
    return [c for c in CAPS_ORDER if c in caps(provider_type)]
