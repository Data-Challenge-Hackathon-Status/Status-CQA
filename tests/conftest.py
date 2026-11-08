import hashlib
import json

import pytest

from cqa.contracts import Checklist, Knowledge, ModelAssessment, Settings
from cqa.io import load_dialogues, read_json
from cqa.provider import ProviderResponse


@pytest.fixture
def checklist():
    return Checklist.model_validate(read_json("config/checklist.claims-v1.json"))


@pytest.fixture
def dialogue():
    return load_dialogues(read_json("examples/dialogue.json"))[0][0]


@pytest.fixture
def settings():
    return Settings.model_validate(read_json("config/settings.json"))


@pytest.fixture
def synthetic_ollama_settings(tmp_path):
    """Small offline tokenizer for provider tests, never an estimate for real Qwen."""
    from tokenizers import Tokenizer, models, pre_tokenizers
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    path = tmp_path / "synthetic-tokenizer.json"
    tokenizer.save(str(path))
    values = read_json("config/settings.brev.json")
    values.update(context_tokenizer_path=str(path),
                  context_tokenizer_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  context_safety_tokens=1024)
    return Settings.model_validate(values)


@pytest.fixture
def knowledge():
    return Knowledge()


def decision(answer, *, na=None, unverified=False):
    return {"answer": answer, "reason": "Проверяемый учебный пример, не оценка DEV.",
            "na_condition_id": na,
            "evidence": [{"kind": "range", "start_message_id": "m1", "end_message_id": "m5",
                          "quote": None, "expected_action": None}],
            "knowledge_status": "unverified" if unverified else "not_needed", "source_ids": [],
            "limitations": ["Нет материалов компании"] if unverified else []}


@pytest.fixture
def assessment():
    return ModelAssessment.model_validate({"criteria": {
        "c1": decision("yes"), "c2": decision("na", na="enough_information_initially"),
        "c3": decision("na", na="identification_not_required"), "c4": decision("20", unverified=True),
        "c5": decision("yes"), "c6": decision("10"), "c7": decision("no"), "c8": decision("no")}})


def provider_response(value, *, status="completed", refusal=False):
    text = value.model_dump_json() if isinstance(value, ModelAssessment) else json.dumps(value)
    raw = {"id": "test-response", "status": status, "model": "test-model",
           "usage": {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 0},
                     "output_tokens": 200},
           "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
    return ProviderResponse(raw=raw, text=text, status=status, refusal=refusal)


class FakeProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result
