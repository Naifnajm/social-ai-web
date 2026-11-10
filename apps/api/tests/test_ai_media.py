"""AI media generation jobs (image / video / audio, refs, callbacks, polling), transcription and brand kits."""
import base64
import io
from datetime import timedelta

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.errors import AppError
from app.core.models import ApiLog, Media
from app.core.storage import read_media, save_media
from app.modules.ai import media as ai_media
from app.modules.ai.generators import specialists
from app.modules.ai.models import AIUsage, MediaJob
from app.modules.ai.tasks import poll_media_jobs
from tests.conftest import signup
from tests.test_ai import add_provider


def _png(color=(37, 99, 235)):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, "PNG")
    return buffer.getvalue()


PNG = _png()
MP4 = b"\x00\x00\x00\x18ftypmp42fake-video-bytes"
MP3 = b"ID3fake-audio-bytes"
CALLS: list = []


def on_job(db, job):
    """Callback used by the tests (dotted path: tests.test_ai_media.on_job)."""
    CALLS.append((job.id, job.state, dict(job.callback_context or {})))


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(specialists, "POLL_SLEEP", 0)
    CALLS.clear()


def binary(mock_http, content, mimetype):
    return mock_http.response(200, content, {"Content-Type": mimetype})


def test_openai_image_sync_with_style_and_callback(client, auth, db, mock_http):
    add_provider(client, auth, "openai")

    def handler(method, url, kw):
        assert url == "https://api.openai.com/v1/images/generations"
        assert kw["json"]["size"] == "1024x1536" and kw["json"]["model"] == "gpt-image-1"
        assert "Photorealistic" in kw["json"]["prompt"]
        return mock_http.response(body={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    mock_http(handler)
    job = ai_media.start_job(db, auth.workspace_id, "image", "A coffee cup", aspect="4:5", style="photo",
                             callback="tests.test_ai_media.on_job", callback_context={"node_id": 4},
                             user_id=auth.user_id)
    assert job.state == "done" and job.progress == 100
    media = db.get(Media, job.media_id)
    assert media.mimetype == "image/png" and media.source == "ai" and media.workspace_id == auth.workspace_id
    assert read_media(media) == PNG and media.width == 8
    assert job.cost == pytest.approx(0.042)
    assert CALLS == [(job.id, "done", {"node_id": 4})]
    usage = db.scalar(select(AIUsage).where(AIUsage.workspace_id == auth.workspace_id))
    assert (usage.capability, usage.model_name, usage.cost) == ("image", "gpt-image-1", pytest.approx(0.042))


def test_image_edit_with_reference_and_model_override(client, auth, db, mock_http):
    provider = add_provider(client, auth, "openai")
    ref = save_media(db, auth.workspace_id, PNG, "ref.png", "image/png")
    models = client.get(f"/api/ai/providers/{provider['id']}/models", headers=auth.headers).json()
    mini = next(m for m in models if m["name"] == "gpt-image-1-mini")

    def handler(method, url, kw):
        assert url.endswith("/images/edits")
        assert kw["data"]["model"] == "gpt-image-1-mini"
        assert kw["files"][0][0] == "image[]"
        return mock_http.response(body={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    mock_http(handler)
    r = client.post("/api/ai/media", headers=auth.headers, json={
        "kind": "image", "prompt": "Same cup, blue background", "model_id": mini["id"], "input_media_ids": [ref.id]})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["state"] == "done" and job["cost"] == pytest.approx(0.011)
    assert job["media"]["mimetype"] == "image/png" and job["media"]["url"] == f"/api/media/{job['media_id']}/file"

    other = signup(client, email="eve@example.com", workspace="Eve")
    add_provider(client, other, "openai")
    r = client.post("/api/ai/media", headers=other.headers, json={
        "kind": "image", "prompt": "steal", "input_media_ids": [ref.id]})
    assert r.status_code == 404  # another workspace's file cannot be used as a reference


def test_reference_ignored_with_notice(client, auth, db, mock_http):
    add_provider(client, auth, "stability")
    ref = save_media(db, auth.workspace_id, PNG, "ref.png", "image/png")
    calls = mock_http(lambda m, u, k: binary(mock_http, PNG, "image/png"))
    job = ai_media.start_job(db, auth.workspace_id, "image", "Logo-free poster", inputs=[ref.id])
    assert job.state == "done" and "cannot use a reference image" in job.notice
    assert "/v2beta/stable-image/generate/core" in calls[0]["url"]
    assert calls[0]["data"]["aspect_ratio"] == "1:1"


def test_sora_video_is_polled_until_ready(client, auth, db, mock_http, monkeypatch):
    from app.core import db as core_db
    from app.core import jobs
    monkeypatch.setattr(jobs, "SessionLocal", core_db.SessionLocal)  # session_scope() bound it at import time
    add_provider(client, auth, "openai")
    progress = {"status": "in_progress"}

    def handler(method, url, kw):
        if method == "POST":
            assert kw["json"]["seconds"] == "8" and kw["json"]["size"] == "720x1280"
            return mock_http.response(body={"id": "video_1", "status": "queued"})
        if url.endswith("/content"):
            return binary(mock_http, MP4, "video/mp4")
        return mock_http.response(body={"id": "video_1", "status": progress["status"], "progress": 40})

    mock_http(handler)
    r = client.post("/api/ai/media", headers=auth.headers, json={
        "kind": "video", "prompt": "A barista pours latte art", "aspect": "9:16", "seconds": 7})
    job_id = r.json()["id"]
    assert r.json()["state"] == "running" and r.json()["seconds"] == 8  # Sora rounds to 4/8/12 s
    job = db.get(MediaJob, job_id)
    job.callback = "tests.test_ai_media.on_job"
    job.next_check_at = None
    r = client.post("/api/ai/jobs/check", json={"ids": [job_id]}, headers=auth.headers).json()
    assert (r[0]["state"], r[0]["progress"]) == ("running", 40)
    assert CALLS == []
    progress["status"] = "completed"
    job.next_check_at = None
    db.flush()
    assert poll_media_jobs() == 1  # the periodic task
    assert job.state == "done" and db.get(Media, job.media_id).mimetype == "video/mp4"
    assert job.cost == pytest.approx(8 * 0.10)
    assert CALLS == [(job.id, "done", {})]
    assert client.get(f"/api/ai/jobs/{job_id}", headers=auth.headers).json()["media"]["duration"] == 8


def test_veo_video_and_image_to_video(client, auth, db, mock_http):
    add_provider(client, auth, "gemini")
    still = save_media(db, auth.workspace_id, PNG, "still.png", "image/png")

    def handler(method, url, kw):
        if url.endswith(":predictLongRunning"):
            assert kw["json"]["parameters"]["aspectRatio"] == "16:9"
            assert kw["json"]["instances"][0]["image"]["mimeType"] == "image/png"
            return mock_http.response(body={"name": "models/veo/operations/op1"})
        if url.endswith("operations/op1"):
            return mock_http.response(body={"done": True, "response": {"generateVideoResponse": {
                "generatedSamples": [{"video": {"uri": "https://files.example/v.mp4"}}]}}})
        assert kw["headers"]["x-goog-api-key"] == "sk-test-123"
        return binary(mock_http, MP4, "video/mp4")

    mock_http(handler)
    job = ai_media.start_job(db, auth.workspace_id, "video", "Drone shot of a city", aspect="16:9", inputs=[still.id])
    assert job.state == "running" and job.external_job == "models/veo/operations/op1"
    ai_media.poll(db, job)
    assert job.state == "done"


def test_failed_video_calls_callback(client, auth, db, mock_http):
    add_provider(client, auth, "runway")

    def handler(method, url, kw):
        if method == "POST":
            assert kw["headers"]["X-Runway-Version"] == "2024-11-06"
            assert url.endswith("/text_to_video")
            return mock_http.response(body={"id": "t1"})
        return mock_http.response(body={"status": "FAILED", "failure": "Content policy"})

    mock_http(handler)
    job = ai_media.start_job(db, auth.workspace_id, "video", "Something", callback="tests.test_ai_media.on_job")
    ai_media.poll(db, job)
    assert job.state == "failed" and "Content policy" in job.error
    assert CALLS == [(job.id, "failed", {})]
    assert job.cost == 0


def test_immediate_failure_and_timeout(client, auth, db, mock_http):
    add_provider(client, auth, "openai")
    mock_http(lambda m, u, k: mock_http.response(400, {"error": {"message": "Your prompt was flagged"}}))
    job = ai_media.start_job(db, auth.workspace_id, "image", "x", callback="tests.test_ai_media.on_job")
    assert job.state == "failed" and "flagged" in job.error
    assert CALLS == [(job.id, "failed", {})]

    mock_http(lambda m, u, k: mock_http.response(body={"id": "v9", "status": "queued", "progress": 0}
                                                  if m == "POST" else {"status": "in_progress", "progress": 10}))
    video = ai_media.start_job(db, auth.workspace_id, "video", "slow")
    video.created_at = video.created_at - timedelta(hours=3)
    ai_media.poll(db, video)
    assert video.state == "failed" and "2 hours" in video.error

    # retry a failed image
    mock_http(lambda m, u, k: mock_http.response(body={"data": [{"b64_json": base64.b64encode(PNG).decode()}]}))
    r = client.post(f"/api/ai/jobs/{job.id}/retry", headers=auth.headers).json()
    assert r["state"] == "done" and r["error"] is None


def test_elevenlabs_voice_sfx_music_and_voice_override(client, auth, db, mock_http):
    add_provider(client, auth, "elevenlabs")
    seen = []

    def handler(method, url, kw):
        seen.append(url)
        assert kw["headers"]["xi-api-key"] == "sk-test-123"
        if "/sound-generation" in url:
            assert kw["json"]["duration_seconds"] == 5
        if url.endswith("/music"):
            assert kw["json"]["music_length_ms"] == 30000
        return binary(mock_http, MP3, "audio/mpeg")

    mock_http(handler)
    speech = ai_media.start_job(db, auth.workspace_id, "audio", "مرحبا بكم في ستراڤيكا")
    assert speech.state == "done" and db.get(Media, speech.media_id).filename.endswith(".mp3")
    assert "/text-to-speech/21m00Tcm4TlvDq8ikWAM" in seen[-1]
    assert speech.cost == pytest.approx(len("مرحبا بكم في ستراڤيكا") / 1000 * 0.18)
    custom = ai_media.start_job(db, auth.workspace_id, "audio", "Hello", voice="voice-xyz")
    assert custom.state == "done" and "/text-to-speech/voice-xyz" in seen[-1]
    sfx = ai_media.start_job(db, auth.workspace_id, "audio", "Door creak", audio_mode="sfx", seconds=5)
    assert sfx.state == "done" and sfx.cost == pytest.approx(5 * 0.008)
    music = ai_media.start_job(db, auth.workspace_id, "audio", "Calm oud", audio_mode="music", seconds=30)
    assert music.cost == pytest.approx(30 * 0.013) and db.get(Media, music.media_id).duration == 30
    log = db.scalars(select(ApiLog).where(ApiLog.operation == "Generate speech")).first()
    assert "bytes" in log.response_body  # binary bodies are summarised, not dumped


def test_openai_tts_and_unsupported_sound(client, auth, db, mock_http):
    add_provider(client, auth, "openai")

    def handler(method, url, kw):
        assert url.endswith("/audio/speech")
        assert kw["json"]["voice"] == "alloy" and kw["json"]["model"] == "gpt-4o-mini-tts"
        return binary(mock_http, MP3, "audio/mpeg")

    mock_http(handler)
    assert ai_media.start_job(db, auth.workspace_id, "audio", "Hi there").state == "done"
    job = ai_media.start_job(db, auth.workspace_id, "audio", "Rain", audio_mode="sfx")
    assert job.state == "failed" and "cannot create" in job.error


def test_replicate_image_and_luma_video(client, auth, db, mock_http):
    add_provider(client, auth, "replicate")

    def handler(method, url, kw):
        if "predictions" in url:
            assert kw["headers"]["Prefer"] == "wait=60"
            return mock_http.response(body={"id": "p1", "status": "succeeded", "output": ["https://r.example/o.png"]})
        return binary(mock_http, PNG, "image/png")

    mock_http(handler)
    assert ai_media.start_job(db, auth.workspace_id, "image", "Flat illustration").state == "done"

    luma = add_provider(client, auth, "luma")

    def luma_handler(method, url, kw):
        if method == "POST":
            assert kw["json"]["duration"] == "5s" and kw["json"]["model"] == "ray-2"
            return mock_http.response(body={"id": "g1"})
        if "/generations/g1" in url:
            return mock_http.response(body={"state": "completed", "assets": {"video": "https://l.example/v.mp4"}})
        return binary(mock_http, MP4, "video/mp4")

    mock_http(luma_handler)
    job = ai_media.start_job(db, auth.workspace_id, "video", "Waves", provider_id=luma["id"], seconds=5)
    ai_media.poll(db, job)
    assert job.state == "done" and job.cost == pytest.approx(5 * 0.08)


def test_capability_routing_and_validation(client, auth, db):
    claude = add_provider(client, auth, "anthropic")
    with pytest.raises(AppError) as exc:
        ai_media.start_job(db, auth.workspace_id, "video", "x", provider_id=claude["id"])
    assert exc.value.code == "no_media_provider"
    openai = add_provider(client, auth, "openai")
    job_provider = ai_media.estimate(db, auth.workspace_id, "image", "x", provider_id=claude["id"])
    assert job_provider["provider_id"] == openai["id"]  # falls back to a provider that can do it
    with pytest.raises(AppError):
        ai_media.start_job(db, auth.workspace_id, "image", "   ")
    r = client.post("/api/ai/media", json={"kind": "image", "prompt": "x", "aspect": "3:2"}, headers=auth.headers)
    assert r.status_code == 422


def test_jobs_listing_isolation(client, auth, db, mock_http):
    add_provider(client, auth, "openai")
    mock_http(lambda m, u, k: mock_http.response(body={"data": [{"b64_json": base64.b64encode(PNG).decode()}]}))
    job = ai_media.start_job(db, auth.workspace_id, "image", "cup")
    assert [j["id"] for j in client.get("/api/ai/jobs", headers=auth.headers).json()] == [job.id]
    other = signup(client, email="z@example.com", workspace="Z")
    assert client.get("/api/ai/jobs", headers=other.headers).json() == []
    assert client.get(f"/api/ai/jobs/{job.id}", headers=other.headers).status_code == 404
    assert client.post("/api/ai/jobs/check", json={"ids": [job.id]}, headers=other.headers).json() == []
    assert client.post(f"/api/ai/jobs/{job.id}/retry", headers=other.headers).status_code == 404


def test_brand_kit_applied_to_media(client, auth, db, mock_http):
    add_provider(client, auth, "openai")
    eleven = add_provider(client, auth, "elevenlabs")
    kit = client.post("/api/brand-kits", json={"name": "B", "visual_style": "Warm earthy tones",
                                               "color_primary": "#aa5500", "voice": "brand-voice"},
                      headers=auth.headers).json()
    seen = []

    def handler(method, url, kw):
        seen.append((url, kw.get("json")))
        if "images" in url:
            return mock_http.response(body={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
        return binary(mock_http, MP3, "audio/mpeg")

    mock_http(handler)
    ai_media.start_job(db, auth.workspace_id, "image", "A mug", brand_kit_id=kit["id"])
    assert "Warm earthy tones" in seen[-1][1]["prompt"] and "#aa5500" in seen[-1][1]["prompt"]
    ai_media.start_job(db, auth.workspace_id, "audio", "Hello", brand_kit_id=kit["id"], provider_id=eleven["id"])
    assert "/text-to-speech/brand-voice" in seen[-1][0]


# ------------------------------------------------------------------ transcription
def test_transcribe_openai_and_elevenlabs(client, auth, db, mock_http):
    add_provider(client, auth, "openai")
    audio = save_media(db, auth.workspace_id, MP3, "voice.mp3", "audio/mpeg")

    def handler(method, url, kw):
        assert url == "https://api.openai.com/v1/audio/transcriptions"
        assert ("model", "whisper-1") in kw["data"] and ("language", "ar") in kw["data"]
        return mock_http.response(body={"text": "Hello world. Bye.", "duration": 120.0, "segments": [
            {"start": 0, "end": 1.5, "text": " Hello world."}, {"start": 1.5, "end": 3, "text": " Bye."}]})

    mock_http(handler)
    result = ai_media.transcribe(db, auth.workspace_id, audio.id, language="ar")
    assert result["segments"] == [{"start": 0, "end": 1.5, "text": "Hello world."},
                                  {"start": 1.5, "end": 3, "text": "Bye."}]
    assert result["duration"] == 120 and result["cost"] == pytest.approx(2 * 0.006)
    usage = db.scalar(select(AIUsage).where(AIUsage.capability == "stt"))
    assert usage.model_name == "whisper-1"

    eleven = add_provider(client, auth, "elevenlabs")
    words = [{"text": w, "start": i * 0.5, "end": i * 0.5 + 0.4, "type": "word"} for i, w in enumerate(
        "one two three four five six seven eight nine".split())]
    words.insert(1, {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"})
    mock_http(lambda m, u, k: mock_http.response(body={"text": "...", "words": words}))
    r = client.post("/api/ai/transcribe", json={"media_id": audio.id, "provider_id": eleven["id"]},
                    headers=auth.headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["segments"]) == 2 and data["segments"][0]["text"] == "one two three four five six seven"
    assert data["model"] == "scribe_v1"

    other = signup(client, email="t@example.com", workspace="T")
    add_provider(client, other, "openai")
    assert client.post("/api/ai/transcribe", json={"media_id": audio.id}, headers=other.headers).status_code == 404


# ------------------------------------------------------------------ brand kits
def test_brand_kits_crud_default_and_isolation(client, auth, db):
    logo = save_media(db, auth.workspace_id, PNG, "logo.png", "image/png")
    first = client.post("/api/brand-kits", json={"name": "Main", "logo_media_id": logo.id, "tone": "Friendly"},
                        headers=auth.headers)
    assert first.status_code == 201, first.text
    first = first.json()
    assert first["is_default"] is True and first["logo_url"] == f"/api/media/{logo.id}/file"
    second = client.post("/api/brand-kits", json={"name": "Sub", "color_primary": "#ff0000"},
                         headers=auth.headers).json()
    assert second["is_default"] is False
    assert client.post("/api/brand-kits", json={"name": "Bad", "color_primary": "red"},
                       headers=auth.headers).status_code == 422
    r = client.post(f"/api/brand-kits/{second['id']}/default", headers=auth.headers).json()
    assert r["is_default"] is True
    assert client.get(f"/api/brand-kits/{first['id']}", headers=auth.headers).json()["is_default"] is False
    assert client.get("/api/brand-kits/default", headers=auth.headers).json()["id"] == second["id"]
    r = client.patch(f"/api/brand-kits/{first['id']}", json={"tagline": "Fast POS", "logo_media_id": None},
                     headers=auth.headers).json()
    assert r["tagline"] == "Fast POS" and r["logo_url"] is None
    assert [k["id"] for k in client.get("/api/brand-kits", headers=auth.headers).json()][0] == second["id"]
    assert "system-ui" in client.get("/api/brand-kits/options", headers=auth.headers).json()["fonts"]

    other = signup(client, email="b2@example.com", workspace="B2")
    assert client.get("/api/brand-kits", headers=other.headers).json() == []
    assert client.get(f"/api/brand-kits/{first['id']}", headers=other.headers).status_code == 404
    assert client.patch(f"/api/brand-kits/{first['id']}", json={"name": "x"}, headers=other.headers).status_code == 404
    assert client.delete(f"/api/brand-kits/{first['id']}", headers=other.headers).status_code == 404
    # cannot attach another workspace's file as logo
    r = client.post("/api/brand-kits", json={"name": "Steal", "logo_media_id": logo.id}, headers=other.headers)
    assert r.status_code == 404

    assert client.delete(f"/api/brand-kits/{second['id']}", headers=auth.headers).status_code == 204
    assert client.get("/api/brand-kits/default", headers=auth.headers).json()["id"] == first["id"]
