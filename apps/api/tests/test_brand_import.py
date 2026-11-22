"""Brand kit import from a design system (Claude export, .md brand book, DTCG json, tokens.css), brand health and
AI suggestions. Every fixture is synthetic and built here."""
import glob
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.core.errors import AppError
from app.core.models import Media
from app.modules.ai import service as ai_service
from app.modules.brand import completeness, fonts, importer, svg
from app.modules.brand.models import BrandFont, BrandImport, BrandKit

TAJAWAL = Path(__file__).resolve().parents[1] / "app/modules/templates/fonts/Tajawal-Regular.ttf"

README = """Acme Studio is a design studio in Riyadh making calm, precise films for brands. The core line is
**Made with care.** and we work in Arabic and English (bilingual EN / AR).

## Content fundamentals

- **Voice:** warm, precise, confident. Say "we". Never hype.
- **Headlines:** 3–8 words, one idea.
- **Write like:** "Made with care." · "Ideas, made visible."
- **Never write like:** "one-stop shop", "think outside the box".
- **No emoji.**

## Imagery
Cinematic, natural colour, real skin tones. No stock photos. Never use heavy filters.

## Logo
Use the black logo on light backgrounds. Never recolour the logo. Keep clear space around it.
"""

TOKENS = {
    "name": "Acme",
    "color": {
        "themes": [{"id": "light", "name": "Light"}, {"id": "dark", "name": "Dark"}],
        "tokens": [
            {"name": "acme-red", "value": "#e0322b", "usage": "Brand anchor."},
            {"name": "acme-teal", "value": "#0f8a7e", "usage": "Second brand colour."},
            {"name": "acme-white", "value": "#ffffff"},
            {"name": "acme-black", "value": "#111111"},
            {"name": "acme-paper", "value": "#faf7f2"},
            {"name": "acme-border", "value": "rgba(0,0,0,0.1)"},
            {"name": "acme-brand", "value": {"light": "{acme-red}", "dark": "#ff5a52"}},
            {"name": "acme-brand-hover", "value": "#b0221c"},
            {"name": "acme-bg", "value": {"light": "{acme-paper}", "dark": "{acme-black}"}},
            {"name": "acme-text", "value": {"light": "{acme-black}", "dark": "{acme-white}"}},
            {"name": "acme-on-brand", "value": "{acme-white}"},
        ],
    },
    "type": {
        "fonts": [{"family": "Tajawal", "file": "fonts/Brand-Regular.ttf", "weight": "400", "style": "normal"},
                  {"family": "Tajawal", "file": "fonts/Brand-Bold.ttf", "weight": "700", "style": "normal"}],
        "families": {"display": "\"Tajawal\", Georgia, serif", "text": "\"Inter\", system-ui, sans-serif"},
    },
    "spacing": {"tokens": [{"name": "s1", "value": "4px"}]},
}
INDEX = {"title": "Acme", "namespace": "Acme_1", "groups": ["Logos", "Imagery"],
         "assetGroups": {"Logos": {"order": ["logo.png", "logo-white.png"], "files": {}},
                         "Imagery": {"order": ["hero.jpg"], "files": {}}}, "docs": {"readme": "project/README.md"}}
SVG_EVIL = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="alert(1)">'
            b'<script>alert(2)</script><rect width="10" height="10" fill="#111111" onclick="x()"/>'
            b'<image xlink:href="https://evil.example/x.png"/><a href="javascript:alert(3)"><text>x</text></a>'
            b'<foreignObject><div>x</div></foreignObject></svg>')


def _png(ink: tuple, size=(120, 40), background=(0, 0, 0, 0)) -> bytes:
    image = Image.new("RGBA", size, background)
    ImageDraw.Draw(image).rectangle((10, 10, 110, 30), fill=ink)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _jpg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (60, 40), (120, 80, 40)).save(out, "JPEG")
    return out.getvalue()


def design_system(prefix: str = "project/", extra: dict | None = None) -> bytes:
    files = {
        "README.md": README.encode(), "tokens.json": json.dumps(TOKENS).encode(),
        "design-system.json": json.dumps(INDEX).encode(),
        "assets/Logos/logo.png": _png((17, 17, 17, 255)), "assets/Logos/logo-white.png": _png((255, 255, 255, 255)),
        "assets/Logos/mark.svg": SVG_EVIL, "assets/Imagery/hero.jpg": _jpg(),
        "assets/Team/person.jpg": _jpg(), "fonts/Brand-Regular.ttf": TAJAWAL.read_bytes(),
        "components/Button.jsx": b"export default 1", "notes.exe": b"MZ",
    }
    files.update(extra or {})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, content in files.items():
            archive.writestr(prefix + name, content)
    return out.getvalue()


