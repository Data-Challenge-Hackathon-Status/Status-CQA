from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Message(Record):
    id: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
    speaker: Literal["client", "operator", "bot", "system"]
    text: str


class Dialogue(Record):
    conversation_id: str = Field(min_length=1)
    channel: Literal["agent chat", "voice call"]
    language: Literal["RU", "KZ", "EN"]
    transcript: list[Message] = Field(min_length=1)
    audio_url: str | None = None

    @model_validator(mode="after")
    def unique_messages(self):
        if len({m.id for m in self.transcript}) != len(self.transcript):
            raise ValueError("Идентификаторы сообщений повторяются")
        if not any(m.speaker == "operator" for m in self.transcript):
            raise ValueError("В разговоре нет реплик оцениваемого оператора")
        return self


class Option(Record):
    value: str = Field(min_length=1)
    raw_score: Decimal = Field(ge=0)
    description: str = Field(min_length=1)


class NACondition(Record):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    channels: list[Literal["agent chat", "voice call"]] | None = Field(default=None, min_length=1)

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        data = handler(self)
        if self.channels is None:
            data.pop("channels", None)
        return data


class Criterion(Record):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    title: str = Field(min_length=1)
    section: str = Field(min_length=1)
    kind: Literal["binary", "scale", "flag"]
    weight: Decimal = Field(ge=0)
    max_score: Decimal = Field(gt=0)
    rule: str = Field(min_length=1)
    options: list[Option] = Field(min_length=2)
    na_conditions: list[NACondition] = Field(default_factory=list)
    channel_rules: dict[str, str] = Field(default_factory=dict)
    requires_company_knowledge: bool = False
    max_observed_facts: int | None = Field(default=None, ge=1)
    violation_value: str | None = None
    flag_evidence_mode: Literal["operator_action"] | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        data = handler(self)
        if self.flag_evidence_mode is None:
            data.pop("flag_evidence_mode", None)
        if self.max_observed_facts is None:
            data.pop("max_observed_facts", None)
        return data

    @model_validator(mode="after")
    def coherent(self):
        values = [x.value for x in self.options]
        if len(set(values)) != len(values) or "na" in values:
            raise ValueError("Значения ответов должны быть уникальны; na зарезервировано")
        if max(x.raw_score for x in self.options) != self.max_score:
            raise ValueError("Верхняя ступень должна совпадать с max_score")
        if min(x.raw_score for x in self.options) != 0:
            raise ValueError("Шкала должна содержать нулевую ступень")
        if len({x.id for x in self.na_conditions}) != len(self.na_conditions):
            raise ValueError("Условия N/A повторяются")
        if self.kind == "flag":
            if self.weight != 0 or self.violation_value not in values:
                raise ValueError("Флаг требует нулевого веса и допустимого violation_value")
        elif self.violation_value is not None:
            raise ValueError("violation_value используется только для флага")
        if self.flag_evidence_mode is not None and self.kind != "flag":
            raise ValueError("flag_evidence_mode используется только для флага")
        if self.max_observed_facts is not None and not self.requires_company_knowledge:
            raise ValueError("max_observed_facts применяется к критерию с проверкой знаний")
        return self


class Checklist(Record):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    total_max: Decimal = Field(default=Decimal(100), gt=0)
    notes: str = ""
    criteria: list[Criterion] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_criteria(self):
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("Идентификаторы критериев повторяются")
        return self


class Evidence(Record):
    kind: Literal["quote", "range", "missing_action"]
    start_message_id: str
    end_message_id: str
    quote: str | None
    expected_action: str | None


class ObservedFact(Record):
    statement: str = Field(min_length=1)
    message_ids: list[str] = Field(min_length=1)


class ContradictionBasis(Record):
    source_id: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    kind: Literal["explicit_denial", "incompatible_value", "exhaustive_rule"]
    explanation: str = Field(min_length=1)


class ExternalClaim(Record):
    statement: str = Field(min_length=1)
    message_ids: list[str] = Field(min_length=1)
    status: Literal["supported", "contradicted", "unverified"]
    source_ids: list[str]
    limitation: str | None
    # Relation to the saved text is distinct from applicability to this case.
    document_relation: Literal["supports", "contradicts", "not_established"] | None = None
    contradiction_basis: ContradictionBasis | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        data = handler(self)
        if self.contradiction_basis is None:
            data.pop("contradiction_basis", None)  # Keep older assessment fingerprints readable.
        return data


class KnowledgeReview(Record):
    coverage: str = Field(min_length=1)
    observed_facts: list[ObservedFact] = Field(min_length=1)
    external_claims: list[ExternalClaim]


