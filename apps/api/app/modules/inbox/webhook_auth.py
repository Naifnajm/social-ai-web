"""Signature checks for incoming webhooks (Meta, Twilio, Telegram)."""
import base64
import hashlib
import hmac


def meta_signature(app_secret: str, body: bytes) -> str:
    """Value Meta sends in ``X-Hub-Signature-256`` for ``body``."""
    digest = hmac.new((app_secret or "").encode(), body or b"", hashlib.sha256).hexdigest()
    return "sha256=%s" % digest


def meta_signature_ok(app_secret: str | None, body: bytes, header: str | None) -> bool:
    if not app_secret or not header:
        return False
    return hmac.compare_digest(meta_signature(app_secret, body), header.strip())


def twilio_signature(auth_token: str, url: str, params: dict) -> str:
    """Twilio: base64(HMAC-SHA1(auth token, url + sorted POST params concatenated))."""
    data = url + "".join("%s%s" % (key, params[key]) for key in sorted(params))
    digest = hmac.new((auth_token or "").encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def twilio_signature_ok(auth_token: str | None, urls, params: dict, header: str | None) -> bool:
    """``urls``: candidate public URLs of the webhook (behind a proxy the scheme/host may differ)."""
    if not auth_token or not header:
        return False
    return any(hmac.compare_digest(twilio_signature(auth_token, url, params), header.strip()) for url in urls if url)


def secret_ok(expected: str | None, given: str | None) -> bool:
    return bool(expected) and bool(given) and hmac.compare_digest(str(expected), str(given))
