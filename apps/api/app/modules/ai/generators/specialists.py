"""Media-only providers: Stability AI, Replicate, Runway, Luma, ElevenLabs."""
import time

from app.core.http import ApiError

from .base import BaseMediaClient

RUNWAY_VERSION = "2024-11-06"
POLL_SLEEP = 3.0  # seconds between polls when a provider must be waited for inline (tests set it to 0)


class StabilityClient(BaseMediaClient):
    """Stability AI Stable Image (core / ultra / sd3)."""

    def _headers(self, accept="image/*"):
        return {"Authorization": "Bearer %s" % self.api_key, "Accept": accept}

    def test(self):
        self._call("GET", "/v1/user/balance", "Check account", headers=self._headers("application/json"))
        return []

    def image(self, prompt, aspect="1:1", refs=None):
        model = self.image_model or "core"
        path = "/v2beta/stable-image/generate/%s" % ("sd3" if model.startswith("sd3") else model)
        data = {"prompt": prompt, "aspect_ratio": aspect, "output_format": "png"}
        if model.startswith("sd3"):
            data["model"] = model
        response = self._call("POST", path, "Generate image", headers=self._headers(), data=data,
                              files={"none": ("", b"")},  # forces multipart/form-data
                              expect_json=False, binary=True, timeout=240)
        return self._binary(response, "image/png")


class ReplicateClient(BaseMediaClient):
    """Replicate: run any public model. Model = "owner/name" or "owner/name:version"."""

    supports_image_to_video = True
    supports_music = True
    music_model = "meta/musicgen"

    def _headers(self, wait=False):
        headers = {"Authorization": "Bearer %s" % self.api_key, "Content-Type": "application/json"}
        if wait:
            headers["Prefer"] = "wait=60"
        return headers

    def test(self):
        data = self._call("GET", "/account", "Check account", headers=self._headers())
        return [data.get("username")] if data.get("username") else []

    def _run(self, model, input_, wait=True):
        if ":" in model:
            path, body = "/predictions", {"version": model.split(":", 1)[1], "input": input_}
        else:
            path, body = "/models/%s/predictions" % model, {"input": input_}
        data = self._call("POST", path, "Run %s" % model, headers=self._headers(wait), json_body=body, timeout=90)
        return self._result(data)

    @staticmethod
    def _result(data):
        status = data.get("status")
        if status == "succeeded":
            output = data.get("output")
            if isinstance(output, list):
                output = output[0] if output else None
            if isinstance(output, dict):
                output = output.get("url") or output.get("audio") or output.get("video")
            if not output:
                raise ApiError("The model finished without output.")
            return {"url": output}
        if status in ("failed", "canceled"):
            raise ApiError("Generation failed: %s" % (data.get("error") or status))
        return {"job": data.get("id"), "status": "running", "progress": 0}

    def image(self, prompt, aspect="1:1", refs=None):
        result = self._run(self.image_model, {"prompt": prompt, "aspect_ratio": aspect})
        return result if "job" not in result else self._wait(result["job"])

    def video_start(self, prompt, aspect="16:9", seconds=8, image=None):
        input_ = {"prompt": prompt, "aspect_ratio": aspect}
        if image:
            key = "first_frame_image" if "minimax" in (self.video_model or "") else "image"
            input_[key] = image.data_uri()
        result = self._run(self.video_model, input_, wait=False)
        return {"job": result["job"]} if "job" in result else result

    def video_poll(self, job):
        return self._result(self._call("GET", "/predictions/%s" % job, "Check job", headers=self._headers()))

    def audio(self, text, instructions=""):
        result = self._run(self.audio_model, {"text": text})
        return result if "job" not in result else self._wait(result["job"])

    def sound(self, prompt, kind="sfx", seconds=10):
        if kind != "music":
            self._unsupported("sound effects")
        result = self._run(self.music_model, {"prompt": prompt, "duration": int(seconds or 10)})
        return result if "job" not in result else self._wait(result["job"], attempts=60)

    def _wait(self, job, attempts=20):
        for _i in range(attempts):
            result = self.video_poll(job)
            if "job" not in result and result.get("status") != "running":
                return result
            time.sleep(POLL_SLEEP)
        raise ApiError("The model is still running. Try again in a minute.")


