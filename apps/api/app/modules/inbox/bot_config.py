"""Meaning of ``SocialAccount.bot_settings`` (owned by the inbox) and of the workspace settings ``inbox.*``.

Account (``bot_settings`` JSON)::

    mode            off | suggest | auto      direct messages            (default suggest)
    comment_mode    off | suggest | auto      comments                   (default suggest)
    hide_offensive  bool                      hide insults / spam        (default false)
    private_reply   bool                      answer details privately   (default true)
    confidence      0-100                     needed to send by itself   (default 75)
    when            always | office_hours | outside_hours               (default always)
    hour_from/to    float                     office hours, workspace time zone (9 / 17)
    brand_kit_id    int | null                tone of voice (BrandKit); default brand kit when empty
    instructions    str                       extra instructions for this account

Workspace (``get_setting(db, ws, "inbox.<key>")``)::

    handover_message   str   sent once when the assistant hands over (auto mode); empty = nothing
    private_ack        str   public reply under a comment answered privately
    human_agent_tag    bool  Meta: humans may answer up to 7 days later (HUMAN_AGENT tag)
    create_contacts    bool  create / match a contact for every new customer (default true)
    company_info       str   facts about the company given to the assistant (address, phone, website…)

WhatsApp accounts keep their provider in ``SocialAccount.extra``: ``{"whatsapp_provider": "cloud"|"twilio",
"whatsapp_number": "+31…", "twilio_account_sid": "AC…"}``; the Twilio auth token is in ``SocialAccount.secrets``
(encrypted JSON ``{"twilio_auth_token": "…"}``); the Cloud API token in ``access_token`` and the
phone_number_id in ``external_id``.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.modules.social.models import SocialAccount
from app.modules.workspaces.settings import get_setting

BOT_MODES = ("off", "suggest", "auto")
BOT_WHEN = ("always", "office_hours", "outside_hours")

DEFAULTS = {
    "mode": "suggest",
    "comment_mode": "suggest",
    "hide_offensive": False,
    "private_reply": True,
    "confidence": 75,
    "when": "always",
    "hour_from": 9.0,
    "hour_to": 17.0,
    "brand_kit_id": None,
    "instructions": "",
}

WORKSPACE_DEFAULTS = {
    "handover_message": "",
    "private_ack": "",
    "human_agent_tag": False,
    "create_contacts": True,
    "company_info": "",
}


def bot_config(account: SocialAccount) -> dict:
    config = dict(DEFAULTS)
    for key, value in (account.bot_settings or {}).items():
        if key in DEFAULTS:
            config[key] = value
    if config["mode"] not in BOT_MODES:
        config["mode"] = "suggest"
    if config["comment_mode"] not in BOT_MODES:
        config["comment_mode"] = "suggest"
    if config["when"] not in BOT_WHEN:
        config["when"] = "always"
    try:
        config["confidence"] = max(0, min(int(config["confidence"]), 100))
    except (TypeError, ValueError):
        config["confidence"] = 75
    return config


def update_bot_config(account: SocialAccount, values: dict) -> dict:
    current = bot_config(account)
    current.update({k: v for k, v in values.items() if k in DEFAULTS})
    account.bot_settings = current  # new dict: SQLAlchemy sees the change
    return bot_config(account)


def mode_for(account: SocialAccount, kind: str) -> str:
    config = bot_config(account)
    return config["mode"] if kind == "dm" else config["comment_mode"]


def workspace_option(db: Session, workspace_id: int, key: str):
    return get_setting(db, workspace_id, f"inbox.{key}", WORKSPACE_DEFAULTS[key])


def is_active_now(account: SocialAccount, tz_name: str | None, now: datetime | None = None) -> bool:
    """Office-hours rule of the assistant (workspace time zone, Monday-Friday)."""
    config = bot_config(account)
    if config["when"] == "always":
        return True
    try:
        zone = ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    local = (now or datetime.now(ZoneInfo("UTC"))).astimezone(zone)
    hour = local.hour + local.minute / 60.0
    office = local.weekday() < 5 and float(config["hour_from"]) <= hour < float(config["hour_to"])
    return office if config["when"] == "office_hours" else not office


# ---------------------------------------------------------------- WhatsApp account helpers
def whatsapp_provider(account: SocialAccount) -> str:
    return (account.extra or {}).get("whatsapp_provider") or "cloud"


def account_secrets(account: SocialAccount) -> dict:
    try:
        return json.loads(account.secrets or "{}") or {}
    except (TypeError, ValueError):
        return {}


def set_account_secret(account: SocialAccount, key: str, value: str | None) -> None:
    data = account_secrets(account)
    if value:
        data[key] = value
    else:
        data.pop(key, None)
    account.secrets = json.dumps(data) if data else None
