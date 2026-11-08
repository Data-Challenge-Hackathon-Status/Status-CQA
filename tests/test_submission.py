import copy
import json

import pytest

from cqa.cli import parser, run
from cqa.contracts import Checklist, Dialogue, Message
from cqa.engine import Engine
from cqa.io import write_json
from cqa.provider import ProviderError
from cqa.storage import Store
from cqa.submission import (
    SubmissionSettings,
    build_submission,
    check_dataset,
    read_submission,
    save_submission,
    validate_submission,
)
from tests.conftest import FakeProvider, provider_response


@pytest.fixture
def submission_case(tmp_path, dialogue, checklist, settings, assessment):
    # The appendix's published example: N/A weights 15 and 20, consultation 15/20,
    # dialogue 7/10, the other applicable binary criteria all passed => 85.38.
    assessment.criteria["c4"].answer = "15"
    assessment.criteria["c6"].answer = "7"
    assessment.criteria["c7"].answer = "yes"
    db = tmp_path / "cqa.db"
    store = Store(db)
    dialogues, evaluations = [], []
    for index in range(10):
        d = dialogue.model_copy(update={"conversation_id": f"original-{index:02}"}, deep=True)
        result = Engine(store, settings, FakeProvider([provider_response(assessment)])).evaluate(d, checklist)
        dialogues.append(d)
        evaluations.append(result)
    return db, dialogues, evaluations, SubmissionSettings(team_name="Status")


def test_appendix_example_and_numeric_types(submission_case, checklist):
    _, dialogues, evaluations, config = submission_case
    payload = build_submission(evaluations, dialogues, "prod", config)
    assert payload["schema_version"] == "1.0" and payload["team_name"] == "Status"
    assert payload["model"]["mode"] == "external_api"
    first = payload["results"][0]
    assert first["score"] == {"final_score": 85.38, "critical_flag": False}
    criteria = {c["criterion_id"]: c for c in first["criteria"]}
    assert criteria["consultation"]["value"] == 15
    assert criteria["dialogue"]["value"] == 7  # Raw grade, not weighted 10.5 points.
    assert criteria["contact"]["value"] is True
    assert criteria["discovery"]["value"] is None
    assert validate_submission(payload, dialogues, "prod", checklist, config) == payload


def test_original_positions_include_every_role(tmp_path, submission_case, checklist, settings, assessment):
    _, dialogues, evaluations, config = submission_case
    data = dialogues[0].model_dump(mode="json")
    data["transcript"][0]["id"] = "source-id-81"
    data["transcript"][-1]["id"] = "source-id-2"
    data["transcript"].insert(1, Message(id="event", timestamp="00:01", speaker="system",
                                       text="Context event").model_dump())
    changed = Dialogue.model_validate(data)
    for decision in assessment.criteria.values():
        decision.evidence[0].start_message_id = "source-id-81"
        decision.evidence[0].end_message_id = "source-id-2"
    assessment.criteria["c7"].evidence[0].kind = "missing_action"
    assessment.criteria["c7"].evidence[0].expected_action = "Предложить дальнейшую помощь"
    new = Engine(Store(tmp_path / "other.db"), settings,
                 FakeProvider([provider_response(assessment)])).evaluate(changed, checklist)
    assert new["message_index"][0]["message_id"] == "source-id-81"
    assert new["message_index"][0]["submission_turn"] == 1
    assert new["message_index"][1]["speaker"] == "system" and new["message_index"][1]["submission_turn"] == 2
    assert new["message_index"][-1]["message_id"] == "source-id-2"
    assert new["message_index"][-1]["submission_turn"] == 6
    dialogues[0], evaluations[0] = changed, new
    payload = build_submission(evaluations, dialogues, "prod", config)
    for criterion in payload["results"][0]["criteria"]:
        assert criterion["evidence_turns"] == [1, 2, 3, 4, 5, 6]
    assert "Предложить дальнейшую помощь" in payload["results"][0]["criteria"][6]["rationale"]


def test_failure_is_retained_without_zero_score(tmp_path, submission_case, checklist, settings):
    _, dialogues, evaluations, config = submission_case
    evaluations[0] = Engine(Store(tmp_path / "failed.db"), settings,
                            FakeProvider([ProviderError("unavailable", retryable=False)])).evaluate(
                                dialogues[0], checklist)
    payload = build_submission(evaluations, dialogues, "prod", config)
    assert len(payload["results"]) == 10
    assert payload["results"][0] == {"conversation_id": "original-00", "status": "error",
                                      "criteria": [], "score": None, "error": "unavailable"}


