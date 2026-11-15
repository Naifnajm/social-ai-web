"""OAuth 2.0 "Connect account" flows for each network.

App credentials come from two places:
* the workspace's own developer app ("bring your own app", workspace setting ``social.app.<platform>``, secret
  encrypted), used first when present;
* the platform-wide app of the SaaS operator, from environment variables (``SAI_META_APP_ID`` /
  ``SAI_META_APP_SECRET``, ``SAI_THREADS_APP_ID`` …, ``SAI_LINKEDIN_CLIENT_ID`` …, ``SAI_X_CLIENT_ID`` …,
  ``SAI_TIKTOK_CLIENT_KEY`` …, ``SAI_GOOGLE_CLIENT_ID`` … for YouTube and Google Business Profile,
  ``SAI_PINTEREST_APP_ID`` …) — one app for all customers.

The account remembers which app issued its token (``extra.oauth_app``) so refreshes use the same app.
"""
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlencode

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.http import ApiError, call
from app.modules.workspaces.settings import get_setting, set_setting

GRAPH = "https://graph.facebook.com"
GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
PINTEREST_TOKEN = "https://api.pinterest.com/v5/oauth/token"
CALLBACK_PATH = "/oauth/callback"


class PlatformApps(BaseSettings):
    """Platform-wide developer apps provided by the SaaS operator (environment / .env)."""

    model_config = SettingsConfigDict(env_prefix="SAI_", env_file=".env", extra="ignore")

    meta_app_id: str = ""
    meta_app_secret: str = ""
    threads_app_id: str = ""
    threads_app_secret: str = ""
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    x_client_id: str = ""
    x_client_secret: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    pinterest_app_id: str = ""
    pinterest_app_secret: str = ""


@lru_cache
def platform_apps() -> PlatformApps:
    return PlatformApps()


PLATFORMS = {
    "facebook": {
        "env": ("meta_app_id", "meta_app_secret"),
        "scopes": "pages_show_list,pages_read_engagement,pages_manage_posts,business_management,"
                  "instagram_basic,instagram_content_publish,instagram_manage_insights,read_insights,"
                  # inbox: messages and comments
                  "pages_messaging,pages_read_user_content,pages_manage_engagement,pages_manage_metadata,"
                  "instagram_manage_messages,instagram_manage_comments",
    },
    "threads": {
        "env": ("threads_app_id", "threads_app_secret"),
        "authorize": "https://threads.net/oauth/authorize",
        "scopes": "threads_basic,threads_content_publish,threads_manage_insights",
    },
    "linkedin": {
        "env": ("linkedin_client_id", "linkedin_client_secret"),
        "authorize": "https://www.linkedin.com/oauth/v2/authorization",
        "scopes": "openid profile email w_member_social",
        "org_scopes": " r_organization_social w_organization_social rw_organization_admin",
    },
    "x": {
        "env": ("x_client_id", "x_client_secret"),
        "authorize": "https://x.com/i/oauth2/authorize",
        "scopes": "tweet.read tweet.write users.read media.write offline.access",
    },
    "tiktok": {
        "env": ("tiktok_client_key", "tiktok_client_secret"),
        "authorize": "https://www.tiktok.com/v2/auth/authorize/",
        "scopes": "user.info.basic,user.info.stats,video.publish,video.list",
    },
    "youtube": {
        "env": ("google_client_id", "google_client_secret"),
        "authorize": GOOGLE_AUTHORIZE,
        "scopes": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
    },
    "google_business": {
        "env": ("google_client_id", "google_client_secret"),
        "authorize": GOOGLE_AUTHORIZE,
        "scopes": "https://www.googleapis.com/auth/business.manage",
    },
    "pinterest": {
        "env": ("pinterest_app_id", "pinterest_app_secret"),
        "authorize": "https://www.pinterest.com/oauth/",
        "scopes": "boards:read,boards:write,pins:read,pins:write,user_accounts:read",
    },
}
# Instagram accounts are discovered through the Facebook (Meta) login.
OAUTH_PLATFORM = {"instagram": "facebook"}
# YouTube and Google Business Profile are two logins (different permissions) of one Google developer app.
APP_KEY = {"youtube": "google", "google_business": "google"}
GOOGLE_PLATFORMS = ("youtube", "google_business")


