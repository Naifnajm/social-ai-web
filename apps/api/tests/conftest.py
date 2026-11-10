"""Test fixtures: a clean PostgreSQL schema per session, a transaction per test, HTTP client helpers.

    def test_something(client, auth):            # auth = signed-up owner with a workspace
        r = client.get("/api/workspace", headers=auth.headers)
"""
import os

os.environ.setdefault("SAI_ENV", "test")
os.environ.setdefault("SAI_DATABASE_URL", "postgresql+psycopg://root:odoo@localhost:5432/stravica_test")
os.environ.setdefault("SAI_JOBS_SYNC", "true")
os.environ.setdefault("SAI_STORAGE_DIR", "/tmp/stravica-test-storage")

from dataclasses import dataclass  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core import db as core_db  # noqa: E402
from app.core import jobs as core_jobs  # noqa: E402
from app.core import registry  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    registry.load_models()
    core_db.Base.metadata.drop_all(core_db.engine)
    core_db.Base.metadata.create_all(core_db.engine)
    yield


@pytest.fixture()
def db():
    """A session bound to an outer transaction rolled back after the test (also used by the app)."""
    connection = core_db.engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)

    def override():
        yield session
        session.flush()

    app.dependency_overrides[core_db.get_db] = override
    original, original_jobs = core_db.SessionLocal, core_jobs.SessionLocal
    core_db.SessionLocal = core_jobs.SessionLocal = lambda: _NoCloseSession(session)  # jobs / logs share the test transaction
    try:
        yield session
    finally:
        core_db.SessionLocal, core_jobs.SessionLocal = original, original_jobs
        app.dependency_overrides.pop(core_db.get_db, None)
        session.close()
        outer.rollback()
        connection.close()


class _NoCloseSession:
    """Wraps the test session for code that opens its own session (session_scope, API logs)."""

    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def commit(self):
        self._s.flush()

    def rollback(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def client(db):
    with TestClient(app) as test_client:
        yield test_client


@dataclass
class Auth:
    user_id: int
    workspace_id: int
    token: str
    email: str

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "X-Workspace": str(self.workspace_id)}


def signup(client, email="owner@example.com", name="Owner", workspace="Acme", password="secret123") -> Auth:
    r = client.post("/api/auth/signup", json={"name": name, "email": email, "password": password,
                                               "workspace_name": workspace, "locale": "en"})
    assert r.status_code == 201, r.text
    data = r.json()
    return Auth(user_id=data["me"]["user"]["id"], workspace_id=data["me"]["current_workspace_id"],
                token=data["access_token"], email=email)


@pytest.fixture()
def auth(client) -> Auth:
    return signup(client)


@pytest.fixture()
def mock_http(monkeypatch):
    """Patch every outgoing HTTP request: ``mock_http(handler)`` where handler(method, url, kwargs) -> Response."""
    import json as _json

    import requests
    calls = []

    def install(handler):
        def fake_request(session, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return handler(method, url, kwargs)
        monkeypatch.setattr(requests.Session, "request", fake_request)
        return calls

    install.response = lambda status=200, body=None, headers=None: _response(status, body, headers, _json)
    return install


def _response(status, body, headers, _json):
    import requests
    response = requests.Response()
    response.status_code = status
    if isinstance(body, (bytes, bytearray)):
        response._content = bytes(body)
    else:
        response._content = _json.dumps(body if body is not None else {}).encode()
        response.headers["Content-Type"] = "application/json"
    response.headers.update(headers or {})
    response.reason = "OK" if status < 400 else "Error"
    return response
