"""Public routes of link tracking (no sign-in):

* ``GET /r/{code}``   — short link: counts the click (no bots, deduplicated) and redirects with UTM tags.
* ``GET /r/t.js?k=``  — tracking snippet for the company's website (remembers the click, reports conversions).
* ``GET /r/conv``     — conversion pixel (1×1 GIF) — ``?k=<public key>&code|utm_…&value&currency&id&kind``.
* ``POST /r/conv``    — the same as JSON (``navigator.sendBeacon``), or server-to-server with
  ``X-Stravica-Key: sk_…`` (trusted: kept even without a click reference).
"""
import base64
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.modules.workspaces.settings import get_setting

from . import service as svc
from .models import TrackedLink

router = APIRouter(tags=["public"])
_logger = logging.getLogger(__name__)

GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
NO_STORE = {"Cache-Control": "no-store, max-age=0"}
KEY_RE = re.compile(r"^pk_[A-Za-z0-9_-]{8,36}$")

SNIPPET = r"""/* Stravica Social conversion tracking */
(function (w, d) {
  var K = "__KEY__", B = "__BASE__", DAY = 864e5, KEEP = 30 * DAY;
  function q(n) { var m = new RegExp("[?&]" + n + "=([^&#]*)").exec(w.location.search); return m ? decodeURIComponent(m[1].replace(/\+/g, " ")) : ""; }
  function save(k, v) { try { w.localStorage.setItem(k, JSON.stringify({ v: v, t: Date.now() })); } catch (e) {} d.cookie = k + "=" + encodeURIComponent(v) + ";path=/;max-age=" + KEEP / 1000 + ";SameSite=Lax"; }
  function load(k) { try { var o = JSON.parse(w.localStorage.getItem(k) || "null"); if (o && Date.now() - o.t < KEEP) return o.v; } catch (e) {} var m = d.cookie.match(new RegExp("(?:^|; )" + k + "=([^;]*)")); return m ? decodeURIComponent(m[1]) : ""; }
  var ref = q("sref"); if (ref) save("sai_ref", ref);
  if (q("utm_source")) save("sai_utm", JSON.stringify({ s: q("utm_source"), m: q("utm_medium"), c: q("utm_campaign") }));
  function send(o) {
    o = o || {}; var u = {}; try { u = JSON.parse(load("sai_utm") || "{}"); } catch (e) {}
    var p = { k: K, code: load("sai_ref"), utm_source: u.s || "", utm_medium: u.m || "", utm_campaign: u.c || "",
      value: o.value || 0, currency: o.currency || "", id: o.id || "", kind: o.kind || "order" };
    if (!p.code && !p.utm_source) return false;
    var body = JSON.stringify(p);
    if (w.navigator.sendBeacon && w.navigator.sendBeacon(B + "/r/conv", body)) return true;
    var i = new Image(); i.src = B + "/r/conv?" + Object.keys(p).map(function (k) { return k + "=" + encodeURIComponent(p[k]); }).join("&");
    return true;
  }
  var queue = w.stravicaQ || [];
  w.stravica = { conversion: send };
  w.stravicaQ = { push: send };
  for (var i = 0; i < queue.length; i++) send(queue[i]);
})(window, document);
"""

