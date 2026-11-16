"""The recommended media mix: who does each job (defaults per capability, fast model), the video models
(Seedance and Wan on Replicate, Gemini Omni) and the two production pipelines."""
import base64

import pytest

from app.modules.ai import providers as prov
from app.modules.ai.generators import specialists
from app.modules.ai.models import AIModel
from app.modules.production.models import Node
from tests.test_ai import add_provider

MP4 = b"\x00\x00\x00\x18ftypmp42fake-video-bytes"


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(specialists, "POLL_SLEEP", 0)


def _model(db, ws, name):
    return db.query(AIModel).filter_by(workspace_id=ws, name=name).one()


def test_each_job_goes_to_the_recommended_provider(client, auth, db):
    openai = add_provider(client, auth, "openai")       # added first on purpose
    gemini = add_provider(client, auth, "gemini")
    replicate = add_provider(client, auth, "replicate")
    eleven = add_provider(client, auth, "elevenlabs")
    ws = auth.workspace_id
    assert prov.provider_for(db, ws, "text").id == openai["id"]
    assert prov.provider_for(db, ws, "image").id == openai["id"]
    assert prov.provider_for(db, ws, "video").id == replicate["id"]       # Seedance, not Omni or Sora
    assert prov.provider_for(db, ws, "audio").id == eleven["id"]          # ElevenLabs, not OpenAI TTS
    assert prov.provider_for(db, ws, "stt").id == openai["id"]

    defaults = client.get("/api/ai/defaults", headers=auth.headers).json()
    assert defaults["capabilities"]["video"]["effective"]["type"] == "replicate"
    assert [o["type"] for o in defaults["capabilities"]["video"]["options"]] == ["replicate", "gemini"]
    assert defaults["fast"]["effective"]["label"] == "GPT-5 nano"

    nano = _model(db, ws, "gpt-5-mini")
    r = client.put("/api/ai/defaults", json={"video": gemini["id"], "fast_model_id": nano.id}, headers=auth.headers)
    assert r.status_code == 200, r.text
    assert r.json()["capabilities"]["video"]["effective"]["id"] == gemini["id"]
    assert r.json()["fast"]["effective"]["label"] == "GPT-5 mini"
    assert prov.provider_for(db, ws, "video").id == gemini["id"]
    bad = client.put("/api/ai/defaults", json={"video": openai["id"]}, headers=auth.headers)
    assert bad.status_code == 400 and bad.json()["code"] == "bad_provider"


