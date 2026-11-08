"""Exercise the shipped jury profiles through the engine and Ollama HTTP client."""
import json

import httpx
import pytest
from test_ollama import mock_server

from cqa.contracts import Settings
from cqa.engine import Engine, recalculate
from cqa.io import fingerprint, read_json
from cqa.ollama_provider import OllamaProvider
from cqa.storage import Store


def jury_settings(filename, tokenizer):
    data = read_json("config/" + filename)
    data.update(context_tokenizer_path=tokenizer.context_tokenizer_path,
                context_tokenizer_sha256=tokenizer.context_tokenizer_sha256)
    return Settings.model_validate(data)


def truncated(content="", done=True):
    return {"done": done, "done_reason": "length", "eval_count": 6000,
            "message": {"role": "assistant", "thinking": "offline fixture", "content": content}}


@pytest.fixture
def run_transport_case(tmp_path, synthetic_ollama_settings, dialogue, checklist, assessment):
    def run(responses, *, filename="settings.product.json", timeout=False):
        settings = jury_settings(filename, synthetic_ollama_settings)
        transport, calls = mock_server(assessment, answers=responses)
        if timeout:
            original_transport = transport

            def fail_chat(request):
                if request.url.path == "/api/chat":
                    calls.append(json.loads(request.content))
                    raise httpx.ReadTimeout("simulated timeout", request=request)
                return original_transport.handle_request(request)

            transport = httpx.MockTransport(fail_chat)
        store = Store(tmp_path / "run.sqlite3")
        provider = OllamaProvider(settings, transport=transport)
        result = Engine(store, settings, provider, sleep=lambda _: None).evaluate(dialogue, checklist)
        return store, result, calls

    return run


@pytest.mark.parametrize("profile", ["settings.product.json", "settings.brev.prod.json"])
def test_shipped_profile_recovers_once_with_same_request_except_thinking(run_transport_case, profile):
    first = truncated()
    store, result, calls = run_transport_case([first, {}], filename=profile)
    assert result["error"] is None and result["status"] == "provisional"
    assert len(calls) == 2 and calls[0]["think"] is True
    assert calls[1] == {**calls[0], "think": False}
    assert calls[0]["format"]["type"] == "object" and calls[0]["options"]["num_predict"] == 6000

    saved = store.get_evaluation(result["evaluation_id"])
    attempts = saved["attempts"]
    assert [a["request"] for a in attempts] == calls
    assert [a["response"]["done_reason"] for a in attempts] == ["length", "stop"]
    assert attempts[0]["response"]["message"] == first["message"]
    assert attempts[0]["call_id"] != attempts[1]["call_id"]
    assert store.budget_summary()["external_compute_calls"] == 2
    assert recalculate(saved) == result["scoring"]
    assert result["scoring"]["total_score"] == "92.31"


def test_success_finishes_with_one_request(run_transport_case):
    store, result, calls = run_transport_case([{}])
    assert result["scoring"] and len(calls) == 1 and calls[0]["think"] is True
    assert store.budget_summary()["external_compute_calls"] == 1


@pytest.mark.parametrize("response,error", [
    (truncated('{"criteria":'), "incomplete_model_response"),
    (truncated(done=False), "incomplete_model_response"),
    ({"message": {"role": "assistant", "content": "{}"}}, "invalid_model_response"),
    (500, "ollama_http_500"),
])
def test_other_failures_keep_first_answer(run_transport_case, response, error):
    store, result, calls = run_transport_case([response])
    assert result["error"] == error and result["scoring"] is None
    assert len(calls) == store.budget_summary()["external_compute_calls"] == 1


def test_unknown_network_outcome_does_not_trigger_a_second_call(run_transport_case):
    store, result, calls = run_transport_case([], timeout=True)
    assert result["error"] == "ollama_connection_or_timeout" and result["scoring"] is None
    assert len(calls) == store.budget_summary()["external_compute_calls"] == 1


def test_failed_direct_answer_has_no_third_attempt(run_transport_case):
    store, result, calls = run_transport_case([truncated(), truncated()])
    assert result["error"] == "incomplete_model_response" and result["scoring"] is None
    assert [c["think"] for c in calls] == [True, False]
    assert store.budget_summary()["external_compute_calls"] == 2


def test_preexisting_experiment_profile_preserves_frozen_hash():
    settings = Settings.model_validate(read_json("config/settings.experiment-control.json"))
    assert fingerprint(settings) == "e66a59beddb9f1c9a74e9c42305f924fb9775756ed09d272b423abe84ca619dd"
