"""Every production template finishes with OpenAI (ChatGPT) as the only AI provider, own key or the platform's:
no video model → a slow zoom on the picture, no music / effects provider → those blocks are skipped, an
undesigned card → designed automatically in the brand."""
import base64

import pytest

from tests.production_fakes import HAS_FFMPEG, png, real_media
from tests.test_ai import add_provider

pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")


def handler_factory(mock_http, seen):
    def handler(method, url, kw):
        seen.append(url.split("?")[0])
        if url.endswith("/chat/completions"):
            return mock_http.response(body={"choices": [{"message": {"content": "A warm iced latte in morning sun. Short voice-over line."}, "finish_reason": "stop"}],
                                            "usage": {"prompt_tokens": 50, "completion_tokens": 30}})
        if "/images/" in url:
            return mock_http.response(body={"data": [{"b64_json": base64.b64encode(png((1024, 1536))).decode()}]})
        if url.endswith("/audio/speech"):
            audio = real_media()[1] if HAS_FFMPEG else b"ID3"
            return mock_http.response(200, audio, {"Content-Type": "audio/mpeg"})
        if url.endswith("/audio/transcriptions"):
            return mock_http.response(body={"text": "A warm iced latte", "duration": 2.0, "segments": [
                {"start": 0.0, "end": 2.0, "text": "A warm iced latte"}]})
        if url.endswith("/models"):
            return mock_http.response(body={"data": [{"id": "gpt-5-mini"}]})
        return mock_http.response(404, {"error": {"message": f"unexpected {url}"}})
    return handler


@pytest.mark.parametrize("mode", ["own_key", "platform_key"])
def test_probe(client, auth, db, mock_http, mode):
    seen = []
    mock_http(handler_factory(mock_http, seen))
    if mode == "own_key":
        add_provider(client, auth, "openai")
    else:
        from app.modules.billing import platform, service
        platform.set_secret(db, "ai.openai_api_key", "sk-platform")
        platform.set_setting(db, "ai.default_provider", "openai")
        service.apply_plan(db, service.get_subscription(db, auth.workspace_id), "business")
        db.flush()
    templates = client.get("/api/production/templates", headers=auth.headers).json()
    results = {}
    for tpl in templates:
        if tpl["key"] == "blank":
            continue
        body = {"template": tpl["key"]}
        r = client.post("/api/production/boards", json=body, headers=auth.headers)
        if r.status_code != 201:
            results[tpl["key"]] = {"create_error": r.json()}
            continue
        board = r.json()["id"]
        est = client.get(f"/api/production/boards/{board}/estimate", headers=auth.headers).json()
        graph = client.post(f"/api/production/boards/{board}/run", json={}, headers=auth.headers).json()
        results[tpl["key"]] = {"preflight_missing": est.get("missing"), "nodes": [
            {"kind": n["kind"], "name": n["name"], "state": n["state"], "error": n.get("error"), "notice": n.get("notice"),
             "model": n.get("model_label"), "audio_mode": n.get("audio_mode")} for n in graph["nodes"]]}
    assert set(results) >= {"pipeline_detailed", "pipeline_quick", "product_ad", "music_reel", "quote_card"}
    for key, result in results.items():
        assert "create_error" not in result, (key, result)
        assert result["preflight_missing"] == [], (key, result["preflight_missing"])
        failed = [(n["kind"], n["error"]) for n in result["nodes"] if n["state"] != "done"]
        assert not failed, (key, failed)
    notices = {n["kind"]: n["notice"] for n in results["pipeline_detailed"]["nodes"] if n["notice"]}
    assert "slow zoom" in notices["video"] and "skipped" in notices["audio"]
    assert not any("sora" in url or "/videos" in url for url in seen)
