"""What paid radar sources cost the workspace, through the AI credits system.

Every paid read (X posts, Brave queries, Reddit calls, TikTok provider requests) is priced at the platform's unit
price × (1 + markup) and recorded as an ``AIUsage`` row with capability ``data`` (no provider = platform paid), so
it counts toward the plan's monthly AI allowance, takes bought credits beyond it, and shows in the usage history
and cost dashboards exactly like platform AI. A workspace using its own key (X, Brave) is not charged.

Before each batch a collector calls ``afford`` (raises ``SourceBlocked`` with ``out_of_credits`` or
``quota_exhausted`` when the credits or the setup's monthly cap would be exceeded); after the batch it calls
``charge`` with the units actually read.

    metering.afford(db, query, "web", cursor, units=1, own=False)
    metering.charge(db, query, "web", cursor, units=1, own=False)
"""
from app.core.db import utcnow
from app.core.errors import LimitReached
from app.core.i18n import _

from . import registry


class SourceBlocked(Exception):
    """A source cannot run now: ``status`` is one of ``registry.STATUSES``; ``message`` is shown to people."""

    def __init__(self, status: str, message: str, action: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.action = status, message, action


def _month() -> str:
    return utcnow().strftime("%Y-%m")


def source_spend(cursor: dict) -> float:
    spend = cursor.get("spend") or {}
    return float(spend.get("usd") or 0.0) if spend.get("month") == _month() else 0.0


def query_spend(query, current: tuple[str, dict] | None = None) -> float:
    """$ the setup spent this month on paid sources (``current``: a source whose cursor is being updated)."""
    cursors = dict(getattr(query, "_live_cursors", None) or query.cursors or {})
    if current:
        cursors[current[0]] = current[1]
    return round(sum(source_spend(c) for k, c in cursors.items() if isinstance(c, dict) and not k.startswith("_")), 6)


def price_of(db, source: str, units: float) -> float:
    from app.modules.billing import credits
    return credits.price_of(db, registry.unit_price(db, source) * units)


def affordable_units(db, query, source: str, cursor: dict, wanted: int, *, own: bool = False) -> int:
    """How many of ``wanted`` units fit in the setup's monthly cap (all of them without a cap or with an own key)."""
    cap = query.monthly_cap_usd
    if own or cap is None:
        return wanted
    unit = price_of(db, source, 1)
    if unit <= 0:
        return wanted
    left = float(cap) - query_spend(query, (source, cursor))
    return max(0, min(wanted, int(left / unit + 1e-9)))


def afford(db, query, source: str, cursor: dict, units: float, *, own: bool = False) -> None:
    """Refuse the next batch when it would pass the setup's monthly cap or the workspace's credits."""
    if own or units <= 0:
        return
    price = price_of(db, source, units)
    cap = query.monthly_cap_usd
    if cap is not None and query_spend(query, (source, cursor)) + price > float(cap) + 1e-9:
        raise SourceBlocked("quota_exhausted", _("This setup reached its monthly spending cap (${cap}). Raise the cap "
                                                 "in the setup to read more.", cap=f"{float(cap):.2f}"),
                            {"kind": "edit_setup", "field": "monthly_cap_usd"})
    from app.modules.billing import limits
    try:
        limits.check(db, query.workspace_id, "ai_credits", amount=max(price, 0.000001))
    except LimitReached:
        raise SourceBlocked("out_of_credits", _("Your AI credits are used up. Buy credits to keep reading this "
                                                "source."), {"kind": "buy_credits"}) from None


def charge(db, query, source: str, cursor: dict, units: float, *, own: bool = False) -> float:
    """Record ``units`` read from ``source``; returns what the workspace was charged ($)."""
    if units <= 0:
        return 0.0
    month = _month()
    spend = cursor.get("spend") or {}
    if spend.get("month") != month:
        spend = {"month": month, "usd": 0.0, "units": 0, "own_units": 0}
    if own:
        spend["own_units"] = int(spend.get("own_units") or 0) + int(units)
        cursor["spend"] = spend
        return 0.0
    from app.modules.ai.providers import record_usage
    spec = registry.SOURCE_DEFS[source]
    cost = registry.unit_price(db, source) * units
    usage = record_usage(db, None, registry.usage_name(source), "data", units=units, cost=cost,
                         purpose=f"Radar: {spec.label} — {int(units)} {spec.unit}{'s' if units != 1 else ''}",
                         workspace_id=query.workspace_id)
    charged = float(usage.price if usage.price is not None else usage.cost or 0.0)
    spend.update(usd=round(float(spend.get("usd") or 0.0) + charged, 6), units=int(spend.get("units") or 0) + int(units))
    cursor["spend"] = spend
    return charged