def oauth_key(platform: str) -> str:
    return OAUTH_PLATFORM.get(platform, platform)


def redirect_uri() -> str:
    return settings.public_api_url.rstrip("/") + CALLBACK_PATH


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def _setting_key(platform: str) -> str:
    key = oauth_key(platform)
    return f"social.app.{APP_KEY.get(key, key)}"


def workspace_credentials(db: Session, workspace_id: int, platform: str) -> tuple[str, str]:
    value = get_setting(db, workspace_id, _setting_key(platform)) or {}
    if not isinstance(value, dict):
        return "", ""
    return (value.get("client_id") or "").strip(), (decrypt(value.get("client_secret")) or "").strip()


def save_workspace_credentials(db: Session, workspace_id: int, platform: str, client_id: str | None,
                               client_secret: str | None) -> None:
    if not client_id:
        set_setting(db, workspace_id, _setting_key(platform), None)
        return
    set_setting(db, workspace_id, _setting_key(platform),
                {"client_id": client_id.strip(), "client_secret": encrypt(client_secret.strip())})


def env_credentials(platform: str) -> tuple[str, str]:
    conf = PLATFORMS.get(oauth_key(platform))
    if not conf:
        return "", ""
    apps = platform_apps()
    return (getattr(apps, conf["env"][0]) or "").strip(), (getattr(apps, conf["env"][1]) or "").strip()


def credentials(db: Session, workspace_id: int, platform: str, source: str | None = None) -> tuple[str, str, str]:
    """``(client_id, secret, source)``: the workspace's own app first, then the platform-wide one.

    ``source`` forces one of them ("workspace" | "platform") — used to refresh a token with the app that issued it.
    """
    if source != "platform":
        client_id, secret = workspace_credentials(db, workspace_id, platform)
        if client_id and secret:
            return client_id, secret, "workspace"
        if source == "workspace":
            return "", "", "workspace"
    client_id, secret = env_credentials(platform)
    if client_id and secret:
        return client_id, secret, "platform"
    return "", "", ""


def is_configured(db: Session, workspace_id: int, platform: str) -> bool:
    return bool(oauth_key(platform) in PLATFORMS and credentials(db, workspace_id, platform)[2])


# ---------------------------------------------------------------------------
# Authorize URL
# ---------------------------------------------------------------------------
def new_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def graph_version(db: Session, workspace_id: int) -> str:
    return get_setting(db, workspace_id, "social.meta_graph_version", "v24.0") or "v24.0"


def linkedin_organizations(db: Session, workspace_id: int) -> bool:
    return bool(get_setting(db, workspace_id, "social.linkedin_organizations", False))


def authorize_url(db: Session, workspace_id: int, platform: str, state: str, verifier: str, client_id: str) -> str:
    platform = oauth_key(platform)
    conf = PLATFORMS[platform]
    redirect = redirect_uri()
    if platform == "facebook":
        url = f"https://www.facebook.com/{graph_version(db, workspace_id)}/dialog/oauth"
        params = {"client_id": client_id, "redirect_uri": redirect, "state": state,
                  "scope": conf["scopes"], "response_type": "code"}
    elif platform == "tiktok":
        url = conf["authorize"]
        params = {"client_key": client_id, "redirect_uri": redirect, "state": state,
                  "scope": conf["scopes"], "response_type": "code"}
    else:
        url = conf["authorize"]
        scopes = conf["scopes"]
        if platform == "linkedin" and linkedin_organizations(db, workspace_id):
            scopes += conf["org_scopes"]
        params = {"client_id": client_id, "redirect_uri": redirect, "state": state, "scope": scopes,
                  "response_type": "code"}
        if platform == "x":
            params.update(code_challenge=challenge(verifier), code_challenge_method="S256")
        if platform in GOOGLE_PLATFORMS:
            # offline + consent: Google only returns a refresh token when the consent screen is shown
            params.update(access_type="offline", prompt="consent")
    return f"{url}?{urlencode(params)}"