def preview(client, auth, content: bytes, filename="ds.zip", **form):
    return client.post("/api/brand-kits/import/preview", headers=auth.headers,
                       files={"file": (filename, content, "application/octet-stream")},
                       data={k: str(v) for k, v in form.items()})


@pytest.fixture()
def no_ai(monkeypatch):
    monkeypatch.setattr(ai_service, "has_provider", lambda db, ws, cap="text": False)


# ---------------------------------------------------------------------------- layouts and formats
@pytest.mark.parametrize("prefix", ["project/", "acme-export/project/", ""])
def test_zip_layouts_give_the_same_draft(client, auth, no_ai, prefix):
    r = preview(client, auth, design_system(prefix))
    assert r.status_code == 200, r.text
    d = r.json()
    f = d["fields"]
    assert f["name"]["value"] == "Acme" and f["name"]["source"] == "tokens"
    assert f["color_primary"] == {"value": "#e0322b", "source": "tokens", "token": "acme-brand"}
    assert f["color_background"]["value"] == "#faf7f2" and f["color_text"]["value"] == "#ffffff"
    assert f["color_secondary"]["value"] == "#0f8a7e" and f["color_secondary"]["source"] == "heuristic"
    assert f["font_heading"]["value"] == "'Tajawal', serif" and f["font_family"]["value"] == "'Inter', sans-serif"
    assert d["logo_primary"] == "assets/Logos/logo.png" and d["logo_dark"] == "assets/Logos/logo-white.png"
    variants = {x["name"]: x["variant"] for x in d["logos"]}
    assert variants["logo-white.png"] == "dark" and variants["logo.png"] == "light"
    imagery = {x["name"]: x["selected"] for x in d["imagery"]}
    assert imagery == {"hero.jpg": True, "person.jpg": False}
    font = d["fonts"][0]
    assert font["family"] == "Tajawal" and font["role"] == "heading" and font["has_arabic"] is True
    assert d["components"] == 1 and d["ignored"] >= 1  # notes.exe never read
    assert any(w["code"] == "fonts_missing" for w in d["warnings"])  # Brand-Bold.ttf listed but absent
    assert d["tokens"]["spacing"] == 1


def test_markdown_only(client, auth, no_ai):
    r = preview(client, auth, README.encode(), "brand.md")
    assert r.status_code == 200, r.text
    f = r.json()["fields"]
    assert f["tagline"]["value"] == "Made with care." and f["tagline"]["source"] == "readme"
    assert f["emoji_style"]["value"] == "none" and f["language_style"]["value"] == "bilingual"
    assert "one-stop shop" in f["banned_words"]["value"] and "think outside the box" in f["banned_words"]["value"]
    assert f["personality"]["value"] == "warm, precise, confident"
    assert "Never recolour the logo" in f["visual_rules"]["value"] and "No stock photos" in f["visual_rules"]["value"]
    assert f["visual_style"]["value"].startswith("Cinematic")
    assert "color_primary" not in f and f["name"]["value"] == "brand"


def test_dtcg_tokens_json(client, auth, no_ai):
    tokens = {"color": {"brand": {"primary": {"$type": "color", "$value": "#1d4ed8"},
                                  "accent": {"$type": "color", "$value": "{color.brand.primary}"}},
                        "neutral": {"bg": {"$value": "#ffffff", "$type": "color"},
                                    "text": {"$value": "#0b0b0b", "$type": "color"}},
                        "highlight": {"$value": "#f59e0b", "$type": "color"}},
              "font": {"heading": {"$type": "fontFamily", "$value": ["Playfair Display", "serif"]},
                       "body": {"$type": "fontFamily", "$value": "Inter, sans-serif"}}}
    r = preview(client, auth, json.dumps(tokens).encode(), "tokens.json")
    f = r.json()["fields"]
    assert f["color_primary"]["value"] == "#1d4ed8" and f["color_background"]["value"] == "#ffffff"
    assert f["color_accent"]["value"] == "#f59e0b"  # an alias of the primary is not a separate accent hue
    assert f["font_heading"]["value"] == "'Playfair Display', serif"
    assert f["font_family"]["value"] == "'Inter', sans-serif"


