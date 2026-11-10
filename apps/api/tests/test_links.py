"""Tracked short links (TEXT_FILTERS hook), the public redirect, clicks, conversions (pixel, API, server key),
attribution per post / network / campaign, and the product catalogue."""
import re
from datetime import timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import settings
from app.modules.ai import service as ai
from app.modules.links import service as links
from app.modules.links.models import Conversion, LinkClick, TrackedLink
from app.modules.planning.models import Campaign
from app.modules.products.models import Product
from app.modules.social import hooks
from app.modules.social.models import Post
from app.modules.templates import frame
from tests.conftest import signup
from tests.planning_fakes import install_fake_social, make_account, make_media, make_post, share_job_session

UTC = timezone.utc
BASE = settings.public_api_url.rstrip("/")
SHORT = re.compile(re.escape(BASE) + r"/r/(\w+)")
BROWSER = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"


def run_filters(db, post, account, text):
    """What publishing does for each account before sending the text."""
    for text_filter in hooks.TEXT_FILTERS:
        text = text_filter(db, post, account, text)
    return text


@pytest.fixture()
def setup(db, auth):
    fb = make_account(db, auth.workspace_id, "facebook", "Page")
    x = make_account(db, auth.workspace_id, "x", "Brand X")
    campaign = Campaign(workspace_id=auth.workspace_id, name="Autumn sale")
    db.add(campaign)
    db.flush()
    content = ("Shop the new range https://shop.example.com/sale?id=7 — again: https://shop.example.com/sale?id=7 "
               "and https://blog.example.com/news.")
    post = make_post(db, auth.workspace_id, [fb, x], content=content, name="Autumn post", campaign_id=campaign.id)
    return fb, x, campaign, post


def click(client, code, ua=BROWSER, ip="1.1.1.1", method="get"):
    return getattr(client, method)(f"/r/{code}", headers={"user-agent": ua, "x-forwarded-for": ip},
                                   follow_redirects=False)


def test_hook_is_registered():
    assert any(f.__name__ == "tracked_links_filter" for f in hooks.TEXT_FILTERS)


def test_links_replaced_per_network_with_utm(client, auth, db, setup):
    fb, x, campaign, post = setup
    fb_text = run_filters(db, post, fb, post.content)
    x_text = run_filters(db, post, x, post.content)
    fb_codes, x_codes = SHORT.findall(fb_text), SHORT.findall(x_text)
    assert len(fb_codes) == 3
    assert fb_codes[0] == fb_codes[1], "the same URL is shortened once"
    assert fb_codes[0] != fb_codes[2]
    assert not set(fb_codes) & set(x_codes), "each network gets its own links"
    assert "shop.example.com" not in x_text and fb_text.endswith("news.") is False
    assert fb_text.rstrip().endswith(".")  # the final dot is kept outside the link

    link = db.query(TrackedLink).filter_by(code=fb_codes[0]).one()
    assert (link.platform, link.utm_source, link.utm_medium, link.utm_campaign) == \
        ("facebook", "facebook", "social", "Autumn sale")
    assert (link.post_id, link.account_id, link.campaign_id) == (post.id, fb.id, campaign.id)
    query = parse_qs(urlsplit(links.destination(link)).query)
    assert query["id"] == ["7"] and query["utm_source"] == ["facebook"] and query["sref"] == [link.code]
    # publishing again (retry) reuses the same links
    count = db.query(TrackedLink).count()
    assert SHORT.findall(run_filters(db, post, fb, post.content)) == fb_codes
    assert db.query(TrackedLink).count() == count


def test_tagged_links_disabled_and_x_limit(client, auth, db, setup):
    fb, x, _campaign, _post = setup
    tagged = "https://shop.example.com/?utm_source=newsletter&utm_campaign=mine"
    post = make_post(db, auth.workspace_id, [fb], content=f"Read {tagged} now", name="Tagged")
    assert tagged in run_filters(db, post, fb, post.content), "own UTM tags are kept by default"
    client.put("/api/links/settings", json={"enabled": True, "retag": True}, headers=auth.headers)
    assert tagged not in run_filters(db, post, fb, post.content)
    client.put("/api/links/settings", json={"enabled": False}, headers=auth.headers)
    assert run_filters(db, post, fb, "Plain https://shop.example.com/x") == "Plain https://shop.example.com/x"
    client.put("/api/links/settings", json={"enabled": True}, headers=auth.headers)
    # a longer short link never pushes an X post over 280 characters
    text = "a" * 266 + " http://t.co/a"
    long_post = make_post(db, auth.workspace_id, [x], content=text, name="Long")
    assert run_filters(db, long_post, x, text) == text
    assert SHORT.search(run_filters(db, long_post, fb, text))
    # our own short links are never wrapped again
    own = f"See {BASE}/r/abcdefg"
    assert run_filters(db, long_post, fb, own) == own


