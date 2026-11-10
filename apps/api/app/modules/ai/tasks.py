"""Background work of the AI feature: polling running media jobs and refreshing provider balances."""
import logging

from sqlalchemy import select

from app.core.http import ApiError
from app.core.jobs import periodic, session_scope

from . import media
from . import providers as prov
from .balance import SUPPORTED as BALANCE_TYPES
from .models import AIProvider

_logger = logging.getLogger(__name__)


@periodic(seconds=20)
def poll_media_jobs() -> int:
    """Check running video (and slow) generations whose next check is due; finished ones call their callback."""
    with session_scope() as db:
        return media.poll_due(db, limit=30)


@periodic(seconds=6 * 3600)
def refresh_balances() -> None:
    with session_scope() as db:
        providers = db.scalars(select(AIProvider).where(AIProvider.active.is_(True),
                                                        AIProvider.provider_type.in_(BALANCE_TYPES)))
        for provider in providers:
            if not provider.api_key:
                continue
            try:
                prov.refresh_balance(db, provider)
            except ApiError:
                _logger.info("balance of AI provider %s could not be read", provider.id)