def _expiry(seconds) -> datetime | None:
    if not seconds:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(seconds))


def _basic(client_id: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()


class _Caller:
    def __init__(self, workspace_id: int, label: str):
        self.workspace_id = workspace_id
        self.label = label

    def __call__(self, method, url, operation, **kwargs):
        return call(method, url, service="social", operation=f"{self.label}: {operation}",
                    workspace_id=self.workspace_id, **kwargs)


# ---------------------------------------------------------------------------
# Code exchange → list of account dicts
# ---------------------------------------------------------------------------
def exchange(db: Session, workspace_id: int, platform: str, code: str, verifier: str | None,
             source: str | None = None) -> list[dict]:
    platform = oauth_key(platform)
    client_id, secret, used = credentials(db, workspace_id, platform, source)
    if not client_id:
        raise ApiError("Add the app credentials for this platform first.")
    handler = {"facebook": _exchange_meta, "threads": _exchange_threads, "linkedin": _exchange_linkedin,
               "x": _exchange_x, "tiktok": _exchange_tiktok, "youtube": _exchange_youtube,
               "google_business": _exchange_google_business, "pinterest": _exchange_pinterest}[platform]
    accounts = handler(db, workspace_id, client_id, secret, code, verifier or "")
    for account in accounts:
        account["extra"] = dict(account.get("extra") or {}, oauth_app=used)
    return accounts


def _exchange_meta(db, workspace_id, client_id, secret, code, verifier):
    http = _Caller(workspace_id, "Facebook")
    base = f"{GRAPH}/{graph_version(db, workspace_id)}"
    short = http("GET", f"{base}/oauth/access_token", "OAuth: exchange code",
                 params={"client_id": client_id, "client_secret": secret, "redirect_uri": redirect_uri(),
                         "code": code})
    long_lived = http("GET", f"{base}/oauth/access_token", "OAuth: long-lived token",
                      params={"grant_type": "fb_exchange_token", "client_id": client_id, "client_secret": secret,
                              "fb_exchange_token": short["access_token"]})
    user_token = long_lived["access_token"]
    pages = http("GET", f"{base}/me/accounts", "OAuth: list pages",
                 params={"access_token": user_token, "limit": 100,
                         "fields": "id,name,access_token,picture{url},"
                                   "instagram_business_account{id,username,name,profile_picture_url}"})
    accounts = []
    for page in pages.get("data", []):
        # Page tokens obtained from a long-lived user token do not expire.
        accounts.append({
            "platform": "facebook", "name": page.get("name"), "username": page.get("name"),
            "external_id": page["id"], "access_token": page["access_token"],
            "avatar_url": ((page.get("picture") or {}).get("data") or {}).get("url"), "token_expires_at": None,
        })
        insta = page.get("instagram_business_account")
        if insta:
            accounts.append({
                "platform": "instagram", "name": insta.get("name") or insta.get("username"),
                "username": insta.get("username"), "external_id": insta["id"], "access_token": page["access_token"],
                "avatar_url": insta.get("profile_picture_url"), "token_expires_at": None,
                "extra": {"page_id": page["id"]},
            })
    if not accounts:
        raise ApiError("No Facebook Page was shared with the app. Re-connect and select at least one Page.")
    return accounts


def _exchange_threads(db, workspace_id, client_id, secret, code, verifier):
    http = _Caller(workspace_id, "Threads")
    short = http("POST", "https://graph.threads.net/oauth/access_token", "OAuth: exchange code",
                 data={"client_id": client_id, "client_secret": secret, "grant_type": "authorization_code",
                       "redirect_uri": redirect_uri(), "code": code})
    long_lived = http("GET", "https://graph.threads.net/access_token", "OAuth: long-lived token",
                      params={"grant_type": "th_exchange_token", "client_secret": secret,
                              "access_token": short["access_token"]})
    token = long_lived["access_token"]
    me = http("GET", "https://graph.threads.net/v1.0/me", "OAuth: profile",
              params={"fields": "id,username,name,threads_profile_picture_url", "access_token": token})
    return [{
        "platform": "threads", "name": me.get("name") or me.get("username"), "username": me.get("username"),
        "external_id": str(me.get("id") or short.get("user_id")), "access_token": token,
        "avatar_url": me.get("threads_profile_picture_url"), "token_expires_at": _expiry(long_lived.get("expires_in")),
    }]


def _exchange_linkedin(db, workspace_id, client_id, secret, code, verifier):
    http = _Caller(workspace_id, "LinkedIn")
    token = http("POST", "https://www.linkedin.com/oauth/v2/accessToken", "OAuth: exchange code",
                 data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
                       "client_id": client_id, "client_secret": secret})
    access = token["access_token"]
    me = http("GET", "https://api.linkedin.com/v2/userinfo", "OAuth: profile",
              headers={"Authorization": f"Bearer {access}"})
    common = {"access_token": access, "refresh_token": token.get("refresh_token"),
              "token_expires_at": _expiry(token.get("expires_in"))}
    accounts = [dict(common, platform="linkedin", name=me.get("name"), username=me.get("email") or me.get("name"),
                     external_id=f"urn:li:person:{me['sub']}", avatar_url=me.get("picture"))]
    if linkedin_organizations(db, workspace_id):
        version = get_setting(db, workspace_id, "social.linkedin_api_version", "202510") or "202510"
        headers = {"Authorization": f"Bearer {access}", "LinkedIn-Version": version,
                   "X-Restli-Protocol-Version": "2.0.0"}
        try:
            acls = http("GET", "https://api.linkedin.com/rest/organizationAcls", "OAuth: list organizations",
                        headers=headers, params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"})
            for element in acls.get("elements", []):
                org_urn = element.get("organization")
                if not org_urn:
                    continue
                org = http("GET", f"https://api.linkedin.com/rest/organizations/{org_urn.rsplit(':', 1)[-1]}",
                           "OAuth: organization", headers=headers)
                accounts.append(dict(common, platform="linkedin", name=org.get("localizedName") or org_urn,
                                     username=org.get("vanityName") or org.get("localizedName"),
                                     external_id=org_urn, avatar_url=None))
        except ApiError:
            pass  # organisation access not approved for this app: keep the personal profile
    return accounts


def _exchange_x(db, workspace_id, client_id, secret, code, verifier):
    http = _Caller(workspace_id, "X")
    token = http("POST", "https://api.x.com/2/oauth2/token", "OAuth: exchange code",
                 headers={"Authorization": _basic(client_id, secret)},
                 data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
                       "code_verifier": verifier, "client_id": client_id})
    access = token["access_token"]
    me = http("GET", "https://api.x.com/2/users/me", "OAuth: profile", headers={"Authorization": f"Bearer {access}"},
              params={"user.fields": "profile_image_url"}).get("data", {})
    return [{
        "platform": "x", "name": me.get("name"), "username": me.get("username"), "external_id": me.get("id"),
        "access_token": access, "refresh_token": token.get("refresh_token"),
        "token_expires_at": _expiry(token.get("expires_in")), "avatar_url": me.get("profile_image_url"),
    }]