def test_redirect_counts_clicks_once_and_ignores_bots(client, auth, db, setup):
    fb, x, campaign, post = setup
    code = SHORT.findall(run_filters(db, post, fb, post.content))[0]
    x_code = SHORT.findall(run_filters(db, post, x, post.content))[0]
    r = click(client, code)
    assert r.status_code == 302
    target = urlsplit(r.headers["location"])
    assert target.netloc == "shop.example.com"
    assert parse_qs(target.query)["utm_campaign"] == ["Autumn sale"]
    assert r.headers["cache-control"].startswith("no-store")
    click(client, code)  # same visitor within 24 h
    click(client, code, ip="2.2.2.2")
    click(client, code, ua="facebookexternalhit/1.1")
    click(client, code, ua="")
    assert click(client, code, method="head").status_code == 302
    click(client, x_code, ip="3.3.3.3")
    link = db.query(TrackedLink).filter_by(code=code).one()
    assert link.clicks == 2
    assert db.query(LinkClick).filter_by(link_id=link.id).count() == 2
    assert client.get("/r/nope123", follow_redirects=False).status_code == 404

    by_platform = links.results_by(db, auth.workspace_id, "platform")
    assert (by_platform["facebook"]["clicks"], by_platform["x"]["clicks"]) == (2, 1)
    assert links.results_by(db, auth.workspace_id, "post")[post.id]["clicks"] == 3
    assert links.results_by(db, auth.workspace_id, "campaign")[campaign.id]["clicks"] == 3
    post_links = client.get(f"/api/links/posts/{post.id}", headers=auth.headers).json()
    assert post_links["clicks"] == 3 and len(post_links["links"]) == 4  # 2 URLs × 2 networks
    listed = client.get("/api/links", params={"platform": "facebook"}, headers=auth.headers).json()
    assert listed[0]["clicks"] == 2 and listed[0]["short_url"].endswith(code)


