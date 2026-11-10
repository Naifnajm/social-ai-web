"""Common interface for AI media generation (images, video, voice, sound) — ported from the Odoo module.

Every method returns a *result* dict:

* ``{"content": bytes, "mimetype": "image/png"}`` — the file is ready, or
* ``{"url": "https://…"}`` — ready, to be downloaded, or
* ``{"job": "<provider job id>"}`` — still running (video), poll with ``video_poll``.

``video_poll`` returns a ready result, or ``{"status": "running", "progress": 0-100}``. Failures raise ApiError.
"""
import base64

from app.core.http import ApiError, call

from .. import catalog

ASPECTS = ("1:1", "16:9", "9:16", "4:5")


class MediaInput:
    """A reference file handed to a generator (e.g. the image to animate or to edit)."""

    def __init__(self, content: bytes, mimetype: str, name: str = "file", url_fn=None):
        self.content = content
        self.mimetype = mimetype or "application/octet-stream"
        self.name = name
        self._url_fn = url_fn

    @property
    def url(self) -> str:
        if not self._url_fn:
            raise ApiError("This provider needs a public URL for the input file.")
        return self._url_fn()

    def b64(self) -> str:
        return base64.b64encode(self.content).decode()

    def data_uri(self) -> str:
        return "data:%s;base64,%s" % (self.mimetype, self.b64())


class BaseMediaClient:
    # What this client can do with reference inputs / sound
    supports_image_edit = False
    supports_image_to_video = False
    supports_sfx = False
    supports_music = False

    def __init__(self, provider, model: str | None = None, capability: str | None = None):
        self.provider = provider
        self.meta = catalog.info(provider.provider_type)
        self.api_key = (provider.api_key or "").strip()
        self.base_url = (provider.base_url or self.meta.get("base_url") or "").rstrip("/")
        defaults = self.meta.get("models", {})
        self.image_model = provider.image_model or defaults.get("image")
        self.video_model = provider.video_model or defaults.get("video")
        self.audio_model = provider.audio_model or defaults.get("audio")
        self.voice = provider.voice or self.meta.get("voice")
        if model and capability in ("image", "video", "audio"):  # a model picked in the UI for this task
            setattr(self, "%s_model" % capability, model)
        if not self.api_key and not self.meta.get("no_key"):
            raise ApiError("No API key is set for “%s”." % provider.name)

    # -- helpers --------------------------------------------------------------
    def _call(self, method, path_or_url, operation, **kwargs):
        url = path_or_url if path_or_url.startswith("http") else "%s/%s" % (self.base_url, path_or_url.lstrip("/"))
        return call(method, url, service="ai", operation=operation, workspace_id=self.provider.workspace_id,
                    ref=("ai_provider", self.provider.id), **kwargs)

    @staticmethod
    def _binary(response, default_mimetype):
        mimetype = (response.headers.get("Content-Type") or default_mimetype).split(";")[0].strip()
        if mimetype in ("application/octet-stream", "binary/octet-stream", ""):
            mimetype = default_mimetype
        return {"content": response.content, "mimetype": mimetype}

    def _unsupported(self, what):
        raise ApiError("%s cannot create %s." % (self.meta["label"], what))

    # -- to implement -------------------------------------------------------------
    def test(self) -> list[str]:
        """Light call proving the key works. Returns a list of names (may be empty)."""
        return []

    def image(self, prompt, aspect="1:1", refs=None):
        self._unsupported("images")

    def video_start(self, prompt, aspect="16:9", seconds=8, image=None):
        self._unsupported("videos")

    def video_poll(self, job):
        self._unsupported("videos")

    def audio(self, text, instructions=""):
        self._unsupported("voice")

    def sound(self, prompt, kind="sfx", seconds=10):
        """Sound effects (``sfx``) or music (``music``)."""
        self._unsupported("music or sound effects")


def download(url, provider=None, headers=None, default_mimetype="application/octet-stream"):
    """Fetch a generated file from the URL a provider returned."""
    response = call("GET", url, service="ai", operation="Download result",
                    workspace_id=getattr(provider, "workspace_id", None),
                    ref=("ai_provider", provider.id) if provider else None,
                    headers=headers, expect_json=False, binary=True, timeout=300)
    mimetype = (response.headers.get("Content-Type") or default_mimetype).split(";")[0].strip()
    if mimetype in ("application/octet-stream", "binary/octet-stream", ""):
        mimetype = default_mimetype
    return response.content, mimetype
