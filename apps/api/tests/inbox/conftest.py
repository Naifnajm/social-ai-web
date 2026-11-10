"""Fixtures of the inbox tests."""
import pytest

from .helpers import InboxEnv


@pytest.fixture()
def ib(db, auth, mock_http, monkeypatch):
    # background jobs (session_scope) must use the test transaction too: conftest only patches core.db
    from app.core import db as core_db
    from app.core import jobs
    monkeypatch.setattr(jobs, "SessionLocal", core_db.SessionLocal)
    return InboxEnv(db, auth, mock_http, monkeypatch)
