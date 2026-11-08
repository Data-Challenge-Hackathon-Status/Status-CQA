from __future__ import annotations

import os
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, OpenAI


class ProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool, charge_unknown=False):
        self.code = code
        self.retryable = retryable
        self.charge_unknown = charge_unknown
        super().__init__(code)


def get_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    # A desktop app may have been started before the user changed Windows settings.
    # Prefer the currently saved user setting on Windows, without printing or persisting it.
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
                saved, _ = winreg.QueryValueEx(handle, "OPENAI_API_KEY")
                key = saved.strip() or key
        except OSError:
            pass
    if not key:
        raise ProviderError("missing_api_key", retryable=False)
    if not key.startswith("sk-"):
        raise ProviderError("invalid_key_format_use_secret_api_key_not_promo_code", retryable=False)
    return key


@dataclass
class ProviderResponse:
    raw: dict
    text: str
    status: str
    refusal: bool
    metadata: dict | None = None


class OpenAIProvider:
    def __init__(self, timeout=90):
        self.client = OpenAI(api_key=get_api_key(), base_url="https://api.openai.com/v1",
                             max_retries=0, timeout=timeout)

    @staticmethod
    def _error(exc):
        # SDK exception text can contain fragments of credentials. Never log str(exc).
        if isinstance(exc, APIConnectionError):
            return ProviderError("connection_or_timeout", retryable=True, charge_unknown=True)
        code = getattr(exc, "code", None)
        body = getattr(exc, "body", None)
        body = body if isinstance(body, dict) else {}
        error = body.get("error", body)
        error = error if isinstance(error, dict) else {}
        if (code in {"insufficient_quota", "billing_hard_limit_reached", "credit_balance_exhausted"}
                or error.get("type") == "insufficient_quota"
                or error.get("code") in {"insufficient_quota", "credit_balance_exhausted"}):
            return ProviderError("insufficient_quota", retryable=False)
        status = getattr(exc, "status_code", 0)
        return ProviderError(f"http_{status}", retryable=status in {408, 409, 429} or status >= 500,
                             charge_unknown=status >= 500 or status == 408)

    def available_models(self) -> list[str]:
        try:
            return sorted(m.id for m in self.client.models.list())
        except (APIConnectionError, APIStatusError) as exc:
            raise self._error(exc) from None

    def evaluate(self, request: dict) -> ProviderResponse:
        try:
            response = self.client.responses.create(**request)
        except (APIConnectionError, APIStatusError) as exc:
            raise self._error(exc) from None
        raw = response.model_dump(mode="json")
        refusal = any(content.get("type") == "refusal"
                      for item in raw.get("output", []) for content in item.get("content", []))
        return ProviderResponse(raw=raw, text=response.output_text, status=response.status,
                                refusal=refusal)


def create_provider(settings):
    if settings.provider == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(settings)
    return OpenAIProvider(timeout=settings.timeout_seconds)


def build_request(settings, messages, schema, output_limit):
    if settings.provider == "ollama":
        from .io import json_text
        # The schema is both a decoding constraint and a description of the expected answer.
        messages = [dict(message) for message in messages]
        messages[0]["content"] += "\nВерни только JSON по этой схеме:\n" + json_text(schema)
        options = {"num_ctx": settings.ollama_num_ctx, "num_predict": output_limit,
                   "temperature": settings.ollama_temperature, "seed": settings.ollama_seed}
        for name in ("top_p", "top_k", "min_p"):
            value = getattr(settings, "ollama_" + name)
            if value is not None:
                options[name] = value
        return {"model": settings.model, "messages": messages, "format": schema,
                "stream": False, "think": settings.ollama_think, "truncate": False, "shift": False,
                "keep_alive": "10m", "options": options}
    request = {"model": settings.model, "input": messages,
               "text": {"format": {"type": "json_schema", "name": "cqa_assessment",
                                    "strict": True, "schema": schema}},
               "max_output_tokens": output_limit, "store": False, "service_tier": "default"}
    if settings.reasoning_effort is not None:
        request["reasoning"] = {"effort": settings.reasoning_effort}
    return request
