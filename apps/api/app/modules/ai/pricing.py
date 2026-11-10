"""Model list with approximate public list prices (USD) and cost estimation (ported from the Odoo module).

Prices change often: they are copied into ``AIModel`` rows that an admin can edit. Units:

* ``tokens``     — ``price_in`` / ``price_out`` per 1 million tokens
* ``image``      — ``price`` per image
* ``second``     — ``price`` per second of video / audio
* ``1k_chars``   — ``price`` per 1,000 characters of speech
* ``minute``     — ``price`` per minute of speech (TTS: per minute spoken; STT: per minute of audio)
* ``free``       — local model
"""
T, I, V, A, S = "text", "image", "video", "audio", "stt"
UNITS = ("tokens", "image", "second", "1k_chars", "minute", "free")

# (model id, capability, unit, price_in, price_out, price, label)
MODELS: dict[str, list[tuple]] = {
    "openai": [
        ("gpt-5", T, "tokens", 1.25, 10.0, 0, "GPT-5"),
        ("gpt-5-mini", T, "tokens", 0.25, 2.0, 0, "GPT-5 mini"),
        ("gpt-5-nano", T, "tokens", 0.05, 0.40, 0, "GPT-5 nano"),
        ("gpt-4.1-mini", T, "tokens", 0.40, 1.60, 0, "GPT-4.1 mini"),
        ("gpt-image-1", I, "image", 0, 0, 0.042, "GPT Image 1"),
        ("gpt-image-1-mini", I, "image", 0, 0, 0.011, "GPT Image 1 mini"),
        ("sora-2", V, "second", 0, 0, 0.10, "Sora 2"),
        ("sora-2-pro", V, "second", 0, 0, 0.30, "Sora 2 Pro"),
        ("gpt-4o-mini-tts", A, "minute", 0, 0, 0.015, "GPT-4o mini TTS"),
        ("tts-1-hd", A, "1k_chars", 0, 0, 0.030, "TTS-1 HD"),
        ("whisper-1", S, "minute", 0, 0, 0.006, "Whisper"),
    ],
    "anthropic": [
        ("claude-opus-5-5", T, "tokens", 4.0, 20.0, 0, "Claude Opus 5.5"),
        ("claude-sonnet-5-5", T, "tokens", 2.0, 10.0, 0, "Claude Sonnet 5.5"),
        ("claude-haiku-5-5", T, "tokens", 0.10, 0.50, 0, "Claude Haiku 5.5"),
        ("claude-fable-5-1", T, "tokens", 10.0, 50.0, 0, "Claude Fable 5.1"),
    ],
    "gemini": [
        ("gemini-2.5-pro", T, "tokens", 1.25, 10.0, 0, "Gemini 2.5 Pro"),
        ("gemini-2.5-flash", T, "tokens", 0.30, 2.50, 0, "Gemini 2.5 Flash"),
        ("gemini-2.5-flash-lite", T, "tokens", 0.10, 0.40, 0, "Gemini 2.5 Flash-Lite"),
        ("gemini-2.5-flash-image", I, "image", 0, 0, 0.039, "Gemini 2.5 Flash Image"),
        ("veo-3.0-generate-001", V, "second", 0, 0, 0.40, "Veo 3"),
        ("veo-3.0-fast-generate-001", V, "second", 0, 0, 0.15, "Veo 3 Fast"),
    ],
    "azure_openai": [
        ("gpt-5-mini", T, "tokens", 0.25, 2.0, 0, "GPT-5 mini (deployment)"),
        ("gpt-image-1", I, "image", 0, 0, 0.042, "GPT Image 1 (deployment)"),
        ("gpt-4o-mini-tts", A, "minute", 0, 0, 0.015, "GPT-4o mini TTS (deployment)"),
    ],
    "xai": [
        ("grok-4", T, "tokens", 3.0, 15.0, 0, "Grok 4"),
        ("grok-3-mini", T, "tokens", 0.30, 0.50, 0, "Grok 3 mini"),
        ("grok-2-image", I, "image", 0, 0, 0.07, "Grok 2 Image"),
    ],
    "mistral": [
        ("mistral-large-latest", T, "tokens", 2.0, 6.0, 0, "Mistral Large"),
        ("mistral-small-latest", T, "tokens", 0.10, 0.30, 0, "Mistral Small"),
    ],
    "deepseek": [
        ("deepseek-chat", T, "tokens", 0.28, 0.42, 0, "DeepSeek Chat"),
        ("deepseek-reasoner", T, "tokens", 0.28, 0.42, 0, "DeepSeek Reasoner"),
    ],
    "qwen": [
        ("qwen-plus", T, "tokens", 0.40, 1.20, 0, "Qwen Plus"),
        ("qwen-max", T, "tokens", 1.60, 6.40, 0, "Qwen Max"),
        ("qwen-turbo", T, "tokens", 0.05, 0.20, 0, "Qwen Turbo"),
    ],
    "moonshot": [("kimi-k2-0905-preview", T, "tokens", 0.60, 2.50, 0, "Kimi K2")],
    "cohere": [
        ("command-a-03-2025", T, "tokens", 2.50, 10.0, 0, "Command A"),
        ("command-r7b-12-2024", T, "tokens", 0.0375, 0.15, 0, "Command R7B"),
    ],
    "perplexity": [
        ("sonar", T, "tokens", 1.0, 1.0, 0, "Sonar"),
        ("sonar-pro", T, "tokens", 3.0, 15.0, 0, "Sonar Pro"),
    ],
    "groq": [
        ("llama-3.3-70b-versatile", T, "tokens", 0.59, 0.79, 0, "Llama 3.3 70B"),
        ("llama-3.1-8b-instant", T, "tokens", 0.05, 0.08, 0, "Llama 3.1 8B"),
    ],
    "together": [
        ("meta-llama/Llama-3.3-70B-Instruct-Turbo", T, "tokens", 0.88, 0.88, 0, "Llama 3.3 70B Turbo"),
        ("black-forest-labs/FLUX.1-schnell", I, "image", 0, 0, 0.003, "FLUX.1 schnell"),
    ],
    "fireworks": [("accounts/fireworks/models/llama-v3p3-70b-instruct", T, "tokens", 0.90, 0.90, 0, "Llama 3.3 70B")],
    "openrouter": [("openai/gpt-5-mini", T, "tokens", 0.25, 2.0, 0, "GPT-5 mini via OpenRouter")],
    "ollama": [("llama3.2", T, "free", 0, 0, 0, "Llama 3.2 (local)")],
    "lmstudio": [],
    "custom": [],
    "stability": [
        ("core", I, "image", 0, 0, 0.03, "Stable Image Core"),
        ("ultra", I, "image", 0, 0, 0.08, "Stable Image Ultra"),
        ("sd3.5-large", I, "image", 0, 0, 0.065, "SD 3.5 Large"),
    ],
    "replicate": [
        ("black-forest-labs/flux-schnell", I, "image", 0, 0, 0.003, "FLUX schnell"),
        ("black-forest-labs/flux-1.1-pro", I, "image", 0, 0, 0.04, "FLUX 1.1 Pro"),
        ("minimax/video-01", V, "second", 0, 0, 0.083, "MiniMax Video-01"),
        ("minimax/speech-02-turbo", A, "1k_chars", 0, 0, 0.06, "MiniMax Speech 02"),
    ],
    "runway": [
        ("veo3.1_fast", V, "second", 0, 0, 0.15, "Veo 3.1 Fast (Runway)"),
        ("veo3.1", V, "second", 0, 0, 0.40, "Veo 3.1 (Runway)"),
        ("gen4_turbo", V, "second", 0, 0, 0.05, "Gen-4 Turbo (image to video)"),
    ],
    "luma": [
        ("photon-1", I, "image", 0, 0, 0.015, "Photon"),
        ("photon-flash-1", I, "image", 0, 0, 0.004, "Photon Flash"),
        ("ray-2", V, "second", 0, 0, 0.08, "Ray 2"),
        ("ray-flash-2", V, "second", 0, 0, 0.03, "Ray Flash 2"),
    ],
    "elevenlabs": [
        ("eleven_multilingual_v2", A, "1k_chars", 0, 0, 0.18, "Multilingual v2"),
        ("eleven_flash_v2_5", A, "1k_chars", 0, 0, 0.09, "Flash v2.5"),
        ("scribe_v1", S, "minute", 0, 0, 0.0067, "Scribe"),
    ],
}

