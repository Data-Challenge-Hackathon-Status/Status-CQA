import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cqa.api import create_app
from cqa.contracts import Settings
from cqa.engine import Engine, recalculate
from cqa.ollama_provider import OllamaProvider
from cqa.provider import ProviderError
from cqa.reporting import text_report
from cqa.storage import BudgetExceeded, Store


@pytest.fixture
def brev_settings(synthetic_ollama_settings):
    return synthetic_ollama_settings


def mock_server(assessment, *, answers=None, version="0.40.15", remote=False):
    captured = []
    values = iter(answers) if answers is not None else None

    def handler(request):
        assert "authorization" not in request.headers
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": version})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:32b", "digest": "test-digest",
                "details": {"quantization_level": "Q4_K_M"}, "remote_host": "cloud" if remote else ""}]})
        assert request.url.path == "/api/chat"
        captured.append(json.loads(request.content))
        value = next(values) if values is not None else {}
        if isinstance(value, int):
            return httpx.Response(value, json={"error": "Do not log sensitive server error text"})
        raw = {"model": "qwen3:32b", "done": True, "done_reason": "stop",
               "message": {"role": "assistant", "content": assessment.model_dump_json()},
               "prompt_eval_count": 8000, "eval_count": 2500}
        raw.update(value)
        return httpx.Response(200, json=raw)

    return httpx.MockTransport(handler), captured


def test_ollama_round_trip_preserves_evidence_schema_and_versions(
        tmp_path, brev_settings, dialogue, checklist, assessment, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "canary-never-send-to-ollama")
    transport, requests = mock_server(assessment)
    store = Store(tmp_path / "db")
    result = Engine(store, brev_settings, OllamaProvider(brev_settings, transport=transport)).evaluate(dialogue, checklist)
    assert result["status"] == "provisional"
    assert result["scoring"]["total_score"] == "92.31"
    assert recalculate(store.get_evaluation(result["evaluation_id"])) == result["scoring"]
    assert result["attempts"][0]["provider_metadata"]["model_digest"] == "test-digest"
    assert result["attempts"][0]["response"]["prompt_eval_count"] == 8000
    request = requests[0]
    assert request["stream"] is False and request["truncate"] is False and request["shift"] is False
    assert request["options"]["num_ctx"] == 32768
    assert request["options"]["num_predict"] == 6000
    assert "max_output_tokens" not in request and "reasoning" not in request
    assert request["format"]["properties"]["criteria"]["properties"]["c6"]["properties"]["answer"]["enum"] == ["0", "4", "7", "10"]
    assert "canary-never-send-to-ollama" not in json.dumps(result)
    assert result["estimated_cost_usd"] is None
    assert store.budget_summary()["external_compute_calls"] == 1
    assert store.budget_summary()["external_compute_cost_usd"] is None
    report = text_report(result)
    assert "аренда сервера" in report and "$0" not in report and "$None" not in report


@pytest.mark.parametrize("changes", [
    {"base_url": "https://example.com"},
    {"base_url": "http://secret@127.0.0.1:11435"},
    {"base_url": "http://127.0.0.1:11435/?key=secret"},
    {"budget_usd": "5"},
    {"ollama_version": "old-version"},
])
def test_ollama_rejects_unsafe_or_misleading_configuration(brev_settings, changes):
    data = brev_settings.model_dump(mode="json")
    data.update(changes)
    with pytest.raises(ValidationError):
        Settings.model_validate(data)


def test_openai_requires_known_prices(settings):
    data = settings.model_dump(mode="json")
    data["pricing"] = None
    with pytest.raises(ValidationError):
        Settings.model_validate(data)


@pytest.mark.parametrize("options,expected", [
    ({"version": "0.1.0"}, "ollama_version_mismatch"),
    ({"remote": True}, "ollama_cloud_model_not_allowed"),
])
def test_incompatible_server_cannot_receive_dialogue(brev_settings, assessment, options, expected):
    transport, requests = mock_server(assessment, **options)
    with pytest.raises(ProviderError) as error:
        OllamaProvider(brev_settings, transport=transport).evaluate({})
    assert error.value.code == expected
    assert not requests


def test_context_rejection_fails_without_total_or_retry(
        tmp_path, brev_settings, dialogue, checklist, assessment):
    transport, requests = mock_server(assessment, answers=[400])
    result = Engine(Store(tmp_path / "db"), brev_settings,
                    OllamaProvider(brev_settings, transport=transport)).evaluate(dialogue, checklist)
    assert result["scoring"] is None and result["error"] == "ollama_http_400"
    assert len(requests) == 1
    assert "sensitive server error" not in json.dumps(result)


