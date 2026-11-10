"""Shared HTTP layer for every outbound call (AI + social networks).

Every request goes through :func:`call`, which:
* applies a timeout and a small retry policy on transient errors,
* writes one ``api_logs`` row per call in its own transaction (secrets redacted),
* raises :class:`ApiError` with a readable message on failure.

    data = call("POST", url, service="social", operation="Publish post", workspace_id=ws.id,
                ref=("social_account", account.id), headers=..., json_body=...)
"""
import json
import logging
import re
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60
MAX_LOG_BODY = 8000
SECRET_KEYS = re.compile(
    r"(access_token|refresh_token|client_secret|api[_-]?key|authorization|x-api-key|"
    r"x-goog-api-key|password|code_verifier|fb_exchange_token)",
    re.IGNORECASE,
)


from .errors import ApiError  # noqa: E402  (re-exported: ``from app.core.http import ApiError``)


def _session():
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=1.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "PUT", "DELETE"}),  # never replay a POST (no duplicate posts)
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def redact(value):
    """Recursively hide secrets in dicts/lists/strings before logging."""
    if isinstance(value, dict):
        return {
            k: ("***" if SECRET_KEYS.search(str(k)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 ***", value)
        value = re.sub(r"/bot\d+:[A-Za-z0-9_-]+", "/bot***", value)
        value = re.sub(
            r"([?&](?:access_token|key|client_secret|fb_exchange_token)=)[^&\s]+", r"\1***", value
        )
    return value


def _dump(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return "<%d bytes>" % len(value)
    try:
        text = json.dumps(redact(value), ensure_ascii=False, indent=1, default=str)
    except (TypeError, ValueError):
        text = redact(str(value))
    return text[:MAX_LOG_BODY]


def extract_error(response):
    """Pull the most human-readable error message out of a provider response."""
    try:
        data = response.json()
    except ValueError:
        return (response.text or response.reason or "").strip()[:500]
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("error_user_msg") or err.get("type")
            if msg:
                return str(msg)
        if isinstance(err, str) and data.get("error_description"):
            return "%s: %s" % (err, data["error_description"])
        for key in ("message", "detail", "error_description", "description", "title"):
            if data.get(key):
                return str(data[key])
        if isinstance(data.get("errors"), list) and data["errors"]:
            first = data["errors"][0]
            if isinstance(first, dict):
                return str(first.get("message") or first.get("detail") or first)
        if isinstance(err, str):
            return err
    return json.dumps(data)[:500]


def _write_log(vals):
    """Persist a log line in its own transaction so it survives a rollback of the caller."""
    from .db import SessionLocal
    from .models import ApiLog
    try:
        with SessionLocal() as db:
            db.add(ApiLog(**vals))
            db.commit()
    except Exception:  # logging must never break the business flow
        _logger.exception("could not write API log")


def call(method, url, *, service, operation="", workspace_id=None, ref=None,
         headers=None, params=None, json_body=None, data=None, files=None,
         timeout=DEFAULT_TIMEOUT, expect_json=True, ok_statuses=None, binary=False,
         allow_redirects=True):
    """Perform an HTTP request, log it, and return the parsed body (or the response)."""
    started = time.monotonic()
    log_vals = {
        "service": service,
        "operation": operation or "%s %s" % (method.upper(), url.split("?")[0][-80:]),
        "method": method.upper(),
        "endpoint": redact(url.split("?")[0]),
        "request_body": _dump(json_body if json_body is not None else (data if not files else {"multipart": list(files)})),
        "workspace_id": workspace_id,
        "ref_model": ref[0] if ref else None,
        "ref_id": ref[1] if ref else None,
    }
    try:
        response = _session().request(
            method, url, headers=headers, params=params, json=json_body,
            data=data, files=files, timeout=timeout, allow_redirects=allow_redirects,
        )
    except requests.exceptions.Timeout:
        log_vals.update(error="Timeout", duration_ms=int((time.monotonic() - started) * 1000))
        _write_log(log_vals)
        raise ApiError("The service did not answer in time (timeout). Please try again.")
    except requests.exceptions.RequestException as exc:
        log_vals.update(error=str(exc)[:500], duration_ms=int((time.monotonic() - started) * 1000))
        _write_log(log_vals)
        raise ApiError("Could not reach the service: %s" % redact(str(exc))[:300])

    ok = response.ok if ok_statuses is None else response.status_code in ok_statuses
    log_vals.update(
        status_code=response.status_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        response_body=(("<%d bytes, %s>" % (len(response.content), response.headers.get("Content-Type", "")))
                       if binary and ok else (_dump(_safe_json(response)) if response.content else None)),
    )
    if not ok:
        message = extract_error(response)
        log_vals["error"] = message[:1000]
        _write_log(log_vals)
        raise ApiError(_friendly(response.status_code, message), response.status_code, _safe_json(response))
    _write_log(log_vals)
    if not expect_json:
        return response
    return _safe_json(response) if response.content else {}


def _safe_json(response):
    try:
        return response.json()
    except ValueError:
        return response.text[:MAX_LOG_BODY]


def _friendly(status, message):
    prefix = {
        400: "The request was rejected",
        401: "Authentication failed — the key or token is invalid or expired",
        403: "Permission denied — check the app permissions / scopes",
        404: "Not found — check the account or page ID",
        413: "The file is too large for this platform",
        422: "The content was rejected",
        429: "Rate limit reached — please wait a moment and retry",
    }.get(status, "The service returned an error (%s)" % status)
    return "%s: %s" % (prefix, message) if message else prefix