def test_tokens_css(client, auth, no_ai):
    css = b"""/* brand */
:root { --brand-primary: #7c3aed; --brand-accent: rgb(236, 72, 153); --bg: #fafafa; --text: #18181b;
        --on-primary: #ffffff; --border: rgba(0,0,0,.1); --font-display: 'Cairo', sans-serif; --font-body: var(--font-display); }
[data-theme="dark"] { --bg: #09090b; }
@font-face { font-family: "Cairo"; src: url("fonts/Cairo.ttf") format("truetype"); font-weight: 700; }
"""
    r = preview(client, auth, css, "tokens.css")
    d = r.json()
    f = d["fields"]
    assert f["color_primary"]["value"] == "#7c3aed" and f["color_accent"]["value"] == "#ec4899"
    assert f["color_background"]["value"] == "#fafafa" and f["color_text"]["value"] == "#ffffff"
    assert f["font_heading"]["value"] == "'Cairo', sans-serif" and f["font_family"]["value"] == "'Cairo', sans-serif"
    bg = next(c for c in d["colours"] if c["name"] == "bg")
    assert bg["dark"] == "#09090b"


def test_colour_mapping_and_contrast_warnings():
    tokens = importer.resolve_tokens([
        {"name": "x-brand", "value": "#ffd400"}, {"name": "x-on-brand", "value": "#ffffff"},
        {"name": "x-bg", "value": "#ffffff"}, {"name": "x-text", "value": "#cccccc"},
        {"name": "x-loop-a", "value": "{x-loop-b}"}, {"name": "x-loop-b", "value": "{x-loop-a}"},
    ])
    assert "x-loop-a" not in {t["name"] for t in tokens}  # unresolvable aliases are left out
    roles, warnings = importer.map_roles(tokens)
    assert roles["primary"]["value"] == "#ffd400" and roles["text"]["value"] == "#ffffff"
    codes = {w["code"] for w in warnings}
    assert codes == {"contrast_on_primary", "contrast_text_background"}
    # without brand names the most saturated colour leads
    roles, _w = importer.map_roles(importer.resolve_tokens([{"name": "grey", "value": "#777777"},
                                                            {"name": "sea", "value": "#0077ff"}]))
    assert roles["primary"] == {"value": "#0077ff", "token": "sea", "source": "heuristic"}
    assert roles["text"]["value"] in ("#ffffff", "#111111")
    assert importer.to_hex("hsl(0, 100%, 50%)") == "#ff0000" and importer.to_hex("#abc") == "#aabbcc"
    assert importer.to_hex("rgba(0,0,0,.5)") is None and importer.to_hex("#11223380") is None


# ---------------------------------------------------------------------------- safety
def test_svg_is_sanitised(client, auth, no_ai):
    clean = svg.sanitize(SVG_EVIL).decode()
    for bad in ("<script", "onload", "onclick", "evil.example", "javascript:", "foreignObject"):
        assert bad not in clean
    assert "<rect" in clean
    assert svg.sanitize(b'<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>') is None
    assert svg.sanitize(b"<html/>") is None
    d = preview(client, auth, design_system()).json()
    r = client.get(f"/api/brand-kits/import/{d['import_id']}/file", params={"key": "assets/Logos/mark.svg"},
                   headers=auth.headers)
    assert r.status_code == 200 and b"<script" not in r.content and "sandbox" in r.headers["content-security-policy"]
    assert client.get(f"/api/brand-kits/import/{d['import_id']}/file", params={"key": "README.md"},
                      headers=auth.headers).status_code == 404


def _zip(entries) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for info, content in entries:
            archive.writestr(info, content)
    return out.getvalue()


def test_unsafe_archives_are_refused(client, auth, no_ai):
    r = preview(client, auth, _zip([("project/README.md", "# x"), ("../evil.md", "x")]))
    assert r.status_code == 400 and r.json()["code"] == "unsafe_zip"
    r = preview(client, auth, _zip([("/etc/passwd.md", "x")]))
    assert r.json()["code"] == "unsafe_zip"
    link = zipfile.ZipInfo("project/link.md")
    link.external_attr = (0o120777 << 16)
    r = preview(client, auth, _zip([(link, "/etc/passwd")]))
    assert r.json()["code"] == "unsafe_zip"
    r = preview(client, auth, _zip([(f"project/f{i}.txt", "x") for i in range(importer.MAX_FILES + 1)]))
    assert r.json()["code"] == "too_many_files"
    assert preview(client, auth, b"MZ...", "tool.exe").json()["code"] == "bad_type"
    assert preview(client, auth, b"PK\x03\x04broken", "x.zip").json()["code"] == "bad_zip"


