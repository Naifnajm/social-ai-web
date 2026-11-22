"""Brand import extras: an SVG main logo, the files tokens.json / design-system.json list but the upload lacks,
industry and audience from the brand book without AI, and live brand health of unsaved form values."""
import io
import json
import zipfile

import pytest
from PIL import Image, ImageDraw

from app.core.models import Media
from app.modules.ai import service as ai_service
from app.modules.brand import importer, svg

LOGO_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
            b'<rect x="0" y="0" width="200" height="100" rx="20" fill="#e6141e"/></svg>')


@pytest.fixture()
def no_ai(monkeypatch):
    monkeypatch.setattr(ai_service, "has_provider", lambda db, ws, cap="text": False)


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _zip(files: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, content in files.items():
            archive.writestr("project/" + name, content)
    return out.getvalue()


def _logo_png(colour=(17, 17, 17, 255)) -> bytes:
    image = Image.new("RGBA", (120, 40), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 10, 110, 30), fill=colour)
    return _png(image)


def test_import_prefers_the_svg_logo_and_lists_missing_files(client, auth, db, no_ai):
    tokens = {"name": "Acme", "color": {"tokens": [{"name": "acme-red", "value": "#e6141e"}]},
              "type": {"fonts": [{"family": "Acme Sans", "file": "fonts/AcmeSans-Bold.woff2", "weight": "700"}]}}
    index = {"title": "Acme", "assetGroups": {
        "Logos": {"order": ["logo.svg", "logo.png", "logo-black.png"]},
        "Imagery": {"order": ["hero.jpg", "team.jpg"]}}}
    content = _zip({"README.md": b"# Acme\n\nAcme is a design studio.\n", "tokens.json": json.dumps(tokens),
                    "design-system.json": json.dumps(index), "assets/Logos/logo.svg": LOGO_SVG,
                    "assets/Logos/logo.png": _logo_png()})
    r = client.post("/api/brand-kits/import/preview", headers=auth.headers,
                    files={"file": ("ds.zip", content, "application/zip")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["logo_primary"] == "assets/Logos/logo.svg"
    codes = {w["code"]: w for w in d["warnings"]}
    assert "svg_logo" not in codes  # designs can draw an SVG now
    assert d["missing_fonts"] == ["fonts/AcmeSans-Bold.woff2"] and codes["fonts_missing"]["files"] == d["missing_fonts"]
    missing = {(x["group"], x["name"]) for x in d["missing_assets"]}
    assert missing == {("Logos", "logo-black.png"), ("Imagery", "hero.jpg"), ("Imagery", "team.jpg")}
    assert "Logos/logo-black.png" in codes["assets_missing"]["files"]
    logo = next(x for x in d["logos"] if x["key"] == "assets/Logos/logo.svg")
    assert logo["width"] == 200 and logo["height"] == 100
    commit = client.post("/api/brand-kits/import/commit", headers=auth.headers, json={
        "import_id": d["import_id"], "fields": {"name": "Acme"},
        "assets": {"logo": d["logo_primary"], "logos": ["assets/Logos/logo.png"]}})
    assert commit.status_code == 200, commit.text
    kit = commit.json()["kit"]
    media = db.get(Media, kit["logo_media_id"])
    assert media.mimetype == "image/svg+xml" and kit["reference_media_ids"]  # the PNG variant is kept too


def test_without_a_rasterizer_the_png_logo_wins(monkeypatch):
    monkeypatch.setattr(svg, "renderer", lambda: None)
    files = {"assets/Logos/logo.svg": LOGO_SVG, "assets/Logos/logo.png": _logo_png()}
    found = importer.analyse({"files": files, "ignored": 0, "kind": "zip"})
    assert found["logo_primary"] == "assets/Logos/logo.png"
    assert svg.rasterize(LOGO_SVG, 10) is None


# ---------------------------------------------------------------------------- live brand health
def test_completeness_preview_scores_unsaved_values(client, auth):
    empty = client.post("/api/brand-kits/completeness/preview", headers=auth.headers, json={"values": {}})
    assert empty.status_code == 200
    base = empty.json()
    filled = client.post("/api/brand-kits/completeness/preview", headers=auth.headers, json={"values": {
        "name": "Acme", "description": "Acme roasts specialty coffee in Riyadh and sells it to cafés across the Gulf.",
        "tone": "Warm, precise and quietly confident; never hype.", "color_primary": "#e6141e",
        "logo_media_id": 999999}}).json()
    assert filled["score"] > base["score"]
    checks = {c["key"]: c["status"] for c in filled["checks"]}
    assert checks["description"] == "ok" and checks["tone"] == "ok" and checks["logo"] == "missing"  # not ours
    kit = client.post("/api/brand-kits", headers=auth.headers, json={"name": "Saved", "tone": "Calm and clear, warm."})
    kit_id = kit.json()["id"]
    r = client.post("/api/brand-kits/completeness/preview", headers=auth.headers,
                    json={"brand_kit_id": kit_id, "values": {"tone": ""}}).json()
    assert {c["key"]: c["status"] for c in r["checks"]}["tone"] == "missing"  # the unsaved edit wins
    saved = client.get(f"/api/brand-kits/{kit_id}/completeness", headers=auth.headers).json()
    assert {c["key"]: c["status"] for c in saved["checks"]}["tone"] == "ok"
    assert client.post("/api/brand-kits/completeness/preview", headers=auth.headers,
                       json={"brand_kit_id": 999999, "values": {}}).status_code == 404


# ---------------------------------------------------------------------------- industry and audience
@pytest.mark.parametrize("text, industry, audience", [
    (("# Bean\n\nWe are an independent coffee roastery in Riyadh.\n\n## Audience\n\nYoung professionals who care "
      "about origin.\n"), "independent coffee roastery", "Young professionals who care about origin"),
    ("# X\n\nX makes things.\n\n- **Industry:** Specialty coffee\n- **Who we serve:** Students and remote workers\n",
     "Specialty coffee", "Students and remote workers"),
    ("# W\n\nW is a bakery.\n\n## Who we serve\n\n- Families\n- Cafés in Amsterdam\n", "bakery",
     "Families, Cafés in Amsterdam"),
    ("# Z\n\nZ helps teams. Built for small restaurant owners in the Gulf.\n", None,
     "small restaurant owners in the Gulf"),
    ("# بن\n\nنحن وكالة تسويقية تعمل في الرياض.\n\n## الجمهور\n\nالشباب المهتمون بالقهوة المختصة.\n",
     "وكالة تسويقية", "الشباب المهتمون بالقهوة المختصة"),
    ("# بن\n\nمرحبا.\n\n- القطاع: المطاعم والمقاهي\n- عملاؤنا: الأسر في جدة\n", "المطاعم والمقاهي", "الأسر في جدة"),
    # conservative: no guess from a negation, a vague "for everyone" or a hyphenated word
    ("# X\n\nX is not a typical agency. We design for everyone.\n", None, None),
    ("# X\n\nX is a brand-new idea.\n", None, None),
    ("# X\n\n## Audience\n\nEveryone.\n", None, None),
])
def test_heading_parser_finds_industry_and_audience(text, industry, audience):
    book = importer.heuristic_book(text)
    assert book.get("industry") == industry
    assert book.get("audience") == audience


