"""Brand health: a weighted checklist of what a brand kit has, what is weak and what is missing, with a score.

    report = completeness.for_kit(db, kit)                 # saved kit
    report = completeness.report(values, facts)             # any dict of kit fields (e.g. an import preview)

Each check: ``{"key", "group", "status": ok|weak|missing, "weight", "field", "tab", "ai", "detail"}``. The web app
translates the label and the fix hint by ``key``; ``field``/``tab`` say where to fix it, ``ai`` whether
"Suggest with AI" can fill it (POST /brand-kits/{id}/suggest).
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .fonts import family_name
from .identity import HEX, contrast

ARABIC_STYLES = {"msa", "gulf", "saudi", "bilingual"}
# CSS families offered in the app that draw Arabic (router.FONTS)
ARABIC_FONTS = {"ibm plex sans arabic", "cairo", "tajawal", "almarai", "readex pro", "alexandria", "noto kufi arabic",
                "changa", "noto naskh arabic", "amiri", "tahoma", "arial", "system-ui"}
DEFAULTS = {"color_primary": "#111111", "color_secondary": "#71717a"}

# key, group, weight, field, tab, ai
CHECKS = [
    ("logo", "identity", 10, "logo_media_id", "look", False),
    ("logo_dark", "identity", 4, "logo_dark_media_id", "look", False),
    ("description", "identity", 6, "description", "basics", True),
    ("audience", "identity", 6, "audience", "basics", True),
    ("color_primary", "colours", 6, "color_primary", "look", False),
    ("color_secondary", "colours", 3, "color_secondary", "look", False),
    ("color_accent", "colours", 3, "color_accent", "look", False),
    ("color_text", "colours", 3, "color_text", "look", False),
    ("color_background", "colours", 3, "color_background", "look", False),
    ("contrast", "colours", 5, "color_text", "look", False),
    ("font_heading", "fonts", 4, "font_heading", "type", False),
    ("font_family", "fonts", 4, "font_family", "type", False),
    ("font_arabic", "fonts", 4, "font_family", "type", False),
    ("tone", "voice", 7, "tone", "voice", True),
    ("personality", "voice", 5, "personality", "voice", True),
    ("language_style", "voice", 4, "language_style", "voice", True),
    ("emoji_style", "voice", 2, "emoji_style", "voice", True),
    ("cta", "voice", 4, "cta", "voice", True),
    ("banned_words", "rules", 4, "banned_words", "rules", True),
    ("hashtags", "rules", 3, "hashtags", "rules", True),
    ("sample_posts", "rules", 5, "sample_posts", "rules", True),
    ("visual_style", "visual", 5, "visual_style", "look", True),
    ("visual_rules", "visual", 4, "visual_rules", "guard", True),
    ("photo_style", "visual", 3, "photo_style", "guard", True),
    ("guard_mode", "visual", 2, "guard_mode", "guard", False),
]
MIN_LENGTH = {"description": 40, "audience": 15, "tone": 20, "visual_style": 20, "visual_rules": 15}


def _text(value) -> str:
    return str(value or "").strip()


def _status(key: str, values: dict, facts: dict) -> tuple[str, dict]:
    v = values.get
    if key == "logo":
        return ("ok" if v("logo_media_id") else "missing"), {}
    if key == "logo_dark":
        return ("ok" if v("logo_dark_media_id") else "missing"), {}
    if key.startswith("color_"):
        value = _text(v(key))
        if not HEX.match(value):
            return "missing", {}
        return ("weak" if DEFAULTS.get(key) == value.lower() else "ok"), {"value": value.lower()}
    if key == "contrast":
        text, primary = _text(v("color_text")), _text(v("color_primary"))
        if not (HEX.match(text) and HEX.match(primary)):
            return "missing", {}
        ratio = round(contrast(text, primary), 1)
        return ("ok" if ratio >= 4.5 else "weak"), {"ratio": ratio}
    if key in ("font_heading", "font_family"):
        value = _text(v(key))
        if not value or value == "system-ui":
            return "missing", {}
        files = [f for f in facts.get("fonts", []) if f.get("family", "").lower() == family_name(value)]
        return "ok", {"family": family_name(value), "files": len(files)}
    if key == "font_arabic":
        if not facts.get("arabic_needed"):
            return "ok", {"skipped": True}
        weak = []
        for css in {_text(v("font_heading")) or _text(v("font_family")), _text(v("font_family"))}:
            family = family_name(css) or "system-ui"
            files = [f for f in facts.get("fonts", []) if f.get("family", "").lower() == family]
            if files:
                if not any(f.get("has_arabic") for f in files):
                    weak.append(family)
            elif family not in ARABIC_FONTS:
                weak.append(family)
        return ("weak" if weak else "ok"), ({"families": sorted(weak)} if weak else {})
    if key == "personality":
        traits = [t for t in re.split(r"[,،]", _text(v(key))) if t.strip()]
        return ("missing" if not traits else "weak" if len(traits) < 2 else "ok"), {}
    if key == "sample_posts":
        posts = [p for p in re.split(r"\n\s*\n", _text(v(key))) if p.strip()]
        return ("missing" if not posts else "weak" if len(posts) < 2 else "ok"), {"count": len(posts)}
    if key == "banned_words":
        return ("ok" if _text(v(key)) else "missing"), {}
    if key == "hashtags":
        return ("ok" if "#" in _text(v(key)) else "missing"), {}
    if key == "photo_style":
        shot = v(key) or {}
        return ("ok" if isinstance(shot, dict) and (len(shot) > 1 or shot.get("preset")) else "missing"), {}
    if key == "guard_mode":
        return ("ok" if (v(key) or "guide") != "off" else "weak"), {"mode": v(key) or "guide"}
    value = _text(v(key))
    if not value:
        return "missing", {}
    return ("weak" if len(value) < MIN_LENGTH.get(key, 1) else "ok"), {}


def report(values: dict, facts: dict | None = None) -> dict:
    facts = facts or {}
    checks, total, got = [], 0.0, 0.0
    for key, group, weight, field, tab, ai in CHECKS:
        if key == "font_arabic" and not facts.get("arabic_needed"):
            continue
        status, detail = _status(key, values, facts)
        total += weight
        got += weight * (1 if status == "ok" else 0.5 if status == "weak" else 0)
        checks.append({"key": key, "group": group, "status": status, "weight": weight, "field": field, "tab": tab,
                       "ai": ai and status != "ok", "detail": detail})
    score = round(100 * got / total) if total else 0
    return {"score": score, "checks": checks, "missing": sum(1 for c in checks if c["status"] == "missing"),
            "weak": sum(1 for c in checks if c["status"] == "weak")}


def arabic_needed(workspace_locale: str | None, language_style: str | None) -> bool:
    return (workspace_locale or "") == "ar" or (language_style or "") in ARABIC_STYLES


def kit_values(kit) -> dict:
    names = ("name", "logo_media_id", "logo_dark_media_id", "color_primary", "color_secondary", "color_text",
             "color_accent", "color_background", "font_family", "font_heading", "tagline", "tone", "guidelines",
             "hashtags", "visual_style", "description", "industry", "audience", "personality", "language_style",
             "emoji_style", "cta", "banned_words", "sample_posts", "website", "guard_mode", "photo_style",
             "visual_rules")
    return {n: getattr(kit, n, None) for n in names}


def kit_facts(db: Session, kit) -> dict:
    from app.modules.workspaces.models import Workspace

    from .models import BrandFont
    workspace = db.get(Workspace, kit.workspace_id)
    fonts = [{"family": f.family, "has_arabic": f.has_arabic, "role": f.role, "weight": f.weight}
             for f in db.scalars(select(BrandFont).where(BrandFont.brand_kit_id == kit.id))]
    return {"fonts": fonts, "arabic_needed": arabic_needed(workspace.locale if workspace else None, kit.language_style)}


def for_kit(db: Session, kit) -> dict:
    return report(kit_values(kit), kit_facts(db, kit))