@pytest.mark.parametrize("mutation", [
    lambda p: p["results"].pop(),
    lambda p: p["results"].append(copy.deepcopy(p["results"][0])),
    lambda p: p["results"][0].update(conversation_id="invented-id"),
    lambda p: p["results"][0]["criteria"][0].update(value=1),
    lambda p: p["results"][0]["criteria"][0].update(value=None),
    lambda p: p["results"][0]["criteria"][3].update(value=True),
    lambda p: p["results"][0]["criteria"][3].update(value=7),
    lambda p: p["results"][0]["criteria"][5].update(value=5),
    lambda p: p["results"][0]["criteria"][0].update(evidence_turns=[0]),
    lambda p: p["results"][0]["criteria"][0].update(evidence_turns=[True]),
    lambda p: p["results"][0]["criteria"][0].update(evidence_turns=[999]),
    lambda p: p["results"][0]["criteria"][0].update(criterion_id="critical"),
    lambda p: p["results"][0]["score"].update(final_score="85.38"),
    lambda p: p["results"][0]["score"].update(final_score=85.381),
    lambda p: p["results"][0]["score"].update(final_score=0),
    lambda p: p["results"][0]["score"].update(critical_flag=True),
])
def test_submission_validator_rejects_invalid_files(submission_case, checklist, mutation):
    _, dialogues, evaluations, config = submission_case
    payload = build_submission(evaluations, dialogues, "prod", config)
    mutation(payload)
    with pytest.raises(ValueError):
        validate_submission(payload, dialogues, "prod", checklist, config)


def test_export_rejects_wrong_or_incomplete_run_selection(submission_case):
    _, dialogues, evaluations, config = submission_case
    with pytest.raises(ValueError):
        build_submission(evaluations[:-1], dialogues, "prod", config)
    evaluations[0]["scoring"]["total_score"] = "100.00"
    with pytest.raises(ValueError, match="баллы"):
        build_submission(evaluations, dialogues, "prod", config)


def test_source_snapshot_cannot_be_changed(submission_case):
    _, dialogues, evaluations, config = submission_case
    dialogues[0].transcript[0].text += " changed"
    with pytest.raises(ValueError, match="другой версии"):
        build_submission(evaluations, dialogues, "prod", config)


def test_dev_composition_and_prod_chat_only(submission_case):
    _, dialogues, _, _ = submission_case
    dev = [dialogues[0].model_copy(update={"conversation_id": str(i),
             "channel": "agent chat" if i < 60 else "voice call"}) for i in range(65)]
    check_dataset(dev, "dev")
    with pytest.raises(ValueError):
        check_dataset(dev[:-1], "dev")
    dialogues[0].channel = "voice call"
    with pytest.raises(ValueError):
        check_dataset(dialogues, "prod")


def test_critical_flag_never_zeroes_total(tmp_path, submission_case, checklist, settings, assessment):
    _, dialogues, evaluations, config = submission_case
    assessment.criteria["c8"].answer = "yes"
    evaluations[0] = Engine(Store(tmp_path / "critical.db"), settings,
                            FakeProvider([provider_response(assessment)])).evaluate(dialogues[0], checklist)
    first = build_submission(evaluations, dialogues, "prod", config)["results"][0]
    assert first["score"]["critical_flag"] is True
    assert first["score"]["final_score"] > 0


def test_export_cli_and_utf8_round_trip(tmp_path, submission_case):
    db, dialogues, evaluations, config = submission_case
    source, runs, output, config_file = (tmp_path / name for name in ("input.json", "runs.json", "results.json",
                                                                    "submission.json"))
    write_json(source, [d.model_dump(mode="json") for d in dialogues])
    write_json(runs, {"evaluation_ids": [r["evaluation_id"] for r in evaluations]})
    write_json(config_file, config)
    arguments = ["--db", str(db), "export-results", str(runs), "--input", str(source),
                 "--dataset", "prod", "--submission-config", str(config_file), "--output", str(output)]
    assert run(parser().parse_args(arguments)) == 0
    assert len(read_submission(output)["results"]) == 10
    assert not output.read_bytes().startswith(b"\xef\xbb\xbf")
    assert run(parser().parse_args(["--db", str(db), "validate-results", str(output), "--input", str(source),
                                   "--dataset", "prod", "--submission-config", str(config_file)])) == 0
    old = output.read_bytes()
    with pytest.raises(ValueError):
        save_submission(output, {"bad": float("nan")})
    assert output.read_bytes() == old


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":"1.0","schema_version":"other"}', encoding="utf-8")
    with pytest.raises(ValueError, match="повторяющиеся ключи"):
        read_submission(path)


def test_renamed_criterion_maps_via_settings(tmp_path, dialogue, checklist, settings, assessment):
    original = checklist.model_dump(mode="json")
    original["criteria"][0]["id"] = "hello"
    original["version"] = "renamed"
    checklist = Checklist.model_validate(original)
    assessment.criteria["hello"] = assessment.criteria.pop("c1")
    config = SubmissionSettings(team_name="Status")
    config.criterion_ids["hello"] = config.criterion_ids.pop("c1")
    store = Store(tmp_path / "db")
    dialogues = [dialogue.model_copy(update={"conversation_id": str(i)}) for i in range(10)]
    evaluations = [Engine(store, settings, FakeProvider([provider_response(assessment)])).evaluate(d, checklist)
                   for d in dialogues]
    payload = build_submission(evaluations, dialogues, "prod", config)
    assert payload["results"][0]["criteria"][0]["criterion_id"] == "contact"
    assert "hello" not in json.dumps(payload)
