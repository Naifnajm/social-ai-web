"""Turn the workspace context into ideas: with the AI (strategist prompt, JSON answer) or, without it, simple
rules on the same signals. Reasons shown to people are always written here from the real signals — never by
the model — so "asked 18 times" is a fact, not a guess."""
import json
import logging

from sqlalchemy.orm import Session

from app.core.i18n import LANGUAGE_NAMES, _, set_locale
from app.modules.workspaces.models import Workspace

from .models import FORMATS

_logger = logging.getLogger(__name__)
VIDEO_PLATFORMS = ("instagram", "tiktok", "youtube", "facebook", "threads", "x", "linkedin")
SHORT_PLATFORMS = ("x", "threads")

SYSTEM = """You are the social media strategist of the brand "{brand}". Write everything in {language}.
From the SIGNALS only, propose {count} content ideas for the coming days that this brand's audience will love.
Mix the formats: when {count} ≥ 3 include at least one "carousel" and one "video".
For every idea return:
- "format": "post" | "carousel" | "video"
- "title": a short internal title (max 8 words)
- "reason_keys": the "key" values of the signals the idea answers (at least one)
- "caption": the ready-to-publish caption in the brand's tone, with a clear call to action, emojis as the brand uses
  them, line breaks for reading, no hashtags inside (they go in "hashtags")
- "variants": only for these networks when the caption is longer than they like: {short} → {{"x": "≤ 260 chars"}}
- "hashtags": 0-5 relevant hashtags (reuse the brand's and the rising ones)
- "slides" (carousel only): 4-6 slides {{"title": "≤ 8 words", "body": "≤ 25 words"}}; slide 1 is the hook,
  the last one the call to action
- "video" (video only): {{"hook": "the first 3 seconds", "duration_seconds": 15-45,
  "scenes": [{{"visual": "what we see", "text": "on-screen text"}}] (3-6 scenes), "voiceover": "full voice-over"}}
- "pillar_id" and "product_id": the id from the signals when the idea is about that pillar / product, else null
Rules: never invent prices, discounts, dates, stock, awards or numbers that are not in the signals; do not repeat
the RECENT posts; respect the brand's banned words and guidelines; one idea per angle.
Answer with ONLY one JSON object: {{"ideas": [ ... ]}}."""


def _reason_labels(context: dict) -> dict[str, dict]:
    """key -> {"kind", "label"} for every signal the ideas may cite."""
    out: dict[str, dict] = {}
    radar = context.get("radar") or {}
    for q in radar.get("questions") or []:
        label = _("{count} people asked about {topic} this week", count=q["count"], topic=q["topic"]) if q["topic"] \
            else _("{count} buying questions this week", count=q["count"])
        out[q["key"]] = {"kind": "question", "label": label}
    for r in radar.get("rising") or []:
        out[r["key"]] = {"kind": "rising", "label": _("“{word}” is rising: {count} mentions this week",
                                                      word=r["word"], count=r["count"])}
    for e in radar.get("events") or []:
        out[e["key"]] = {"kind": "event", "label": e["title"]}
    for p in context.get("pillars") or []:
        out[p["key"]] = {"kind": "pillar", "label": _("Your “{name}” pillar is behind: {share}% of posts, target "
                                                      "{target}%", name=p["name"], share=round(p["share"]),
                                                      target=p["target"])}
    for p in context.get("products") or []:
        out[p["key"]] = {"kind": "product", "label": _("Product to show: {name}", name=p["name"])}
    perf = context.get("performance") or {}
    if perf.get("best_format"):
        f = perf["best_format"]
        out["format"] = {"kind": "format", "label": _("{format} posts get your best engagement ({rate}%)",
                                                      format=f["label"], rate=f["engagement_rate"])}
    for i, post in enumerate(perf.get("top_posts") or []):
        out[f"top:{i}"] = {"kind": "top_post", "label": _("In the style of your top post “{name}”",
                                                          name=post["name"])}
    out["brief"] = {"kind": "brief", "label": _("Your request")}
    return out