# Prices of the sound/music side products that are not "models" the user picks.
SOUND_PRICE_PER_SECOND = {"elevenlabs": {"sfx": 0.008, "music": 0.013}, "replicate": {"music": 0.002}}

CHARS_PER_TOKEN = 3.0       # mixed Arabic / English
SPEECH_CHARS_PER_MINUTE = 900


def entries(provider_type: str) -> list[tuple]:
    return MODELS.get(provider_type, [])


def cost_of(model, tokens_in: int = 0, tokens_out: int = 0, units: float = 0, chars: int = 0,
            seconds: float = 0) -> float:
    """Cost in USD for an ``AIModel`` row (or anything with ``unit/price/price_in/price_out``)."""
    if not model:
        return 0.0
    unit = model.unit
    if unit == "tokens":
        return (tokens_in * (model.price_in or 0) + tokens_out * (model.price_out or 0)) / 1_000_000
    if unit == "image":
        return (units or 1) * (model.price or 0)
    if unit == "second":
        return (seconds or 0) * (model.price or 0)
    if unit == "1k_chars":
        return chars / 1000.0 * (model.price or 0)
    if unit == "minute":
        return (seconds / 60.0 if seconds else chars / SPEECH_CHARS_PER_MINUTE) * (model.price or 0)
    return 0.0


