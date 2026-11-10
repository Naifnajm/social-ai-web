"""AI text-generation clients (ported from the Odoo module). Each one exposes:

* ``generate(system, prompt) -> str`` (``last_usage`` = (input tokens, output tokens) afterwards)
* ``list_models() -> list[str]``

Which client is used comes from the provider catalog (``catalog.py``). All HTTP goes through ``app.core.http.call``.
"""
from app.core.http import ApiError, call

from . import catalog

# Anthropic API version 2026-10-21: sampling params (temperature/top_p/top_k) are rejected, so we never send them.
ANTHROPIC_VERSION = "2026-10-21"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that support the server-side refusal fallback ("fallbacks": "default").
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")


class BaseAIClient:
    default_base_url = ""

    def __init__(self, provider, model: str | None = None, max_tokens: int | None = None):
        self.provider = provider
        self.meta = catalog.info(provider.provider_type)
        self.api_key = (provider.api_key or "").strip()
        self.model = (model or provider.text_model or self.meta.get("models", {}).get("text") or "").strip()
        self.last_usage = (0, 0)
        self.base_url = (provider.base_url or self.meta.get("base_url") or self.default_base_url).rstrip("/")
        self.max_tokens = max_tokens or provider.max_tokens or self.meta.get("max_tokens") or 4096

    def _call(self, method, path, operation, **kwargs):
        return call(method, "%s/%s" % (self.base_url, path.lstrip("/")), service="ai", operation=operation,
                    workspace_id=self.provider.workspace_id, ref=("ai_provider", self.provider.id), **kwargs)

    def _require_key(self):
        if not self.api_key and not self.meta.get("no_key"):
            raise ApiError("No API key is set for “%s”." % self.provider.name)
        if not self.model:
            raise ApiError("No model is set for “%s”." % self.provider.name)

    def generate(self, system: str, prompt: str) -> str:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        raise NotImplementedError


class OpenAIClient(BaseAIClient):
    """OpenAI Chat Completions API."""

    default_base_url = "https://api.openai.com/v1"

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        return headers

    def _payload(self, system, prompt):
        return {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            # Current OpenAI models only accept max_completion_tokens.
            "max_completion_tokens": self.max_tokens,
        }

    def generate(self, system, prompt):
        self._require_key()
        data = self._call("POST", "/chat/completions", "Generate text", headers=self._headers(),
                          json_body=self._payload(system, prompt), timeout=180)
        usage = (data.get("usage") or {}) if isinstance(data, dict) else {}
        self.last_usage = (usage.get("prompt_tokens", 0) or 0, usage.get("completion_tokens", 0) or 0)
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            raise ApiError("Unexpected answer from the AI provider.")
        if not text.strip():
            if choice.get("finish_reason") == "length":
                raise ApiError("The AI ran out of tokens. Increase “Max tokens” on the provider.")
            raise ApiError("The AI returned an empty answer.")
        return text.strip()

    def list_models(self):
        data = self._call("GET", "/models", "List models", headers=self._headers(), timeout=20)
        return sorted(m.get("id") for m in (data.get("data") or []) if m.get("id"))


class OpenAICompatibleClient(OpenAIClient):
    """Any server that speaks the OpenAI Chat Completions dialect
    (DeepSeek, Groq, Mistral, OpenRouter, Together, Ollama, LM Studio…)."""

    default_base_url = ""

    def _require_key(self):
        if not self.base_url:
            raise ApiError("Please set the Base URL of the OpenAI-compatible server.")
        super()._require_key()

    def _payload(self, system, prompt):
        payload = super()._payload(system, prompt)
        # Most compatible servers still expect the classic parameter name.
        payload["max_tokens"] = payload.pop("max_completion_tokens")
        return payload

    def list_models(self):
        if not self.base_url:
            raise ApiError("Please set the Base URL of the OpenAI-compatible server.")
        if not self.api_key and not self.meta.get("no_key"):
            raise ApiError("No API key is set for “%s”." % self.provider.name)
        return super().list_models()