def _exchange_tiktok(db, workspace_id, client_id, secret, code, verifier):
    http = _Caller(workspace_id, "TikTok")
    token = http("POST", "https://open.tiktokapis.com/v2/oauth/token/", "OAuth: exchange code",
                 data={"client_key": client_id, "client_secret": secret, "code": code,
                       "grant_type": "authorization_code", "redirect_uri": redirect_uri()})
    if token.get("error"):
        raise ApiError(f"TikTok: {token.get('error_description') or token['error']}")
    access = token["access_token"]
    user = http("GET", "https://open.tiktokapis.com/v2/user/info/", "OAuth: profile",
                headers={"Authorization": f"Bearer {access}"},
                params={"fields": "open_id,avatar_url,display_name"}).get("data", {}).get("user", {})
    return [{
        "platform": "tiktok", "name": user.get("display_name"), "username": user.get("display_name"),
        "external_id": user.get("open_id") or token.get("open_id"), "access_token": access,
        "refresh_token": token.get("refresh_token"), "token_expires_at": _expiry(token.get("expires_in")),
        "avatar_url": user.get("avatar_url"), "extra": {"privacy_level": "SELF_ONLY"},
    }]


def _google_token(http, client_id, secret, code):
    token = http("POST", GOOGLE_TOKEN, "OAuth: exchange code",
                 data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
                       "client_id": client_id, "client_secret": secret})
    if not token.get("access_token"):
        raise ApiError("Google did not return an access token.")
    return token


