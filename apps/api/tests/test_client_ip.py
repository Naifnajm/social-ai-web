"""Rate limits key on an address the client cannot choose."""
from starlette.requests import Request

from app.core.hardening import client_ip


def _request(headers: dict, host: str = "10.0.0.5") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (host, 1234)})


def test_forged_forwarded_for_is_ignored():
    # nginx: X-Real-IP is the real peer, X-Forwarded-For starts with what the client typed
    assert client_ip(_request({"X-Real-IP": "203.0.113.9", "X-Forwarded-For": "1.2.3.4, 203.0.113.9"})) == "203.0.113.9"
    # a proxy that only appends X-Forwarded-For: the last hop is the real one
    assert client_ip(_request({"X-Forwarded-For": "1.2.3.4, 198.51.100.7"})) == "198.51.100.7"
    assert client_ip(_request({})) == "10.0.0.5"


def test_changing_the_forged_address_does_not_reset_the_login_limit(client, monkeypatch):
    from app.core import hardening
    monkeypatch.setattr(hardening, "enabled", True)
    hardening._memory.clear()
    statuses = []
    for i in range(12):
        r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-123"},
                        headers={"X-Forwarded-For": f"9.9.9.{i}, 203.0.113.9", "X-Real-IP": "203.0.113.9"})
        statuses.append(r.status_code)
    assert 429 in statuses  # the limit (10 per 5 min) still applies although each request "came" from a new IP
