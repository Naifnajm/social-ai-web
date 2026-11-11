"""HTTP hardening: request rate limits, response security headers, and safe outbound URLs.

    @router.post("/login", dependencies=[Depends(rate_limit("login", 10, 300))])    # 10 tries per 5 minutes per IP
    ensure_public_url(url)                      # refuse http://, localhost and private networks (server-side requests)
    FileResponse(path, headers=UPLOAD_HEADERS)  # an uploaded file can never run script when opened directly

Rate limits count in Redis and let the request through when Redis is down (availability over strictness).
"""
import ipaddress
import socket
import time
from urllib.parse import urlparse

from fastapi import Request

from app.core.config import settings
from app.core.errors import AppError
from app.core.i18n import _

# Tests switch this on only where they test the limiter (every test client shares one address).
enabled = not settings.is_test
_memory: dict[str, tuple[int, float]] = {}

# For user uploads served from our own origin: no script, no plugins, no framing, no MIME sniffing.
UPLOAD_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; media-src 'self'; sandbox",
    "X-Content-Type-Options": "nosniff",
}
API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def first_use(key: str, ttl: int) -> bool:
    """True the first time ``key`` is seen within ``ttl`` seconds (single-use sign-in challenges)."""
    if settings.is_test:
        now = time.monotonic()
        seen = _memory.get(f"once:{key}")
        if seen and seen[1] > now:
            return False
        _memory[f"once:{key}"] = (1, now + ttl)
        return True
    try:
        from redis import Redis
        redis = Redis.from_url(settings.redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
        return bool(redis.set(f"sai:once:{key}", 1, nx=True, ex=ttl))
    except Exception:  # noqa: BLE001 - the challenge still expires on its own
        return True


def _hit(key: str, window: int) -> int:
    """Count one request under ``key`` and return the count inside the current window."""
    if settings.is_test:
        count, until = _memory.get(key, (0, 0.0))
        now = time.monotonic()
        count, until = (1, now + window) if now >= until else (count + 1, until)
        _memory[key] = (count, until)
        return count
    try:
        from redis import Redis
        redis = Redis.from_url(settings.redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, window)
        return int(count)
    except Exception:  # noqa: BLE001 - never block sign-in because the counter is unavailable
        return 0


def rate_limit(scope: str, limit: int, window: int):
    """FastAPI dependency: at most ``limit`` requests per ``window`` seconds per client address."""
    def check(request: Request) -> None:
        if not enabled:
            return
        if _hit(f"sai:rl:{scope}:{client_ip(request)}", window) > limit:
            raise AppError(_("Too many attempts. Wait a few minutes and try again."), code="rate_limited", status_code=429)
    return check


def ensure_public_url(url: str) -> str:
    """Return ``url`` when the server may call it: https, and a host that is not on a private network."""
    if settings.env != "prod":
        return url  # local development talks to local model servers
    parsed = urlparse(url or "")
    host = parsed.hostname or ""
    bad = AppError(_("This address is not allowed. Use a public https:// address."), code="bad_url")
    if parsed.scheme != "https" or not host:
        raise bad
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        raise bad from None
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified):
            raise bad
    return url
