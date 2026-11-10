"""Periodic sending of the scheduled reports."""
import logging

from app.core.jobs import periodic, session_scope

from . import service

_logger = logging.getLogger(__name__)


@periodic(seconds=600)
def send_due_reports():
    with session_scope() as db:
        sent = service.send_due(db)
    if sent:
        _logger.info("reports: %s scheduled report(s) sent", sent)