def _exchange_youtube(db, workspace_id, client_id, secret, code, verifier):
    http = _Caller(workspace_id, "YouTube")
    token = _google_token(http, client_id, secret, code)
    access = token["access_token"]
    data = http("GET", "https://www.googleapis.com/youtube/v3/channels", "OAuth: channel",
                headers={"Authorization": f"Bearer {access}"}, params={"part": "snippet", "mine": "true"})
    channels = data.get("items") or []
    if not channels:
        raise ApiError("This Google account has no YouTube channel. Create the channel on YouTube first.")
    accounts = []
    for channel in channels:
        snippet = channel.get("snippet") or {}
        accounts.append({
            "platform": "youtube", "name": snippet.get("title"),
            "username": (snippet.get("customUrl") or snippet.get("title") or "").lstrip("@"),
            "external_id": channel["id"], "access_token": access, "refresh_token": token.get("refresh_token"),
            "token_expires_at": _expiry(token.get("expires_in")),
            "avatar_url": ((snippet.get("thumbnails") or {}).get("default") or {}).get("url"),
            "extra": {"privacy_status": "public"},
        })
    return accounts


def _exchange_google_business(db, workspace_id, client_id, secret, code, verifier):
    """One account per business location the Google user manages."""
    http = _Caller(workspace_id, "Google Business Profile")
    token = _google_token(http, client_id, secret, code)
    access = token["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    listed = http("GET", "https://mybusinessaccountmanagement.googleapis.com/v1/accounts", "OAuth: list accounts",
                  headers=headers)
    accounts = []
    for owner in listed.get("accounts") or []:
        data = http("GET", f"https://mybusinessbusinessinformation.googleapis.com/v1/{owner['name']}/locations",
                    "OAuth: list locations", headers=headers, params={"readMask": "name,title", "pageSize": 100})
        for location in data.get("locations") or []:
            accounts.append({
                "platform": "google_business", "name": location.get("title") or location["name"],
                "username": location.get("title"), "external_id": f"{owner['name']}/{location['name']}",
                "access_token": access, "refresh_token": token.get("refresh_token"),
                "token_expires_at": _expiry(token.get("expires_in")),
            })
    if not accounts:
        raise ApiError("This Google account manages no business location. Add or claim the business on Google "
                       "first.")
    return accounts