def test_sora_is_retired(client, auth, db):
    openai = add_provider(client, auth, "openai")
    ws = auth.workspace_id
    db.add(AIModel(workspace_id=ws, provider_id=openai["id"], name="sora-2", label="Sora 2", capability="video",
                   unit="second", price=0.1, active=True))
    db.flush()
    prov.seed_models(db, prov.get_provider(db, ws, openai["id"]))
    assert _model(db, ws, "sora-2").active is False
    r = client.post("/api/ai/media", json={"kind": "video", "prompt": "waves"}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "no_media_provider"


def test_radar_classification_uses_the_fast_model(client, auth, db, monkeypatch):
    from app.modules.ai import service as ai
    from app.modules.listening import analysis
    from tests.test_listening import _mention, _query
    add_provider(client, auth, "openai")
    query = _query(db, auth.workspace_id)
    _mention(db, query, "nakhla latte", analyzed=False)
    seen = {}

    def fake(db_, ws, system, user, **kwargs):
        seen.update(kwargs)
        return {"items": []}

    monkeypatch.setattr(ai, "generate_json", fake)
    analysis.classify_pending(db, auth.workspace_id, use_ai=True)
    assert seen["model_id"] == _model(db, auth.workspace_id, "gpt-5-nano").id


def test_seedance_and_wan_inputs_on_replicate(client, auth, db, mock_http):
    from app.core.storage import save_media
    from app.modules.ai import media as ai_media
    replicate = add_provider(client, auth, "replicate")
    ws = auth.workspace_id
    prov.seed_models(db, prov.get_provider(db, ws, replicate["id"]))
    still = save_media(db, ws, base64.b64decode(b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="),
                       "still.png", "image/png")
    sent = []

    def handler(method, url, kw):
        if method == "POST":
            sent.append((url, kw["json"]["input"]))
            return mock_http.response(body={"id": "p%d" % len(sent), "status": "starting"})
        return mock_http.response(body={"status": "processing"})

    mock_http(handler)
    ai_media.start_job(db, ws, "video", "Pour latte art", aspect="9:16", seconds=8, inputs=[still.id])
    url, body = sent[-1]
    assert url.endswith("/models/bytedance/seedance-2.0/predictions")
    assert body["image"].startswith("data:image/png;base64,") and body["duration"] == 8
    wan = _model(db, ws, "wan-video/wan-2.5-t2v")
    ai_media.start_job(db, ws, "video", "Pour latte art", aspect="9:16", seconds=8, inputs=[still.id],
                       model_id=wan.id)
    url, body = sent[-1]
    assert url.endswith("/models/wan-video/wan-2.5-i2v/predictions")  # a start image switches Wan to i2v
    assert body["duration"] == 10 and "aspect_ratio" not in body
    ai_media.start_job(db, ws, "video", "Pour latte art", aspect="9:16", seconds=5, model_id=wan.id)
    url, body = sent[-1]
    assert url.endswith("/models/wan-video/wan-2.5-t2v/predictions") and body["duration"] == 5


def test_gemini_omni_video(client, auth, db, mock_http):
    from app.modules.ai import media as ai_media
    add_provider(client, auth, "gemini")

    def handler(method, url, kw):
        if method == "POST":
            assert url.endswith("/v1beta/interactions") and kw["json"]["model"] == "gemini-omni-1.2-flash"
            assert kw["json"]["response_format"] == {"type": "video", "duration": "10s", "resolution": "720p",
                                                     "aspect_ratio": "9:16", "delivery": "uri"}
            return mock_http.response(body={"id": "i1", "status": "in_progress"})
        if url.endswith("/interactions/i1"):
            return mock_http.response(body={"id": "i1", "status": "completed", "outputs": [
                {"type": "video", "mime_type": "video/mp4", "uri": "https://files.example/omni.mp4"}]})
        return mock_http.response(200, MP4, {"Content-Type": "video/mp4"})

    mock_http(handler)
    job = ai_media.start_job(db, auth.workspace_id, "video", "A barista smiles", aspect="9:16", seconds=10)
    assert job.state == "running" and job.external_job == "interactions/i1"
    ai_media.poll(db, job)
    assert job.state == "done" and job.cost == pytest.approx(10 * 0.07)


def test_video_models_suggest_seedance_and_omni(client, auth, db):
    add_provider(client, auth, "gemini")
    add_provider(client, auth, "replicate")
    i2v = client.get("/api/ai/video-models", params={"mode": "i2v", "seconds": 10}, headers=auth.headers).json()
    names = [m["name"] for m in i2v["models"]]
    assert names[:3] == ["bytedance/seedance-2.0", "wan-video/wan-2.5-i2v", "gemini-omni-1.2-flash"]
    assert i2v["models"][0]["recommended"] and i2v["models"][0]["cost"] == pytest.approx(1.3)
    assert "wan-video/wan-2.5-t2v" not in names
    t2v = client.get("/api/ai/video-models", params={"mode": "t2v"}, headers=auth.headers).json()
    assert t2v["models"][0]["name"] == "gemini-omni-1.2-flash" and t2v["models"][0]["recommended"]
    assert t2v["models"][0]["audio"] is True

    from app.modules.workspaces.models import Workspace
    db.get(Workspace, auth.workspace_id).timezone = "Europe/Amsterdam"
    db.flush()
    eu = client.get("/api/ai/video-models", params={"mode": "t2v"}, headers=auth.headers).json()["models"]
    omni = next(m for m in eu if m["name"] == "gemini-omni-1.2-flash")
    assert omni["eu_limited"] and not omni["recommended"]
    assert next(m for m in eu if m["recommended"])["name"] == "wan-video/wan-2.5-t2v"


def test_production_pipelines(client, auth, db):
    add_provider(client, auth, "replicate")
    add_provider(client, auth, "gemini")
    ws = auth.workspace_id
    for provider in prov.list_providers(db, ws, "video"):
        prov.seed_models(db, provider)
    h = auth.headers
    templates = {t["key"]: t for t in client.get("/api/production/templates", headers=h).json()}
    assert templates["pipeline_detailed"]["video_mode"] == "i2v"
    assert templates["pipeline_quick"]["video_mode"] == "t2v" and "pipeline_quick_voice" not in templates

    seedance = _model(db, ws, "bytedance/seedance-2.0")
    r = client.post("/api/production/boards", json={"template": "pipeline_detailed", "video_model_id": seedance.id,
                                                    "text": "Cold brew launch"}, headers=h)
    assert r.status_code == 201, r.text
    nodes = db.query(Node).filter_by(board_id=r.json()["id"]).all()
    kinds = sorted(n.kind for n in nodes)
    assert kinds.count("audio") == 3 and {"image", "video", "merge", "captions", "post"} <= set(kinds)
    video = next(n for n in nodes if n.kind == "video")
    assert video.model_id == seedance.id and video.provider_id == seedance.provider_id
    assert next(n for n in nodes if n.kind == "text").text_value == "Cold brew launch"

    omni = _model(db, ws, "gemini-omni-1.2-flash")
    quick = client.post("/api/production/boards", json={"template": "pipeline_quick", "video_model_id": omni.id},
                        headers=h).json()
    assert {n.kind for n in db.query(Node).filter_by(board_id=quick["id"])} == {"text", "llm", "video", "post"}
    voiced = client.post("/api/production/boards", json={"template": "pipeline_quick", "video_model_id": omni.id,
                                                         "voice_over": True}, headers=h).json()
    voiced_kinds = {n.kind for n in db.query(Node).filter_by(board_id=voiced["id"])}
    assert {"audio", "merge"} <= voiced_kinds
    text_model = db.query(AIModel).filter_by(workspace_id=ws, capability="text").first()
    wrong = client.post("/api/production/boards", json={"template": "pipeline_quick", "video_model_id": text_model.id},
                        headers=h)
    assert wrong.status_code == 400 and wrong.json()["code"] == "bad_model"


def test_video_models_on_the_platform_ai_are_priced_in_credits(client, auth, db):
    from app.modules.billing import credits, platform
    platform.set_secret(db, "ai.gemini_api_key", "platform-key")
    platform.set_setting(db, "billing.ai_markup_percent", 50.0)
    rows = client.get("/api/ai/video-models", params={"mode": "t2v", "seconds": 8}, headers=auth.headers).json()["models"]
    assert rows, "the platform's video models are offered when the workspace has no own key"
    omni = next(m for m in rows if m["name"] == "gemini-omni-1.2-flash")
    model = db.get(AIModel, omni["id"])
    raw = prov.pricing.cost_of(model, seconds=8)
    assert omni["cost"] == pytest.approx(raw * 1.5, abs=0.001)
    assert omni["credits"] == pytest.approx(omni["cost"] * credits.credits_per_usd(db), rel=0.01)

    add_provider(client, auth, "gemini")  # own key: plain provider price, no credits
    own = client.get("/api/ai/video-models", params={"mode": "t2v", "seconds": 8}, headers=auth.headers).json()["models"]
    assert own and all(m["credits"] is None for m in own)