class RunwayClient(BaseMediaClient):
    """Runway API (text to video, image to video)."""

    supports_image_to_video = True

    def _headers(self):
        return {"Authorization": "Bearer %s" % self.api_key, "X-Runway-Version": RUNWAY_VERSION,
                "Content-Type": "application/json"}

    def test(self):
        self._call("GET", "/organization", "Check account", headers=self._headers())
        return []

    def video_start(self, prompt, aspect="16:9", seconds=8, image=None):
        ratio = "720:1280" if aspect in ("9:16", "4:5") else "1280:720"
        body = {"model": self.video_model, "promptText": prompt[:1000], "ratio": ratio,
                "duration": int(seconds or 8)}
        path = "/text_to_video"
        if image:
            path = "/image_to_video"
            body["promptImage"] = image.data_uri()
        data = self._call("POST", path, "Start video", headers=self._headers(), timeout=60, json_body=body)
        if not data.get("id"):
            raise ApiError("Runway did not return a task id.")
        return {"job": data["id"]}

    def video_poll(self, job):
        data = self._call("GET", "/tasks/%s" % job, "Check video", headers=self._headers())
        status = data.get("status")
        if status == "SUCCEEDED":
            return {"url": (data.get("output") or [None])[0]}
        if status in ("FAILED", "CANCELLED"):
            raise ApiError("Video generation failed: %s" % (data.get("failure") or status))
        return {"status": "running", "progress": int(float(data.get("progress") or 0) * 100)}


class LumaClient(BaseMediaClient):
    """Luma Dream Machine: Photon (images) and Ray (video, image to video)."""

    supports_image_to_video = True

    def _headers(self):
        return {"Authorization": "Bearer %s" % self.api_key, "Content-Type": "application/json",
                "Accept": "application/json"}

    def test(self):
        self._call("GET", "/generations", "Check account", headers=self._headers(), params={"limit": 1})
        return []

    def _poll(self, job):
        data = self._call("GET", "/generations/%s" % job, "Check generation", headers=self._headers())
        state = data.get("state")
        assets = data.get("assets") or {}
        if state == "completed":
            return {"url": assets.get("video") or assets.get("image")}
        if state == "failed":
            raise ApiError("Generation failed: %s" % (data.get("failure_reason") or "unknown reason"))
        return {"status": "running", "progress": 0}

    def image(self, prompt, aspect="1:1", refs=None):
        data = self._call("POST", "/generations/image", "Generate image", headers=self._headers(),
                          json_body={"prompt": prompt, "model": self.image_model, "aspect_ratio": aspect})
        for _i in range(30):
            result = self._poll(data["id"])
            if result.get("url"):
                return result
            time.sleep(POLL_SLEEP)
        raise ApiError("Luma is still creating the image. Try again in a minute.")

    def video_start(self, prompt, aspect="16:9", seconds=5, image=None):
        body = {"prompt": prompt, "model": self.video_model, "aspect_ratio": aspect,
                "duration": "9s" if int(seconds or 5) > 6 else "5s", "resolution": "720p"}
        if image:
            body["keyframes"] = {"frame0": {"type": "image", "url": image.url}}
        data = self._call("POST", "/generations", "Start video", headers=self._headers(), timeout=60, json_body=body)
        if not data.get("id"):
            raise ApiError("Luma did not return a generation id.")
        return {"job": data["id"], "seconds": 9 if int(seconds or 5) > 6 else 5}

    def video_poll(self, job):
        return self._poll(job)


class ElevenLabsClient(BaseMediaClient):
    """ElevenLabs: speech, sound effects and music."""

    supports_sfx = True
    supports_music = True

    def _headers(self):
        return {"xi-api-key": self.api_key, "Content-Type": "application/json"}

    def test(self):
        data = self._call("GET", "/voices", "List voices", headers=self._headers())
        return ["%s (%s)" % (v.get("name"), v.get("voice_id")) for v in data.get("voices") or []]

    def audio(self, text, instructions=""):
        response = self._call("POST", "/text-to-speech/%s" % self.voice, "Generate speech",
                              headers=self._headers(), params={"output_format": "mp3_44100_128"},
                              json_body={"text": text, "model_id": self.audio_model},
                              expect_json=False, binary=True, timeout=180)
        return self._binary(response, "audio/mpeg")

    def sound(self, prompt, kind="sfx", seconds=10):
        seconds = max(1, int(seconds or 10))
        if kind == "music":
            response = self._call("POST", "/music", "Generate music", headers=self._headers(),
                                  json_body={"prompt": prompt, "music_length_ms": min(seconds, 300) * 1000},
                                  expect_json=False, binary=True, timeout=300)
        else:
            response = self._call("POST", "/sound-generation", "Generate sound effect", headers=self._headers(),
                                  json_body={"text": prompt, "duration_seconds": min(seconds, 22)},
                                  expect_json=False, binary=True, timeout=180)
        return self._binary(response, "audio/mpeg")
