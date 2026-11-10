"""Plan limits for other features — CONTRACT (the billing builder implements the bodies).

    from app.modules.billing import limits
    limits.check(db, ws_id, "social_accounts")      # raises LimitReached (HTTP 402) when the plan is full
    limits.check(db, ws_id, "posts_month")
    limits.check(db, ws_id, "ai_credits", amount=0.04)   # $ of AI the platform pays for (not BYO keys)
    limits.check(db, ws_id, "members")
    limits.feature(db, ws_id, "production")         # bool: is this feature in the plan?

Until billing exists every check passes.
"""
from sqlalchemy.orm import Session


def check(db: Session, workspace_id: int, resource: str, amount: float = 1) -> None:
    return None


def feature(db: Session, workspace_id: int, name: str) -> bool:
    return True