def _signals_for_prompt(context: dict, focus: str | None) -> str:
    brand = {k: v for k, v in (context.get("brand") or {}).items() if k not in ("colors", "logo_media_id", "kit_id")}
    perf = context.get("performance") or {}
    data = {
        "BRAND": brand, "NETWORKS": context.get("platforms") or [],
        "PERFORMANCE": {"best_format": (perf.get("best_format") or {}).get("key"),
                        "best_length": (perf.get("best_length") or {}).get("key"),
                        "top_posts": [{"key": f"top:{i}", **p} for i, p in enumerate(perf.get("top_posts") or [])]},
        "SIGNALS": {"radar": context.get("radar") or {}, "pillars_behind": context.get("pillars") or [],
                    "products": [{k: v for k, v in p.items() if k != "image_media_id"}
                                 for p in context.get("products") or []]},
        "RECENT": context.get("recent") or [],
    }
    if perf.get("best_format"):
        data["SIGNALS"]["format"] = {"key": "format", "best": perf["best_format"]["key"]}
    if focus:
        data["SIGNALS"]["brief"] = {"key": "brief", "request": focus}
    return json.dumps(data, ensure_ascii=False, default=str)


def _clean(item: dict, labels: dict, context: dict) -> dict | None:
    fmt = str(item.get("format") or "post").lower()
    fmt = fmt if fmt in FORMATS else "post"
    caption = str(item.get("caption") or "").strip()
    title = str(item.get("title") or "").strip()[:200]
    if not caption or not title:
        return None
    keys = [k for k in item.get("reason_keys") or [] if k in labels]
    slides = [{"title": str(s.get("title") or "").strip()[:120], "body": str(s.get("body") or "").strip()[:400]}
              for s in item.get("slides") or [] if isinstance(s, dict) and (s.get("title") or s.get("body"))][:8]
    video = item.get("video") if isinstance(item.get("video"), dict) else None
    if fmt == "carousel" and len(slides) < 2:
        fmt = "post"
    if fmt == "video" and not (video and video.get("scenes")):
        fmt = "post"
    pillar_ids = {p["id"] for p in context.get("pillars") or []}
    product_ids = {p["id"] for p in context.get("products") or []}
    tags = [("#" + str(t).lstrip("#").strip().replace(" ", "_")) for t in item.get("hashtags") or [] if str(t).strip()]
    variants = {k: str(v).strip() for k, v in (item.get("variants") or {}).items()
                if k in (context.get("platforms") or []) and str(v).strip()} if isinstance(item.get("variants"), dict) else {}
    return {
        "format": fmt, "title": title, "reasons": [labels[k] for k in dict.fromkeys(keys)], "caption": caption,
        "variants": variants or None, "hashtags": list(dict.fromkeys(tags))[:5],
        "slides": slides if fmt == "carousel" else [],
        "video": ({"hook": str(video.get("hook") or "")[:300], "voiceover": str(video.get("voiceover") or "")[:2000],
                   "duration": int(video.get("duration_seconds") or video.get("duration") or 30),
                   "scenes": [{"visual": str(s.get("visual") or "")[:300], "text": str(s.get("text") or "")[:200]}
                              for s in video.get("scenes") or [] if isinstance(s, dict)][:8]}
                  if fmt == "video" else None),
        "pillar_id": item.get("pillar_id") if item.get("pillar_id") in pillar_ids else None,
        "product_id": item.get("product_id") if item.get("product_id") in product_ids else None,
    }


def with_ai(db: Session, workspace: Workspace, context: dict, count: int, language: str,
            focus: str | None = None, user_id: int | None = None) -> list[dict]:
    from app.modules.ai import service as ai
    labels = _reason_labels(context)
    system = SYSTEM.format(brand=(context.get("brand") or {}).get("name") or workspace.name,
                           language=LANGUAGE_NAMES.get(language, "Arabic"), count=count,
                           short=", ".join(p for p in SHORT_PLATFORMS if p in (context.get("platforms") or []))
                           or "none")
    data = ai.generate_json(db, workspace.id, system, _signals_for_prompt(context, focus),
                            purpose="Ideas of the day", max_tokens=900 * count + 400, user_id=user_id)
    items = data.get("ideas") or data.get("items") or []
    out = [idea for idea in (_clean(i, labels, context) for i in items if isinstance(i, dict)) if idea]
    return out[:count]


