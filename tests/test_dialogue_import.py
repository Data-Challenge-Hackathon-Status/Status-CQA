from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from cqa.api import create_app


def test_uploads_keep_order_and_preserve_timestamps_and_roles(tmp_path, dialogue):
    original = dialogue.model_dump(mode="json")
    first = dict(original, conversation_id="jury-one")
    second = dict(original, conversation_id="jury-two")
    second["transcript"] = [{k: v for k, v in m.items() if k != "id"} for m in original["transcript"]]
    envelope = {"isSuccess": True, "data": {"total_records": 2, "records": [first, second]}}
    with TestClient(create_app(tmp_path / "test.sqlite3")) as client:
        assert client.post("/conversations/import", json=first).json()["added_ids"] == ["jury-one"]
        result = client.post("/conversations/import", json=envelope)
        assert result.status_code == 200
        assert result.json() == {"imported": 2, "added_ids": ["jury-two"],
                                 "conversation_ids": ["jury-one", "jury-two"]}
        assert client.post("/conversations/import", json=[second, first]).json()["added_ids"] == []
        stored = client.get("/conversations/jury-two").json()["transcript"]
        assert [m["id"] for m in stored] == [f"m{i + 1}" for i in range(len(stored))]
        assert [{k: v for k, v in m.items() if k != "id"} for m in stored] == second["transcript"]
        assert len(client.get("/conversations").json()) == 2
        assert client.get("/evaluations").json() == []
        assert client.get("/budget").json()["calls"] == 0


def test_collision_rolls_back_whole_batch(tmp_path, dialogue):
    original = dialogue.model_dump(mode="json")
    changed = deepcopy(original)
    changed["transcript"][0]["text"] += " Другая реплика."
    with TestClient(create_app(tmp_path / "test.sqlite3")) as client:
        assert client.post("/conversations/import", json=original).is_success
        response = client.post("/conversations/import", json=[dict(original, conversation_id="new"), changed])
        assert response.status_code == 409
        assert original["conversation_id"] in response.json()["detail"]
        assert client.get("/conversations/new").status_code == 404
        assert client.get("/conversations/" + original["conversation_id"]).json() == original


@pytest.mark.parametrize("invalid", [None, {"transcript": "bad"}, {"transcript": [17]},
                                     {"speaker": "operator"}])
def test_malformed_batch_returns_explanation_without_writes(tmp_path, dialogue, invalid):
    with TestClient(create_app(tmp_path / "test.sqlite3")) as client:
        response = client.post("/conversations/import", json=[dialogue.model_dump(mode="json"), invalid])
        assert response.status_code == 422
        assert "№2" in response.json()["detail"]
        assert client.get("/conversations").json() == []
