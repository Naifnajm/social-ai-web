"""Billing: plans & limits, trial, Stripe checkout/portal/webhooks, past_due grace, platform admin, isolation."""
import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.errors import LimitReached
from app.core.i18n import set_locale
from app.core.models import Media, Notification
from app.modules.ai.models import AIProvider, AIUsage
from app.modules.auth.models import User
from app.modules.billing import cli, limits, service
from app.modules.billing.config import billing_settings
from app.modules.billing.models import BillingEvent, Subscription
from app.modules.billing.tasks import run_reminders
from app.modules.social import hooks as social_hooks
from app.modules.social.models import Post, SocialAccount
from app.modules.workspaces.models import Workspace
from tests.conftest import signup

WEBHOOK_SECRET = "whsec_test_secret"


@pytest.fixture()
def stripe_env(monkeypatch):
    settings = billing_settings()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_123")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    for plan in ("starter", "pro", "business"):
        for interval in ("month", "year"):
            monkeypatch.setattr(settings, f"stripe_price_{plan}_{interval}", f"price_{plan}_{interval}")
    return settings


def _sub(db, workspace_id) -> Subscription:
    return service.get_subscription(db, workspace_id)


def _set_plan(db, workspace_id, plan, status="active"):
    sub = _sub(db, workspace_id)
    service.apply_plan(db, sub, plan, status=status)
    db.flush()
    return sub


def _accounts(db, workspace_id, n):
    for i in range(n):
        db.add(SocialAccount(workspace_id=workspace_id, name=f"acc{i}", platform="facebook"))
    db.flush()


def _sign(body: bytes, secret=WEBHOOK_SECRET, timestamp=None) -> str:
    timestamp = timestamp or int(time.time())
    sig = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def _webhook(client, event_type, obj, event_id=None, secret=WEBHOOK_SECRET):
    body = json.dumps({"id": event_id or f"evt_{time.time_ns()}", "type": event_type,
                       "data": {"object": obj}}).encode()
    return client.post("/billing/webhooks/stripe", content=body,
                       headers={"Stripe-Signature": _sign(body, secret), "Content-Type": "application/json"})


# ---------------------------------------------------------------- plans & trial
def test_public_plans(client):
    r = client.get("/api/billing/plans")
    assert r.status_code == 200
    data = r.json()
    codes = [p["code"] for p in data["plans"]]
    assert codes == ["starter", "pro", "business", "enterprise"]
    pro = next(p for p in data["plans"] if p["code"] == "pro")
    assert pro["price_month"] == 49 and pro["price_month_sar"] == round(49 * 3.75)
    assert pro["highlight"] and pro["self_service"]
    assert data["trial_days"] == 14