def estimate(model, prompt: str = "", seconds: float = 0, max_tokens: int = 600) -> tuple[float, str]:
    """(cost, explanation) before running a task."""
    if not model:
        return 0.0, ""
    prompt_chars = len(prompt or "")
    if model.unit == "tokens":
        tokens_in = int(prompt_chars / CHARS_PER_TOKEN) + 400   # + system prompt
        tokens_out = min(max_tokens or 600, 800)
        return cost_of(model, tokens_in, tokens_out), "~%d + %d tokens" % (tokens_in, tokens_out)
    if model.unit == "image":
        return model.price or 0.0, "1 image"
    if model.unit == "second":
        return (seconds or 0) * (model.price or 0), "%ss × $%s/s" % (fmt_number(seconds or 0), fmt(model.price or 0))
    if model.unit == "1k_chars":
        return prompt_chars / 1000.0 * (model.price or 0), "%d characters" % prompt_chars
    if model.unit == "minute":
        if model_capability(model) == "stt":
            minutes = max((seconds or 60) / 60.0, 0.1)
            return minutes * (model.price or 0), "~%.1f min of audio" % minutes
        minutes = max(prompt_chars / SPEECH_CHARS_PER_MINUTE, 0.1)
        return minutes * (model.price or 0), "~%.1f min of speech" % minutes
    return 0.0, "free"


def model_capability(model) -> str:
    return getattr(model, "capability", "") or ""


def price_label(model) -> str:
    """Short human price, e.g. "$0.25 / $2 per 1M" or "$0.042 / image"."""
    if model.unit == "free":
        return "free"
    if model.unit == "tokens":
        if not (model.price_in or model.price_out):
            return ""
        return "$%s / $%s per 1M" % (fmt(model.price_in or 0), fmt(model.price_out or 0))
    if not model.price:
        return ""
    suffix = {"image": "image", "second": "second", "1k_chars": "1K chars", "minute": "minute"}.get(model.unit, model.unit)
    return "$%s / %s" % (fmt(model.price), suffix)


def fmt(value: float) -> str:
    return ("%.4f" % value).rstrip("0").rstrip(".") or "0"


def fmt_number(value: float) -> str:
    return ("%.1f" % value).rstrip("0").rstrip(".")
