"""Our OAuth 2.1 authorization server for AI assistants and MCP clients (not the social-network OAuth at /oauth/…).

Endpoints (mounted at the root by ``public.py``):

* ``GET  /.well-known/oauth-authorization-server``   — RFC 8414 metadata
* ``GET  /.well-known/oauth-protected-resource[/mcp]`` — RFC 9728 metadata of the MCP server
* ``POST /oauth2/register``  — RFC 7591 dynamic client registration (public clients + PKCE; a client may also ask for
  a secret with ``client_secret_post`` / ``client_secret_basic``)
* ``GET  /oauth2/authorize`` — validates the request and sends the browser to the consent page of the web app
* ``POST /oauth2/token``     — ``authorization_code`` (PKCE S256) and ``refresh_token`` (rotating) grants
* ``POST /oauth2/revoke``    — RFC 7009

Clients may also identify themselves with a client ID metadata document: ``client_id`` is then an https URL whose
JSON describes the client (fetched safely, cached a day). Every authorization response carries ``iss`` (RFC 9207).
The decision itself (approve / deny, workspace, scopes) is taken by the signed-in user through
``POST /api/connect/authorize/decision`` (``router.py``).
"""
import base64
import hmac
import json
import logging
import re
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, utcnow
from app.core.hardening import rate_limit
from app.core.i18n import clean_locale, pick_locale

from . import auth
from .auth import SCOPES, aware, sha256
from .models import OAuthClient, OAuthCode, OAuthGrant, OAuthRequest, OAuthToken

router = APIRouter(tags=["connect"], include_in_schema=False)
_logger = logging.getLogger(__name__)

AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")
CHALLENGE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
VERIFIER = CHALLENGE
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1")
CIMD_MAX_BYTES = 64 * 1024
CIMD_TTL_HOURS = 24
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class OAuthFail(Exception):
    """An OAuth error answered as ``{"error", "error_description"}`` (RFC 6749 §5.2)."""

    def __init__(self, error: str, description: str = "", status: int = 400):
        super().__init__(description or error)
        self.error, self.description, self.status = error, description, status

    def response(self) -> JSONResponse:
        headers = dict(NO_STORE)
        if self.status == 401:
            headers["WWW-Authenticate"] = 'Basic realm="oauth2"'
        return JSONResponse({"error": self.error, "error_description": self.description}, status_code=self.status,
                            headers=headers)


# ------------------------------------------------------------------------------------------------- metadata
def authorization_server_metadata() -> dict:
    base = auth.issuer()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth2/authorize",
        "token_endpoint": f"{base}/oauth2/token",
        "registration_endpoint": f"{base}/oauth2/register",
        "revocation_endpoint": f"{base}/oauth2/revoke",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": list(AUTH_METHODS),
        "revocation_endpoint_auth_methods_supported": list(AUTH_METHODS),
        "scopes_supported": list(SCOPES),
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": settings.web_url.rstrip("/") + "/settings/connect",
    }


