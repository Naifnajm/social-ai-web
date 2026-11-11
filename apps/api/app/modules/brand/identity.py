"""Draft a whole brand identity with AI from a short brief (and the colours taken from the logo).

    draft = identity.generate(db, ws_id, brief, fonts=FONTS, user_id=user.id)   # dict of BrandKit fields, not saved

The answer is cleaned before it is returned: colours must be #RRGGBB, the text colour must read on the primary
colour, fonts come from the offered list, codes from their sets, every text is cut to its column size.
"""
import re

from sqlalchemy.orm import Session

from app.modules.ai import service as ai

from .models import EMOJI_STYLES, LANGUAGE_STYLES

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

SYSTEM = (
    "You are a senior brand strategist for brands in the Gulf and the Arab world. From a short brief you design "
    "a complete, usable brand identity for social media. Write every text field in the language the brief asks "
    "for (Arabic by default); Arabic must read as natural Arabic, never as a translation. Colours are hex "
    "#RRGGBB; the text colour must read clearly on the primary colour (WCAG AA). When the brief lists colours "
    "taken from the logo, build the palette from them. Fonts: choose only from the list given, copying a value "
    "exactly. Reply with only one JSON object with these keys: tagline (at most 80 characters), description "
    "(2 to 3 sentences on what the brand offers), audience (who the customers are, 1 to 2 sentences), "
    "personality (array of 3 to 5 single words), tone (how the brand writes, 2 to 3 sentences), language_style "
    "(one of: msa, gulf, saudi, english, bilingual), emoji_style (one of: none, light, rich), cta (a short usual "
    "call to action), guidelines (4 to 8 short do and don't lines, each starting with ✓ or ✗), "
    "banned_words (comma separated words to avoid), hashtags (array of 3 to 6 hashtags), visual_style (how photos "
    "and designs should look, 1 to 2 sentences usable as an image prompt), color_primary, color_secondary, "
    "color_accent, color_text, color_background, font_heading, font_family (the body font), sample_posts (array of "
    "2 short example posts in the brand's voice)."
)

LIMITS = {"tagline": 200, "description": 2000, "audience": 1000, "personality": 300, "tone": 4000, "cta": 200,
          "guidelines": 8000, "banned_words": 2000, "hashtags": 500, "visual_style": 4000, "sample_posts": 6000}


def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def readable_on(background: str, wanted: str | None) -> str:
    """``wanted`` when it reads on ``background`` (4.5:1), else white or near-black, whichever reads better."""
    if wanted and HEX.match(wanted) and contrast(wanted, background) >= 4.5:
        return wanted.lower()
    return "#ffffff" if contrast("#ffffff", background) >= contrast("#111111", background) else "#111111"


def _text(value, limit: int, sep: str = ", ") -> str | None:
    if isinstance(value, list):
        value = sep.join(str(v).strip() for v in value if str(v).strip())
    value = str(value or "").strip()
    return value[:limit] or None


def _color(value, fallback: str | None) -> str | None:
    value = str(value or "").strip()
    return value.lower() if HEX.match(value) else fallback


def clean(data: dict, *, fonts: list[str], palette: list[str]) -> dict:
    """Turn the model's answer into valid BrandKit fields (never trusting its shape)."""
    first = (palette + ["#111111", "#71717a", "#ff3d8b"])
    primary = _color(data.get("color_primary"), first[0])
    out = {
        "color_primary": primary,
        "color_secondary": _color(data.get("color_secondary"), first[1]),
        "color_accent": _color(data.get("color_accent"), first[2]),
        "color_background": _color(data.get("color_background"), None),
        "color_text": readable_on(primary, _color(data.get("color_text"), None)),
        "font_heading": data.get("font_heading") if data.get("font_heading") in fonts else None,
        "font_family": data.get("font_family") if data.get("font_family") in fonts else "system-ui",
        "language_style": data.get("language_style") if data.get("language_style") in LANGUAGE_STYLES else None,
        "emoji_style": data.get("emoji_style") if data.get("emoji_style") in EMOJI_STYLES else None,
    }
    for key, limit in LIMITS.items():
        sep = " " if key == "hashtags" else "\n\n" if key == "sample_posts" else "\n" if key == "guidelines" else ", "
        out[key] = _text(data.get(key), limit, sep)
    if out["hashtags"]:
        out["hashtags"] = " ".join(t if t.startswith("#") else f"#{t}" for t in out["hashtags"].split())[:500]
    return out


def generate(db: Session, workspace_id: int, brief: dict, *, fonts: list[str], user_id: int | None = None) -> dict:
    lines = [f"Brand name: {brief['name']}", f"What it does: {brief['description']}"]
    for label, key in (("Industry", "industry"), ("Customers", "audience"), ("Website", "website")):
        if (brief.get(key) or "").strip():
            lines.append(f"{label}: {brief[key].strip()}")
    if brief.get("language_style") in LANGUAGE_STYLES:
        lines.append(f"Write the texts in: {LANGUAGE_STYLES[brief['language_style']]}")
    palette = [c.lower() for c in brief.get("palette") or [] if HEX.match(c or "")]
    if palette:
        lines.append("Colours taken from the logo (most used first): " + ", ".join(palette))
    lines.append("Fonts to choose from: " + " | ".join(fonts))
    data = ai.generate_json(db, workspace_id, SYSTEM, "\n".join(lines), purpose="brand identity", user_id=user_id)
    return clean(data, fonts=fonts, palette=palette)
