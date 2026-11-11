"""Brand kits: identity details and the AI draft (POST /brand-kits/generate)."""
from app.core.errors import AppError
from app.modules.ai import service as ai_service
from app.modules.brand import identity


def test_kit_keeps_identity_details(client, auth):
    body = {"name": "Rif Coffee", "color_primary": "#1f3d2b", "color_accent": "#d9a441", "font_heading": "'Cairo', sans-serif",
            "description": "Specialty coffee roasted in Riyadh.", "industry": "Coffee", "audience": "Young professionals",
            "personality": "warm, modern", "language_style": "saudi", "emoji_style": "light", "cta": "اطلب الآن",
            "banned_words": "رخيص", "sample_posts": "صباحكم قهوة", "website": "https://rif.example"}
    r = client.post("/api/brand-kits", json=body, headers=auth.headers)
    assert r.status_code == 201, r.text
    kit = r.json()
    for key, value in body.items():
        assert kit[key] == value
    r = client.patch(f"/api/brand-kits/{kit['id']}", json={"color_accent": None, "emoji_style": "none"}, headers=auth.headers)
    assert r.status_code == 200 and r.json()["color_accent"] is None and r.json()["emoji_style"] == "none"
    assert client.patch(f"/api/brand-kits/{kit['id']}", json={"language_style": "klingon"}, headers=auth.headers).status_code == 422
    assert client.patch(f"/api/brand-kits/{kit['id']}", json={"color_background": "blue"}, headers=auth.headers).status_code == 422


def test_profile_reaches_the_ai_prompts(db, client, auth):
    from app.modules.brand.models import BrandKit
    kit = BrandKit(workspace_id=auth.workspace_id, name="Rif", audience="Students", language_style="gulf",
                   emoji_style="none", banned_words="cheap")
    db.add(kit)
    db.flush()
    profile = kit.llm_profile()
    assert "Audience: Students" in profile and "Gulf dialect" in profile and "no emojis" in profile
    assert "Never use these words: cheap" in profile


def test_generate_cleans_the_ai_answer(client, auth, monkeypatch):
    seen = {}

    def fake(db, workspace_id, system, user, **kwargs):
        seen["user"] = user
        return {"tagline": "قهوتك كل صباح", "color_primary": "#1F3D2B", "color_secondary": "not-a-colour",
                "color_text": "#203020", "font_family": "Comic Sans", "font_heading": "'Cairo', sans-serif",
                "language_style": "saudi", "emoji_style": "lots", "personality": ["دافئة", "عصرية"],
                "hashtags": ["قهوة", "#الرياض"], "sample_posts": ["one", "two"], "guidelines": ["✓ a", "✗ b"]}

    monkeypatch.setattr(ai_service, "generate_json", fake)
    r = client.post("/api/brand-kits/generate", headers=auth.headers,
                    json={"name": "Rif", "description": "Coffee", "palette": ["#1f3d2b", "#D9A441", "bad"]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["color_primary"] == "#1f3d2b"
    assert d["color_secondary"] == "#d9a441"            # invalid -> taken from the logo palette
    assert d["color_text"] == "#ffffff"                 # #203020 does not read on the dark primary
    assert d["font_family"] == "system-ui" and d["font_heading"] == "'Cairo', sans-serif"
    assert d["language_style"] == "saudi" and d["emoji_style"] is None
    assert d["personality"] == "دافئة, عصرية" and d["hashtags"] == "#قهوة #الرياض"
    assert d["guidelines"] == "✓ a\n✗ b" and d["sample_posts"] == "one\n\ntwo"
    assert "Colours taken from the logo (most used first): #1f3d2b, #d9a441" in seen["user"]
    assert "'Cairo', sans-serif" in seen["user"]


def test_generate_needs_an_ai_provider(client, auth, monkeypatch):
    def none(*args, **kwargs):
        raise AppError("Add an AI provider first.", code="no_ai_provider")

    monkeypatch.setattr(ai_service, "generate_json", none)
    r = client.post("/api/brand-kits/generate", json={"name": "Rif", "description": "Coffee"}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "no_ai_provider"


def test_readable_text_colour():
    assert identity.readable_on("#ffffff", "#ffffff") == "#111111"
    assert identity.readable_on("#111111", None) == "#ffffff"
    assert identity.readable_on("#ffffff", "#1f3d2b") == "#1f3d2b"