def protected_resource_metadata() -> dict:
    return {
        "resource": auth.mcp_url(),
        "authorization_servers": [auth.issuer()],
        "scopes_supported": list(SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": settings.app_name,
        "resource_documentation": settings.web_url.rstrip("/") + "/settings/connect",
    }


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/mcp")
def as_metadata():
    return JSONResponse(authorization_server_metadata(), headers={"Cache-Control": "public, max-age=3600"})


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def pr_metadata():
    return JSONResponse(protected_resource_metadata(), headers={"Cache-Control": "public, max-age=3600"})


# ------------------------------------------------------------------------------------------------- redirect URIs
def valid_redirect_uri(uri: str) -> bool:
    """https anywhere, or http on a loopback address (native apps, RFC 8252). No fragment, no user info."""
    if not isinstance(uri, str) or len(uri) > 1000:
        return False
    parsed = urlparse(uri)
    if parsed.fragment or parsed.username or parsed.password or not parsed.hostname:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS


def _is_loopback(uri: str) -> bool:
    parsed = urlparse(uri)
    return parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS


def redirect_matches(registered: list[str], uri: str) -> bool:
    """Exact match; loopback redirects match on any port (RFC 8252 §7.3, also for ``localhost``)."""
    if uri in (registered or []):
        return True
    if not _is_loopback(uri):
        return False
    wanted = urlparse(uri)
    for item in registered or []:
        if not _is_loopback(item):
            continue
        reg = urlparse(item)
        if (reg.hostname, reg.path or "/", reg.query) == (wanted.hostname, wanted.path or "/", wanted.query):
            return True
    return False


def only_loopback(client: OAuthClient) -> bool:
    return bool(client.redirect_uris) and all(_is_loopback(u) for u in client.redirect_uris)


# ------------------------------------------------------------------------------------------------- clients
def _client_metadata_document(db: Session, client_id: str) -> OAuthClient | None:
    """Read (or refresh) a client described by a client ID metadata document at ``client_id``."""
    from datetime import timedelta

    from .fetch import FetchError, fetch_public

    client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
    if client and client.fetched_at and aware(client.fetched_at) > utcnow() - timedelta(hours=CIMD_TTL_HOURS):
        return client
    parsed = urlparse(client_id)
    if parsed.scheme != "https" or not parsed.path or parsed.path == "/" or parsed.fragment:
        return None
    try:
        content, _mimetype, _final = fetch_public(client_id, max_bytes=CIMD_MAX_BYTES, accept="application/json")
        doc = json.loads(content)
    except (FetchError, ValueError) as exc:
        _logger.info("client metadata document %s unusable: %s", client_id, exc)
        return client  # keep a cached copy when the host is down
    if not isinstance(doc, dict) or doc.get("client_id") != client_id:
        return None
    uris = doc.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(valid_redirect_uri(u) for u in uris):
        return None
    method = doc.get("token_endpoint_auth_method") or "none"
    if method != "none":
        return None  # we accept metadata-document clients as public clients only
    name = doc.get("client_name") if isinstance(doc.get("client_name"), str) else ""
    client = client or OAuthClient(client_id=client_id, kind="cimd")
    client.client_name = (name.strip() or parsed.hostname or "app")[:200]
    client.redirect_uris = uris[:20]
    client.client_uri = doc.get("client_uri") if isinstance(doc.get("client_uri"), str) else None
    client.logo_uri = doc.get("logo_uri") if isinstance(doc.get("logo_uri"), str) else None
    client.token_endpoint_auth_method = "none"
    client.fetched_at = utcnow()
    db.add(client)
    db.flush()
    return client


def get_client(db: Session, client_id: str | None) -> OAuthClient | None:
    if not client_id or len(client_id) > 500:
        return None
    if client_id.startswith("https://"):
        return _client_metadata_document(db, client_id)
    return db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id, OAuthClient.kind == "dcr"))


def client_display_host(client: OAuthClient) -> str | None:
    """For metadata-document clients: the host that vouches for the name (shown on the consent page)."""
    return urlparse(client.client_id).hostname if client.kind == "cimd" else None


