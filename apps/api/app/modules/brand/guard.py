"""Brand guard: keep the AI inside the brand's identity (colours, visual style, approved photo style, tone, banned
words).

Each brand kit has a ``guard_mode``:

* ``off``    — the kit is only used when someone picks it;
* ``guide``  — (default) the brand is added to prompts as guidance; the person's camera choices win;
* ``strict`` — the brand always applies, even when no kit was picked: images and videos get the brand's colours,
  visual rules and approved photo style (which override the person's camera choices), texts are checked for
  banned words and the emoji policy and rewritten once by the fast model when they break a rule, and every
  generated image gets a colour match score against the brand palette.

    from app.modules.brand import guard
    kit = guard.kit_for(db, ws_id, brand_kit_id)            # the picked kit, else the default kit when strict
    prompt, shot = guard.visual(kit, "image", prompt, shot)  # prompt + effective camera settings
    issues = guard.text_issues(kit, text)                    # [{"code", "message"}]
    text, notes = guard.enforce_text(db, ws_id, kit, text)   # strict: fixed text (+ what was fixed)
    guard.color_match(kit, image_bytes)                      # {"score": 0-100, "colors": ["#aabbcc", …]}
"""
import io
import logging
import re

from sqlalchemy.orm import Session

from app.core.i18n import _

from .models import BrandKit

_logger = logging.getLogger(__name__)
MODES = ("off", "guide", "strict")
LOW_MATCH = 45  # below this colour match an image gets a notice
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")


def mode(kit: BrandKit | None) -> str:
    return (kit.guard_mode if kit and kit.guard_mode in MODES else "guide") if kit else "off"


def kit_for(db: Session, workspace_id: int, brand_kit_id: int | None = None) -> BrandKit | None:
    """The kit to apply: the one picked, else the workspace's default kit when its guard is strict."""
    from . import service as brand
    if brand_kit_id:
        return brand.get_kit(db, workspace_id, brand_kit_id)  # a kit someone picked always applies
    kit = brand.default_kit(db, workspace_id)
    return kit if kit and mode(kit) == "strict" else None


def palette(kit: BrandKit) -> list[str]:
    return [c for c in (kit.color_primary, kit.color_secondary, kit.color_accent, kit.color_background) if c]


def visual_rules(kit: BrandKit, kind: str) -> str:
    """Prompt words for images/videos."""
    if mode(kit) != "strict":
        hint = kit.visual_hint()
        if (kit.visual_rules or "").strip():
            hint = (hint + " Visual rules: %s." % kit.visual_rules.strip()).strip()
        return hint
    lines = ["BRAND RULES (must be followed exactly):"]
    colors = palette(kit)
    if colors:
        lines.append("- Colour palette: use only these brand colours %s plus neutral whites, greys and blacks; no "
                     "other dominant colours." % ", ".join(colors))
    if (kit.visual_style or "").strip():
        lines.append("- Visual style: %s." % kit.visual_style.strip())
    if (kit.visual_rules or "").strip():
        lines.append("- Rules: %s." % kit.visual_rules.strip())
    if (kit.personality or "").strip():
        lines.append("- Mood: %s." % kit.personality.strip())
    lines.append("- No text or logos other than the brand's own; nothing that contradicts the rules above.")
    return "\n".join(lines)


def visual(kit: BrandKit | None, kind: str, prompt: str, shot: dict | None) -> tuple[str, dict | None]:
    """(prompt with the brand, effective camera settings)."""
    from app.modules.ai import camera
    if not kit or kind not in ("image", "video"):
        return prompt, camera.clean(shot)
    rules = visual_rules(kit, kind)
    if rules and rules not in prompt:
        prompt = "%s\n\n%s" % (prompt, rules)
    style = camera.clean(kit.photo_style)
    if mode(kit) == "strict":
        shot = camera.merge(shot, style)       # the approved photo style wins
    else:
        shot = camera.merge(style, shot)       # the person's choices win
    return prompt, shot


