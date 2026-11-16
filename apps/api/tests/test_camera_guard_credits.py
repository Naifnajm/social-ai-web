"""Camera settings for AI images/videos, the brand guard, and AI credits with the platform markup."""
import io

import pytest
from PIL import Image

from app.core.errors import LimitReached
from app.core.i18n import set_locale
from app.modules.ai import camera
from app.modules.ai import media as ai_media
from app.modules.ai import providers as prov
from app.modules.ai.generators import get_media_client  # noqa: F401  (patched below)
from app.modules.ai.models import AIProvider, AIUsage
from app.modules.billing import credits, limits, platform, service
from app.modules.billing.models import CreditTransaction
from app.modules.brand import guard
from app.modules.brand.models import BrandKit
from tests.test_ai import add_provider
from tests.test_billing import _set_plan, _webhook, stripe_env  # noqa: F401  (fixture)


def _png(color) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, "PNG")
    return buffer.getvalue()


class FakeImages:
    """A media client that remembers the prompt and returns a plain image."""
    supports_image_edit = True
    supports_image_to_video = True
    prompts: list = []
    color = (17, 17, 17)

    def __init__(self, *a, **k):
        self.voice = None

    def image(self, prompt, aspect, refs=None):
        FakeImages.prompts.append(prompt)
        return {"content": _png(FakeImages.color), "mimetype": "image/png"}

    def video_start(self, prompt, aspect, seconds, image=None):
        FakeImages.prompts.append(prompt)
        return {"job": "v1", "status": "running"}


@pytest.fixture()
def fake_images(monkeypatch):
    FakeImages.prompts = []
    FakeImages.color = (17, 17, 17)
    monkeypatch.setattr(ai_media, "get_media_client", FakeImages)
    return FakeImages


@pytest.fixture(autouse=True)
def _english():
    set_locale("en")  # server messages in English (another test may have left Arabic)
    yield
    set_locale("en")


def _kit(db, ws, **extra):
    kit = BrandKit(workspace_id=ws, name="Nakhla", color_primary="#1f3a2e", color_secondary="#c8a96a",
                   visual_style="Warm minimal cafe photos", is_default=True, active=True, **extra)
    db.add(kit)
    db.flush()
    return kit


# ---------------------------------------------------------------------------------------- camera
def test_camera_words_and_presets():
    shot = camera.clean({"lens": "85", "aperture": "1.8", "light": "golden_hour", "movement": "orbit",
                         "shutter": "freeze", "bogus": "x", "angle": "sideways"})
    assert shot == {"mode": "manual", "lens": "85", "aperture": "1.8", "light": "golden_hour", "movement": "orbit",
                    "shutter": "freeze"}
    image = camera.describe(shot, "image")
    assert "85mm portrait lens" in image and "f/1.8" in image and "golden hour" in image
    assert "orbits" not in image and "fast shutter" in image  # movement is for video only
    video = camera.describe(shot, "video")
    assert "orbits" in video and "fast shutter" not in video
    assert camera.describe({"mode": "auto"}) == "" and camera.describe(None) == ""
    food = camera.resolved({"preset": "food", "light": "neon"})
    assert food["lens"] == "macro" and food["light"] == "neon"  # the person's choice over the preset
    assert camera.merge({"lens": "50", "light": "softbox"}, {"lens": "85"}) == \
        {"mode": "manual", "lens": "85", "light": "softbox"}


def test_camera_options_endpoint(client, auth):
    data = client.get("/api/ai/camera", headers={**auth.headers, "Accept-Language": "ar"}).json()
    groups = {g["key"]: g for g in data["groups"]}
    assert {"camera", "lens", "aperture", "angle", "framing", "light", "light_dir", "look", "movement"} <= set(groups)
    assert groups["movement"]["kinds"] == ["video"] and groups["shutter"]["kinds"] == ["image"]
    lens = {o["key"]: o for o in groups["lens"]["options"]}
    assert lens["85"]["icon"] == "portrait" and lens["85"]["label"] == "عدسة بورتريه 85مم"
    assert {p["key"] for p in data["presets"]} >= {"product", "food", "portrait", "cinematic"}


def test_media_job_uses_the_camera(client, auth, db, fake_images):
    add_provider(client, auth, "openai")
    r = client.post("/api/ai/media", json={"kind": "image", "prompt": "Iced latte on a marble table",
                                           "shot": {"lens": "macro", "light": "window", "angle": "top_down"}},
                    headers=auth.headers)
    assert r.status_code == 201, r.text
    assert r.json()["shot"] == {"mode": "manual", "lens": "macro", "light": "window", "angle": "top_down"}
    prompt = fake_images.prompts[-1]
    assert prompt.startswith("Iced latte") and "100mm macro lens" in prompt and "top-down flat lay" in prompt