NOT_FOUND_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Link not found</title><style>body{font-family:system-ui,-apple-system,Segoe UI,Tahoma,sans-serif;background:#f4f4f5;
color:#18181b;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
div{background:#fff;border-radius:20px;padding:28px 32px;box-shadow:0 10px 30px rgba(0,0,0,.08);text-align:center}
h1{font-size:18px;margin:0 0 6px}p{color:#71717a;margin:0}</style></head><body><div>
<h1>This link does not exist · هذا الرابط غير موجود</h1><p>Check the address and try again.</p></div></body></html>"""


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _float(value) -> float:
    try:
        return min(max(float(value or 0), 0.0), svc.MAX_PUBLIC_VALUE)
    except (TypeError, ValueError):
        return 0.0


def _record(db: Session, data: dict, *, trusted_workspace: int | None, source: str) -> bool:
    """Store a conversion from public input. Untrusted input needs a click code or social UTM tags."""
    data = {k: (str(v)[:200] if v is not None else "") for k, v in (data or {}).items()}
    workspace_id = trusted_workspace
    code = (data.get("code") or data.get("sref") or "").strip()[:16]
    if workspace_id is None and code:
        link = db.scalar(select(TrackedLink).where(TrackedLink.code == code))
        workspace_id = link.workspace_id if link else None
    if workspace_id is None:
        workspace_id = svc.workspace_for_key(db, (data.get("k") or "").strip())
    if workspace_id is None:
        return False
    currency = (data.get("currency") or "").strip().upper()
    occurred = None
    if trusted_workspace and data.get("occurred_at"):
        try:
            occurred = datetime.fromisoformat(data["occurred_at"].replace("Z", "+00:00"))
        except ValueError:
            occurred = None
    conversion = svc.record_conversion(
        db, workspace_id, kind=(data.get("kind") or "order").lower(), value=_float(data.get("value")),
        currency=currency if len(currency) == 3 and currency.isalpha() else None,
        external_id=data.get("id") or data.get("external_id"), code=code or None,
        utm_source=data.get("utm_source") or None, utm_medium=data.get("utm_medium") or None,
        utm_campaign=data.get("utm_campaign") or None, occurred_at=occurred, source=source,
        note=(data.get("note") or None) if trusted_workspace else None,
        require_attribution=trusted_workspace is None)
    return conversion is not None


@router.get("/r/t.js", include_in_schema=False)
def tracking_script(k: str = "", db: Session = Depends(get_db)):
    key = k if KEY_RE.match(k or "") and svc.workspace_for_key(db, k) else ""
    body = SNIPPET.replace("__KEY__", key).replace("__BASE__", settings.public_api_url.rstrip("/"))
    return Response(body, media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"})


@router.get("/r/conv", include_in_schema=False)
def conversion_pixel(request: Request, db: Session = Depends(get_db)):
    try:
        _record(db, dict(request.query_params), trusted_workspace=None, source="pixel")
    except Exception:  # a pixel never fails visibly
        _logger.exception("conversion pixel failed")
    return Response(GIF, media_type="image/gif", headers=NO_STORE)


@router.post("/r/conv", include_in_schema=False)
async def conversion_post(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    try:
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        data = dict(request.query_params)
    secret = request.headers.get("x-stravica-key")
    trusted = svc.workspace_for_secret(db, secret) if secret else None
    if secret and trusted is None:
        return Response(json.dumps({"ok": False, "detail": "invalid key"}), status_code=401,
                        media_type="application/json")
    ok = _record(db, data, trusted_workspace=trusted, source="api" if trusted else "pixel")
    return Response(json.dumps({"ok": ok}), media_type="application/json",
                    headers={**NO_STORE, "Access-Control-Allow-Origin": "*"})


@router.api_route("/r/{code}", methods=["GET", "HEAD"], include_in_schema=False)
def redirect(code: str, request: Request, db: Session = Depends(get_db)):
    link = db.scalar(select(TrackedLink).where(TrackedLink.code == code[:16]))
    if not link:
        return HTMLResponse(NOT_FOUND_PAGE, status_code=404)
    if request.method == "GET":
        try:
            with db.begin_nested():
                svc.register_click(db, link, client_ip(request), request.headers.get("user-agent"),
                                   request.headers.get("referer"))
        except Exception:  # never block the visitor
            _logger.exception("click count failed for %s", code)
    add_ref = bool(get_setting(db, link.workspace_id, "links.add_ref", True))
    return RedirectResponse(svc.destination(link, add_ref), status_code=302, headers=NO_STORE)