def _exchange_pinterest(db, workspace_id, client_id, secret, code, verifier):
    http = _Caller(workspace_id, "Pinterest")
    token = http("POST", PINTEREST_TOKEN, "OAuth: exchange code", headers={"Authorization": _basic(client_id, secret)},
                 data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()})
    access = token["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    me = http("GET", "https://api.pinterest.com/v5/user_account", "OAuth: profile", headers=headers)
    listed = http("GET", "https://api.pinterest.com/v5/boards", "OAuth: list boards", headers=headers,
                  params={"page_size": 100})
    boards = [{"id": str(b["id"]), "name": b.get("name") or str(b["id"])} for b in listed.get("items") or []
              if b.get("id")]
    if not boards:
        raise ApiError("This Pinterest account has no board. Create a board on Pinterest first.")
    return [{
        "platform": "pinterest", "name": me.get("business_name") or me.get("username"),
        "username": me.get("username"), "external_id": str(me.get("id") or me.get("username")),
        "access_token": access, "refresh_token": token.get("refresh_token"),
        "token_expires_at": _expiry(token.get("expires_in")), "avatar_url": me.get("profile_image"),
        "extra": {"boards": boards},  # the chosen board (extra.board_id) is kept when reconnecting
    }]


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------
def refresh(db: Session, account) -> dict:
    """Return new token values for ``account`` (access_token, refresh_token, token_expires_at) or raise ApiError."""
    platform = account.platform
    http = _Caller(account.workspace_id, platform)
    rt = account.refresh_token
    if platform == "threads":
        data = http("GET", "https://graph.threads.net/refresh_access_token", "Refresh token",
                    params={"grant_type": "th_refresh_token", "access_token": account.access_token})
        return {"access_token": data["access_token"], "token_expires_at": _expiry(data.get("expires_in"))}
    if not rt:
        raise ApiError("This token has expired and cannot be renewed automatically. Please reconnect the account.")
    source = (account.extra or {}).get("oauth_app") or None
    client_id, secret, _source = credentials(db, account.workspace_id, platform, source)
    if not client_id:
        raise ApiError("The app used to connect this account is no longer configured. Please reconnect the account.")
    if platform == "x":
        data = http("POST", "https://api.x.com/2/oauth2/token", "Refresh token",
                    headers={"Authorization": _basic(client_id, secret)},
                    data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id})
    elif platform == "linkedin":
        data = http("POST", "https://www.linkedin.com/oauth/v2/accessToken", "Refresh token",
                    data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id,
                          "client_secret": secret})
    elif platform == "tiktok":
        data = http("POST", "https://open.tiktokapis.com/v2/oauth/token/", "Refresh token",
                    data={"client_key": client_id, "client_secret": secret, "grant_type": "refresh_token",
                          "refresh_token": rt})
    elif platform in GOOGLE_PLATFORMS:
        data = http("POST", GOOGLE_TOKEN, "Refresh token",
                    data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id,
                          "client_secret": secret})
    elif platform == "pinterest":
        data = http("POST", PINTEREST_TOKEN, "Refresh token", headers={"Authorization": _basic(client_id, secret)},
                    data={"grant_type": "refresh_token", "refresh_token": rt})
    else:
        raise ApiError("Automatic token renewal is not available for this platform.")
    if not data.get("access_token"):
        raise ApiError("Token renewal failed. Please reconnect the account.")
    return {"access_token": data["access_token"], "refresh_token": data.get("refresh_token") or rt,
            "token_expires_at": _expiry(data.get("expires_in"))}