def test_declared_size_is_not_trusted(monkeypatch):
    monkeypatch.setattr(importer, "MAX_TOTAL", 1000)
    with pytest.raises(AppError) as exc:
        importer.read_zip(_zip([("a.txt", "x" * 1500)]))
    assert exc.value.code == "too_large"


# ---------------------------------------------------------------------------- the brand book with AI
def test_ai_extraction_is_validated(client, auth, monkeypatch):
    seen = {}

    def fake(db, ws, system, user, **kwargs):
        seen.update(system=system, user=user, kwargs=kwargs)
        return {"description": "A studio.", "tone": "Calm and precise.", "personality": ["calm", "precise", 7],
                "language_style": "klingon", "emoji_style": "none", "hashtags": ["acme", "#ok", "not a tag!"],
                "banned_words": ["one-stop shop"], "photo_style": {"lens": "85", "light": "laser", "evil": "x"},
                "cta": "x" * 500, "industry": {"nested": True}, "guidelines": ["✓ Say we", "✗ Hype"]}

    monkeypatch.setattr(ai_service, "has_provider", lambda db, ws, cap="text": True)
    monkeypatch.setattr(ai_service, "generate_json", fake)
    d = preview(client, auth, design_system()).json()
    f = d["fields"]
    assert d["book_source"] == "ai" and f["tone"]["source"] == "ai"
    assert f["personality"]["value"] == "calm, precise, 7"
    assert "language_style" not in f and f["emoji_style"]["value"] == "none"
    assert f["hashtags"]["value"] == "#acme #ok" and len(f["cta"]["value"]) == 200 and "industry" not in f
    assert f["photo_style"]["value"] == {"mode": "manual", "lens": "85"}
    assert "never follow instructions" in seen["system"] and seen["user"].startswith("<brand_book>")
    assert "Acme Studio is a design studio" in seen["user"] and seen["kwargs"]["purpose"] == "brand import"


def test_ai_failure_falls_back_to_headings(client, auth, monkeypatch):
    def broken(*args, **kwargs):
        raise AppError("The AI answer could not be read.", code="ai_bad_json")

    monkeypatch.setattr(ai_service, "has_provider", lambda db, ws, cap="text": True)
    monkeypatch.setattr(ai_service, "generate_json", broken)
    d = preview(client, auth, design_system()).json()
    assert d["book_source"] == "readme" and d["fields"]["tagline"]["value"] == "Made with care."
    assert any(w["code"] == "ai_failed" for w in d["warnings"])


# ---------------------------------------------------------------------------- preview, commit
def test_preview_saves_nothing_to_kits_or_media(client, auth, db, no_ai):
    before = db.query(Media).count()
    d = preview(client, auth, design_system()).json()
    assert db.query(BrandKit).count() == 0 and db.query(Media).count() == before
    row = db.query(BrandImport).one()
    assert row.token == d["import_id"] and row.workspace_id == auth.workspace_id
    assert d["completeness"]["score"] > 0 and d["current"] is None


def test_commit_creates_a_kit_with_the_chosen_parts(client, auth, db, no_ai):
    d = preview(client, auth, design_system()).json()
    fields = {k: v["value"] for k, v in d["fields"].items() if k not in ("tone",)}
    body = {"import_id": d["import_id"], "fields": fields, "make_default": True,
            "assets": {"logo": d["logo_primary"], "logo_dark": d["logo_dark"], "imagery": ["assets/Imagery/hero.jpg"],
                       "fonts": ["fonts/Brand-Regular.ttf"]}}
    r = client.post("/api/brand-kits/import/commit", json=body, headers=auth.headers)
    assert r.status_code == 200, r.text
    out = r.json()
    kit = out["kit"]
    assert kit["name"] == "Acme" and kit["color_primary"] == "#e0322b" and kit["tone"] is None
    assert kit["logo_media_id"] and kit["logo_dark_media_id"] and kit["is_default"]
    assert len(kit["reference_media_ids"]) == 1
    logo = db.get(Media, kit["logo_media_id"])
    assert logo.source == "brand" and logo.tags == ["brand", "logo"] and logo.mimetype == "image/png"
    font = db.query(BrandFont).one()
    assert font.family == "Tajawal" and font.role == "heading" and font.has_arabic is True
    assert db.query(BrandImport).count() == 0  # used once
    assert client.post("/api/brand-kits/import/commit", json=body, headers=auth.headers).status_code == 404
    checks = {c["key"]: c for c in out["completeness"]["checks"]}
    assert checks["logo"]["status"] == "ok" and checks["logo_dark"]["status"] == "ok"
    assert checks["tone"]["status"] == "missing" and checks["tone"]["ai"] is True
    fonts_list = client.get(f"/api/brand-kits/{kit['id']}/fonts", headers=auth.headers).json()
    assert fonts_list[0]["family"] == "Tajawal" and fonts_list[0]["url"].startswith("/api/media/")
    # the renderers find the file for the kit's heading font
    files = fonts.for_kit(db, db.get(BrandKit, kit["id"]))
    assert files["heading"]["regular"].endswith(".ttf")