class Decision(Record):
    answer: str
    reason: str = Field(min_length=1)
    na_condition_id: str | None
    evidence: list[Evidence] = Field(min_length=1)
    knowledge_status: Literal["not_needed", "supported", "contradicted", "unverified"]
    source_ids: list[str]
    limitations: list[str]
    # Old saved assessments remain readable; new model requests require this field.
    knowledge_review: KnowledgeReview | None = None


class ModelAssessment(Record):
    criteria: dict[str, Decision]


class Source(Record):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    effective_date: str | None = None
    provenance: dict | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        data = handler(self)
        if self.provenance is None:
            data.pop("provenance", None)
        return data


class Knowledge(Record):
    version: str = "none"
    sources: list[Source] = Field(default_factory=list)
    selection: dict | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        data = handler(self)
        if self.selection is None:
            data.pop("selection", None)
        return data

    @model_validator(mode="after")
    def unique_sources(self):
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("Идентификаторы источников повторяются")
        return self


class Pricing(Record):
    input_per_million: Decimal = Field(gt=0)
    cached_input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(gt=0)
    source: str
    checked_on: date

    @model_validator(mode="after")
    def cache_rate(self):
        if self.cached_input_per_million > self.input_per_million:
            raise ValueError("Цена кешированного входа выше обычного входа")
        return self


class Settings(Record):
    provider: Literal["openai", "ollama"] = "openai"
    model: str = Field(min_length=1)
    base_url: str | None = None
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    max_output_tokens: int = Field(default=6000, ge=1000, le=32000)
    timeout_seconds: float = Field(default=90, ge=1, le=300)
    max_attempts: int = Field(default=3, ge=1, le=3)
    budget_usd: Decimal | None = Field(default=Decimal(5), gt=0)
    max_input_bytes: int = Field(default=150000, ge=1000, le=1000000)
    pricing: Pricing | None = None
    max_calls: int = Field(default=20, ge=1, le=10000)
    ollama_version: str | None = None
    ollama_num_ctx: int = Field(default=32768, ge=8192, le=32768)
    ollama_think: bool = False
    ollama_temperature: float = Field(default=0, ge=0, le=2)
    ollama_seed: int = 42
    ollama_top_p: float | None = Field(default=None, gt=0, le=1)
    ollama_top_k: int | None = Field(default=None, ge=0, le=100000, strict=True)
    ollama_min_p: float | None = Field(default=None, ge=0, le=1)
    context_tokenizer_path: str | None = None
    context_tokenizer_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    context_safety_tokens: int | None = Field(default=None, ge=512, le=8192)

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        data = handler(self)
        # Do not change hashes of historical settings when new options are absent.
        for key in ("ollama_top_p", "ollama_top_k", "ollama_min_p", "context_tokenizer_path",
                    "context_tokenizer_sha256", "context_safety_tokens"):
            if getattr(self, key) is None:
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def provider_settings(self):
        if bool(self.context_tokenizer_path) != bool(self.context_tokenizer_sha256):
            raise ValueError("Токенизатор требует путь и SHA256 вместе")
        if self.provider == "openai":
            if self.pricing is None or self.budget_usd is None:
                raise ValueError("Для OpenAI нужны тарифы и денежный лимит")
            if self.base_url is not None:
                raise ValueError("Адрес OpenAI фиксирован; base_url используется только для Ollama")
        else:
            from urllib.parse import urlsplit
            url = urlsplit(self.base_url or "")
            if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}
                    or url.username or url.password or url.path not in {"", "/"}
                    or url.query or url.fragment):
                raise ValueError("Ollama подключается только через локальный адрес SSH-туннеля без ключей")
            if self.pricing is not None or self.budget_usd is not None:
                raise ValueError("Для аренды сервера pricing и budget_usd должны быть null; расход проверяется в Brev")
            if self.reasoning_effort is not None:
                raise ValueError("Ollama использует ollama_think, а не reasoning_effort")
            if self.ollama_version != "0.40.15":
                raise ValueError("Для защиты от обрезания контекста пока поддерживается Ollama 0.40.15")
        return self


def parse_timestamp(timestamp: str, channel: str) -> float:
    """Parse separately; never rewrite the original timestamp or reorder messages."""
    if channel == "agent chat":
        import re
        if not re.fullmatch(r"\d{2,}:[0-5]\d", timestamp):
            raise ValueError("Для чата ожидается исходная метка MM:SS")
        minutes, seconds = map(int, timestamp.split(":"))
        return minutes * 60 + seconds
    value = datetime.fromisoformat(timestamp)
    if value.utcoffset() is None:
        raise ValueError("Метка звонка должна содержать часовой пояс")
    return value.timestamp()