# ---------------------------------------------------------------------------
# Guided one-time app setup (shown in the Connect dialog)
# ---------------------------------------------------------------------------
SETUP_GUIDES = {
    "facebook": {
        "brand": "Meta", "portal_url": "https://developers.facebook.com/apps/",
        "id_label": "App ID", "secret_label": "App Secret",
        "steps": [
            "Open developers.facebook.com › My Apps › Create app, and choose the “Business” type.",
            "In the app, add the product “Facebook Login for Business”.",
            "In Facebook Login › Settings, paste the redirect URL below into “Valid OAuth Redirect URIs” and save.",
            "Open App settings › Basic, then copy the App ID and the App Secret here.",
        ],
        "note": "Instagram business accounts linked to your Pages are added in the same login.",
    },
    "threads": {
        "brand": "Threads", "portal_url": "https://developers.facebook.com/apps/",
        "id_label": "Threads App ID", "secret_label": "Threads App Secret",
        "steps": [
            "Open developers.facebook.com › Create app and pick the use case “Access the Threads API”.",
            "In Use cases › Threads API › Settings, paste the redirect URL below as the callback URL.",
            "Copy the Threads App ID and Threads App Secret from the same page.",
        ],
    },
    "linkedin": {
        "brand": "LinkedIn", "portal_url": "https://www.linkedin.com/developers/apps",
        "id_label": "Client ID", "secret_label": "Client Secret",
        "steps": [
            "Open linkedin.com/developers › Create app and link it to your company page.",
            "In Products, add “Sign In with LinkedIn using OpenID Connect” and “Share on LinkedIn”.",
            "In Auth, add the redirect URL below under “Authorized redirect URLs”.",
            "Copy the Client ID and the Primary Client Secret here.",
        ],
    },
    "x": {
        "brand": "X", "portal_url": "https://developer.x.com/en/portal/dashboard",
        "id_label": "OAuth 2.0 Client ID", "secret_label": "Client Secret",
        "steps": [
            "Open developer.x.com › Projects & Apps and select (or create) your app.",
            "In User authentication settings choose OAuth 2.0, type “Web App”, permissions “Read and write”.",
            "Paste the redirect URL below as the Callback URI and save.",
            "Copy the OAuth 2.0 Client ID and Client Secret here.",
        ],
    },
    "tiktok": {
        "brand": "TikTok", "portal_url": "https://developers.tiktok.com/apps/",
        "id_label": "Client key", "secret_label": "Client secret",
        "steps": [
            "Open developers.tiktok.com › Manage apps › Connect an app.",
            "Add the products “Login Kit” and “Content Posting API”.",
            "In Login Kit, paste the redirect URL below as the Redirect URI.",
            "Copy the Client key and Client secret here.",
        ],
    },
    "youtube": {
        "brand": "Google", "portal_url": "https://console.cloud.google.com/apis/credentials",
        "id_label": "Client ID", "secret_label": "Client secret",
        "steps": [
            "Open console.cloud.google.com, create a project and enable “YouTube Data API v3”.",
            "In “OAuth consent screen”, fill in the app details and add the YouTube upload permission.",
            "In Credentials › Create credentials › OAuth client ID, choose “Web application”.",
            "Paste the redirect URL below under “Authorized redirect URIs”, then copy the Client ID and secret here.",
        ],
        "note": "The same Google app also connects Google Business Profile. A new Google project can upload "
                "about 100 videos a day.",
    },
    "google_business": {
        "brand": "Google", "portal_url": "https://console.cloud.google.com/apis/credentials",
        "id_label": "Client ID", "secret_label": "Client secret",
        "steps": [
            "Ask Google for access to the Business Profile APIs (a request form; approval can take days).",
            "In console.cloud.google.com, enable “My Business Account Management API”, “My Business Business "
            "Information API” and “Google My Business API”.",
            "In Credentials › Create credentials › OAuth client ID, choose “Web application”.",
            "Paste the redirect URL below under “Authorized redirect URIs”, then copy the Client ID and secret here.",
        ],
        "note": "The same Google app also connects YouTube. Each business location becomes one account here.",
    },
    "pinterest": {
        "brand": "Pinterest", "portal_url": "https://developers.pinterest.com/apps/",
        "id_label": "App ID", "secret_label": "App secret key",
        "steps": [
            "Open developers.pinterest.com › My apps › Connect app (the account must be a business account).",
            "Paste the redirect URL below under “Redirect URIs” and save.",
            "Copy the App ID and the App secret key here.",
        ],
        "note": "Until Pinterest approves “Standard” access for the app, pins it creates are visible to you only.",
    },
}

# How to connect with a token (manual path)
MANUAL_HELP = {
    "facebook": "Page ID + a Page access token (from Graph API Explorer, permission pages_manage_posts).",
    "instagram": "Instagram Business account ID + the access token of the linked Facebook Page.",
    "linkedin": "Author URN (urn:li:person:… or urn:li:organization:…) + an access token with w_member_social.",
    "x": "An OAuth 2.0 user access token with tweet.write (and media.write for images).",
    "tiktok": "An access token with video.publish. Media must be served from a domain verified in TikTok.",
    "threads": "Threads user ID + a long-lived Threads access token.",
    "telegram": "Bot token from @BotFather + the channel (@name or -100…). Add the bot as channel admin.",
    "youtube": "Channel ID + a Google access token with youtube.upload (expires after an hour: prefer the login).",
    "pinterest": "A Pinterest access token with pins:write and boards:read; the first board is used.",
    "google_business": "Location (accounts/123/locations/456) + a Google access token with business.manage.",
}