@router.post("/oauth2/register", status_code=201, dependencies=[Depends(rate_limit("oauth_register", 30, 3600))])
async def register(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return OAuthFail("invalid_client_metadata", "The body must be a JSON object.").response()
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not uris or len(uris) > 10:
        return OAuthFail("invalid_redirect_uri", "redirect_uris must list 1 to 10 URIs.").response()
    bad = [u for u in uris if not valid_redirect_uri(u)]
    if bad:
        return OAuthFail("invalid_redirect_uri", "Redirect URIs must use https, or http on a loopback address."
                         ).response()
    grant_types = body.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grant_types, list) or not set(grant_types) <= {"authorization_code", "refresh_token"}:
        return OAuthFail("invalid_client_metadata", "Only authorization_code and refresh_token are supported."
                         ).response()
    response_types = body.get("response_types") or ["code"]
    if response_types != ["code"]:
        return OAuthFail("invalid_client_metadata", "Only the code response type is supported.").response()
    method = body.get("token_endpoint_auth_method") or "none"
    if method not in AUTH_METHODS:
        return OAuthFail("invalid_client_metadata", "Unsupported token_endpoint_auth_method.").response()
    name = body.get("client_name") if isinstance(body.get("client_name"), str) else ""
    name = re.sub(r"\s+", " ", name).strip()[:200] or urlparse(uris[0]).hostname or "MCP client"
    client_uri = body.get("client_uri") if isinstance(body.get("client_uri"), str) else None
    client = OAuthClient(client_id="mcp_" + auth.new_secret(18), client_name=name, redirect_uris=uris, kind="dcr",
                         token_endpoint_auth_method=method, client_uri=(client_uri or "")[:500] or None)
    secret = None
    if method != "none":
        secret = auth.new_secret(32)
        client.client_secret_hash = sha256(secret)
    db.add(client)
    db.flush()
    out = {"client_id": client.client_id, "client_id_issued_at": int(client.created_at.timestamp())
           if client.created_at else int(utcnow().timestamp()), "client_name": client.client_name,
           "redirect_uris": uris, "grant_types": grant_types, "response_types": ["code"],
           "token_endpoint_auth_method": method, "scope": " ".join(SCOPES)}
    if client_uri:
        out["client_uri"] = client.client_uri
    if secret:
        out["client_secret"] = secret
        out["client_secret_expires_at"] = 0
    return JSONResponse(out, status_code=201, headers=NO_STORE)


# ------------------------------------------------------------------------------------------------- authorize
def _redirect_with(uri: str, **params) -> RedirectResponse:
    params = {k: v for k, v in params.items() if v is not None}
    params["iss"] = auth.issuer()
    sep = "&" if urlparse(uri).query else "?"
    return RedirectResponse(uri + sep + urlencode(params), status_code=302)


def _consent_url(locale: str, **params) -> str:
    return f"{settings.web_url.rstrip('/')}/{locale}/connect/authorize?{urlencode(params)}"


def _locale(request: Request) -> str:
    wanted = (request.query_params.get("ui_locales") or "").split()
    for code in wanted:
        if clean_locale(code[:2]) == code[:2]:
            return code[:2]
    return pick_locale(request.headers.get("accept-language"))


def same_resource(value: str | None) -> bool:
    return (value or "").rstrip("/") == auth.mcp_url()


@router.get("/oauth2/authorize")
def authorize(request: Request, db: Session = Depends(get_db)):
    q = request.query_params
    locale = _locale(request)
    client = get_client(db, q.get("client_id"))
    redirect_uri = q.get("redirect_uri") or ""
    # Without a known client and a registered redirect URI we must not redirect anywhere: show the error page.
    if not client:
        return RedirectResponse(_consent_url(locale, error="invalid_client"), status_code=302)
    if not redirect_uri and len(client.redirect_uris or []) == 1:
        redirect_uri = client.redirect_uris[0]
    if not redirect_matches(client.redirect_uris, redirect_uri):
        return RedirectResponse(_consent_url(locale, error="invalid_redirect_uri"), status_code=302)
    state = q.get("state")
    if state is not None and len(state) > 1000:
        return _redirect_with(redirect_uri, error="invalid_request", error_description="state is too long")

    def fail(error: str, description: str):
        return _redirect_with(redirect_uri, error=error, error_description=description, state=state)

    if q.get("response_type") != "code":
        return fail("unsupported_response_type", "Only response_type=code is supported.")
    challenge = q.get("code_challenge") or ""
    if q.get("code_challenge_method") != "S256" or not CHALLENGE.match(challenge):
        return fail("invalid_request", "PKCE with code_challenge_method=S256 is required.")
    raw_scope = q.get("scope")
    requested = auth.clean_scopes(raw_scope)
    if raw_scope and raw_scope.split() and not requested and not set(raw_scope.split()) <= set(auth.IGNORED_SCOPES):
        return fail("invalid_scope", "Supported scopes: " + " ".join(SCOPES))
    resource = q.get("resource")
    if resource and not same_resource(resource):
        return fail("invalid_target", "Unknown resource.")
    if requested:
        offered = auth.clean_scopes(["read", *requested])
        preselected = [s for s in offered if s in auth.SAFE_DEFAULT and (s in requested or s == "read")]
    else:
        offered = list(SCOPES)
        preselected = list(auth.DEFAULT_SCOPES)
    secret = auth.new_secret(24)
    db.add(OAuthRequest(request_hash=sha256(secret), client_pk=client.id, redirect_uri=redirect_uri, state=state,
                        code_challenge=challenge, scopes=offered, preselected=preselected,
                        resource=auth.mcp_url(), expires_at=utcnow() + auth.REQUEST_TTL))
    db.flush()
    return RedirectResponse(_consent_url(locale, request=secret), status_code=302)


