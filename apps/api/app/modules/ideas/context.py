"""What the idea engine knows about a workspace: its brand, what worked on its pages, what people ask and say
(Radar), what is rising, which content pillar is behind, which product to show and when the audience is there.

Every piece is optional: a new workspace with no history still gets ideas from its brand kit and products.
Signals carry a stable ``key`` so an idea can name the reason it was made ("asked 18 times this week").
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.social.models import PUBLISH_PLATFORMS, Post, SocialAccount
from app.modules.workspaces.models import Workspace


def _brand(db: Session, workspace: Workspace) -> dict:
    from app.modules.brand import service as brand
    kit = brand.default_kit(db, workspace.id)
    if not kit:
        return {"name": workspace.name}
    fields = ("tone", "guidelines", "hashtags", "description", "industry", "audience", "personality", "cta",
              "banned_words", "sample_posts", "tagline", "emoji_style", "language_style")
    out = {"name": kit.name or workspace.name, "kit_id": kit.id, "colors": {
        "primary": kit.color_primary, "secondary": kit.color_secondary, "text": kit.color_text,
        "accent": kit.color_accent, "background": kit.color_background}, "logo_media_id": kit.logo_media_id}
    out.update({f: getattr(kit, f) for f in fields if getattr(kit, f, None)})
    return out


def _performance(db: Session, workspace_id: int) -> dict:
    from app.modules.social import analytics
    end = utcnow()
    try:
        data = analytics.dashboard_data(db, workspace_id, end - timedelta(days=60), end)
    except Exception:  # no history yet, or a network without metrics
        return {}
    content = data.get("content") or {}

    def best(group):
        rows = [r for r in content.get(group) or [] if r["count"] >= 2]
        return max(rows, key=lambda r: r["engagement_rate"]) if rows else None

    return {
        "best_format": best("media"), "best_length": best("length"), "best_hashtags": best("hashtags"),
        "top_posts": [{"name": p["name"], "platform": p["platform"], "media_type": p["media_type"],
                       "engagement_rate": p["engagement_rate"]} for p in (data.get("top_posts") or [])[:4]],
    }


def _radar(db: Session, workspace: Workspace) -> dict:
    from app.modules.billing import limits
    if not limits.feature(db, workspace.id, "listening"):
        return {}
    from app.modules.listening import service as radar
    from app.modules.listening.models import ListeningQuery, Mention, RadarEvent
    query = db.scalar(select(ListeningQuery).where(ListeningQuery.workspace_id == workspace.id,
                                                   ListeningQuery.active.is_(True)).order_by(ListeningQuery.id))
    if not query:
        return {}
    since = utcnow() - timedelta(days=7)
    voice = radar.voice(db, workspace, query, days=14)
    questions = db.scalars(select(Mention).where(
        Mention.query_id == query.id, Mention.brand.is_(None), Mention.published_at >= since,
        Mention.intent.in_(("question", "purchase"))).order_by(Mention.published_at.desc()).limit(40)).all()
    by_topic: dict[str, list] = {}
    for m in questions:
        by_topic.setdefault(m.topic or "", []).append(m)
    events = db.scalars(select(RadarEvent).where(RadarEvent.query_id == query.id, RadarEvent.state == "open",
                                                 RadarEvent.kind.in_(("opportunity", "rising", "competitor")))
                        .order_by(RadarEvent.started_at.desc()).limit(5)).all()
    praised = [w for w in voice.get("words") or [] if w["sentiment"] == "positive"][:6]
    return {
        "questions": [{"key": f"question:{topic or '-'}", "topic": topic or None, "count": len(rows),
                       "examples": [(m.text or "")[:160] for m in rows[:3]]}
                      for topic, rows in sorted(by_topic.items(), key=lambda kv: -len(kv[1]))[:3]],
        "rising": [{"key": f"rising:{r['word']}", "word": r["word"], "count": r["count"], "before": r["before"]}
                   for r in (voice.get("rising") or [])[:4]],
        "hashtags": [h["tag"] for h in (voice.get("hashtags") or [])[:6]],
        "praised": [w["word"] for w in praised],
        "events": [{"key": f"event:{e.id}", "kind": e.kind, "title": e.title, "suggestion": e.suggestion}
                   for e in events],
    }


def _pillars(db: Session, workspace_id: int) -> list[dict]:
    from app.modules.planning.service import pillar_rows
    rows = [r for r in pillar_rows(db, workspace_id, include_inactive=False) if r["target_share"]]
    behind = sorted(rows, key=lambda r: r["share_30"] + r["planned_share_30"] - 2 * r["target_share"])
    return [{"key": f"pillar:{r['id']}", "id": r["id"], "name": r["name"], "description": r["description"],
             "target": r["target_share"], "share": r["share_30"]} for r in behind[:3]]


def _products(db: Session, workspace_id: int) -> list[dict]:
    from app.modules.products.models import Product
    rows = db.scalars(select(Product).where(Product.workspace_id == workspace_id, Product.active.is_(True))
                      .order_by(Product.announced_at.asc().nullsfirst(), Product.id.desc()).limit(4)).all()
    return [{"key": f"product:{p.id}", "id": p.id, "name": p.name, "description": (p.description or "")[:300],
             "price": p.price, "currency": p.currency, "image_media_id": p.image_media_id} for p in rows]


def _recent(db: Session, workspace_id: int) -> list[str]:
    rows = db.scalars(select(Post.content).where(Post.workspace_id == workspace_id, Post.content.is_not(None))
                      .order_by(Post.id.desc()).limit(12)).all()
    return [(c or "")[:140] for c in rows if (c or "").strip()]


def _platforms(db: Session, workspace_id: int) -> list[str]:
    rows = db.scalars(select(SocialAccount.platform).where(
        SocialAccount.workspace_id == workspace_id, SocialAccount.active.is_(True),
        SocialAccount.platform.in_(PUBLISH_PLATFORMS))).all()
    return list(dict.fromkeys(rows))


def build(db: Session, workspace: Workspace) -> dict:
    from app.modules.social import service as social
    platforms = _platforms(db, workspace.id)
    try:
        slots = social.next_best_slots(db, workspace.id, platforms or None, count=8)
    except Exception:
        slots = []
    return {
        "brand": _brand(db, workspace), "performance": _performance(db, workspace.id),
        "radar": _radar(db, workspace), "pillars": _pillars(db, workspace.id),
        "products": _products(db, workspace.id), "recent": _recent(db, workspace.id),
        "platforms": platforms, "slots": slots,
    }