def test_commit_updates_only_chosen_fields(client, auth, db, no_ai):
    kit = client.post("/api/brand-kits", json={"name": "Old", "tone": "Keep me", "color_primary": "#123456"},
                      headers=auth.headers).json()
    d = preview(client, auth, design_system(), brand_kit_id=kit["id"]).json()
    assert d["current"]["tone"] == "Keep me" and d["brand_kit_id"] == kit["id"]
    r = client.post("/api/brand-kits/import/commit", headers=auth.headers, json={
        "import_id": d["import_id"], "brand_kit_id": kit["id"],
        "fields": {"color_primary": "#e0322b", "tagline": "Made with care.", "unknown": "x"}, "assets": {}})
    assert r.status_code == 200, r.text
    out = r.json()["kit"]
    assert out["name"] == "Old" and out["tone"] == "Keep me" and out["color_primary"] == "#e0322b"
    assert out["tagline"] == "Made with care." and out["logo_media_id"] is None
    d = preview(client, auth, design_system(), brand_kit_id=kit["id"]).json()
    r = client.post("/api/brand-kits/import/commit", headers=auth.headers, json={
        "import_id": d["import_id"], "brand_kit_id": kit["id"], "fields": {"color_primary": "red"}})
    assert r.status_code == 422
    r = client.post("/api/brand-kits/import/commit", headers=auth.headers, json={
        "import_id": d["import_id"], "fields": {}, "assets": {"logo": "../../etc/passwd"}})
    assert r.status_code == 404


def test_admin_only(client, auth, db, no_ai):
    from app.modules.workspaces.models import Membership

    from .conftest import signup
    editor = signup(client, email="editor@example.com", workspace="Other")
    db.add(Membership(user_id=editor.user_id, workspace_id=auth.workspace_id, role="editor"))
    db.flush()
    headers = {**editor.headers, "X-Workspace": str(auth.workspace_id)}
    r = client.post("/api/brand-kits/import/preview", headers=headers,
                    files={"file": ("b.md", README.encode(), "text/markdown")})
    assert r.status_code == 403
    assert client.post("/api/brand-kits/import/commit", headers=headers, json={"import_id": "x" * 10}).status_code == 403
    kit = client.post("/api/brand-kits", json={"name": "K"}, headers=auth.headers).json()
    assert client.post(f"/api/brand-kits/{kit['id']}/suggest", json={"fields": ["tone"]}, headers=headers).status_code == 403
    assert client.get(f"/api/brand-kits/{kit['id']}/completeness", headers=headers).status_code == 200


