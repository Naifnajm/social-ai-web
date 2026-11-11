"""AI providers, catalog, price list, pricing/costs, budgets, text generation clients and JSON parsing."""
import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.core.http import ApiError
from app.core.models import ApiLog
from app.modules.ai import catalog, pricing, prompts
from app.modules.ai import providers as prov
from app.modules.ai import service as ai
from app.modules.ai.models import AIModel, AIProvider, AIUsage
from tests.conftest import signup

KEY = "sk-test-123"


def add_provider(client, auth, provider_type="openai", **extra):
    body = {"provider_type": provider_type, "api_key": KEY, **extra}
    r = client.post("/api/ai/providers", json=body, headers=auth.headers)
    assert r.status_code == 201, r.text
    return r.json()


def chat_answer(text, prompt_tokens=0, completion_tokens=0):
    body = {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
    if prompt_tokens or completion_tokens:
        body["usage"] = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    return body


# ------------------------------------------------------------------ catalog
def test_catalog_is_consistent(client, auth):
    assert len(catalog.CATALOG) >= 20
    for key, meta in catalog.CATALOG.items():
        assert meta["label"], key
        assert meta["caps"] <= {"text", "image", "video", "audio", "stt"}, key
        if "text" in meta["caps"]:
            assert meta["engine"], key
        for name, cap, unit, *_rest in pricing.entries(key):
            assert cap in meta["caps"], (key, name)
            assert unit in pricing.UNITS
    r = client.get("/api/ai/catalog", headers=auth.headers)
    assert r.status_code == 200
    entries = {e["type"]: e for e in r.json()}
    assert entries["openai"]["key_url"] == "https://platform.openai.com/api-keys"
    assert entries["openai"]["default_models"]["text"] == "gpt-5-mini"
    assert entries["elevenlabs"]["balance_supported"] is True
    assert entries["anthropic"]["balance_supported"] is False
    assert entries["custom"]["needs_base_url"] is True
    assert any(m["name"] == "claude-opus-5-5" and m["price_in"] == 4.0 for m in entries["anthropic"]["models"])


# ------------------------------------------------------------------ providers CRUD
def test_provider_crud_defaults_and_key_never_returned(client, auth):
    data = add_provider(client, auth, "openai")
    assert data["has_key"] is True and "api_key" not in data
    assert KEY not in str(data)
    assert data["name"] == "OpenAI"
    assert data["text_model"] == "gpt-5-mini" and data["video_model"] == "sora-2" and data["voice"] == "alloy"
    assert data["is_default"] is True  # first text provider becomes the default
    assert data["capabilities"] == ["text", "image", "video", "audio", "stt"]
    assert data["models_count"] == len(pricing.entries("openai"))
    assert data["wallet"]["kind"] == "spent"

    listing = client.get("/api/ai/providers", headers=auth.headers).json()
    assert KEY not in str(listing)

    second = add_provider(client, auth, "gemini", is_default=True)
    assert second["is_default"] is True
    first = client.get(f"/api/ai/providers/{data['id']}", headers=auth.headers).json()
    assert first["is_default"] is False

    # update: change key (state back to draft), clear key, rename
    r = client.patch(f"/api/ai/providers/{data['id']}", json={"name": "My OpenAI", "monthly_budget": 25},
                     headers=auth.headers)
    assert r.json()["name"] == "My OpenAI" and r.json()["wallet"]["kind"] == "budget"
    r = client.patch(f"/api/ai/providers/{data['id']}", json={"api_key": ""}, headers=auth.headers)
    assert r.json()["has_key"] is False

    # a media-only provider cannot be the text default
    eleven = add_provider(client, auth, "elevenlabs")
    assert eleven["is_default"] is False
    r = client.post(f"/api/ai/providers/{eleven['id']}/default", headers=auth.headers)
    assert r.status_code == 400
    r = client.post(f"/api/ai/providers/{data['id']}/default", headers=auth.headers)
    assert r.json()["is_default"] is True

    # deleting the default promotes another text provider
    assert client.delete(f"/api/ai/providers/{data['id']}", headers=auth.headers).status_code == 204
    assert client.get(f"/api/ai/providers/{second['id']}", headers=auth.headers).json()["is_default"] is True


def test_provider_validation(client, auth):
    r = client.post("/api/ai/providers", json={"provider_type": "nope"}, headers=auth.headers)
    assert r.status_code == 400
    r = client.post("/api/ai/providers", json={"provider_type": "custom", "api_key": "x"}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "base_url_required"


def test_provider_isolation_and_roles(client, auth, db):
    mine = add_provider(client, auth, "openai")
    other = signup(client, email="other@example.com", workspace="Other")
    for method, path in (("get", f"/api/ai/providers/{mine['id']}"), ("patch", f"/api/ai/providers/{mine['id']}"),
                         ("delete", f"/api/ai/providers/{mine['id']}"),
                         ("post", f"/api/ai/providers/{mine['id']}/test"),
                         ("get", f"/api/ai/providers/{mine['id']}/models")):
        kwargs = {"json": {"name": "hack"}} if method == "patch" else {}
        r = getattr(client, method)(path, headers=other.headers, **kwargs)
        assert r.status_code == 404, (method, path, r.status_code)
    assert client.get("/api/ai/providers", headers=other.headers).json() == []
    model_id = client.get(f"/api/ai/providers/{mine['id']}/models", headers=auth.headers).json()[0]["id"]
    assert client.patch(f"/api/ai/models/{model_id}", json={"price": 9}, headers=other.headers).status_code == 404
    assert client.post("/api/ai/estimate", json={"capability": "text", "model_id": model_id},
                       headers=other.headers).status_code == 404
    assert client.get("/api/ai/pickers?capability=text", headers=other.headers).json()["groups"] == []
    assert not ai.has_provider(db, other.workspace_id, "text")
    assert ai.has_provider(db, auth.workspace_id, "text")
    # an editor of the workspace cannot manage providers
    from app.modules.workspaces.models import Membership
    db.add(Membership(user_id=other.user_id, workspace_id=auth.workspace_id, role="editor"))
    db.flush()
    as_editor = {**other.headers, "X-Workspace": str(auth.workspace_id)}
    assert client.get("/api/ai/providers", headers=as_editor).status_code == 403
    assert client.get("/api/ai/pickers?capability=text", headers=as_editor).status_code == 200


# ------------------------------------------------------------------ models & prices
def test_models_seeded_with_prices_and_crud(client, auth):
    provider = add_provider(client, auth, "openai")
    models = client.get(f"/api/ai/providers/{provider['id']}/models", headers=auth.headers).json()
    image = next(m for m in models if m["name"] == "gpt-image-1")
    assert (image["capability"], image["unit"], image["price"]) == ("image", "image", 0.042)
    assert image["price_label"] == "$0.042 / image"
    text = next(m for m in models if m["name"] == "gpt-5-mini")
    assert text["price_label"] == "$0.25 / $2 per 1M"

    r = client.post(f"/api/ai/providers/{provider['id']}/models", headers=auth.headers,
                    json={"name": "gpt-9", "capability": "text", "unit": "tokens", "price_in": 1, "price_out": 3})
    assert r.status_code == 201 and r.json()["label"] == "gpt-9"
    assert client.post(f"/api/ai/providers/{provider['id']}/models", headers=auth.headers,
                       json={"name": "gpt-9", "capability": "text"}).status_code == 400
    r = client.patch(f"/api/ai/models/{image['id']}", json={"price": 0.05}, headers=auth.headers)
    assert r.json()["price"] == 0.05
    assert client.delete(f"/api/ai/models/{text['id']}", headers=auth.headers).status_code == 204
    reloaded = client.post(f"/api/ai/providers/{provider['id']}/models/load-catalog", headers=auth.headers).json()
    names = [m["name"] for m in reloaded]
    assert "gpt-5-mini" in names and "gpt-9" in names
    assert next(m for m in reloaded if m["name"] == "gpt-image-1")["price"] == 0.05  # edited price kept


def test_pickers_and_estimates(client, auth):
    openai = add_provider(client, auth, "openai")
    r = client.get("/api/ai/pickers?capability=video", headers=auth.headers).json()
    group = r["groups"][0]
    assert group["provider"] == "OpenAI" and group["wallet"]["kind"] == "spent"
    sora = next(m for m in group["models"] if m["name"] == "sora-2")
    assert sora["default"] is True and sora["price_label"] == "$0.1 / second"

    est = client.post("/api/ai/estimate", json={"capability": "video", "model_id": sora["id"], "prompt": "x",
                                                "seconds": 8}, headers=auth.headers).json()
    assert est["cost"] == pytest.approx(0.8) and "8s" in est["detail"] and est["known"] is True
    text = client.post("/api/ai/estimate", json={"capability": "text", "prompt": "Write a launch post " * 20},
                       headers=auth.headers).json()
    assert text["cost"] > 0 and text["model"] == "GPT-5 mini"

    local = add_provider(client, auth, "ollama")
    assert client.post("/api/ai/estimate", json={"capability": "text", "provider_id": local["id"]},
                       headers=auth.headers).json()["cost"] == 0
    eleven = add_provider(client, auth, "elevenlabs")
    music = client.post("/api/ai/estimate", json={"capability": "audio", "provider_id": eleven["id"], "seconds": 30,
                                                  "audio_mode": "music"}, headers=auth.headers).json()
    assert music["cost"] == pytest.approx(30 * 0.013)
    speech = client.post("/api/ai/estimate", json={"capability": "audio", "provider_id": eleven["id"],
                                                   "prompt": "a" * 2000}, headers=auth.headers).json()
    assert speech["cost"] == pytest.approx(2 * 0.18)
    assert openai["id"] != eleven["id"]
    status = client.get("/api/ai/status", headers=auth.headers).json()
    assert status["text"] and status["video"] and status["audio"] and status["stt"]


# ------------------------------------------------------------------ text generation (request shapes)
def test_openai_generate_records_usage(client, auth, db, mock_http):
    provider = add_provider(client, auth, "openai")

    def handler(method, url, kw):
        assert url == "https://api.openai.com/v1/chat/completions"
        assert kw["headers"]["Authorization"] == f"Bearer {KEY}"
        assert kw["json"]["max_completion_tokens"] == 4000
        assert kw["json"]["messages"][0] == {"role": "system", "content": "sys"}
        return mock_http.response(body=chat_answer("Hello world", 1000, 500))

    calls = mock_http(handler)
    text, usage = ai.generate_text_with_usage(db, auth.workspace_id, "sys", "prompt", purpose="post caption",
                                              user_id=auth.user_id)
    assert text == "Hello world" and len(calls) == 1
    # gpt-5-mini: $0.25 / $2 per 1M tokens
    assert usage.cost == pytest.approx(1000 * 0.25 / 1e6 + 500 * 2.0 / 1e6)
    row = db.get(AIUsage, usage.usage_id)
    assert (row.provider_id, row.model_name, row.tokens_in, row.tokens_out, row.purpose) == (
        provider["id"], "gpt-5-mini", 1000, 500, "post caption")
    assert row.model_id is not None
    spent = client.get(f"/api/ai/providers/{provider['id']}", headers=auth.headers).json()["spent_month"]
    assert spent == pytest.approx(usage.cost, abs=1e-4)
    log = db.scalars(select(ApiLog).where(ApiLog.ref_id == provider["id"])).first()
    assert log and KEY not in (log.request_body or "")


def test_anthropic_generate_skips_thinking_and_sampling(client, auth, db, mock_http):
    add_provider(client, auth, "anthropic")

    def handler(method, url, kw):
        assert url == "https://api.anthropic.com/v1/messages"
        assert kw["headers"]["x-api-key"] == KEY
        assert kw["headers"]["anthropic-version"] == "2026-10-21"
        assert kw["headers"]["anthropic-beta"] == "server-side-fallback-2026-07-01"
        body = kw["json"]
        assert "temperature" not in body and "top_p" not in body
        assert body["fallbacks"] == "default"
        assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 16000 and body["system"] == "sys"
        return mock_http.response(body={"stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5},
                                        "content": [{"type": "thinking", "thinking": ""},
                                                    {"type": "text", "text": "Bonjour"}]})

    mock_http(handler)
    text, usage = ai.generate_text_with_usage(db, auth.workspace_id, "sys", "prompt")
    assert text == "Bonjour"
    assert usage.cost == pytest.approx(10 * 4.0 / 1e6 + 5 * 20.0 / 1e6)


def test_anthropic_refusal_and_haiku_without_fallback(client, auth, db, mock_http):
    provider = add_provider(client, auth, "anthropic")
    mock_http(lambda m, u, k: mock_http.response(body={"stop_reason": "refusal", "content": []}))
    with pytest.raises(ApiError) as exc:
        ai.generate_text(db, auth.workspace_id, "sys", "prompt")
    assert "declined" in exc.value.message
    assert db.scalar(select(AIUsage).where(AIUsage.workspace_id == auth.workspace_id)) is None

    haiku = db.scalar(select(AIModel).where(AIModel.provider_id == provider["id"],
                                            AIModel.name == "claude-haiku-5-5"))

    def handler(method, url, kw):
        assert "fallbacks" not in kw["json"] and "anthropic-beta" not in kw["headers"]
        assert kw["json"]["model"] == "claude-haiku-5-5"
        return mock_http.response(body={"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]})

    mock_http(handler)
    assert ai.generate_text(db, auth.workspace_id, "sys", "prompt", model_id=haiku.id) == "ok"


def test_gemini_generate(client, auth, db, mock_http):
    add_provider(client, auth, "gemini")

    def handler(method, url, kw):
        assert url.endswith("/v1beta/models/gemini-2.5-flash:generateContent")
        assert kw["headers"]["x-goog-api-key"] == KEY
        assert kw["json"]["systemInstruction"] == {"parts": [{"text": "sys"}]}
        assert kw["json"]["generationConfig"]["maxOutputTokens"] == 8000
        return mock_http.response(body={"candidates": [{"content": {"parts": [
            {"text": "thinking…", "thought": True}, {"text": "Hallo"}]}}],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, "thoughtsTokenCount": 2}})

    mock_http(handler)
    text, usage = ai.generate_text_with_usage(db, auth.workspace_id, "sys", "prompt")
    assert text == "Hallo" and (usage.tokens_in, usage.tokens_out) == (7, 5)


def test_openai_compatible_and_azure(client, auth, db, mock_http):
    custom = add_provider(client, auth, "custom", base_url="https://api.example.ai/v1", text_model="deepseek-chat")

    def handler(method, url, kw):
        assert url == "https://api.example.ai/v1/chat/completions"
        assert "max_tokens" in kw["json"] and "max_completion_tokens" not in kw["json"]
        return mock_http.response(body=chat_answer("ok"))

    mock_http(handler)
    text, usage = ai.generate_text_with_usage(db, auth.workspace_id, "sys", "prompt", provider_id=custom["id"])
    assert text == "ok" and usage.tokens_in > 0  # estimated when the server reports no usage

    azure = add_provider(client, auth, "azure_openai", base_url="https://acme.openai.azure.com/openai/v1")

    def azure_handler(method, url, kw):
        assert url == "https://acme.openai.azure.com/openai/v1/chat/completions"
        assert kw["headers"]["api-key"] == KEY and "Authorization" not in kw["headers"]
        return mock_http.response(body=chat_answer("azure ok"))

    mock_http(azure_handler)
    assert ai.generate_text(db, auth.workspace_id, "s", "p", provider_id=azure["id"]) == "azure ok"


def test_no_provider_and_generate_json(client, auth, db, mock_http):
    with pytest.raises(AppError) as exc:
        ai.generate_text(db, auth.workspace_id, "sys", "prompt")
    assert exc.value.code == "no_ai_provider"
    add_provider(client, auth, "openai")
    answer = 'Sure! Here it is:\n```json\n{"intent": "price", "urgent": false,}\n```\nAnything else?'
    seen = {}

    def handler(method, url, kw):
        seen["system"] = kw["json"]["messages"][0]["content"]
        return mock_http.response(body=chat_answer(answer))

    mock_http(handler)
    data = ai.generate_json(db, auth.workspace_id, "Classify the message.", "How much?", purpose="inbox triage")
    assert data == {"intent": "price", "urgent": False}
    assert "JSON" in seen["system"]
    mock_http(lambda m, u, k: mock_http.response(body=chat_answer("I cannot do that.")))
    with pytest.raises(AppError) as exc:
        ai.generate_json(db, auth.workspace_id, "sys", "user")
    assert exc.value.code == "ai_bad_json"
    mock_http(lambda m, u, k: mock_http.response(body=chat_answer('[{"a": 1}, {"a": 2}]')))
    assert ai.generate_json(db, auth.workspace_id, "Return JSON.", "x") == {"items": [{"a": 1}, {"a": 2}]}


def test_parse_json_strategies():
    assert prompts.parse_json('{"a": "b"}') == {"a": "b"}
    assert prompts.parse_json('Answer: {"a": {"b": "}"}} done') == {"a": {"b": "}"}}
    assert prompts.parse_json("```\n[1, 2]\n```") == [1, 2]
    assert prompts.parse_json('text [ {"x": 1} ] tail') == [{"x": 1}]
    assert prompts.parse_json("nothing here") is None


def test_test_connection_and_errors_logged_without_secret(client, auth, db, mock_http):
    provider = add_provider(client, auth, "openai")
    mock_http(lambda m, u, k: mock_http.response(body={"data": [{"id": "gpt-5-mini"}, {"id": "gpt-5"}]}))
    r = client.post(f"/api/ai/providers/{provider['id']}/test", headers=auth.headers).json()
    assert r["ok"] is True and r["provider"]["state"] == "ok" and "gpt-5" in r["models"]
    assert r["provider"]["available_models"] == ["gpt-5", "gpt-5-mini"]

    mock_http(lambda m, u, k: mock_http.response(401, {"error": {"message": "Incorrect API key"}}))
    r = client.post(f"/api/ai/providers/{provider['id']}/test", headers=auth.headers).json()
    assert r["ok"] is False and r["provider"]["state"] == "error"
    assert "Incorrect API key" in r["provider"]["last_error"]
    log = db.scalars(select(ApiLog).where(ApiLog.ref_id == provider["id"], ApiLog.status_code == 401)).first()
    assert log and KEY not in (log.request_body or "") + (log.response_body or "")

    eleven = add_provider(client, auth, "elevenlabs")
    mock_http(lambda m, u, k: mock_http.response(body={"voices": [{"name": "Rachel", "voice_id": "v1"}]}))
    r = client.post(f"/api/ai/providers/{eleven['id']}/test", headers=auth.headers).json()
    assert r["ok"] and r["models"] == ["Rachel (v1)"]


def test_try_prompt_endpoint(client, auth, mock_http):
    provider = add_provider(client, auth, "openai")
    mock_http(lambda m, u, k: mock_http.response(body=chat_answer("I work!", 20, 5)))
    r = client.post(f"/api/ai/providers/{provider['id']}/try", headers=auth.headers).json()
    assert r["ok"] and r["message"] == "I work!"
    mock_http(lambda m, u, k: mock_http.response(500, {"error": {"message": "boom"}}))
    r = client.post(f"/api/ai/providers/{provider['id']}/try", headers=auth.headers).json()
    assert r["ok"] is False and "boom" in r["message"]


# ------------------------------------------------------------------ balances, budgets, billing
def test_balance_refresh(client, auth, mock_http):
    stability = add_provider(client, auth, "stability")
    assert stability["balance_supported"] is True
    mock_http(lambda m, u, k: mock_http.response(body={"credits": 123.5}))
    r = client.post(f"/api/ai/providers/{stability['id']}/balance", headers=auth.headers).json()
    assert r["ok"] and r["provider"]["balance"] == 123.5 and r["provider"]["balance_unit"] == "credits"
    assert r["provider"]["wallet"]["kind"] == "balance"

    eleven = add_provider(client, auth, "elevenlabs")
    mock_http(lambda m, u, k: mock_http.response(body={"character_limit": 100000, "character_count": 25000}))
    r = client.post(f"/api/ai/providers/{eleven['id']}/balance", headers=auth.headers).json()
    assert r["provider"]["balance"] == 75000

    router = add_provider(client, auth, "openrouter")

    def or_handler(method, url, kw):
        assert url == "https://openrouter.ai/api/v1/credits"
        return mock_http.response(body={"data": {"total_credits": 20, "total_usage": 4.5}})

    mock_http(or_handler)
    r = client.post(f"/api/ai/providers/{router['id']}/balance", headers=auth.headers).json()
    assert r["provider"]["balance"] == 15.5 and r["provider"]["balance_unit"] == "USD"

    openai = add_provider(client, auth, "openai")
    assert openai["balance_supported"] is False
    assert client.post(f"/api/ai/providers/{openai['id']}/balance", headers=auth.headers).status_code == 400


def test_budget_enforced(client, auth, db, mock_http):
    provider = add_provider(client, auth, "openai", monthly_budget=20)
    db.add(AIUsage(workspace_id=auth.workspace_id, provider_id=provider["id"], cost=5, capability="text"))
    db.flush()
    data = client.get(f"/api/ai/providers/{provider['id']}", headers=auth.headers).json()
    assert (data["wallet"]["kind"], data["wallet"]["amount"], data["wallet"]["budget"]) == ("budget", 15, 20)

    db.add(AIUsage(workspace_id=auth.workspace_id, provider_id=provider["id"], cost=15, capability="image"))
    db.flush()
    calls = mock_http(lambda m, u, k: pytest.fail("must not call the provider"))
    with pytest.raises(AppError) as exc:
        ai.generate_text(db, auth.workspace_id, "sys", "prompt")
    assert exc.value.code == "ai_budget_exceeded" and exc.value.status_code == 402
    r = client.post("/api/ai/text", json={"brief": "launch"}, headers=auth.headers)
    assert r.status_code == 402 and r.json()["code"] == "ai_budget_exceeded"
    r = client.post("/api/ai/media", json={"kind": "video", "prompt": "waves", "seconds": 8}, headers=auth.headers)
    assert r.status_code == 402
    assert calls == []
    # raising the budget unblocks
    client.patch(f"/api/ai/providers/{provider['id']}", json={"monthly_budget": 50}, headers=auth.headers)
    mock_http(lambda m, u, k: mock_http.response(body=chat_answer("ok")))
    assert ai.generate_text(db, auth.workspace_id, "sys", "prompt") == "ok"


def test_billing_limit_is_checked_with_cost(client, auth, db, mock_http, monkeypatch):
    from app.core.errors import LimitReached
    from app.modules.billing import limits
    add_provider(client, auth, "openai")
    seen = []

    def fake_check(db_, ws_id, resource, amount=1):
        seen.append((ws_id, resource, amount))
        raise LimitReached("AI credits used up", code="limit_ai_credits")

    monkeypatch.setattr(limits, "check", fake_check)
    with pytest.raises(LimitReached):
        ai.generate_text(db, auth.workspace_id, "sys", "prompt")
    # own keys never consume plan credits (amount 0), but a blocked workspace is still refused
    assert seen[0][0] == auth.workspace_id and seen[0][1] == "ai_credits" and seen[0][2] == 0


# ------------------------------------------------------------------ "Write with AI"
def test_build_prompt_respects_limits_and_voice():
    system, user = prompts.build_prompts("We sell POS systems.", "New kiosk", "friendly", "ar", "short",
                                         ["x", "facebook"])
    assert "We sell POS systems." in system and "Arabic" in system and "Friendly" in system
    assert "270" in user  # strictest limit (X) is enforced
    system, _user = prompts.build_prompts("", "x", None, "auto", "long", [], hashtags=False, emojis=False)
    assert "same language as the brief" in system and "Do not use hashtags" in system and "Do not use emojis" in system


def test_parse_tailored_answer():
    text = '```json\n{"main": "**Hi** there", "variants": {"x": "Hi", "tiktok": "ignored"}}\n```'
    assert prompts.parse_answer(text, tailor=True, platforms=["x"]) == ("Hi there", {"x": "Hi"})
    assert prompts.parse_answer('"Just a post"', tailor=True, platforms=["x"]) == ("Just a post", {})


def test_write_endpoint_tailored_with_brand(client, auth, db, mock_http):
    add_provider(client, auth, "openai")
    kit = client.post("/api/brand-kits", json={"name": "Stravica", "tone": "Warm and short", "hashtags": "#pos"},
                      headers=auth.headers).json()
    answer = '{"main": "Main text", "variants": {"x": "Short", "facebook": "Long version"}}'
    seen = {}

    def handler(method, url, kw):
        seen["system"], seen["user"] = kw["json"]["messages"][0]["content"], kw["json"]["messages"][1]["content"]
        return mock_http.response(body=chat_answer(answer, 300, 80))

    mock_http(handler)
    r = client.post("/api/ai/text", headers=auth.headers, json={
        "brief": "launch", "tailor": True, "platforms": ["x", "facebook"], "tone": "playful", "language": "en"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["text"] == "Main text" and data["variants"] == {"x": "Short", "facebook": "Long version"}
    assert data["provider"] == "OpenAI" and data["model"] == "gpt-5-mini" and data["cost"] > 0
    assert "Warm and short" in seen["system"] and "Playful" in seen["system"]  # default brand kit applied
    assert '"x": "<version adapted to x>"' in seen["user"]
    assert kit["is_default"]
    usage = db.scalars(select(AIUsage).where(AIUsage.workspace_id == auth.workspace_id)).all()
    assert len(usage) == 1 and usage[0].purpose.endswith(": launch") and usage[0].user_id == auth.user_id

    mock_http(lambda m, u, k: mock_http.response(body=chat_answer("#coffee #morning")))
    r = client.post("/api/ai/text", json={"preset": "hashtags", "brief": "Morning coffee post"}, headers=auth.headers)
    assert r.json()["text"] == "#coffee #morning"
    assert client.post("/api/ai/text", json={"brief": " "}, headers=auth.headers).status_code == 400


def test_write_uses_account_platforms(client, auth, db, mock_http):
    from app.modules.social.models import SocialAccount
    add_provider(client, auth, "openai")
    other = signup(client, email="o2@example.com", workspace="O2")
    seen = {}

    def handler(method, url, kw):
        seen["user"] = kw["json"]["messages"][1]["content"]
        return mock_http.response(body=chat_answer("post"))

    mock_http(handler)
    mine = SocialAccount(workspace_id=auth.workspace_id, name="X", platform="x")
    foreign = SocialAccount(workspace_id=other.workspace_id, name="LI", platform="linkedin")
    db.add_all([mine, foreign])
    db.flush()
    client.post("/api/ai/text", json={"brief": "hi", "account_ids": [mine.id, foreign.id]}, headers=auth.headers)
    assert "- x:" in seen["user"] and "linkedin" not in seen["user"]


def test_suggest_visual(client, auth, mock_http):
    add_provider(client, auth, "openai")

    def handler(method, url, kw):
        assert "image generators" in kw["json"]["messages"][0]["content"]
        return mock_http.response(body=chat_answer('"A warm cafe at sunrise"'))

    mock_http(handler)
    r = client.post("/api/ai/suggest-visual", json={"kind": "image", "text": "New breakfast menu"},
                    headers=auth.headers)
    assert r.json()["prompt"] == "A warm cafe at sunrise"


# ------------------------------------------------------------------ usage & costs
def test_usage_list_and_summary(client, auth, db):
    provider = add_provider(client, auth, "openai")
    other = signup(client, email="x@example.com", workspace="X")
    for cost, cap, model in ((0.5, "text", "gpt-5-mini"), (1.5, "video", "sora-2"), (0.25, "text", "gpt-5-mini")):
        db.add(AIUsage(workspace_id=auth.workspace_id, provider_id=provider["id"], cost=cost, capability=cap,
                       model_name=model, user_id=auth.user_id, purpose="test"))
    db.add(AIUsage(workspace_id=other.workspace_id, cost=99, capability="text"))
    db.flush()
    page = client.get("/api/ai/usage", headers=auth.headers).json()
    assert page["total"] == 3 and page["items"][0]["provider"] == "OpenAI" and page["items"][0]["user_name"] == "Owner"
    assert client.get("/api/ai/usage?capability=video", headers=auth.headers).json()["total"] == 1
    summary = client.get("/api/ai/usage/summary", headers=auth.headers).json()
    assert summary["total_cost"] == pytest.approx(2.25) and summary["total_calls"] == 3
    assert summary["by_provider"][0]["label"] == "OpenAI"
    assert {r["key"]: r["cost"] for r in summary["by_model"]} == {"sora-2": 1.5, "gpt-5-mini": 0.75}
    assert len(summary["by_day"]) == 30 and summary["by_day"][-1]["cost"] == pytest.approx(2.25)
    assert summary["month_cost"] == pytest.approx(2.25)
    assert summary["budgets"][0]["spent_month"] == pytest.approx(2.25)
    assert client.get("/api/ai/usage/summary", headers=other.headers).json()["total_cost"] == 99


def test_provider_helpers(db, auth):
    provider = prov.create_provider(db, auth.workspace_id, {"provider_type": "luma", "api_key": "k"})
    assert provider.name == "Luma AI" and provider.image_model == "photon-1" and not provider.is_default
    assert prov.provider_for(db, auth.workspace_id, "video").id == provider.id
    with pytest.raises(AppError) as exc:
        prov.provider_for(db, auth.workspace_id, "audio")
    assert exc.value.code == "no_media_provider" and "ElevenLabs" in exc.value.detail
    assert db.get(AIProvider, provider.id).api_key == "k"


def test_platform_keys_serve_workspaces_without_a_provider(db, client, auth, monkeypatch):
    """No own provider: the platform key is used, the cost counts as AI credits, and member limits apply."""
    from app.modules.ai import clients, providers as prov, service
    from app.modules.ai.models import AIProvider
    from app.modules.billing import limits, platform
    from app.modules.workspaces.models import Membership

    class FakeClient:
        last_usage = (1000, 500)

        def __init__(self, model):
            self.model = model

        def generate(self, system, user):
            return "مرحبا"

    seen = {}

    def fake_client(provider, model=None, max_tokens=None):
        seen["key"], seen["managed"] = provider.api_key, provider.managed
        return FakeClient(model or provider.text_model)

    monkeypatch.setattr(clients, "get_client", fake_client)
    assert not service.has_provider(db, auth.workspace_id)
    platform.set_secret(db, "ai.openai_api_key", "sk-platform")
    platform.set_setting(db, "ai.default_provider", "openai")
    db.flush()
    assert service.has_provider(db, auth.workspace_id)

    text, usage = service.generate_text_with_usage(db, auth.workspace_id, "sys", "write a post", user_id=auth.user_id)
    assert text == "مرحبا" and seen == {"key": "sk-platform", "managed": True}
    managed = db.scalar(__import__("sqlalchemy").select(AIProvider).where(AIProvider.managed.is_(True)))
    assert managed.workspace_id == auth.workspace_id and usage.provider_id == managed.id
    spent = limits.ai_spend_month(db, auth.workspace_id)
    assert spent > 0 and limits.ai_spend_month(db, auth.workspace_id, auth.user_id) == spent
    # the workspace cannot see or edit the platform's provider
    assert prov.list_providers(db, auth.workspace_id) == []
    assert client.get(f"/api/ai/providers/{managed.id}", headers=auth.headers).status_code == 404
    # a personal limit below what was spent blocks the next request
    membership = db.scalar(__import__("sqlalchemy").select(Membership).where(Membership.user_id == auth.user_id))
    membership.ai_monthly_limit = spent / 2
    db.flush()
    import pytest
    from app.core.errors import AppError
    with pytest.raises(AppError) as error:
        service.generate_text(db, auth.workspace_id, "sys", "again", user_id=auth.user_id)
    assert error.value.code == "member_ai_limit"
    # a new key in the admin settings reaches the workspace on its next request
    membership.ai_monthly_limit = None
    platform.set_secret(db, "ai.openai_api_key", "sk-rotated")
    db.flush()
    service.generate_text(db, auth.workspace_id, "sys", "again", user_id=auth.user_id)
    assert seen["key"] == "sk-rotated"