def find_request(db: Session, secret: str | None) -> OAuthRequest | None:
    if not secret or len(secret) > 200:
        return None
    row = db.scalar(select(OAuthRequest).where(OAuthRequest.request_hash == sha256(secret)))
    if not row or row.decided_at or aware(row.expires_at) <= utcnow():
        return None
    return row


def decide(db: Session, req: OAuthRequest, *, user_id: int, workspace_id: int | None, scopes: list[str],
           approve: bool) -> str:
    """Approve (a code for a new grant) or deny the request; returns the URL to send the browser to."""
    req.decided_at = utcnow()
    if not approve:
        db.flush()
        return _redirect_with(req.redirect_uri, error="access_denied",
                              error_description="The user denied access.", state=req.state).headers["location"]
    grant = OAuthGrant(client_pk=req.client_pk, user_id=user_id, workspace_id=workspace_id, scopes=scopes,
                       resource=req.resource)
    db.add(grant)
    db.flush()
    code = auth.new_secret(32)
    db.add(OAuthCode(code_hash=sha256(code), grant_id=grant.id, redirect_uri=req.redirect_uri,
                     code_challenge=req.code_challenge, expires_at=utcnow() + auth.CODE_TTL))
    db.flush()
    return _redirect_with(req.redirect_uri, code=code, state=req.state).headers["location"]


# ------------------------------------------------------------------------------------------------- token
async def _form(request: Request) -> dict:
    kind = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if kind == "application/json":
        try:
            body = await request.json()
            return {k: str(v) for k, v in body.items()} if isinstance(body, dict) else {}
        except ValueError:
            return {}
    form = await request.form()
    return {k: v for k, v in form.items() if isinstance(v, str)}


def _client_credentials(request: Request, form: dict) -> tuple[str | None, str | None]:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("basic "):
        try:
            from urllib.parse import unquote
            decoded = base64.b64decode(header[6:].strip()).decode()
            client_id, _sep, secret = decoded.partition(":")
            return unquote(client_id), unquote(secret)
        except (ValueError, UnicodeDecodeError):
            raise OAuthFail("invalid_client", "Malformed client credentials.", 401) from None
    return form.get("client_id"), form.get("client_secret")


def authenticate_client(db: Session, request: Request, form: dict) -> OAuthClient:
    client_id, secret = _client_credentials(request, form)
    client = get_client(db, client_id)
    if not client:
        raise OAuthFail("invalid_client", "Unknown client.", 401)
    if client.token_endpoint_auth_method != "none":
        if not secret or not client.client_secret_hash or not hmac.compare_digest(sha256(secret),
                                                                                   client.client_secret_hash):
            raise OAuthFail("invalid_client", "Client authentication failed.", 401)
    return client


def pkce_ok(verifier: str | None, challenge: str) -> bool:
    if not verifier or not VERIFIER.match(verifier):
        return False
    import hashlib
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(digest, challenge)


