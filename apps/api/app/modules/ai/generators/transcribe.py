"""Speech-to-text with timestamps (OpenAI Whisper, ElevenLabs Scribe), used by captions/subtitles features."""
from app.core.http import ApiError, call

from .. import catalog

SUPPORTED = ("openai", "elevenlabs")


def _group_words(words, max_words=7, max_seconds=3.2):
    segments, current = [], []
    for word in words:
        if word.get("type") not in (None, "word"):
            continue
        if current and (len(current) >= max_words or word["start"] - current[0]["start"] > max_seconds):
            segments.append(current)
            current = []
        current.append(word)
    if current:
        segments.append(current)
    return [{"start": seg[0]["start"], "end": seg[-1]["end"],
             "text": " ".join(w["text"].strip() for w in seg)} for seg in segments]


def transcribe(provider, content: bytes, mimetype: str = "audio/mpeg", language: str | None = None,
               model: str | None = None):
    """Returns ``(segments, duration_seconds, model, text)``; segments are ``{"start", "end", "text"}``."""
    kind = provider.provider_type
    key = (provider.api_key or "").strip()
    if kind not in SUPPORTED:
        raise ApiError("%s cannot transcribe speech. Use OpenAI or ElevenLabs." % provider.name)
    if not key:
        raise ApiError("No API key is set for “%s”." % provider.name)
    model = model or catalog.default_model(kind, catalog.STT)
    files = {"file": ("speech" + (".mp4" if mimetype.startswith("video/") else ".mp3"), content,
                      mimetype or "audio/mpeg")}
    log = {"service": "ai", "operation": "Transcribe speech", "workspace_id": provider.workspace_id,
           "ref": ("ai_provider", provider.id), "timeout": 300}
    if kind == "openai":
        base = (provider.base_url or catalog.info(kind)["base_url"]).rstrip("/")
        data = [("model", model), ("response_format", "verbose_json"), ("timestamp_granularities[]", "segment")]
        if language:
            data.append(("language", language))
        body = call("POST", base + "/audio/transcriptions", headers={"Authorization": "Bearer %s" % key},
                    data=data, files=files, **log)
        segments = [{"start": s.get("start", 0), "end": s.get("end", 0), "text": (s.get("text") or "").strip()}
                    for s in body.get("segments") or []]
        if not segments and body.get("text"):
            segments = [{"start": 0, "end": body.get("duration") or 5, "text": body["text"]}]
        duration = body.get("duration") or (segments[-1]["end"] if segments else 0)
        text = body.get("text") or " ".join(s["text"] for s in segments)
    else:
        data = {"model_id": model}
        if language:
            data["language_code"] = language
        base = (provider.base_url or catalog.info(kind)["base_url"]).rstrip("/")
        body = call("POST", base + "/speech-to-text", headers={"xi-api-key": key}, data=data, files=files, **log)
        words = body.get("words") or []
        segments = _group_words(words)
        if not segments and body.get("text"):
            segments = [{"start": 0, "end": 5, "text": body["text"]}]
        duration = words[-1]["end"] if words else 0
        text = body.get("text") or " ".join(s["text"] for s in segments)
    return segments, float(duration or 0), model, (text or "").strip()