# ---------------------------------------------------------------------------------------- brand guard
def test_guide_mode_person_choices_win(client, auth, db, fake_images):
    add_provider(client, auth, "openai")
    kit = _kit(db, auth.workspace_id, photo_style={"lens": "50", "light": "softbox"}, guard_mode="guide")
    job = ai_media.start_job(db, auth.workspace_id, "image", "A croissant", brand_kit_id=kit.id,
                             shot={"light": "neon"})
    assert job.shot == {"mode": "manual", "lens": "50", "light": "neon"}
    assert "Warm minimal cafe photos" in fake_images.prompts[-1] and "BRAND RULES" not in fake_images.prompts[-1]
    # without a picked kit, a "guide" kit is not forced
    ai_media.start_job(db, auth.workspace_id, "image", "A croissant")
    assert "Warm minimal" not in fake_images.prompts[-1]


def test_strict_mode_applies_brand_everywhere(client, auth, db, fake_images):
    add_provider(client, auth, "openai")
    kit = _kit(db, auth.workspace_id, guard_mode="strict", photo_style={"lens": "50", "light": "softbox"},
               visual_rules="No people, always on light wood")
    fake_images.color = (220, 30, 200)  # bright magenta: not a brand colour
    job = ai_media.start_job(db, auth.workspace_id, "image", "A croissant", shot={"light": "neon", "angle": "low"})
    prompt = fake_images.prompts[-1]
    assert job.brand_kit_id == kit.id
    assert "BRAND RULES" in prompt and "#1f3a2e" in prompt and "No people, always on light wood" in prompt
    assert job.shot == {"mode": "manual", "light": "softbox", "angle": "low", "lens": "50"}  # brand light wins
    assert job.brand_score == 0 and "drift" in job.notice
    fake_images.color = (31, 58, 46)  # the brand green
    ok = ai_media.start_job(db, auth.workspace_id, "image", "A croissant")
    assert ok.brand_score == 100 and not ok.notice


def test_text_guard(db, auth, monkeypatch):
    from app.modules.ai import service as ai
    kit = _kit(db, auth.workspace_id, banned_words="cheap, رخيص", emoji_style="none", guard_mode="guide")
    text = "Our cheap coffee ☕ is رخيص"
    assert [i["code"] for i in guard.text_issues(kit, text)] == ["banned_words", "emojis"]
    same, notes = guard.enforce_text(db, auth.workspace_id, kit, text)
    assert same == text and len(notes) == 2  # guide: report only
    kit.guard_mode = "strict"
    monkeypatch.setattr(ai, "generate_text", lambda *a, **k: "Our great coffee is lovely")
    fixed, notes = guard.enforce_text(db, auth.workspace_id, kit, text)
    assert fixed == "Our great coffee is lovely" and "Brand guard fixed" in notes[0]
    monkeypatch.setattr(ai, "generate_text", lambda *a, **k: "still cheap ☕")  # the AI failed: words removed
    fixed, _notes = guard.enforce_text(db, auth.workspace_id, kit, text)
    assert "cheap" not in fixed and "☕" not in fixed and "رخيص" not in fixed


def test_brand_kit_api_and_check(client, auth, db):
    h = auth.headers
    r = client.post("/api/brand-kits", json={"name": "Nakhla", "color_primary": "#1f3a2e", "guard_mode": "strict",
                                             "photo_style": {"preset": "food", "lens": "nope"},
                                             "visual_rules": "Natural light only", "banned_words": "cheap"},
                    headers=h)
    assert r.status_code == 201, r.text
    kit = r.json()
    assert kit["guard_mode"] == "strict" and kit["photo_style"] == {"mode": "auto", "preset": "food"}
    assert client.patch(f"/api/brand-kits/{kit['id']}", json={"guard_mode": "bad"}, headers=h).status_code == 422
    from app.core.storage import save_media
    media = save_media(db, auth.workspace_id, _png((31, 58, 46)), "a.png", "image/png")
    check = client.post("/api/brand-kits/check", json={"brand_kit_id": kit["id"], "text": "so cheap",
                                                       "media_id": media.id}, headers=h).json()
    assert check["mode"] == "strict" and check["issues"][0]["code"] == "banned_words"
    assert check["colors"]["score"] == 100


# ---------------------------------------------------------------------------------------- credits
def _platform_ai(db, ws):
    platform.set_secret(db, "ai.openai_api_key", "sk-platform")
    provider = prov.platform_provider(db, ws, "text")
    assert provider and provider.managed
    return provider


def test_markup_is_in_every_price(client, auth, db):
    ws = auth.workspace_id
    _set_plan(db, ws, "pro")
    provider = _platform_ai(db, ws)
    usage = prov.record_usage(db, provider, None, "text", cost=1.0)
    assert usage.cost == 1.0 and usage.price == pytest.approx(1.1) and usage.charged == pytest.approx(1.1)
    platform.set_setting(db, "billing.ai_markup_percent", 25.0)
    assert credits.price_of(db, 2.0) == pytest.approx(2.5)
    picker = prov.picker(db, ws, "text")
    model = next(m for m in picker[0]["models"] if m["price_in"])
    raw = db.get(AIProvider, provider.id)
    from app.modules.ai.models import AIModel
    stored = db.query(AIModel).filter_by(provider_id=raw.id, name=model["name"]).one()
    assert model["price_in"] == pytest.approx(stored.price_in * 1.25)
    estimate = prov.estimate_task(db, ws, "text", prompt="hello " * 200)
    assert estimate["credits"] == pytest.approx(estimate["cost"] * 100, rel=0.02)
    own = AIProvider(workspace_id=ws, name="Mine", provider_type="openai")
    db.add(own)
    db.flush()
    assert prov.record_usage(db, own, None, "text", cost=1.0).price is None  # own keys: no markup