# ---------------------------------------------------------------------------- health and suggestions
def test_completeness_scores_and_gaps(client, auth):
    kit = client.post("/api/brand-kits", json={"name": "Bare"}, headers=auth.headers).json()
    bare = client.get(f"/api/brand-kits/{kit['id']}/completeness", headers=auth.headers).json()
    checks = {c["key"]: c for c in bare["checks"]}
    assert checks["color_primary"]["status"] == "weak"  # still the default colour
    assert checks["logo"]["status"] == "missing" and checks["tone"]["tab"] == "voice"
    assert "font_arabic" not in checks  # an English workspace without an Arabic language style
    full = {"color_primary": "#e0322b", "color_secondary": "#0f8a7e", "color_accent": "#ffd400",
            "color_text": "#ffffff", "color_background": "#faf7f2", "font_heading": "'Cairo', sans-serif",
            "font_family": "'Tajawal', sans-serif", "tone": "Warm, precise and confident in every line.",
            "personality": "warm, precise", "audience": "Brand managers in the Gulf", "language_style": "msa",
            "emoji_style": "none", "cta": "Talk to us", "banned_words": "cheap", "hashtags": "#acme",
            "sample_posts": "One post\n\nTwo posts", "description": "A studio in Riyadh making calm, precise films.",
            "visual_style": "Cinematic, natural colour, soft light.", "visual_rules": "✗ No stock photos ever",
            "photo_style": {"lens": "85"}, "guard_mode": "strict"}
    client.patch(f"/api/brand-kits/{kit['id']}", json=full, headers=auth.headers)
    better = client.get(f"/api/brand-kits/{kit['id']}/completeness", headers=auth.headers).json()
    assert better["score"] > bare["score"] and better["missing"] == 2  # only the two logos
    assert next(c for c in better["checks"] if c["key"] == "font_arabic")["status"] == "ok"  # Cairo, Tajawal
    low = completeness.report({"color_text": "#ffff00", "color_primary": "#ffffff"})
    contrast = next(c for c in low["checks"] if c["key"] == "contrast")
    assert contrast["status"] == "weak" and contrast["detail"]["ratio"] < 4.5
    latin = completeness.report({"font_family": "'Inter', sans-serif"},
                                {"arabic_needed": True, "fonts": [{"family": "Inter", "has_arabic": False}]})
    assert next(c for c in latin["checks"] if c["key"] == "font_arabic")["status"] == "weak"
    assert all(c["key"] != "font_arabic" for c in completeness.report({}, {"arabic_needed": False})["checks"])


def test_suggest_returns_clean_suggestions(client, auth, monkeypatch):
    kit = client.post("/api/brand-kits", json={"name": "Rif", "description": "Coffee in Riyadh"},
                      headers=auth.headers).json()
    seen = {}

    def fake(db, ws, system, user, **kwargs):
        seen.update(system=system, user=user)
        return {"tone": "Warm.", "emoji_style": "tons", "hashtags": ["قهوة"], "name": "Hacked"}

    monkeypatch.setattr(ai_service, "generate_json", fake)
    r = client.post(f"/api/brand-kits/{kit['id']}/suggest", json={"fields": ["tone", "emoji_style", "hashtags", "name"]},
                    headers=auth.headers)
    assert r.status_code == 200, r.text
    assert r.json()["suggestions"] == {"tone": "Warm.", "hashtags": "#قهوة"}
    assert "Brand: Rif" in seen["user"] and "tone, emoji_style, hashtags" in seen["system"]
    assert client.get(f"/api/brand-kits/{kit['id']}", headers=auth.headers).json()["tone"] is None  # nothing saved

    def none(*args, **kwargs):
        raise AppError("Add an AI provider first.", code="no_ai_provider")

    monkeypatch.setattr(ai_service, "generate_json", none)
    r = client.post(f"/api/brand-kits/{kit['id']}/suggest", json={"fields": ["tone"]}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "no_ai_provider"


# ---------------------------------------------------------------------------- brand fonts in the renderers
def test_font_inspection_and_fallback():
    info = fonts.inspect(TAJAWAL.read_bytes(), "Tajawal-Regular.ttf")
    assert info["family"] == "Tajawal" and info["weight"] == 400 and info["has_arabic"] is True
    assert fonts.inspect(b"not a font") is None
    assert fonts.weight_of("ExtraBold") == 800 and fonts.weight_of("", "thmanyahsans-Black.woff2") == 900
    from app.modules.templates import render
    assert render.brand_font_path({"regular": str(TAJAWAL)}, False, "مرحبا Hello") == str(TAJAWAL)
    assert render.brand_font_path({"regular": "/nope.ttf"}, False, "Hi") is None
    latin = [p for p in glob.glob("/usr/share/fonts/**/LiberationSans-Regular.ttf", recursive=True)]
    if latin:  # a Latin-only font: Arabic text falls back to Tajawal, Latin text keeps the brand font
        assert render.brand_font_path(latin[0], False, "مرحبا") is None
        assert render.brand_font_path(latin[0], False, "Hello") == latin[0]
        font = render.load_font(40, False, latin[0], "مرحبا")
        assert "Liberation" not in font.getname()[0]


def test_slides_draw_with_the_brand_font(db, client, auth):
    from app.modules.ideas import slides
    jpeg = slides.render_slide({"title": "عنوان الشريحة", "body": "Body text"}, 0, 2,
                               {"name": "Acme", "colors": {"primary": "#e0322b"},
                                "fonts": {"heading": {"regular": str(TAJAWAL), "bold": str(TAJAWAL)}}})
    assert jpeg[:2] == b"\xff\xd8"
