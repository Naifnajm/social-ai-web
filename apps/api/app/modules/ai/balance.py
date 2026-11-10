"""Read the remaining balance from providers that expose it through their API.

OpenAI, Anthropic and Google do not expose a balance to normal API keys; for those the platform tracks spending
against a monthly budget instead.
"""
from app.core.http import ApiError, call

from .catalog import info

SUPPORTED = {"elevenlabs", "stability", "runway", "openrouter", "deepseek", "moonshot"}


def supports_balance(provider_type: str) -> bool:
    return provider_type in SUPPORTED


def fetch_balance(provider) -> dict:
    """Return ``{"amount": float, "unit": "USD" | "credits" | "characters"}``."""
    ptype = provider.provider_type
    key = (provider.api_key or "").strip()
    base = (provider.base_url or info(ptype).get("base_url") or "").rstrip("/")
    if not key:
        raise ApiError("No API key is set for “%s”." % provider.name)

    def get(url, headers):
        return call("GET", url, service="ai", operation="Read balance", workspace_id=provider.workspace_id,
                    ref=("ai_provider", provider.id), headers=headers, timeout=20)

    if ptype == "elevenlabs":
        data = get("%s/user/subscription" % base, {"xi-api-key": key})
        left = int(data.get("character_limit", 0) or 0) - int(data.get("character_count", 0) or 0)
        return {"amount": float(max(left, 0)), "unit": "credits"}
    if ptype == "stability":
        data = get("https://api.stability.ai/v1/user/balance", {"Authorization": "Bearer %s" % key})
        return {"amount": float(data.get("credits", 0) or 0), "unit": "credits"}
    if ptype == "runway":
        data = get("%s/organization" % base, {"Authorization": "Bearer %s" % key, "X-Runway-Version": "2024-11-06"})
        return {"amount": float(data.get("creditBalance", 0) or 0), "unit": "credits"}
    if ptype == "openrouter":
        data = get("%s/credits" % base, {"Authorization": "Bearer %s" % key}).get("data", {})
        return {"amount": float(data.get("total_credits", 0) or 0) - float(data.get("total_usage", 0) or 0),
                "unit": "USD"}
    if ptype == "deepseek":
        root = base.removesuffix("/v1")
        data = get("%s/user/balance" % root, {"Authorization": "Bearer %s" % key})
        infos = data.get("balance_infos") or [{}]
        usd = next((i for i in infos if i.get("currency") == "USD"), infos[0])
        return {"amount": float(usd.get("total_balance", 0) or 0), "unit": usd.get("currency", "USD")}
    if ptype == "moonshot":
        data = get("%s/users/me/balance" % base, {"Authorization": "Bearer %s" % key}).get("data", {})
        return {"amount": float(data.get("available_balance", 0) or 0), "unit": "USD"}
    raise ApiError("This provider does not share its balance through the API.")