def test_conversions_pixel_api_and_attribution(client, auth, db, setup):
    fb, x, campaign, post = setup
    code = SHORT.findall(run_filters(db, post, x, post.content))[0]
    run_filters(db, post, fb, post.content)
    key = client.get("/api/links/settings", headers=auth.headers).json()["public_key"]
    # pixel with the click reference
    r = client.get("/r/conv", params={"code": code, "value": "200", "currency": "SAR", "id": "A-1"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/gif"
    # the same order again is not counted twice
    client.get("/r/conv", params={"code": code, "value": "200", "currency": "SAR", "id": "A-1"})
    # beacon with UTM tags only (campaign found by name)
    r = client.post("/r/conv", content=b'{"k": "%s", "utm_source": "facebook", "utm_medium": "social", '
                                        b'"utm_campaign": "autumn sale", "value": 50, "id": "A-2"}' % key.encode())
    assert r.json() == {"ok": True}
    # not from social: ignored by the public pixel
    r = client.post("/r/conv", content=('{"k": "%s", "utm_source": "newsletter", "utm_medium": "email", '
                                        '"value": 99}' % key).encode())
    assert r.json() == {"ok": False}
    assert client.get("/r/conv", params={"k": "pk_wrongkey123", "utm_source": "x", "utm_medium": "social"}
                      ).status_code == 200
    conversions = db.query(Conversion).filter_by(workspace_id=auth.workspace_id).all()
    assert len(conversions) == 2
    first = next(c for c in conversions if c.external_id == "A-1")
    assert (first.post_id, first.platform, first.campaign_id, first.source) == (post.id, "x", campaign.id, "pixel")
    second = next(c for c in conversions if c.external_id == "A-2")
    assert (second.platform, second.campaign_id, second.post_id) == ("facebook", campaign.id, post.id)

    # authenticated API (orders from a shop without Odoo) and another currency
    r = client.post("/api/links/conversions", json={"kind": "lead", "utm_source": "x", "utm_medium": "social",
                                                    "utm_campaign": "Autumn sale", "external_id": "L-1"},
                    headers=auth.headers)
    assert r.status_code == 201 and r.json()["campaign_name"] == "Autumn sale"
    client.post("/api/links/conversions", json={"value": 10, "currency": "EUR", "post_id": post.id},
                headers=auth.headers)
    totals = links.results_by(db, auth.workspace_id, "all")["all"]
    assert (totals["conversions"], totals["orders"], totals["leads"], totals["revenue"]) == (4, 3, 1, 250.0)
    by_platform = links.results_by(db, auth.workspace_id, "platform")
    assert by_platform["x"]["revenue"] == 200.0 and by_platform["facebook"]["revenue"] == 50.0
    assert links.results_by(db, auth.workspace_id, "campaign")[campaign.id]["revenue"] == 250.0

    summary = client.get("/api/links/summary?days=30", headers=auth.headers).json()
    assert summary["totals"]["revenue"] == 250.0 and summary["currency"] == "SAR"
    assert summary["top_posts"][0]["id"] == post.id
    assert summary["by_campaign"][0]["label"] == "Autumn sale"
    assert len(summary["daily"]) >= 30
    stats = client.get("/api/campaigns", headers=auth.headers).json()[0]["stats"]
    assert stats["revenue"] == 250.0 and stats["conversions"] == 4
    listed = client.get("/api/links/conversions", headers=auth.headers).json()
    assert len(listed) == 4
    assert client.delete(f"/api/links/conversions/{listed[0]['id']}", headers=auth.headers).status_code == 204


def test_server_key_and_snippet(client, auth, db):
    secret = client.post("/api/links/settings/secret", headers=auth.headers).json()["secret"]
    assert client.get("/api/links/settings", headers=auth.headers).json()["has_secret"] is True
    r = client.post("/r/conv", json={"value": 120, "id": "S-1", "note": "phone order"},
                    headers={"X-Stravica-Key": secret})
    assert r.json() == {"ok": True}, "a trusted server call is kept even without attribution"
    assert db.query(Conversion).filter_by(workspace_id=auth.workspace_id, external_id="S-1").one().source == "api"
    assert client.post("/r/conv", json={"value": 1}, headers={"X-Stravica-Key": "sk_wrong"}).status_code == 401
    key = client.get("/api/links/settings", headers=auth.headers).json()["public_key"]
    js = client.get(f"/r/t.js?k={key}")
    assert js.status_code == 200 and key in js.text and "sendBeacon" in js.text
    assert "pk_" not in client.get("/r/t.js?k=pk_unknown_key_123").text.split("var K = ")[1][:8]
    rotated = client.post("/api/links/settings/rotate-key", headers=auth.headers).json()["public_key"]
    assert rotated != key


def test_manual_links_and_isolation(client, auth, db, setup):
    fb, _x, campaign, post = setup
    r = client.post("/api/links", json={"url": "https://shop.example.com/bio", "label": "Instagram bio",
                                        "utm_source": "instagram", "campaign_id": campaign.id}, headers=auth.headers)
    assert r.status_code == 201, r.text
    manual = r.json()
    assert manual["utm_campaign"] == "Autumn sale" and manual["platform"] == "instagram"
    assert client.post("/api/links", json={"url": "notaurl"}, headers=auth.headers).status_code == 422

    other = signup(client, email="links2@example.com", workspace="Links2")
    assert client.get("/api/links", headers=other.headers).json() == []
    assert client.patch(f"/api/links/{manual['id']}", json={"label": "x"}, headers=other.headers).status_code == 404
    assert client.delete(f"/api/links/{manual['id']}", headers=other.headers).status_code == 404
    assert client.get(f"/api/links/posts/{post.id}", headers=other.headers).status_code == 404
    assert client.post("/api/links", json={"url": "https://a.example.com", "campaign_id": campaign.id},
                       headers=other.headers).status_code == 404
    assert client.post("/api/links/conversions", json={"post_id": post.id}, headers=other.headers).status_code == 404
    # a click code of workspace A cannot attribute a conversion reported by B's server key
    code = SHORT.findall(run_filters(db, post, fb, post.content))[0]
    secret = client.post("/api/links/settings/secret", headers=other.headers).json()["secret"]
    client.post("/r/conv", json={"code": code, "value": 5, "id": "B-1"}, headers={"X-Stravica-Key": secret})
    stored = db.query(Conversion).filter_by(external_id="B-1").one()
    assert stored.workspace_id == other.workspace_id and stored.post_id is None
    assert links.results_by(db, auth.workspace_id, "all") == {}
    summary = client.get("/api/links/summary", headers=other.headers).json()
    assert summary["totals"]["revenue"] == 5.0 and summary["top_posts"] == []
    assert client.delete(f"/api/links/{manual['id']}", headers=auth.headers).status_code == 204
    post_link = db.query(TrackedLink).filter_by(code=code).one()
    assert client.delete(f"/api/links/{post_link.id}", headers=auth.headers).status_code == 400


# ---------------------------------------------------------------------------------------------- products
def test_product_catalogue_and_announce(client, auth, db, monkeypatch):
    fake = install_fake_social(monkeypatch, db)
    fb = make_account(db, auth.workspace_id)
    photo = make_media(db, auth.workspace_id, "chair.png")
    r = client.put("/api/products/settings", json={"account_ids": [fb.id], "caption": "template",
                                                   "template": "New: {name} for {price} {url}"}, headers=auth.headers)
    assert r.status_code == 200, r.text
    r = client.post("/api/products", json={"name": "Oak chair", "price": 120, "image_media_id": photo.id,
                                           "url": "https://shop.example.com/chair"}, headers=auth.headers)
    assert r.status_code == 201, r.text
    product = r.json()
    assert product["price_label"] == "120 SAR" and product["announced_post_id"] is None
    r = client.post(f"/api/products/{product['id']}/announce", json={}, headers=auth.headers)
    assert r.status_code == 200, r.text
    post = db.get(Post, r.json()["post_id"])
    assert post.content == "New: Oak chair for 120 SAR https://shop.example.com/chair"
    assert post.source_ref == f"product:{product['id']}" and post.state == "draft"
    assert [link.media_id for link in post.media_links] == [photo.id]
    assert [a.id for a in post.accounts] == [fb.id]
    # announced once (unless forced)
    again = client.post(f"/api/products/{product['id']}/announce", json={}, headers=auth.headers).json()
    assert again["post_id"] == post.id
    forced = client.post(f"/api/products/{product['id']}/announce", json={"force": True, "mode": "best_time"},
                         headers=auth.headers).json()
    assert forced["post_id"] != post.id and forced["state"] == "scheduled"
    # a file used by a product cannot be deleted from the library
    assert client.delete(f"/api/library/media/{photo.id}", headers=auth.headers).status_code == 409

    other = signup(client, email="prod2@example.com", workspace="P2")
    assert client.get(f"/api/products/{product['id']}", headers=other.headers).status_code == 404
    assert client.post(f"/api/products/{product['id']}/announce", json={}, headers=other.headers).status_code == 404
    assert client.post("/api/products", json={"name": "x", "image_media_id": photo.id},
                       headers=other.headers).status_code == 404
    assert client.put("/api/products/settings", json={"account_ids": [fb.id]}, headers=other.headers).status_code == 404
    assert len(fake.created) == 2


def test_product_auto_announce_with_ai_and_design(client, auth, db, monkeypatch):
    install_fake_social(monkeypatch, db)
    share_job_session(monkeypatch)
    fb = make_account(db, auth.workspace_id)
    photo = make_media(db, auth.workspace_id, "lamp.png")
    framed = make_media(db, auth.workspace_id, "lamp-framed.png", source="template")
    calls = {}

    def compose_for_post(db_, ws, design, media_id, text=None, story=False):
        calls["frame"] = (design, media_id, text)
        return framed

    def generate(db_, ws, system, user, **kwargs):
        calls["ai"] = user
        return "“Meet our new Lamp ✨”"

    monkeypatch.setattr(frame, "compose_for_post", compose_for_post)
    monkeypatch.setattr(ai, "generate_text", generate)
    client.put("/api/products/settings", json={"auto_announce": True, "account_ids": [fb.id], "caption": "ai",
                                               "mode": "best_time", "design": "set:3"}, headers=auth.headers)
    product = client.post("/api/products", json={"name": "Lamp", "price": 30.5, "image_media_id": photo.id},
                          headers=auth.headers).json()
    row = db.get(Product, product["id"])
    post = db.get(Post, row.announced_post_id)
    assert post.content == "Meet our new Lamp ✨" and post.state == "scheduled"
    assert calls["frame"] == ("set:3", photo.id, "30.5 SAR")
    assert "Lamp" in calls["ai"]
    assert [link.media_id for link in post.media_links] == [framed.id]
    # AI not configured: the template is used
    monkeypatch.setattr(ai, "generate_text", ai.generate_text_with_usage)
    product2 = client.post("/api/products", json={"name": "Desk", "price": 99}, headers=auth.headers).json()
    post2 = db.get(Post, db.get(Product, product2["id"]).announced_post_id)
    assert post2.content.startswith("✨ Desk") and "99 SAR" in post2.content


def test_links_settings_need_admin(client, auth, db):
    from app.modules.workspaces.models import Membership
    editor = signup(client, email="ed@example.com", workspace="Ed")
    db.add(Membership(user_id=editor.user_id, workspace_id=auth.workspace_id, role="editor"))
    db.flush()
    headers = {**editor.headers, "X-Workspace": str(auth.workspace_id)}
    assert client.put("/api/links/settings", json={"enabled": False}, headers=headers).status_code == 403
    assert client.post("/api/links/settings/secret", headers=headers).status_code == 403
    assert client.get("/api/links/settings", headers=headers).status_code == 200