@pytest.mark.parametrize("first", [500, {"done_reason": "length"},
    {"message": {"role": "assistant", "content": '{"criteria": {}}'}}])
def test_retryable_response_reuses_validation_and_bounded_retries(
        tmp_path, brev_settings, dialogue, checklist, assessment, first):
    transport, requests = mock_server(assessment, answers=[first, {}])
    result = Engine(Store(tmp_path / "db"), brev_settings,
                    OllamaProvider(brev_settings, transport=transport), sleep=lambda _: None).evaluate(dialogue, checklist)
    assert result["scoring"]["total_score"] == "92.31" and len(requests) == 2
    if isinstance(first, dict) and first.get("done_reason") == "length":
        assert requests[1]["options"]["num_predict"] == 12000
    if isinstance(first, dict) and "message" in first:
        assert "VALIDATION_ERRORS_TO_FIX" in requests[1]["messages"][1]["content"]


def test_missing_evidence_is_never_accepted_from_ollama(
        tmp_path, brev_settings, dialogue, checklist, assessment):
    wrong = assessment.model_copy(deep=True)
    wrong.criteria["c1"].evidence[0].end_message_id = "m999"
    transport, requests = mock_server(wrong)
    result = Engine(Store(tmp_path / "db"), brev_settings,
                    OllamaProvider(brev_settings, transport=transport), sleep=lambda _: None).evaluate(dialogue, checklist)
    assert result["status"] == "failed" and result["scoring"] is None
    assert len(requests) == brev_settings.max_attempts


def test_count_limit_prevents_additional_model_calls(
        tmp_path, brev_settings, dialogue, checklist, assessment):
    brev_settings.max_calls = 1
    transport, requests = mock_server(assessment)
    engine = Engine(Store(tmp_path / "db"), brev_settings, OllamaProvider(brev_settings, transport=transport))
    assert engine.evaluate(dialogue, checklist)["scoring"]
    result = engine.evaluate(dialogue, checklist)
    assert result["error"] == "local_call_limit_exceeded"
    assert result["scoring"] is None and len(requests) == 1


def test_request_count_limit_is_atomic(tmp_path):
    store = Store(tmp_path / "db")

    def reserve(_):
        try:
            store.reserve_call("evaluation", Decimal(0), None, {}, billing_mode="external_compute", call_limit=2)
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=6) as executor:
        assert sum(executor.map(reserve, range(6))) == 2


def test_old_call_ledger_migrates_without_losing_api_reservations(tmp_path):
    path = tmp_path / "db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE calls (id TEXT PRIMARY KEY, evaluation_id TEXT, charge_ceiling TEXT, "
                   "actual_cost TEXT, state TEXT, payload TEXT)")
        db.execute("INSERT INTO calls VALUES ('old','eval','1.25',NULL,'reserved','{}')")
    store = Store(path)
    assert store.budget_summary()["accounted_usd"] == "1.25"
    assert store.budget_summary()["uncertain_calls"] == 1
    external = store.reserve_call("new", Decimal(0), None, {}, billing_mode="external_compute", call_limit=1)
    store.finish_call(external, cost=None, state="response_received", payload={})
    summary = store.budget_summary()
    assert summary["accounted_usd"] == "1.25" and summary["uncertain_calls"] == 1
    assert summary["calls"] == 2 and summary["external_compute_calls"] == 1


def test_http_api_uses_brev_settings_and_reports_external_cost(
        tmp_path, brev_settings, dialogue, checklist, assessment):
    transport, _ = mock_server(assessment)
    from cqa.io import write_json
    profile = tmp_path / "settings.json"
    write_json(profile, brev_settings)
    app = create_app(db_path=tmp_path / "db", settings_path=profile,
                     provider=OllamaProvider(brev_settings, transport=transport))
    with TestClient(app) as client:
        assert client.post("/conversations/import", json=dialogue.model_dump(mode="json")).status_code == 200
        response = client.post("/evaluations", json={"conversation_id": dialogue.conversation_id,
            "checklist_id": checklist.id, "checklist_version": checklist.version})
        assert response.status_code == 200
        assert response.json()["scoring"]["total_score"] == "92.31"
        assert response.json()["estimated_cost_usd"] is None
        assert client.get("/budget").json()["external_compute_calls"] == 1
