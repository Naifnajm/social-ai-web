"""Brand font files: what a file can draw, and which file the renderers use for a kit.

    fonts.inspect(content)                    # {"family", "weight", "style", "has_arabic", "loadable"} or None
    fonts.covers(path, text)                  # True when the file has a glyph for every letter of ``text``
    fonts.for_kit(db, kit)                    # {"heading": {"bold": path, "regular": path}, "body": {...}}

Pillow (FreeType with brotli) reads TTF, OTF, WOFF and WOFF2 directly, so nothing is converted. A glyph is
"missing" when the letter draws exactly like a code point no font has (the .notdef box or nothing). The renderers
fall back to the bundled Tajawal for text a brand font cannot draw (e.g. Arabic with a Latin-only font).
"""
import io
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session

FONT_EXT = {".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf"}
NOWHERE = "\U000F0000"  # private use plane: no font maps it, so it draws as .notdef
ARABIC_SAMPLE = "بحث"
WEIGHTS = {"thin": 100, "hairline": 100, "extralight": 200, "ultralight": 200, "light": 300, "regular": 400,
           "normal": 400, "book": 400, "roman": 400, "medium": 500, "semibold": 600, "demibold": 600, "bold": 700,
           "extrabold": 800, "ultrabold": 800, "black": 900, "heavy": 900}


def _signature(font, char: str) -> bytes:
    image = Image.new("L", (96, 96))
    ImageDraw.Draw(image).text((12, 12), char, font=font, fill=255)
    return image.tobytes()


def _has(font, chars: str) -> bool:
    missing = _signature(font, NOWHERE)
    return all(_signature(font, c) != missing for c in chars if not c.isspace())


def weight_of(style_name: str | None, filename: str = "") -> int:
    words = re.sub(r"[^a-z]", " ", f"{style_name or ''} {filename}".lower().replace("-", " ")).split()
    joined = "".join(words)
    for word in sorted(WEIGHTS, key=len, reverse=True):  # "extrabold" before "bold"
        if word in words or word in joined:
            return WEIGHTS[word]
    match = re.search(r"\b([1-9]00)\b", f"{style_name} {filename}")
    return int(match.group(1)) if match else 400


def inspect(content: bytes, filename: str = "") -> dict | None:
    """What a font file is (None when Pillow cannot read it)."""
    try:
        font = ImageFont.truetype(io.BytesIO(content), 40, layout_engine=ImageFont.Layout.BASIC)
        family, style = font.getname()
    except Exception:
        return None
    style = style or ""
    return {"family": (family or "").strip()[:120], "weight": weight_of(style, filename),
            "style": "italic" if "italic" in style.lower() or "oblique" in style.lower() else "normal",
            "has_arabic": _has(font, ARABIC_SAMPLE), "loadable": True}


@lru_cache(maxsize=256)
def _font(path: str):
    return ImageFont.truetype(path, 40, layout_engine=ImageFont.Layout.BASIC)


@lru_cache(maxsize=4096)
def _covers_char(path: str, char: str) -> bool:
    try:
        return _has(_font(path), char)
    except Exception:
        return False


def covers(path: str | None, text: str | None) -> bool:
    if not path:
        return False
    return all(_covers_char(path, c) for c in set(text or "") if c.isprintable() and not c.isspace())


def family_name(css: str | None) -> str:
    """The first family of a CSS stack, unquoted and lower case ("'Thmanyah Sans', sans-serif" -> "thmanyah sans")."""
    first = (css or "").split(",")[0].strip().strip("'\"").strip()
    return first.lower()


def css_stack(family: str, generic: str = "sans-serif") -> str:
    value = f"'{family.replace(chr(39), '')}', {generic}"
    return value[:80]


def _pick(rows: list, bold: bool):
    target = 700 if bold else 400
    upright = [r for r in rows if r.style != "italic"] or rows
    return min(upright, key=lambda r: (abs((r.weight or 400) - target),
                                       -(r.weight or 400) if bold else r.weight or 400))


def for_kit(db: Session, kit) -> dict:
    """Font file paths for the kit's heading and body fonts: ``{"heading": {"bold": p, "regular": p}, "body": …}``
    (a role is missing when the kit has no file of that family)."""
    if kit is None or not getattr(kit, "id", None):
        return {}
    from app.core.models import Media
    from app.core.storage import media_path

    from .models import BrandFont
    rows = list(db.scalars(select(BrandFont).where(BrandFont.brand_kit_id == kit.id)))
    if not rows:
        return {}
    out = {}
    for role, css in (("heading", kit.font_heading or kit.font_family), ("body", kit.font_family)):
        family = family_name(css)
        same = [r for r in rows if r.family.lower() == family] or [r for r in rows if r.role == role]
        if not same:
            continue
        paths = {}
        for key, bold in (("bold", True), ("regular", False)):
            row = _pick(same, bold)
            media = db.get(Media, row.media_id)
            if media and media.workspace_id == kit.workspace_id:
                path = media_path(media)
                if path.exists():
                    paths[key] = str(path)
        if paths:
            out[role] = paths
    return out


def kit_fonts_for_brand(db: Session, kit_id: int | None) -> dict:
    """``for_kit`` by id (renderers that only have the kit id in a brand dict)."""
    if not kit_id:
        return {}
    from .models import BrandKit
    kit = db.get(BrandKit, kit_id)
    return for_kit(db, kit) if kit else {}