# ------------------------------------------------------------------------------------------- texts
def _words(value: str | None) -> list[str]:
    return [w.strip() for w in re.split(r"[,\n،;]+", value or "") if w.strip()]


def text_issues(kit: BrandKit | None, text: str) -> list[dict]:
    if not kit or not text:
        return []
    issues = []
    lowered = text.lower()
    found = [w for w in _words(kit.banned_words) if w.lower() in lowered]
    if found:
        issues.append({"code": "banned_words", "words": found,
                       "message": _("Uses words the brand never uses: {words}", words=", ".join(found))})
    if kit.emoji_style == "none" and EMOJI.search(text):
        issues.append({"code": "emojis", "message": _("The brand does not use emojis.")})
    return issues


def _strip(kit: BrandKit, text: str) -> str:
    for word in _words(kit.banned_words):
        text = re.sub(re.escape(word), "", text, flags=re.IGNORECASE)
    if kit.emoji_style == "none":
        text = EMOJI.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def enforce_text(db: Session, workspace_id: int, kit: BrandKit | None, text: str,
                 user_id: int | None = None) -> tuple[str, list[str]]:
    """Strict kits: rewrite a text that breaks a rule (fast model, one try; plain removal as the fallback).
    Other modes only report. Returns (text, notes for the person)."""
    issues = text_issues(kit, text)
    if not issues:
        return text, []
    notes = [i["message"] for i in issues]
    if mode(kit) != "strict":
        return text, notes
    from app.modules.ai import providers as prov
    from app.modules.ai import service as ai
    fixed = None
    try:
        fast = prov.fast_model(db, workspace_id)
        system = ("You edit social media texts so they follow the brand rules. Keep the meaning, language, length, "
                  "line breaks and hashtags. Answer with the corrected text only.\n" + kit.llm_profile())
        problems = "\n".join("- " + i["message"] for i in issues)
        fixed = ai.generate_text(db, workspace_id, system, "Problems:\n%s\n\nText:\n%s" % (problems, text),
                                 model_id=fast.id if fast else None, purpose=_("Brand guard"), user_id=user_id)
    except Exception as exc:  # no AI or spend limit: fall back to removing the words
        _logger.info("brand guard rewrite skipped: %s", exc)
    if not fixed or text_issues(kit, fixed):
        fixed = _strip(kit, fixed or text)
    return fixed.strip(), [_("Brand guard fixed: {issues}", issues="; ".join(notes))]


# ------------------------------------------------------------------------------------------- colours
def _rgb(hex_color: str) -> tuple[int, int, int] | None:
    value = (hex_color or "").lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except (ValueError, IndexError):
        return None


def _distance(a, b) -> float:  # "redmean" colour distance, close to how people see it
    rmean = (a[0] + b[0]) / 2
    dr, dg, db_ = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + rmean / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rmean) / 256) * db_ * db_) ** 0.5


def _neutral(rgb) -> bool:
    return max(rgb) - min(rgb) < 28


def color_match(kit: BrandKit | None, content: bytes) -> dict | None:
    """Share of the image (0-100) in the brand colours or neutrals, and its five main colours."""
    if not kit:
        return None
    brand = [c for c in (_rgb(x) for x in palette(kit)) if c]
    if not brand:
        return None
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(content)).convert("RGB")
        image.thumbnail((96, 96))
        quantized = image.quantize(colors=8)
        pal = quantized.getpalette()
        counts = sorted(quantized.getcolors() or [], reverse=True)
    except Exception:  # not an image we can read
        return None
    total = sum(c for c, _i in counts) or 1
    matched, colors = 0, []
    for count, index in counts:
        rgb = tuple(pal[index * 3:index * 3 + 3])
        colors.append("#%02x%02x%02x" % rgb)
        if _neutral(rgb) or min(_distance(rgb, b) for b in brand) < 150:
            matched += count
    return {"score": round(100 * matched / total), "colors": colors[:5]}
