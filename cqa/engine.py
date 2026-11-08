from __future__ import annotations

import hashlib
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from . import __version__
from .context import context_report
from .contracts import Checklist, Dialogue, Knowledge, ModelAssessment, Settings
from .io import fingerprint, json_text, message_index
from .normalization import aggregate_claim_limitations
from .prompting import PROMPT_VERSION, build_input, response_schema
from .provider import ProviderError, build_request, create_provider
from .scoring import calculate
from .storage import BudgetExceeded, Store, utc_now
from .validation import AssessmentError, validate_assessment

VALIDATION_POLICY = "configured-evidence-and-source-3"
LEGACY_EVIDENCE_POLICY = "source-applicability-and-contradiction-2"


def _validation_options(result):
    explicit = result.get("validation_policy")
    if explicit is not None and explicit not in {VALIDATION_POLICY, LEGACY_EVIDENCE_POLICY, "source-applicability-1"}:
        raise ValueError("Неизвестная сохранённая политика проверки; пересчёт запрещён")
    policy = result.get("validation_policy") or {
        "cqa-1.5.0": "source-applicability-1", "cqa-1.5.1": "source-applicability-1",
        "cqa-1.6.0": LEGACY_EVIDENCE_POLICY, "cqa-1.7.0": VALIDATION_POLICY,
        "cqa-1.7.1": VALIDATION_POLICY, "cqa-1.7.2": VALIDATION_POLICY,
    }.get(result.get("prompt_version"))
    evidence = policy in {VALIDATION_POLICY, LEGACY_EVIDENCE_POLICY}
    return {"strict_sources": evidence or policy == "source-applicability-1",
            "require_contradiction_basis": evidence, "require_operator_flag_evidence": evidence,
            "legacy_operator_flags": policy == LEGACY_EVIDENCE_POLICY}


def implementation_hash() -> str:
    files = sorted(Path(__file__).parent.glob("*.py"))
    return hashlib.sha256(b"".join(f.name.encode() + f.read_bytes() for f in files)).hexdigest()


def _ollama_length_without_answer(raw: dict) -> bool:
    message = raw.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return (raw.get("done") is True and raw.get("done_reason") == "length"
            and isinstance(content, str) and not content.strip())


def usage_cost(raw: dict, settings: Settings) -> Decimal | None:
    if settings.pricing is None:
        return None
    usage = raw.get("usage")
    if not usage or "input_tokens" not in usage or "output_tokens" not in usage:
        return None
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    regular = usage["input_tokens"] - cached
    if min(regular, cached, usage["output_tokens"]) < 0:
        return None
    rates = settings.pricing
    return (regular * rates.input_per_million + cached * rates.cached_input_per_million
            + usage["output_tokens"] * rates.output_per_million) / Decimal(1_000_000)


def reservation(request: dict, settings: Settings) -> Decimal:
    if settings.pricing is None:
        return Decimal(0)  # Rental charges are external, not a zero-cost model estimate.
    # UTF-8 bytes form a conservative token bound for these byte-tokenized text inputs.
    # Add envelope overhead. No tools, explicit cache writes or regional/priority tiers are used.
    bound = len(json_text(request).encode("utf-8")) + 4096
    return (bound * settings.pricing.input_per_million
            + request["max_output_tokens"] * settings.pricing.output_per_million) / Decimal(1_000_000)