# ---------------------------------------------------------------------------------------------- without AI
def without_ai(context: dict, count: int) -> list[dict]:
    """Plain ideas from the strongest signals, written from templates (the AI writes much better ones)."""
    labels = _reason_labels(context)
    brand = context.get("brand") or {}
    tags = [t if t.startswith("#") else f"#{t}" for t in (brand.get("hashtags") or "").replace(",", " ").split()][:3]
    cta = brand.get("cta") or _("Tell us what you think in the comments.")
    radar = context.get("radar") or {}
    groups: dict[str, list[dict]] = {"question": [], "product": [], "rising": [], "pillar": []}
    ideas = groups["question"]
    for q in radar.get("questions") or []:
        topic = q["topic"] or _("our products")
        ideas.append({
            "format": "carousel", "title": _("Answer the question about {topic}", topic=topic),
            "reasons": [labels[q["key"]]], "hashtags": tags,
            "caption": _("You asked us about {topic}, so here are the answers 👇\n\n{cta}", topic=topic, cta=cta),
            "slides": [{"title": _("Your questions about {topic}", topic=topic), "body": _("Swipe for the answers")},
                       *[{"title": (ex[:60] + "…") if len(ex) > 60 else ex, "body": _("Our answer here")}
                         for ex in q["examples"][:3]],
                       {"title": _("Anything else?"), "body": cta}]})
    for p in context.get("products") or []:
        groups["product"].append({
            "format": "post", "title": _("Show {name}", name=p["name"]), "reasons": [labels[p["key"]]],
            "hashtags": tags, "product_id": p["id"],
            "caption": "\n\n".join(filter(None, [p["name"], p["description"], cta]))})
    for r in radar.get("rising") or []:
        groups["rising"].append({
            "format": "video", "title": _("Join the talk about {word}", word=r["word"]),
            "reasons": [labels[r["key"]]], "hashtags": tags,
            "caption": _("Everyone is talking about {word}. Here is our take 👀\n\n{cta}", word=r["word"], cta=cta),
            "video": {"hook": _("Have you heard about {word}?", word=r["word"]), "duration": 20,
                      "voiceover": "", "scenes": [{"visual": _("Close-up of the product"), "text": r["word"]},
                                                  {"visual": _("Your team or a customer reacting"), "text": ""},
                                                  {"visual": _("Logo and call to action"), "text": cta}]}})
    for p in context.get("pillars") or []:
        groups["pillar"].append({
            "format": "post", "title": _("A post for “{name}”", name=p["name"]), "reasons": [labels[p["key"]]],
            "hashtags": tags, "pillar_id": p["id"],
            "caption": "\n\n".join(filter(None, [p["description"] or p["name"], cta]))})
    ideas = []  # one of each kind first, then the rest
    while any(groups.values()):
        for rows in groups.values():
            if rows:
                ideas.append(rows.pop(0))
    if not ideas:
        name = brand.get("name") or ""
        ideas.append({"format": "post", "title": _("Introduce {name}", name=name), "reasons": [], "hashtags": tags,
                      "caption": "\n\n".join(filter(None, [brand.get("description") or brand.get("tagline") or name,
                                                           cta]))})
    for idea in ideas:
        idea.setdefault("slides", [])
        idea.setdefault("video", None)
        idea.setdefault("variants", None)
    return ideas[:count]


def generate(db: Session, workspace: Workspace, context: dict, count: int, language: str, *,
             focus: str | None = None, user_id: int | None = None) -> tuple[list[dict], bool]:
    """(ideas, written_by_ai)."""
    from app.modules.ai import service as ai
    set_locale(language)
    if ai.has_provider(db, workspace.id, "text"):
        try:
            ideas = with_ai(db, workspace, context, count, language, focus, user_id)
            if ideas:
                return ideas, True
        except Exception as exc:  # spend limit, unreadable answer: rules keep the feature useful
            _logger.info("ideas: AI failed for workspace %s: %s", workspace.id, exc)
    return without_ai(context, count), False
