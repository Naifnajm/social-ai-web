"""Download a file from a URL someone gave us, safely (server-side request forgery protection).

* https only, no user:password in the URL;
* every address the host resolves to must be public (no loopback, private, link-local, carrier-grade NAT, reserved,
  multicast, or IPv4-mapped forms of those) — checked again after each redirect (at most 3);
* the connection goes to the address that was checked (the TLS certificate is still verified for the host name),
  so a DNS answer that changes between the check and the request cannot reach an internal address;
* size and time limits; the body is read in chunks and abandoned past the limit.

When the server must go through an outbound HTTP proxy (``HTTPS_PROXY``), the proxy makes the connection; the
address check still runs first.

    content, mimetype, final_url = fetch_public("https://example.com/a.jpg", max_bytes=20 * 1024 * 1024)
"""
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse

from app.core.errors import AppError
from app.core.i18n import _

TIMEOUT = 15
MAX_REDIRECTS = 3


class FetchError(AppError):
    pass


def _blocked() -> FetchError:
    return FetchError(_("This address is not allowed. Use a public https:// address."), code="bad_url")


def is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def check_url(url: str) -> tuple[str, int, list[str]]:
    """``(host, port, public addresses)`` of ``url``, or ``FetchError`` when it may not be fetched."""
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise _blocked()
    host = parsed.hostname
    port = parsed.port or 443
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)})
    except (OSError, UnicodeError):
        raise FetchError(_("This address could not be found."), code="bad_url") from None
    if not addresses or not all(is_public_ip(a) for a in addresses):
        raise _blocked()
    return host, port, addresses


def _proxy() -> str | None:
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")


def _open(url: str, host: str, port: int, address: str, headers: dict):
    """An urllib3 response (not preloaded) for ``url``, connected to ``address``."""
    import urllib3

    parsed = urlparse(url)
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    timeout = urllib3.Timeout(connect=5, read=TIMEOUT)
    if _proxy():
        manager = urllib3.ProxyManager(_proxy(), timeout=timeout, cert_reqs="CERT_REQUIRED")
        return manager.request("GET", url, headers=headers, redirect=False, preload_content=False, retries=False)
    pool = urllib3.HTTPSConnectionPool(address, port=port, server_hostname=host, assert_hostname=host,
                                       cert_reqs="CERT_REQUIRED", timeout=timeout, retries=False, maxsize=1)
    return pool.urlopen("GET", path, headers={**headers, "Host": host if port == 443 else f"{host}:{port}"},
                        redirect=False, preload_content=False, retries=False)


def fetch_public(url: str, *, max_bytes: int, accept: str = "*/*") -> tuple[bytes, str, str]:
    """``(content, mimetype, final url)``. Raises ``FetchError`` (code bad_url / too_large / fetch_failed)."""
    headers = {"User-Agent": "StravicaSocial/1.0 (+media import)", "Accept": accept}
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        host, port, addresses = check_url(current)
        try:
            response = _open(current, host, port, addresses[0], headers)
        except FetchError:
            raise
        except Exception:
            raise FetchError(_("The file could not be downloaded from this address."), code="fetch_failed") from None
        try:
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise FetchError(_("The file could not be downloaded from this address."), code="fetch_failed")
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise FetchError(_("The address answered with an error ({status}).", status=response.status),
                                 code="fetch_failed")
            length = response.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise FetchError(_("The file is too large (max {mb} MB).", mb=max_bytes // (1024 * 1024)),
                                 code="too_large")
            chunks, total = [], 0
            for chunk in response.stream(64 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError(_("The file is too large (max {mb} MB).", mb=max_bytes // (1024 * 1024)),
                                     code="too_large")
                chunks.append(chunk)
            mimetype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return b"".join(chunks), mimetype, current
        finally:
            response.release_conn()
    raise FetchError(_("Too many redirects."), code="fetch_failed")