def test_credits_cover_usage_beyond_the_plan(db, auth):
    set_locale("en")
    ws = auth.workspace_id
    _set_plan(db, ws, "starter")  # $3 of AI a month
    provider = _platform_ai(db, ws)
    db.add(AIUsage(workspace_id=ws, provider_id=provider.id, cost=2.5, price=2.75))
    db.flush()
    with pytest.raises(LimitReached) as exc:
        limits.check(db, ws, "ai_credits", amount=1.0)
    assert exc.value.code == "credits_needed" and exc.value.extra["buy_credits"]
    credits.add(db, ws, "grant", 100, note="Welcome")  # 100 credits = $1
    limits.check(db, ws, "ai_credits", amount=1.0)      # $0.25 left in the plan + $1 credits
    usage = prov.record_usage(db, provider, None, "text", cost=0.5)  # price 0.55 → 0.25 plan + 0.30 credits
    assert credits.balance(db, ws) == pytest.approx(70)
    row = db.query(CreditTransaction).filter_by(workspace_id=ws, kind="usage").one()
    assert row.credits == pytest.approx(-30) and row.ref == "usage:%s" % usage.id
    prov.record_usage(db, provider, None, "text", cost=0.1)  # fully from credits
    assert credits.balance(db, ws) == pytest.approx(59)
    info = credits.available(db, ws)
    assert info["included_left"] == 0 and info["balance"] == pytest.approx(59)


def test_buy_credits_with_stripe(client, auth, db, mock_http, stripe_env):  # noqa: F811
    def handler(method, url, kw):
        if url.endswith("/v1/customers"):
            return mock_http.response(body={"id": "cus_A"})
        return mock_http.response(body={"id": "cs_9", "url": "https://checkout.stripe.com/c/cs_9"})

    calls = mock_http(handler)
    summary = client.get("/api/billing/credits", headers=auth.headers).json()
    assert summary["balance"] == 0 and summary["can_buy"] and summary["packs"][1] == \
        {"id": 1, "usd": 25.0, "credits": 2600, "bonus": 4}
    r = client.post("/api/billing/credits/checkout", json={"pack_id": 1}, headers=auth.headers)
    assert r.status_code == 200, r.text and r.json()["url"].endswith("cs_9")
    session = calls[-1]["data"]
    assert session["mode"] == "payment" and session["line_items[0][price_data][unit_amount]"] == "2500"
    assert session["metadata[kind]"] == "credits" and session["metadata[credits]"] == "2600"
    assert client.post("/api/billing/credits/checkout", json={"pack_id": 9}, headers=auth.headers).status_code == 400

    paid = {"id": "cs_9", "mode": "payment", "payment_status": "paid", "amount_total": 2500, "currency": "usd",
            "customer": "cus_A", "metadata": {"workspace_id": str(auth.workspace_id), "kind": "credits",
                                             "credits": "2600", "user_id": str(auth.user_id)}}
    assert _webhook(client, "checkout.session.completed", paid).status_code == 200
    assert _webhook(client, "checkout.session.completed", paid).status_code == 200  # a retry adds nothing
    summary = client.get("/api/billing/credits", headers=auth.headers).json()
    assert summary["balance"] == 2600
    assert summary["history"][0]["kind"] == "purchase" and summary["history"][0]["amount_paid"] == 25.0
    sub = service.get_subscription(db, auth.workspace_id)
    assert sub.plan_code == "trial"  # buying credits does not touch the plan


def test_admin_markup_packs_and_grants(client, db, auth):
    from app.modules.auth.models import User
    db.get(User, auth.user_id).is_superadmin = True
    db.flush()
    h = auth.headers
    r = client.put("/api/admin/settings", json={"values": {"billing.ai_markup_percent": "15",
                                                           "billing.credit_packs": [{"usd": 5, "credits": 500}]}},
                   headers=h)
    assert r.status_code == 200, r.text
    assert credits.markup(db) == 15.0 and credits.packs(db) == [{"id": 0, "usd": 5.0, "credits": 500, "bonus": 0}]
    bad = client.put("/api/admin/settings", json={"values": {"billing.ai_markup_percent": "-3"}}, headers=h)
    assert bad.status_code == 400
    r = client.post(f"/api/admin/workspaces/{auth.workspace_id}/credits", json={"credits": 300, "note": "Bank"},
                    headers=h)
    assert r.json() == {"balance": 300}
