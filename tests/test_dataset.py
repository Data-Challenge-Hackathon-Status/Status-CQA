import pytest

from cqa.cli import parser, run
from cqa.context import context_report
from cqa.contracts import Checklist, Settings
from cqa.dataset import evaluate_dataset
from cqa.io import fingerprint, read_json, write_json
from cqa.storage import Store
from cqa.submission import SubmissionSettings
from tests.conftest import FakeProvider, provider_response
from tests.test_format_contract import valid_answer


def dataset_records(dialogue):
    result = []
    for i in range(10):
        d = dialogue.model_copy(update={"conversation_id": f"prod-{i}"}, deep=True)
        result.append((d, d.model_dump(mode="json")))
    return result


def test_control_cli_uses_reviewed_rubric_and_exports_new_ids(tmp_path, dialogue, monkeypatch,
                                                             synthetic_ollama_settings):
    checklist = Checklist.model_validate(read_json("config/checklist.review-v4.1.json"))
    control = Settings.model_validate(read_json("config/settings.brev.prod.json"))
    product = Settings.model_validate(read_json("config/settings.product.json"))
    assert control.model_dump(exclude={"timeout_seconds"}) == product.model_dump(exclude={"timeout_seconds"})
    assert control.timeout_seconds == 180 and control.max_attempts == 1
    assert checklist.version == "1.2.1"
    provider = FakeProvider([provider_response(valid_answer(checklist)) for _ in range(10)])
    monkeypatch.setattr("cqa.engine.create_provider", lambda settings: provider)

    # Keep the test runnable in a fresh installation without downloading the large Qwen tokenizer.
    def offline_context(request, settings):
        assert settings == control
        return context_report(request, settings.model_copy(update={
            "context_tokenizer_path": synthetic_ollama_settings.context_tokenizer_path,
            "context_tokenizer_sha256": synthetic_ollama_settings.context_tokenizer_sha256}))

    monkeypatch.setattr("cqa.engine.context_report", offline_context)
    source, runs, output = (tmp_path / name for name in ("input.json", "runs.json", "results.json"))
    records = [raw for _, raw in dataset_records(dialogue)]
    write_json(source, {"isSuccess": True, "data": {"records": records, "total_records": 10}})
    common = ["--db", str(tmp_path / "audit.sqlite3")]
    args = parser().parse_args([*common, "evaluate-set", str(source), "--dataset", "prod",
                                "--runs", str(runs), "--output", str(output)])
    assert run(args) == 0
    assert len(provider.requests) == 10
    manifest = read_json(runs)
    assert manifest["signature"]["checklist_hash"] == fingerprint(checklist)
    assert manifest["signature"]["settings_hash"] == fingerprint(control)
    rows = read_json(output)["results"]
    assert [row["conversation_id"] for row in rows] == [record["conversation_id"] for record in records]
    assert all(row["status"] == "ok" and len(row["criteria"]) == 8 for row in rows)
    assert run(parser().parse_args([*common, "validate-results", str(output), "--input", str(source),
                                    "--dataset", "prod"])) == 0


def test_whole_set_exports_and_resume_does_not_repeat_calls(tmp_path, dialogue, checklist,
                                                          knowledge, settings, assessment):
    store = Store(tmp_path / "db")
    provider = FakeProvider([provider_response(assessment) for _ in range(10)])
    kwargs = {"dataset": "prod", "runs_path": tmp_path / "runs.json", "output": tmp_path / "results.json",
              "max_minutes": 40, "provider": provider}
    args = (store, settings, dataset_records(dialogue), checklist, knowledge, SubmissionSettings(team_name="Status"))
    payload = evaluate_dataset(*args, **kwargs)
    assert len(provider.requests) == 10
    assert len(payload["results"]) == 10
    assert all(r["status"] == "ok" for r in payload["results"])
    assert len(read_json(kwargs["runs_path"])["evaluation_ids"]) == 10
    assert evaluate_dataset(*args, **kwargs, resume=True) == payload
    assert len(provider.requests) == 10
    with pytest.raises(ValueError, match="--resume"):
        evaluate_dataset(*args, **kwargs)
    settings.model = "different-model"
    with pytest.raises(ValueError, match="изменились"):
        evaluate_dataset(*args, **kwargs, resume=True)


def test_deadline_keeps_all_ids_and_never_calls_model(tmp_path, dialogue, checklist, knowledge, settings):
    store = Store(tmp_path / "db")
    provider = FakeProvider([])
    timestamps = iter([0] + [61] * 10)
    payload = evaluate_dataset(store, settings, dataset_records(dialogue), checklist, knowledge,
                               SubmissionSettings(team_name="Status"), dataset="prod",
                               runs_path=tmp_path / "runs.json", output=tmp_path / "results.json",
                               max_minutes=1, provider=provider, clock=lambda: next(timestamps))
    assert len(payload["results"]) == 10 and not provider.requests
    assert all(r["status"] == "error" and r["score"] is None for r in payload["results"])
    assert {r["error"] for r in payload["results"]} == {"dataset_time_limit_exceeded"}
    assert store.budget_summary()["calls"] == 0


def test_interrupted_batch_retains_progress(tmp_path, dialogue, checklist, knowledge, settings, assessment):
    class InterruptedProvider(FakeProvider):
        def evaluate(self, request):
            if len(self.requests) == 2:
                raise KeyboardInterrupt
            return super().evaluate(request)

    store = Store(tmp_path / "db")
    runs = tmp_path / "runs.json"
    args = (store, settings, dataset_records(dialogue), checklist, knowledge, SubmissionSettings(team_name="Status"))
    kwargs = {"dataset": "prod", "runs_path": runs, "output": tmp_path / "results.json", "max_minutes": 40}
    with pytest.raises(KeyboardInterrupt):
        evaluate_dataset(*args, **kwargs, provider=InterruptedProvider([provider_response(assessment)] * 10))
    assert len(read_json(runs)["evaluation_ids"]) == 2
    resumed = FakeProvider([provider_response(assessment)] * 8)
    payload = evaluate_dataset(*args, **kwargs, resume=True, provider=resumed)
    assert len(resumed.requests) == 8 and len(payload["results"]) == 10