class Engine:
    def __init__(self, store: Store, settings: Settings, provider=None, sleep=time.sleep):
        self.store, self.settings, self.provider, self.sleep = store, settings, provider, sleep

    def _begin(self, dialogue: Dialogue, checklist: Checklist, knowledge: Knowledge) -> dict:
        external_compute = self.settings.provider == "ollama"
        billing_mode = "external_compute" if external_compute else "api_tokens"
        self.store.save_checklist(checklist)
        self.store.save_dialogues([(dialogue, dialogue.model_dump(mode="json"))])
        result = {
            "evaluation_id": str(uuid4()), "created_at": utc_now(), "status": "running",
            "conversation_id": dialogue.conversation_id, "dialogue": dialogue.model_dump(mode="json"),
            "message_index": message_index(dialogue),
            "dialogue_hash": fingerprint(dialogue), "checklist": checklist.model_dump(mode="json"),
            "checklist_hash": fingerprint(checklist), "knowledge": knowledge.model_dump(mode="json"),
            "knowledge_hash": fingerprint(knowledge), "settings": self.settings.model_dump(mode="json"),
            "prompt_version": PROMPT_VERSION, "implementation_version": __version__,
            "validation_policy": VALIDATION_POLICY,
            "implementation_hash": implementation_hash(), "attempts": [], "assessment": None,
            "scoring": None, "error": None, "needs_review": False, "limitations": [],
            "estimated_cost_usd": None if external_compute else "0", "billing_uncertain": external_compute,
            "billing_mode": billing_mode,
        }
        if dialogue.channel == "voice call":
            result["limitations"].append("Анализ только транскрипта: дикция, произношение, темп и интонация не проверены.")
            result["limitations"].append("Метка operator может объединять нескольких сотрудников; персональная атрибуция не подтверждена.")
        self.store.save_evaluation(result)
        return result

    def fail_without_call(self, dialogue: Dialogue, checklist: Checklist, error: str,
                          knowledge: Knowledge | None = None) -> dict:
        result = self._begin(dialogue, checklist, knowledge or Knowledge())
        result.update(status="failed", error=error)
        self.store.save_evaluation(result)
        return result

    def evaluate(self, dialogue: Dialogue, checklist: Checklist, knowledge: Knowledge | None = None,
                 *, prepared: dict | None = None) -> dict:
        started = time.perf_counter()
        result = self._evaluate(dialogue, checklist, knowledge, prepared=prepared)
        result["elapsed_seconds"] = time.perf_counter() - started
        self.store.save_evaluation(result)
        return result

    def _evaluate(self, dialogue: Dialogue, checklist: Checklist, knowledge: Knowledge | None = None,
                  *, prepared: dict | None = None) -> dict:
        knowledge = knowledge or Knowledge()
        if prepared is not None:
            if self.settings.max_attempts != 1:
                raise ValueError("Замороженный опыт допускает ровно одну попытку")
            for key, value in (("dialogue_hash", dialogue), ("checklist_hash", checklist),
                               ("knowledge_hash", knowledge), ("settings_hash", self.settings)):
                if prepared[key] != fingerprint(value):
                    raise ValueError("Снимок подготовленного запроса изменён: " + key)
            supplied = prepared["request"]
            expected = build_request(self.settings, [{"role": "system", "content": ""}], {},
                                     self.settings.max_output_tokens)
            if ({k: v for k, v in supplied.items() if k not in {"messages", "format"}} !=
                    {k: v for k, v in expected.items() if k not in {"messages", "format"}}):
                raise ValueError("Параметры подготовленного запроса не совпадают с настройками")
        result = self._begin(dialogue, checklist, knowledge)
        if prepared is not None:
            result["prompt_version"] = prepared["prompt_version"]
            if prepared["prompt_version"] != PROMPT_VERSION:
                result["validation_policy"] = (
                    VALIDATION_POLICY if prepared["prompt_version"] in {"cqa-1.7.0", "cqa-1.7.1", "cqa-1.7.2"}
                    else LEGACY_EVIDENCE_POLICY if prepared["prompt_version"] == "cqa-1.6.0"
                    else "source-applicability-1")
            result["prepared_job_hash"] = fingerprint(prepared)
            result["prompt_origin"] = prepared.get("prompt_origin")
        external_compute = self.settings.provider == "ollama"
        billing_mode = result["billing_mode"]
        previous_errors = None
        spent = Decimal(0)
        output_limit = self.settings.max_output_tokens
        direct_retry_only = self.settings.ollama_retry_without_thinking_on_length
        next_request = prepared["request"] if prepared is not None else None
        try:
            provider = self.provider or create_provider(self.settings)
        except ProviderError as exc:
            result.update(status="failed", error=exc.code)
            self.store.save_evaluation(result)
            return result
        for number in range(1, self.settings.max_attempts + 1):
            try:
                if next_request is None:
                    request = build_request(
                        self.settings, build_input(dialogue, checklist, knowledge, previous_errors),
                        response_schema(checklist, knowledge, dialogue), output_limit)
                else:
                    request = next_request
                    next_request = None
            except ValueError as exc:
                result.update(status="failed", error="request_preflight:" + str(exc))
                break
            if len(json_text(request).encode("utf-8")) > self.settings.max_input_bytes:
                result.update(status="failed", error="input_too_large_no_truncation_performed")
                break
            try:
                context = context_report(request, self.settings)
            except (ValueError, OSError, ImportError) as exc:
                result.update(status="failed", error="context_preflight:" + type(exc).__name__)
                break
            result["context_preflight"] = context
            if not context["fits"]:
                result.update(status="failed", error="context_budget_exceeded_no_truncation_performed")
                break
            try:
                call_id = self.store.reserve_call(result["evaluation_id"], reservation(request, self.settings),
                                                  self.settings.budget_usd, request, billing_mode=billing_mode,
                                                  call_limit=self.settings.max_calls)
            except BudgetExceeded:
                result.update(status="failed", error="local_call_limit_exceeded" if external_compute else "local_budget_exceeded")
                break
            attempt = {"number": number, "call_id": call_id, "request": request,
                       "started_at": utc_now(), "response": None, "errors": [], "context_preflight": context}
            result["attempts"].append(attempt)
            self.store.save_evaluation(result)
            retryable = False
            try:
                response = provider.evaluate(request)
                attempt["response"] = response.raw
                attempt["response_text"] = response.text
                attempt["provider_metadata"] = response.metadata
                cost = usage_cost(response.raw, self.settings)
                spent += cost or Decimal(0)
                result["estimated_cost_usd"] = None if external_compute else str(spent)
                result["billing_uncertain"] |= cost is None
                self.store.finish_call(call_id, cost=cost, state="response_received",
                                       payload={"response": response.raw})
                if response.refusal:
                    result.update(status="failed", error="model_refusal")
                elif response.status != "completed":
                    result.update(status="failed", error="incomplete_model_response")
                    if direct_retry_only:
                        if number == 1 and request["think"] and _ollama_length_without_answer(response.raw):
                            next_request = {**request, "think": False}
                            attempt["retry_reason"] = "ollama_length_without_final_content"
                            retryable = True
                    else:
                        previous_errors = ["Предыдущий ответ не завершён. Дай краткий, но полный ответ по всем критериям."]
                        output_limit = min(output_limit * 2, 32000)
                        retryable = True
                else:
                    try:
                        assessment = ModelAssessment.model_validate_json(response.text)
                        if result["prompt_version"] == "cqa-1.7.2":
                            assessment, transformation = aggregate_claim_limitations(assessment)
                            attempt["assessment_transformation"] = transformation
                        validate_assessment(assessment, dialogue, checklist, knowledge, **_validation_options(result))
                        score = calculate(assessment, checklist)
                    except (ValidationError, AssessmentError) as exc:
                        if isinstance(exc, AssessmentError):
                            previous_errors = exc.errors
                        else:
                            previous_errors = ["Ошибка структуры в " + ".".join(map(str, e["loc"]))
                                               + ": " + e["type"] for e in exc.errors()]
                        attempt["errors"] = previous_errors
                        result.update(status="failed", error="invalid_model_response")
                        retryable = not direct_retry_only
                    else:
                        unverified = any(d.knowledge_status == "unverified" for d in assessment.criteria.values())
                        result.update(status="provisional" if unverified else "completed", error=None,
                                      assessment=assessment.model_dump(mode="json"), scoring=score,
                                      needs_review=unverified)
                        for decision in assessment.criteria.values():
                            result["limitations"].extend(decision.limitations)
                        result["limitations"] = list(dict.fromkeys(result["limitations"]))
            except ProviderError as exc:
                result.update(status="failed", error=exc.code)
                attempt["errors"] = [exc.code]
                result["billing_uncertain"] |= exc.charge_unknown
                self.store.finish_call(call_id, cost=None if external_compute or exc.charge_unknown else Decimal(0),
                                       state="provider_error", payload={"error": exc.code})
                retryable = exc.retryable and not direct_retry_only
            except Exception as exc:  # noqa: BLE001 -- persist a safe failure at the external-call boundary
                # Keep the reservation; an unexpected client error can happen after billing.
                result.update(status="failed", error="internal_error:" + type(exc).__name__, billing_uncertain=True)
                attempt["errors"] = [result["error"]]
                self.store.finish_call(call_id, cost=None, state="internal_error",
                                       payload={"error": result["error"]})
            attempt["finished_at"] = utc_now()
            self.store.save_evaluation(result)
            if not retryable:
                break
            if number < self.settings.max_attempts:
                self.sleep(2 ** number)
        self.store.save_evaluation(result)
        return result


def recalculate(result: dict) -> dict:
    if not result.get("assessment"):
        raise ValueError("Нет принятого результата модели для пересчёта")
    dialogue = Dialogue.model_validate(result["dialogue"])
    checklist = Checklist.model_validate(result["checklist"])
    knowledge = Knowledge.model_validate(result["knowledge"])
    assessment = ModelAssessment.model_validate(result["assessment"])
    if (fingerprint(checklist) != result["checklist_hash"] or fingerprint(dialogue) != result["dialogue_hash"]
            or fingerprint(knowledge) != result["knowledge_hash"]):
        raise ValueError("Содержимое снимка изменено")
    validate_assessment(assessment, dialogue, checklist, knowledge, **_validation_options(result))
    return calculate(assessment, checklist)