def test_signup_starts_trial(client, db, auth):
    sub = _sub(db, auth.workspace_id)
    assert sub.plan_code == "trial" and sub.status == "trialing"
    assert 13 <= (sub.trial_ends_at - service.utcnow()).days <= 14
    r = client.get("/api/billing/summary", headers=auth.headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["plan"] == "trial" and data["status"] == "trialing" and data["trial_days_left"] == 14
    assert data["blocked"] is None and data["can_manage"] is True
    assert data["usage"]["members"] == {"used": 1, "limit": 5}
    assert client.get("/api/workspace", headers=auth.headers).json()["workspace"]["plan_code"] == "trial"
    # a second workspace of the same user gets its own trial
    r = client.post("/api/workspaces", json={"name": "Second"}, headers=auth.headers)
    assert _sub(db, r.json()["id"]).status == "trialing"


def test_legacy_workspace_without_subscription_gets_implicit_trial(db, client, auth):
    ws = Workspace(name="Old", slug="old-ws")
    db.add(ws)
    db.flush()
    state = service.billing_state(db, ws.id)
    assert state.plan.code == "trial" and not state.blocked
    sub = service.ensure_subscription(db, ws)
    assert sub.status == "trialing" and sub.trial_ends_at


# ---------------------------------------------------------------- limits per plan
def test_social_account_limit_per_plan(db, auth):
    set_locale("en")
    ws = auth.workspace_id
    _set_plan(db, ws, "starter")
    _accounts(db, ws, 5)
    with pytest.raises(LimitReached) as exc:
        limits.check(db, ws, "social_accounts")
    err = exc.value
    assert err.code == "limit_reached" and err.status_code == 402
    assert err.extra["reason"] == "limit" and err.extra["upgrade"] == "pro"
    assert err.extra["limit"] == 5 and err.extra["used"] == 5
    assert "Pro" in err.detail and "5" in err.detail
    _set_plan(db, ws, "pro")
    limits.check(db, ws, "social_accounts")  # 15 allowed
    # inactive accounts do not count
    _set_plan(db, ws, "starter")
    for acc in db.query(SocialAccount).filter_by(workspace_id=ws).limit(2):
        acc.active = False
    db.flush()
    limits.check(db, ws, "social_accounts")


def test_enterprise_is_unlimited_and_overrides(db, auth):
    ws = auth.workspace_id
    _set_plan(db, ws, "enterprise")
    _accounts(db, ws, 50)
    limits.check(db, ws, "social_accounts")
    sub = _sub(db, ws)
    sub.limit_overrides = {"social_accounts": 50}
    db.flush()
    with pytest.raises(LimitReached) as exc:
        limits.check(db, ws, "social_accounts")
    assert exc.value.extra["upgrade"] is None


def test_posts_month_limit_and_publishing_hook(db, auth):
    ws = auth.workspace_id
    _set_plan(db, ws, "starter")  # 150 posts / month
    now = service.utcnow()
    for i in range(150):
        db.add(Post(workspace_id=ws, content=f"p{i}", state="posted", published_at=now))
    db.add(Post(workspace_id=ws, content="draft", state="draft"))  # drafts are free
    db.add(Post(workspace_id=ws, content="old", state="posted", published_at=now - timedelta(days=40),
                created_at=now - timedelta(days=40)))
    db.flush()
    assert limits.count_posts_month(db, ws) == 150
    assert any(getattr(f, "__name__", "") == "_posts_quota" for f in social_hooks.POST_LIMIT_CHECKS)
    with pytest.raises(LimitReached):
        for check in social_hooks.POST_LIMIT_CHECKS:
            check(db, ws)
    _set_plan(db, ws, "business")  # unlimited posts
    for check in social_hooks.POST_LIMIT_CHECKS:
        check(db, ws)


def test_ai_credits_count_platform_usage_only(db, auth):
    set_locale("en")
    ws = auth.workspace_id
    _set_plan(db, ws, "starter")  # $3
    provider = AIProvider(workspace_id=ws, name="Mine", provider_type="openai")
    db.add(provider)
    db.flush()
    db.add(AIUsage(workspace_id=ws, provider_id=provider.id, cost=50.0))  # own key: free
    db.add(AIUsage(workspace_id=ws, provider_id=None, cost=2.9))           # platform credits
    db.flush()
    assert limits.ai_spend_month(db, ws) == pytest.approx(2.9)
    limits.check(db, ws, "ai_credits", amount=0.05)
    with pytest.raises(LimitReached) as exc:
        limits.check(db, ws, "ai_credits", amount=0.2)
    assert exc.value.extra["resource"] == "ai_credits"
    assert "$3.00" in exc.value.detail


def test_storage_limit(db, auth):
    ws = auth.workspace_id
    _set_plan(db, ws, "starter")  # 5 GB
    db.add(Media(workspace_id=ws, filename="big.mp4", mimetype="video/mp4", size=int(4.9 * limits.GB),
                 storage_key="k/big.mp4"))
    db.flush()
    limits.check(db, ws, "storage", amount=50 * 1024 ** 2)
    with pytest.raises(LimitReached) as exc:
        limits.check(db, ws, "storage", amount=200 * 1024 ** 2)
    assert exc.value.extra["resource"] == "storage_gb"


def test_members_limit_on_invitations(client, db, auth):
    _set_plan(db, auth.workspace_id, "starter")  # 2 members
    r = client.post("/api/workspace/invitations", json={"email": "a@example.com", "role": "editor"},
                    headers=auth.headers)
    assert r.status_code == 201, r.text
    r = client.post("/api/workspace/invitations", json={"email": "b@example.com", "role": "editor"},
                    headers=auth.headers)
    assert r.status_code == 402
    body = r.json()
    assert body["code"] == "limit_reached" and body["resource"] == "members" and body["upgrade"] == "pro"
    # the refused invitation is not left behind; the session keeps working
    assert client.get("/api/workspace/invitations", headers=auth.headers).json()[0]["email"] == "a@example.com"
    assert len(client.get("/api/workspace/invitations", headers=auth.headers).json()) == 1


def test_arabic_message(client, db):
    ar = signup(client, email="ar@example.com")
    db.get(User, ar.user_id).locale = "ar"
    _set_plan(db, ar.workspace_id, "starter")
    client.post("/api/workspace/invitations", json={"email": "x@example.com"}, headers=ar.headers)
    r = client.post("/api/workspace/invitations", json={"email": "y@example.com"}, headers=ar.headers)
    assert r.status_code == 402
    assert "باقتك" in r.json()["detail"] and "الاحترافية" in r.json()["detail"]


def test_features_per_plan(db, auth):
    ws = auth.workspace_id
    assert limits.feature(db, ws, "production")  # the trial shows everything (business features)
    _set_plan(db, ws, "starter")
    assert not limits.feature(db, ws, "production")
    assert not limits.feature(db, ws, "approvals")
    assert limits.feature(db, ws, "templates")
    assert limits.feature(db, ws, "something_new")  # unknown features are never blocked
    with pytest.raises(LimitReached) as exc:
        limits.require(db, ws, "approvals")
    assert exc.value.extra == {**exc.value.extra, "reason": "feature", "upgrade": "pro", "feature": "approvals"}
    _set_plan(db, ws, "business")
    assert limits.feature(db, ws, "production")
    limits.require(db, ws, "production")


def test_trial_end_makes_workspace_read_only(client, db, auth):
    sub = _sub(db, auth.workspace_id)
    sub.trial_ends_at = service.utcnow() - timedelta(minutes=1)
    db.flush()
    with pytest.raises(LimitReached) as exc:
        limits.check(db, auth.workspace_id, "social_accounts")
    assert exc.value.extra["reason"] == "trial_ended" and exc.value.extra["upgrade"] == "pro"
    r = client.post("/api/workspace/invitations", json={"email": "z@example.com"}, headers=auth.headers)
    assert r.status_code == 402 and r.json()["reason"] == "trial_ended"
    # reads keep working
    assert client.get("/api/billing/summary", headers=auth.headers).json()["blocked"] == "trial_ended"
    assert client.get("/api/workspace/members", headers=auth.headers).status_code == 200
    # reminders: one "trial ended" notification for the owner, sent once
    assert run_reminders(db) == 1
    assert run_reminders(db) == 0
    assert db.query(Notification).filter_by(workspace_id=auth.workspace_id, kind="billing.trial_ended").count() == 1


def test_trial_ending_reminder(db, auth):
    sub = _sub(db, auth.workspace_id)
    sub.trial_ends_at = service.utcnow() + timedelta(days=2)
    db.flush()
    assert run_reminders(db) == 1
    assert db.query(Notification).filter_by(kind="billing.trial_ending").count() == 1


# ---------------------------------------------------------------- Stripe checkout / portal / invoices
def test_checkout_session_creation(client, db, auth, mock_http, stripe_env):
    def handler(method, url, kwargs):
        if url.endswith("/v1/customers"):
            return mock_http.response(200, {"id": "cus_A"})
        if url.endswith("/v1/checkout/sessions"):
            return mock_http.response(200, {"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"})
        return mock_http.response(404, {"error": {"message": "unexpected"}})

    calls = mock_http(handler)
    r = client.post("/api/billing/checkout", json={"plan": "pro", "interval": "year"}, headers=auth.headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"url": "https://checkout.stripe.com/c/cs_1", "updated": False}
    assert calls[0]["headers"]["Authorization"] == "Bearer sk_test_123"
    session = calls[1]["data"]
    assert session["mode"] == "subscription" and session["customer"] == "cus_A"
    assert session["line_items[0][price]"] == "price_pro_year"
    assert session["client_reference_id"] == str(auth.workspace_id)
    assert session["subscription_data[metadata][workspace_id]"] == str(auth.workspace_id)
    assert "/settings/billing?checkout=success" in session["success_url"]
    sub = _sub(db, auth.workspace_id)
    assert sub.provider_customer_id == "cus_A" and sub.provider == "stripe"
    # a second checkout reuses the customer
    calls.clear()
    client.post("/api/billing/checkout", json={"plan": "starter"}, headers=auth.headers)
    assert [c["url"].rsplit("/v1", 1)[1] for c in calls] == ["/checkout/sessions"]


def test_checkout_requires_owner_and_config(client, db, auth, mock_http):
    r = client.post("/api/billing/checkout", json={"plan": "pro"}, headers=auth.headers)
    assert r.status_code == 400 and r.json()["code"] == "billing_not_configured"
    editor = signup(client, email="editor@example.com", workspace="Other")
    # make the editor a member (editor role) of auth's workspace
    from app.modules.workspaces.models import Membership
    db.add(Membership(user_id=editor.user_id, workspace_id=auth.workspace_id, role="editor"))
    db.flush()
    headers = {**editor.headers, "X-Workspace": str(auth.workspace_id)}
    assert client.post("/api/billing/checkout", json={"plan": "pro"}, headers=headers).status_code == 403
    assert client.post("/api/billing/portal", headers=headers).status_code == 403
    assert client.get("/api/billing/invoices", headers=headers).status_code == 403
    summary = client.get("/api/billing/summary", headers=headers).json()
    assert summary["can_manage"] is False
    assert client.post("/api/billing/checkout", json={"plan": "enterprise"}, headers=auth.headers).status_code == 422


def test_change_plan_in_place_when_already_paying(client, db, auth, mock_http, stripe_env):
    sub = _sub(db, auth.workspace_id)
    sub.provider, sub.provider_customer_id, sub.provider_subscription_id = "stripe", "cus_A", "sub_A"
    service.apply_plan(db, sub, "starter", status="active")
    db.flush()

    def handler(method, url, kwargs):
        if method == "GET" and url.endswith("/v1/subscriptions/sub_A"):
            return mock_http.response(200, {"id": "sub_A", "items": {"data": [{"id": "si_1"}]}})
        if method == "POST" and url.endswith("/v1/subscriptions/sub_A"):
            assert kwargs["data"]["items[0][price]"] == "price_business_month"
            return mock_http.response(200, {
                "id": "sub_A", "customer": "cus_A", "status": "active", "cancel_at_period_end": False,
                "items": {"data": [{"id": "si_1", "current_period_end": int(time.time()) + 86400 * 30,
                                    "price": {"id": "price_business_month", "recurring": {"interval": "month"}}}]}})
        return mock_http.response(404, {})

    mock_http(handler)
    r = client.post("/api/billing/checkout", json={"plan": "business"}, headers=auth.headers)
    assert r.json() == {"url": None, "updated": True}
    assert sub.plan_code == "business" and sub.status == "active" and sub.current_period_end
    assert db.get(Workspace, auth.workspace_id).plan_code == "business"


def test_portal_and_invoices(client, db, auth, mock_http, stripe_env):
    assert client.post("/api/billing/portal", headers=auth.headers).json()["code"] == "no_customer"
    assert client.get("/api/billing/invoices", headers=auth.headers).json() == []
    sub = _sub(db, auth.workspace_id)
    sub.provider, sub.provider_customer_id = "stripe", "cus_A"
    db.flush()

    def handler(method, url, kwargs):
        if url.endswith("/v1/billing_portal/sessions"):
            assert kwargs["data"]["customer"] == "cus_A"
            return mock_http.response(200, {"url": "https://billing.stripe.com/p/session"})
        if url.endswith("/v1/invoices"):
            assert kwargs["params"]["customer"] == "cus_A"
            return mock_http.response(200, {"data": [
                {"id": "in_1", "number": "A-001", "status": "paid", "amount_paid": 4900, "amount_due": 4900,
                 "currency": "usd", "created": 1760000000, "hosted_invoice_url": "https://inv", "invoice_pdf": "https://pdf"},
                {"id": "in_0", "status": "draft", "amount_due": 100, "currency": "usd", "created": 1750000000},
            ]})
        return mock_http.response(404, {})

    mock_http(handler)
    assert client.post("/api/billing/portal", headers=auth.headers).json()["url"].startswith("https://billing.stripe")
    invoices = client.get("/api/billing/invoices", headers=auth.headers).json()
    assert len(invoices) == 1 and invoices[0]["amount"] == 49.0 and invoices[0]["currency"] == "USD"


# ---------------------------------------------------------------- Stripe webhooks
def test_webhook_signature(client, stripe_env, auth):
    body = json.dumps({"id": "evt_x", "type": "invoice.paid", "data": {"object": {}}}).encode()
    assert client.post("/billing/webhooks/stripe", content=body).status_code == 400
    assert client.post("/billing/webhooks/stripe", content=body,
                       headers={"Stripe-Signature": _sign(body, "whsec_wrong")}).status_code == 400
    old = int(time.time()) - 3600
    assert client.post("/billing/webhooks/stripe", content=body,
                       headers={"Stripe-Signature": _sign(body, timestamp=old)}).status_code == 400
    tampered = body.replace(b"invoice.paid", b"invoice.void")
    assert client.post("/billing/webhooks/stripe", content=tampered,
                       headers={"Stripe-Signature": _sign(body)}).status_code == 400
    assert client.post("/billing/webhooks/stripe", content=body,
                       headers={"Stripe-Signature": _sign(body)}).status_code == 200
    assert client.post("/billing/webhooks/nope", content=body).status_code == 404


def test_webhook_lifecycle(client, db, auth, stripe_env):
    ws = auth.workspace_id
    period_end = int(time.time()) + 30 * 86400
    r = _webhook(client, "checkout.session.completed", {
        "id": "cs_1", "mode": "subscription", "customer": "cus_A", "subscription": "sub_A",
        "client_reference_id": str(ws), "payment_status": "paid",
        "metadata": {"workspace_id": str(ws), "plan_code": "pro", "interval": "month"}}, event_id="evt_1")
    assert r.status_code == 200, r.text
    sub = _sub(db, ws)
    assert (sub.plan_code, sub.status, sub.provider) == ("pro", "active", "stripe")
    assert sub.provider_subscription_id == "sub_A" and sub.provider_customer_id == "cus_A"
    assert db.get(Workspace, ws).plan_code == "pro"

    # replay of the same event is ignored
    r = _webhook(client, "checkout.session.completed", {"mode": "subscription"}, event_id="evt_1")
    assert r.json()["duplicate"] is True

    subscription = {"id": "sub_A", "customer": "cus_A", "status": "active", "cancel_at_period_end": False,
                    "metadata": {"workspace_id": str(ws)},
                    "items": {"data": [{"id": "si_1", "current_period_end": period_end,
                                        "price": {"id": "price_business_year", "recurring": {"interval": "year"}}}]}}
    _webhook(client, "customer.subscription.updated", subscription)
    assert (sub.plan_code, sub.interval) == ("business", "year")
    assert int(sub.current_period_end.timestamp()) == period_end

    # payment fails → past_due, owners notified, still working during the grace period
    _webhook(client, "invoice.payment_failed", {"id": "in_1", "customer": "cus_A", "subscription": "sub_A"})
    assert sub.status == "past_due" and sub.past_due_since
    assert db.query(Notification).filter_by(workspace_id=ws, kind="billing.past_due").count() == 1
    limits.check(db, ws, "social_accounts")
    summary = client.get("/api/billing/summary", headers=auth.headers).json()
    assert summary["status"] == "past_due" and summary["grace_ends_at"] and summary["blocked"] is None

    # grace period over → read-only
    sub.past_due_since = service.utcnow() - timedelta(days=8)
    db.flush()
    with pytest.raises(LimitReached) as exc:
        limits.check(db, ws, "posts_month")
    assert exc.value.extra["reason"] == "payment_overdue"
    assert run_reminders(db) == 1

    # paid again → active
    _webhook(client, "invoice.paid", {"id": "in_2", "customer": "cus_A", "subscription": "sub_A",
                                      "lines": {"data": [{"period": {"end": period_end + 86400}}]}})
    assert sub.status == "active" and sub.past_due_since is None
    limits.check(db, ws, "posts_month")

    # cancel at period end, then deleted → canceled and blocked
    _webhook(client, "customer.subscription.updated", {**subscription, "cancel_at_period_end": True})
    assert sub.cancel_at_period_end is True and sub.status == "active"
    _webhook(client, "customer.subscription.deleted", {**subscription, "status": "canceled",
                                                       "ended_at": int(time.time()) - 10})
    assert sub.status == "canceled"
    with pytest.raises(LimitReached) as exc:
        limits.check(db, ws, "social_accounts")
    assert exc.value.extra["reason"] == "canceled"
    assert db.query(BillingEvent).filter_by(provider="stripe", workspace_id=ws).count() == 6


def test_webhook_incomplete_subscription_does_not_activate(client, db, auth, stripe_env):
    ws = auth.workspace_id
    _webhook(client, "customer.subscription.created", {
        "id": "sub_B", "customer": "cus_B", "status": "incomplete", "metadata": {"workspace_id": str(ws)},
        "items": {"data": [{"price": {"id": "price_pro_month"}}]}})
    sub = _sub(db, ws)
    assert sub.status == "trialing" and sub.plan_code == "trial"


def test_webhook_isolation(client, db, auth, stripe_env):
    """An event for workspace B's customer never changes workspace A, even if metadata is forged."""
    other = signup(client, email="b@example.com", workspace="Beta")
    sub_a = _sub(db, auth.workspace_id)
    sub_a.provider, sub_a.provider_customer_id = "stripe", "cus_A"
    db.flush()
    _webhook(client, "checkout.session.completed", {
        "mode": "subscription", "customer": "cus_B", "subscription": "sub_B", "payment_status": "paid",
        "metadata": {"workspace_id": str(auth.workspace_id), "plan_code": "business"}})
    assert sub_a.plan_code == "trial"
    _webhook(client, "invoice.payment_failed", {"customer": "cus_unknown", "subscription": "sub_unknown"})
    assert sub_a.status == "trialing" and _sub(db, other.workspace_id).status == "trialing"


# ---------------------------------------------------------------- onboarding
def test_onboarding_checklist(client, db, auth):
    r = client.get("/api/onboarding", headers=auth.headers)
    assert r.status_code == 200
    assert r.json()["done"] == 0 and r.json()["total"] == 5
    other = signup(client, email="other@example.com", workspace="Other")
    _accounts(db, other.workspace_id, 1)  # another workspace's rows never count
    _accounts(db, auth.workspace_id, 1)
    db.add(Post(workspace_id=auth.workspace_id, content="hi", state="posted"))
    db.flush()
    data = client.get("/api/onboarding", headers=auth.headers).json()
    done = {s["key"]: s["done"] for s in data["steps"]}
    assert done == {"connect_account": True, "ai_provider": False, "brand_kit": False, "invite_teammate": False,
                    "first_post": True}
    assert client.get("/api/onboarding", headers=other.headers).json()["done"] == 1
    assert client.post("/api/onboarding/dismiss", headers=auth.headers).json()["dismissed"] is True
    assert client.get("/api/onboarding", headers=other.headers).json()["dismissed"] is False


def test_summary_isolation(client, db, auth):
    other = signup(client, email="iso@example.com", workspace="Iso")
    _accounts(db, other.workspace_id, 3)
    _set_plan(db, other.workspace_id, "business")
    # asking for another workspace id falls back to the user's own membership
    headers = {**auth.headers, "X-Workspace": str(other.workspace_id)}
    data = client.get("/api/billing/summary", headers=headers).json()
    assert data["plan"] == "trial" and data["usage"]["social_accounts"]["used"] == 0


# ---------------------------------------------------------------- platform admin
@pytest.fixture()
def admin(client, db):
    a = signup(client, email="root@example.com", workspace="HQ")
    db.get(User, a.user_id).is_superadmin = True
    db.flush()
    return a


def test_admin_requires_superadmin(client, auth):
    for method, path in (("get", "/api/admin/stats"), ("get", "/api/admin/workspaces"),
                         ("get", f"/api/admin/workspaces/{auth.workspace_id}"), ("get", "/api/admin/settings"),
                         ("post", f"/api/admin/workspaces/{auth.workspace_id}/suspend"),
                         ("post", f"/api/admin/workspaces/{auth.workspace_id}/extend-trial"),
                         ("post", f"/api/admin/workspaces/{auth.workspace_id}/plan"),
                         ("put", "/api/admin/settings")):
        r = getattr(client, method)(path, headers=auth.headers, **({"json": {}} if method != "get" else {}))
        assert r.status_code == 403, path
    client.cookies.clear()
    assert client.get("/api/admin/stats").status_code == 401


def test_admin_workspaces_and_support_view(client, db, admin, auth):
    _accounts(db, auth.workspace_id, 2)
    r = client.get("/api/admin/workspaces", headers=admin.headers)
    assert r.status_code == 200
    assert r.json()["total"] == 2
    row = next(i for i in r.json()["items"] if i["id"] == auth.workspace_id)
    assert row["owner_email"] == "owner@example.com" and row["social_accounts"] == 2 and row["plan"] == "trial"
    assert client.get("/api/admin/workspaces", params={"q": "owner@"}, headers=admin.headers).json()["total"] == 1
    assert client.get("/api/admin/workspaces", params={"plan": "pro"}, headers=admin.headers).json()["total"] == 0
    detail = client.get(f"/api/admin/workspaces/{auth.workspace_id}", headers=admin.headers).json()
    assert detail["members"][0]["email"] == "owner@example.com"
    assert detail["usage"]["social_accounts"]["used"] == 2
    assert client.get("/api/admin/workspaces/999999", headers=admin.headers).status_code == 404


def test_admin_suspend_reactivate(client, db, admin, auth):
    r = client.post(f"/api/admin/workspaces/{auth.workspace_id}/suspend", json={"reason": "fraud"},
                    headers=admin.headers)
    assert r.status_code == 200 and r.json()["status"] == "suspended" and r.json()["blocked"] == "suspended"
    assert client.get("/api/workspace", headers=auth.headers).json()["code"] == "workspace_suspended"
    with pytest.raises(LimitReached):
        limits.check(db, auth.workspace_id, "members")
    assert client.get("/api/admin/workspaces", params={"status": "suspended"},
                      headers=admin.headers).json()["total"] == 1
    client.post(f"/api/admin/workspaces/{auth.workspace_id}/reactivate", headers=admin.headers)
    assert client.get("/api/workspace", headers=auth.headers).status_code == 200
    events = client.get(f"/api/admin/workspaces/{auth.workspace_id}", headers=admin.headers).json()["events"]
    assert [e["type"] for e in events] == ["admin.reactivate", "admin.suspend"]


def test_admin_extend_trial_and_change_plan(client, db, admin, auth):
    sub = _sub(db, auth.workspace_id)
    sub.trial_ends_at = service.utcnow() - timedelta(days=1)
    db.flush()
    r = client.post(f"/api/admin/workspaces/{auth.workspace_id}/extend-trial", json={"days": 7},
                    headers=admin.headers)
    assert r.status_code == 200 and r.json()["blocked"] is None
    assert 6 <= (sub.trial_ends_at - service.utcnow()).days <= 7
    r = client.post(f"/api/admin/workspaces/{auth.workspace_id}/plan", headers=admin.headers, json={
        "plan": "enterprise", "status": "active", "limit_overrides": {"social_accounts": 200, "bogus": 1},
        "note": "Annual contract"})
    assert r.status_code == 200, r.text
    assert sub.plan_code == "enterprise" and sub.provider == "manual"
    assert sub.limit_overrides == {"social_accounts": 200}
    assert db.get(Workspace, auth.workspace_id).plan_code == "enterprise"
    r = client.post(f"/api/admin/workspaces/{auth.workspace_id}/extend-trial", json={"days": 7},
                    headers=admin.headers)
    assert r.json()["code"] == "has_paid_plan"
    # a manual plan cannot be changed through checkout
    assert client.post("/api/billing/checkout", json={"plan": "pro"}, headers=auth.headers).json()["code"] == \
        "managed_plan"


def test_admin_stats(client, db, admin, auth):
    _set_plan(db, auth.workspace_id, "pro")
    _sub(db, auth.workspace_id).interval = "year"
    db.flush()
    data = client.get("/api/admin/stats", headers=admin.headers).json()
    assert data["workspaces_total"] == 2 and data["paying"] == 1 and data["trialing"] == 1
    assert data["mrr_usd"] == pytest.approx(490 / 12, abs=0.01)
    assert data["signups_30d"] == 2 and len(data["signups_by_day"]) == 30
    assert data["signups_by_day"][-1]["count"] == 2
    assert data["by_plan"]["pro"] == 1


def test_platform_settings_secrets_encrypted(client, db, admin):
    r = client.put("/api/admin/settings", headers=admin.headers, json={"values": {
        "ai.openai_api_key": "sk-platform-secret", "ai.default_provider": "openai", "billing.trial_days": "21",
        "billing.stripe_prices": {"pro_month": "price_override"}}})
    assert r.status_code == 200, r.text
    values = r.json()["values"]
    assert values["ai.openai_api_key"] is True and values["ai.anthropic_api_key"] is False
    assert "sk-platform-secret" not in r.text
    assert values["billing.trial_days"] == 21
    from app.modules.billing import platform
    from app.modules.billing.providers.stripe import price_table
    assert platform.ai_key(db, "openai") == "sk-platform-secret"
    raw = db.execute(text("SELECT secret FROM platform_settings WHERE key = 'ai.openai_api_key'")).scalar()
    assert raw and "sk-platform-secret" not in raw
    assert price_table(db)["pro_month"] == "price_override"
    # booleans for secrets mean "keep"; "" clears
    client.put("/api/admin/settings", headers=admin.headers, json={"values": {"ai.openai_api_key": True}})
    assert platform.ai_key(db, "openai") == "sk-platform-secret"
    client.put("/api/admin/settings", headers=admin.headers, json={"values": {"ai.openai_api_key": ""}})
    assert platform.ai_key(db, "openai") is None
    assert client.put("/api/admin/settings", headers=admin.headers,
                      json={"values": {"nope": 1}}).json()["code"] == "bad_setting"
    # new trials use the platform trial length
    new = signup(client, email="late@example.com", workspace="Late")
    assert 20 <= (_sub(db, new.workspace_id).trial_ends_at - service.utcnow()).days <= 21


def test_cli_create_superadmin(db, capsys):
    assert cli.main(["create-superadmin", "boss@example.com", "--name", "Boss"]) == 0
    out = capsys.readouterr().out
    assert "Created superadmin boss@example.com" in out and "Temporary password" in out
    user = db.query(User).filter_by(email="boss@example.com").one()
    assert user.is_superadmin and user.last_workspace_id
    assert cli.main(["create-superadmin", "BOSS@example.com"]) == 0
    assert "Promoted" in capsys.readouterr().out
    assert cli.main(["revoke-superadmin", "boss@example.com"]) == 0
    assert not user.is_superadmin
    assert cli.main(["revoke-superadmin", "ghost@example.com"]) == 1