class AzureOpenAIClient(OpenAIClient):
    """Azure OpenAI (v1 API). Base URL: https://<resource>.openai.azure.com/openai/v1, model = deployment name."""

    def _headers(self):
        return {"Content-Type": "application/json", "api-key": self.api_key}


class AnthropicClient(BaseAIClient):
    """Anthropic Messages API (Claude): no sampling params, text blocks only, server-side refusal fallback."""

    default_base_url = "https://api.anthropic.com/v1"

    def _headers(self, beta=None):
        headers = {"Content-Type": "application/json", "x-api-key": self.api_key,
                   "anthropic-version": ANTHROPIC_VERSION}
        if beta:
            headers["anthropic-beta"] = beta
        return headers

    def generate(self, system, prompt):
        self._require_key()
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        beta = None
        if self.model in FALLBACK_MODELS and "api.anthropic.com" in self.base_url:
            # If a safety classifier declines, let the API retry on a suitable model.
            payload["fallbacks"] = "default"
            beta = FALLBACK_BETA
        data = self._call("POST", "/messages", "Generate text", headers=self._headers(beta), json_body=payload,
                          timeout=300)
        usage = data.get("usage") or {}
        self.last_usage = (usage.get("input_tokens", 0) or 0, usage.get("output_tokens", 0) or 0)
        stop_reason = data.get("stop_reason")
        if stop_reason == "refusal":
            raise ApiError("Claude declined this request. Try rephrasing the brief.")
        # Responses can include thinking blocks — keep only the text blocks.
        text = "".join(block.get("text", "") for block in data.get("content") or []
                       if block.get("type") == "text").strip()
        if not text:
            if stop_reason == "max_tokens":
                raise ApiError("Claude ran out of tokens. Increase “Max tokens” on the provider.")
            raise ApiError("Claude returned an empty answer.")
        return text

    def list_models(self):
        if not self.api_key:
            raise ApiError("No API key is set for “%s”." % self.provider.name)
        data = self._call("GET", "/models", "List models", headers=self._headers(), params={"limit": 100}, timeout=20)
        return [m["id"] for m in data.get("data") or [] if m.get("id")]


class GeminiClient(BaseAIClient):
    """Google Gemini API (generateContent)."""

    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _headers(self):
        return {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

    def generate(self, system, prompt):
        self._require_key()
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": self.max_tokens},
        }
        model = self.model if self.model.startswith("models/") else "models/%s" % self.model
        data = self._call("POST", "/%s:generateContent" % model, "Generate text", headers=self._headers(),
                          json_body=payload, timeout=180)
        usage = data.get("usageMetadata") or {}
        self.last_usage = (usage.get("promptTokenCount", 0) or 0,
                           (usage.get("candidatesTokenCount", 0) or 0) + (usage.get("thoughtsTokenCount", 0) or 0))
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise ApiError("Gemini blocked this request (%s)." % reason if reason else "Gemini returned no answer.")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        if not text:
            if candidates[0].get("finishReason") == "MAX_TOKENS":
                raise ApiError("Gemini ran out of tokens. Increase “Max tokens” on the provider.")
            raise ApiError("Gemini returned an empty answer.")
        return text

    def list_models(self):
        if not self.api_key:
            raise ApiError("No API key is set for “%s”." % self.provider.name)
        data = self._call("GET", "/models", "List models", headers=self._headers(), params={"pageSize": 200},
                          timeout=20)
        return [m["name"].split("/", 1)[-1] for m in data.get("models") or []
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]


ENGINES = {
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
    "gemini": GeminiClient,
    "openai_compatible": OpenAICompatibleClient,
    "azure": AzureOpenAIClient,
}


def get_client(provider, model: str | None = None, max_tokens: int | None = None) -> BaseAIClient:
    """The text client for an ``AIProvider`` row."""
    meta = catalog.info(provider.provider_type)
    engine = meta.get("engine")
    if not engine or catalog.TEXT not in meta["caps"]:
        raise ApiError("%s does not write text — choose a text provider." % meta["label"])
    return ENGINES[engine](provider, model=model, max_tokens=max_tokens)
