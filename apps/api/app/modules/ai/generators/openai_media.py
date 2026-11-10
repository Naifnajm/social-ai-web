"""OpenAI media: gpt-image (images, edits), Sora (video, image-to-video), TTS (voice). Also Azure and
OpenAI-compatible image APIs (xAI Grok, Together)."""
import base64

from app.core.http import ApiError

from .base import BaseMediaClient
from .compose import fit_image

IMAGE_SIZES = {"1:1": "1024x1024", "16:9": "1536x1024", "9:16": "1024x1536", "4:5": "1024x1536"}
VIDEO_SIZES = {"16:9": "1280x720", "1:1": "1280x720", "9:16": "720x1280", "4:5": "720x1280"}


class OpenAIMediaClient(BaseMediaClient):
    supports_image_edit = True
    supports_image_to_video = True

    def _headers(self, json_body=True):
        headers = {"Authorization": "Bearer %s" % self.api_key}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def test(self):
        data = self._call("GET", "/models", "List models", headers=self._headers(False), timeout=20)
        return sorted(m.get("id") for m in data.get("data") or [] if m.get("id"))

    def image(self, prompt, aspect="1:1", refs=None):
        if refs:
            files = [("image[]", (ref.name or "ref.png", ref.content, ref.mimetype)) for ref in refs[:10]]
            data = self._call("POST", "/images/edits", "Edit image", headers=self._headers(False), timeout=300,
                              data={"model": self.image_model, "prompt": prompt,
                                    "size": IMAGE_SIZES.get(aspect, "1024x1024")}, files=files)
            return self._image_result(data)
        data = self._call("POST", "/images/generations", "Generate image", headers=self._headers(), timeout=240,
                          json_body={"model": self.image_model, "prompt": prompt, "n": 1,
                                     "size": IMAGE_SIZES.get(aspect, "1024x1024")})
        return self._image_result(data)

    @staticmethod
    def _image_result(data):
        item = (data.get("data") or [{}])[0] if isinstance(data, dict) else {}
        if item.get("b64_json"):
            return {"content": base64.b64decode(item["b64_json"]), "mimetype": "image/png"}
        if item.get("url"):
            return {"url": item["url"]}
        raise ApiError("The image service returned no image.")

    def video_start(self, prompt, aspect="16:9", seconds=8, image=None):
        seconds = min((4, 8, 12), key=lambda allowed: abs(allowed - int(seconds or 8)))
        size = VIDEO_SIZES.get(aspect, "1280x720")
        if image:
            # Sora needs the reference image at exactly the video size.
            width, height = (int(v) for v in size.split("x"))
            ref = fit_image(image.content, width, height, fmt="PNG")
            data = self._call("POST", "/videos", "Start video from image", headers=self._headers(False), timeout=120,
                              data={"model": self.video_model, "prompt": prompt, "seconds": str(seconds),
                                    "size": size},
                              files={"input_reference": ("reference.png", ref, "image/png")})
        else:
            data = self._call("POST", "/videos", "Start video", headers=self._headers(), timeout=60,
                              json_body={"model": self.video_model, "prompt": prompt, "seconds": str(seconds),
                                         "size": size})
        if not data.get("id"):
            raise ApiError("The video service did not return a job id.")
        return {"job": data["id"], "seconds": seconds}

    def video_poll(self, job):
        data = self._call("GET", "/videos/%s" % job, "Check video", headers=self._headers(False), timeout=30)
        status = data.get("status")
        if status == "completed":
            response = self._call("GET", "/videos/%s/content" % job, "Download video",
                                  headers=self._headers(False), expect_json=False, binary=True, timeout=300)
            return self._binary(response, "video/mp4")
        if status == "failed":
            error = data.get("error") or {}
            raise ApiError("Video generation failed: %s" % (error.get("message") or "unknown reason"))
        return {"status": "running", "progress": int(data.get("progress") or 0)}

    def audio(self, text, instructions=""):
        body = {"model": self.audio_model, "voice": self.voice or "alloy", "input": text, "response_format": "mp3"}
        if instructions:
            body["instructions"] = instructions
        response = self._call("POST", "/audio/speech", "Generate speech", headers=self._headers(),
                              json_body=body, expect_json=False, binary=True, timeout=180)
        return self._binary(response, "audio/mpeg")


class AzureOpenAIMediaClient(OpenAIMediaClient):
    supports_image_to_video = False

    def _headers(self, json_body=True):
        headers = {"api-key": self.api_key}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers


class OpenAICompatibleImageClient(OpenAIMediaClient):
    """xAI Grok, Together… : OpenAI-style /images/generations without size control."""

    supports_image_edit = False
    supports_image_to_video = False

    def image(self, prompt, aspect="1:1", refs=None):
        data = self._call("POST", "/images/generations", "Generate image", headers=self._headers(), timeout=240,
                          json_body={"model": self.image_model, "prompt": prompt, "n": 1,
                                     "response_format": "b64_json"})
        return self._image_result(data)
