from copy import deepcopy

import pytest
from conftest import FakeProvider, provider_response
from fastapi.testclient import TestClient

from cqa.api import create_app
from cqa.engine import Engine
from cqa.io import fingerprint
from cqa.storage import Store


@pytest.fixture
def product(tmp_path, checklist, dialogue, settings, assessment):
    path = tmp_path / "product.sqlite3"
    store = Store(path)
    result = Engine(store, settings, FakeProvider([provider_response(assessment)])).evaluate(dialogue, checklist)
    assert result["assessment"]
    with TestClient(create_app(db_path=path)) as client:
        yield client, store, result


def proposal(result, *, revision=0, answer="7"):
    decision = deepcopy(result["assessment"]["criteria"]["c6"])
    decision.update(answer=answer, reason="Человек пересмотрел объяснение в учебном сценарии.")
    return {"reviewer": "Рецензент", "reason": "Проверка ручного пересмотра", "base_revision": revision,
            "changes": {"c6": decision}}


def test_accept_creates_final_revision_preserves_original_and_recalculates(product):
    client, store, original = product
    eid = original["evaluation_id"]
    before_hash = fingerprint(store.get_evaluation(eid))
    call_count = store.budget_summary()["calls"]
    submitted = client.post(f"/evaluations/{eid}/appeals", json=proposal(original))
    assert submitted.status_code == 201
    item = submitted.json()
    assert item["status"] == "pending"
    assert client.get(f"/evaluations/{eid}/final").json()["revision"] == 0
    accepted = client.post(f"/appeals/{item['appeal_id']}/resolve", json={
        "reviewer": "Проверяющий", "reason": "Изменение подтверждено", "decision": "accept", "base_revision": 0})
    assert accepted.status_code == 200
    final = client.get(f"/evaluations/{eid}/final").json()
    assert final["revision"] == 1 and final["source"] == "human_appeal"
    assert final["assessment"]["criteria"]["c6"]["answer"] == "7"
    assert final["scoring"]["total_score"] != original["scoring"]["total_score"]
    assert final["original"]["assessment"] == original["assessment"]
    assert fingerprint(store.get_evaluation(eid)) == before_hash
    assert store.budget_summary()["calls"] == call_count
    listing = client.get(f"/evaluations?conversation_id={original['conversation_id']}").json()[0]
    assert listing["final_revision"] == 1 and listing["pending_appeals"] == 0
    assert listing["checklist_hash"] == original["checklist_hash"]
    assert len(final["history"]) == 1


def test_reject_preserves_original_final_and_decision_is_immutable(product):
    client, _, result = product
    eid = result["evaluation_id"]
    item = client.post(f"/evaluations/{eid}/appeals", json=proposal(result)).json()
    request = {"reviewer": "Проверяющий", "reason": "Не подтверждено", "decision": "reject", "base_revision": 0}
    assert client.post(f"/appeals/{item['appeal_id']}/resolve", json=request).status_code == 200
    assert client.post(f"/appeals/{item['appeal_id']}/resolve", json=request).status_code == 409
    final = client.get(f"/evaluations/{eid}/final").json()
    assert final["revision"] == 0 and final["assessment"] == result["assessment"]
    assert client.get(f"/evaluations/{eid}/appeals").json()[0]["status"] == "rejected"


def test_concurrent_appeal_cannot_overwrite_a_new_revision(product):
    client, _, result = product
    eid = result["evaluation_id"]
    a = client.post(f"/evaluations/{eid}/appeals", json=proposal(result)).json()
    b = client.post(f"/evaluations/{eid}/appeals", json=proposal(result, answer="4")).json()
    resolution = {"reviewer": "Проверяющий", "reason": "Подтверждено", "decision": "accept", "base_revision": 0}
    assert client.post(f"/appeals/{a['appeal_id']}/resolve", json=resolution).status_code == 200
    assert client.post(f"/appeals/{b['appeal_id']}/resolve", json=resolution).status_code == 409
    resolution["base_revision"] = 1
    assert client.post(f"/appeals/{b['appeal_id']}/resolve", json=resolution).status_code == 409
    assert client.post(f"/evaluations/{eid}/appeals", json=proposal(result)).status_code == 409
    final = client.get(f"/evaluations/{eid}/final").json()
    assert final["revision"] == 1 and final["assessment"]["criteria"]["c6"]["answer"] == "7"


@pytest.mark.parametrize("failure", ["answer", "na", "missing_message", "missing_action", "quote", "blank_reason"])
def test_invalid_human_changes_are_rejected(product, failure):
    client, _, result = product
    body = proposal(result)
    decision = body["changes"]["c6"]
    if failure == "answer":
        decision["answer"] = "9"
    elif failure == "na":
        decision.update(answer="na", na_condition_id="made_up_condition")
    elif failure == "missing_message":
        decision["evidence"][0]["end_message_id"] = "does-not-exist"
    elif failure == "missing_action":
        decision["evidence"][0].update(kind="missing_action", expected_action=None)
    elif failure == "quote":
        decision["evidence"][0].update(kind="quote", end_message_id="m1", quote="Invented quote")
    else:
        decision["reason"] = " "
    response = client.post(f"/evaluations/{result['evaluation_id']}/appeals", json=body)
    assert response.status_code == 422
    assert client.get(f"/evaluations/{result['evaluation_id']}/appeals").json() == []


def test_valid_na_uses_original_checklist_and_recalculates(product):
    client, _, result = product
    eid = result["evaluation_id"]
    decision = deepcopy(result["assessment"]["criteria"]["c7"])
    decision.update(answer="na", na_condition_id="interrupted_before_closing",
                    reason="Учебный пересмотр условия N/A")
    body = {"reviewer": "Человек", "reason": "Уточнение", "base_revision": 0, "changes": {"c7": decision}}
    item = client.post(f"/evaluations/{eid}/appeals", json=body)
    assert item.status_code == 201
    assert item.json()["proposed_scoring"]["total_score"] == "100.00"
    assert item.json()["checklist_hash"] == result["checklist_hash"]


def test_checklist_same_version_is_immutable_new_version_changes_hash(product):
    client, _, result = product
    old = result["checklist"]
    changed = deepcopy(old)
    changed["criteria"][0]["rule"] = "Новое требование пользователя"
    assert client.post("/checklists", json=changed).status_code == 409
    changed["version"] = "test-user-version"
    assert client.post("/checklists", json=changed).status_code == 201
    assert client.get(f"/checklists/{old['id']}/{old['version']}").json() == old
    listed = client.get("/checklists").json()
    assert next(x["hash"] for x in listed if x["version"] == changed["version"]) != result["checklist_hash"]


def test_history_survives_new_store_connection(product):
    client, store, result = product
    eid = result["evaluation_id"]
    item = client.post(f"/evaluations/{eid}/appeals", json=proposal(result)).json()
    client.post(f"/appeals/{item['appeal_id']}/resolve", json={
        "reviewer": "Человек", "reason": "Проверено", "decision": "accept", "base_revision": 0})
    from cqa.appeals import final_result
    persisted = final_result(Store(store.path), eid)
    assert persisted["revision"] == 1 and persisted["history"][0]["appeal_id"] == item["appeal_id"]


def test_unknown_evaluation_returns_not_found(product):
    client, _, _ = product
    assert client.get("/evaluations/not-real/final").status_code == 404
    assert client.get("/evaluations/not-real/appeals").status_code == 404
