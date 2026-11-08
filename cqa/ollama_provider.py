from __future__ import annotations

import httpx

from .contracts import Settings
from .provider import ProviderError, ProviderResponse


class OllamaProvider:
    """Native Ollama API over a loopback SSH forward; no cloud API credentials."""

    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    def _json(self, method, path, payload=None):
        try:
            # Ignore proxy variables and never follow redirects carrying dialogue data.
            with httpx.Client(base_url=self.settings.base_url,
                              timeout=min(10, self.settings.timeout_seconds) if method == "GET"
                              else self.settings.timeout_seconds, trust_env=False,
                              follow_redirects=False, transport=self.transport) as client:
                response = client.request(method, path, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ProviderError(f"ollama_http_{status}", retryable=status in {408, 429} or status >= 500) from None
        except httpx.RequestError:
            raise ProviderError("ollama_connection_or_timeout", retryable=True) from None
        try:
            data = response.json()
        except ValueError:
            raise ProviderError("ollama_invalid_json", retryable=True) from None
        if not isinstance(data, dict) or data.get("error"):
            raise ProviderError("ollama_invalid_response", retryable=False)
        return data

    def inspect(self):
        version = self._json("GET", "/api/version").get("version")
        if version != self.settings.ollama_version:
            raise ProviderError("ollama_version_mismatch", retryable=False)
        models = self._json("GET", "/api/tags").get("models")
        if not isinstance(models, list) or any(not isinstance(m, dict) for m in models):
            raise ProviderError("ollama_invalid_model_list", retryable=False)
        selected = next((m for m in models if m.get("name") == self.settings.model), None)
        if selected and (selected.get("remote_host") or selected.get("remote_model")):
            raise ProviderError("ollama_cloud_model_not_allowed", retryable=False)
        if selected and not selected.get("digest"):
            raise ProviderError("ollama_missing_model_digest", retryable=False)
        return {"server_version": version, "model_available": selected is not None,
                "model_digest": selected.get("digest") if selected else None,
                "model_details": selected.get("details") if selected else None,
                "available_models": [m["name"] for m in models if isinstance(m.get("name"), str)]}

    def evaluate(self, request):
        metadata = self.inspect()
        if not metadata["model_available"]:
            raise ProviderError("ollama_model_not_installed", retryable=False)
        raw = self._json("POST", "/api/chat", request)
        message = raw.get("message")
        if (not isinstance(message, dict) or not isinstance(message.get("content"), str)
                or message.get("role") != "assistant" or message.get("tool_calls")
                or raw.get("model") != self.settings.model):
            raise ProviderError("ollama_invalid_message", retryable=False)
        status = "completed" if raw.get("done") is True and raw.get("done_reason") == "stop" else "incomplete"
        return ProviderResponse(raw=raw, text=message["content"], status=status,
                                refusal=False, metadata=metadata)