def _code_grant(db: Session, client: OAuthClient, form: dict) -> dict:
    # locked: two concurrent redemptions of one code cannot both pass the used_at check
    code = db.scalar(select(OAuthCode).where(OAuthCode.code_hash == sha256(form.get("code") or "")).with_for_update())
    if not code:
        raise OAuthFail("invalid_grant", "Unknown authorization code.")
    grant = db.get(OAuthGrant, code.grant_id)
    if code.used_at:
        # A code used twice: someone may have stolen it. End everything issued from it (RFC 6749 §4.1.2).
        if grant:
            auth.revoke_grant(db, grant)
        raise OAuthFail("invalid_grant", "This authorization code was already used.")
    if not grant or grant.client_pk != client.id or grant.revoked_at:
        raise OAuthFail("invalid_grant", "This authorization code was not issued to this client.")
    if aware(code.expires_at) <= utcnow():
        raise OAuthFail("invalid_grant", "The authorization code has expired.")
    if form.get("redirect_uri") and form.get("redirect_uri") != code.redirect_uri:
        raise OAuthFail("invalid_grant", "redirect_uri does not match the authorization request.")
    if not pkce_ok(form.get("code_verifier"), code.code_challenge):
        raise OAuthFail("invalid_grant", "PKCE verification failed.")
    if form.get("resource") and not same_resource(form.get("resource")):
        raise OAuthFail("invalid_target", "Unknown resource.")
    code.used_at = utcnow()
    return auth.issue_tokens(db, grant, list(grant.scopes or []))


def _refresh_grant(db: Session, client: OAuthClient, form: dict) -> dict:
    row = db.scalar(select(OAuthToken).where(OAuthToken.token_hash == sha256(form.get("refresh_token") or ""),
                                             OAuthToken.kind == "refresh").with_for_update())
    if not row:
        raise OAuthFail("invalid_grant", "Unknown refresh token.")
    grant = row.grant
    if not grant or grant.client_pk != client.id:
        raise OAuthFail("invalid_grant", "This refresh token was not issued to this client.")
    if row.used_at:
        # A rotated refresh token came back: it was copied. Disconnect the app (OAuth 2.1 §4.3.1).
        auth.revoke_grant(db, grant)
        raise OAuthFail("invalid_grant", "This refresh token was already used.")
    if row.revoked_at or grant.revoked_at or aware(row.expires_at) <= utcnow():
        raise OAuthFail("invalid_grant", "The refresh token has expired or was revoked.")
    if form.get("resource") and not same_resource(form.get("resource")):
        raise OAuthFail("invalid_target", "Unknown resource.")
    scopes = list(row.scopes or [])
    if form.get("scope"):
        narrower = auth.clean_scopes(form["scope"])
        if not narrower or not set(narrower) <= set(scopes):
            raise OAuthFail("invalid_scope", "A refresh can only keep or narrow the granted scopes.")
        scopes = narrower
    row.used_at = utcnow()
    # the access tokens of the previous pair stay valid until they expire (at most an hour)
    return auth.issue_tokens(db, grant, scopes)


@router.post("/oauth2/token")
async def token(request: Request, db: Session = Depends(get_db)):
    form = await _form(request)
    try:
        client = authenticate_client(db, request, form)
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            body = _code_grant(db, client, form)
        elif grant_type == "refresh_token":
            body = _refresh_grant(db, client, form)
        else:
            raise OAuthFail("unsupported_grant_type", "Use authorization_code or refresh_token.")
    except OAuthFail as fail:
        return fail.response()  # returned, not raised: revocations made while detecting a replay are kept
    return JSONResponse(body, headers=NO_STORE)


@router.post("/oauth2/revoke")
async def revoke(request: Request, db: Session = Depends(get_db)):
    form = await _form(request)
    value = form.get("token") or ""
    row = db.scalar(select(OAuthToken).where(OAuthToken.token_hash == sha256(value))) if value else None
    if row and row.grant:
        client_id, _secret = _client_credentials(request, form)
        if not client_id or (row.grant.client and row.grant.client.client_id == client_id):
            auth.revoke_grant(db, row.grant)
    return JSONResponse({}, headers=NO_STORE)  # always 200, even for unknown tokens (RFC 7009 §2.2)
