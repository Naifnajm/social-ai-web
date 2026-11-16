"""AI credits: what a workspace pays for AI that runs on the platform's keys, with the platform's margin.

* Every platform-paid AI call is priced at ``cost × (1 + markup%)``; the markup (default 10%) is set by the
  platform admin (``billing.ai_markup_percent``) and is reflected in every estimate shown before a run.
* The plan includes a monthly AI allowance (``ai_credits`` limit, in $ at that price). Beyond it, the
  workspace's bought credits are used: ``billing.credits_per_usd`` credits = $1 (default 100, so 1 credit = 1¢).
* Credits are bought in packs (``billing.credit_packs``) through a Stripe one-time payment and recorded in the
  ledger (``CreditTransaction``) with the running balance kept on the subscription.

    from app.modules.billing import credits
    credits.price_of(db, 0.04)                 # 0.044 with a 10% markup
    credits.available(db, ws_id)               # {"included_left", "balance", "credits_per_usd", …}
    credits.add(db, ws_id, "grant", 500, note="Welcome")
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.i18n import _

from . import platform
from .models import CreditTransaction, Subscription

DEFAULT_MARKUP = 10.0
DEFAULT_CREDITS_PER_USD = 100
DEFAULT_PACKS = [{"usd": 10, "credits": 1000}, {"usd": 25, "credits": 2600}, {"usd": 50, "credits": 5400},
                 {"usd": 100, "credits": 11000}]
KINDS = ("purchase", "usage", "grant", "refund", "adjust")


def markup(db: Session) -> float:
    try:
        value = float(platform.get_setting(db, "billing.ai_markup_percent", DEFAULT_MARKUP))
    except (TypeError, ValueError):
        value = DEFAULT_MARKUP
    return max(0.0, min(value, 500.0))


def price_of(db: Session, cost: float) -> float:
    """What the workspace pays for a platform-paid AI cost."""
    return round(float(cost or 0.0) * (1 + markup(db) / 100), 6)


def credits_per_usd(db: Session) -> int:
    try:
        return max(1, int(platform.get_setting(db, "billing.credits_per_usd", DEFAULT_CREDITS_PER_USD)))
    except (TypeError, ValueError):
        return DEFAULT_CREDITS_PER_USD


def packs(db: Session) -> list[dict]:
    rows = platform.get_setting(db, "billing.credit_packs") or DEFAULT_PACKS
    out = []
    for index, row in enumerate(rows if isinstance(rows, list) else DEFAULT_PACKS):
        try:
            usd, amount = float(row["usd"]), int(row["credits"])
        except (KeyError, TypeError, ValueError):
            continue
        if usd > 0 and amount > 0:
            base = usd * credits_per_usd(db)
            out.append({"id": index, "usd": usd, "credits": amount,
                        "bonus": max(0, round(100 * (amount - base) / base)) if base else 0})
    return out


def _sub(db: Session, workspace_id: int, lock: bool = False) -> Subscription:
    query = select(Subscription).where(Subscription.workspace_id == workspace_id)
    sub = db.scalar(query.with_for_update() if lock else query)
    if sub is None:
        from app.modules.workspaces.models import Workspace

        from .service import ensure_subscription
        sub = ensure_subscription(db, db.get(Workspace, workspace_id))
    return sub


def balance(db: Session, workspace_id: int) -> float:
    return round(float(_sub(db, workspace_id).credit_balance or 0.0), 2)


def add(db: Session, workspace_id: int, kind: str, amount: float, *, ref: str | None = None, note: str | None = None,
        paid: float | None = None, currency: str | None = None, user_id: int | None = None) -> CreditTransaction:
    if kind not in KINDS:
        raise AppError(_("Unknown credit operation."), code="bad_credit_kind")
    sub = _sub(db, workspace_id, lock=True)
    sub.credit_balance = round(float(sub.credit_balance or 0.0) + float(amount), 4)
    row = CreditTransaction(workspace_id=workspace_id, kind=kind, credits=round(float(amount), 4),
                            balance_after=sub.credit_balance, ref=(ref or None) and ref[:160],
                            note=(note or None) and note[:300], amount_paid=paid, currency=currency, user_id=user_id)
    db.add(row)
    db.flush()
    return row


def already(db: Session, ref: str) -> bool:
    return db.scalar(select(CreditTransaction.id).where(CreditTransaction.ref == ref)) is not None


def available(db: Session, workspace_id: int) -> dict:
    """The plan's AI allowance this month and the bought credits, in $ and credits."""
    from . import limits
    from .service import billing_state
    limit = billing_state(db, workspace_id).limits.get("ai_credits")
    used = limits.ai_spend_month(db, workspace_id)
    cpu = credits_per_usd(db)
    left = None if limit is None else max(float(limit) - used, 0.0)
    bal = balance(db, workspace_id)
    return {"included": limit, "included_used": round(used, 4), "included_left": None if left is None else round(left, 4),
            "balance": bal, "balance_usd": round(bal / cpu, 4), "credits_per_usd": cpu,
            "available_usd": None if left is None else round(left + max(bal, 0) / cpu, 4)}


def need_from_balance(db: Session, workspace_id: int, amount: float, used: float, limit: float | None) -> float:
    """$ that must come from the bought credits for a run of ``amount`` $."""
    if limit is None:
        return 0.0
    return max(float(amount) - max(float(limit) - used, 0.0), 0.0)


def charge_usage(db: Session, usage) -> None:
    """Take from the bought credits what a platform-paid call cost beyond the plan's monthly allowance."""
    from . import limits
    from .service import billing_state
    price = float(usage.price or 0.0)
    if price <= 0:
        return
    limit = billing_state(db, usage.workspace_id).limits.get("ai_credits")
    if limit is None:
        return
    used_before = limits.ai_spend_month(db, usage.workspace_id) - price
    overflow = need_from_balance(db, usage.workspace_id, price, used_before, limit)
    if overflow > 0:
        add(db, usage.workspace_id, "usage", -overflow * credits_per_usd(db), ref="usage:%s" % usage.id,
            note=(usage.purpose or usage.model_name or "")[:300], user_id=usage.user_id)


def history(db: Session, workspace_id: int, limit: int = 50) -> list[CreditTransaction]:
    return list(db.scalars(select(CreditTransaction).where(CreditTransaction.workspace_id == workspace_id)
                           .order_by(CreditTransaction.id.desc()).limit(limit)))
