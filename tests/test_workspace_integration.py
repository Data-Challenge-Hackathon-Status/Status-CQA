from copy import deepcopy

import pytest
from conftest import FakeProvider, provider_response
from fastapi.testclient import TestClient

from cqa.engine import Engine
from cqa.io import json_text
from cqa.web import create_web_app
from cqa.workspace import Workspace


@pytest.fixture
def workspace(tmp_path, settings, dialogue, checklist, assessment):
    app = create_web_app(tmp_path / 'workspace.db', provider=FakeProvider([]))
    with TestClient(app) as client:
        store = app.state.store
        store.save_dialogues([(dialogue, dialogue.model_dump(mode='json'))])
        result = Engine(store, settings, FakeProvider([provider_response(assessment)])).evaluate(dialogue, checklist)
        assert result['assessment']
        yield app.state.workspace, client, result


def test_review_from_either_entry_point_uses_same_decisions_and_evidence(workspace):
    ws, client, original = workspace
    eid, cid = original['evaluation_id'], original['conversation_id']
    appeal = ws.create_appeal(eid, 'c7', 'Check closing', 'Operator')
    ws.resolve_appeal(appeal['id'], 'yes', None, 'Closing was present', 'QC')
    final_url = f'/evaluations/{eid}/final'
    first = client.get(final_url).json()
    assert first['revision'] == 1 and first['scoring']['total_score'] == '100.00'
    assert first['history'][0]['appeal_id'] == appeal['id']
    changed = deepcopy(original['assessment']['criteria']['c6'])
    changed.update(answer='7', reason='Examples in message 2')
    changed['evidence'][0].update(start_message_id='m2', end_message_id='m2')
    changed_c1 = deepcopy(original['assessment']['criteria']['c1'])
    changed_c1.update(answer='no', reason='Opening corrected')
    submitted = client.post(f'/evaluations/{eid}/appeals', json={
        'reviewer': 'Operator', 'reason': 'Review explanation and opening', 'base_revision': 1,
        'changes': {'c6': changed, 'c1': changed_c1}}).json()
    assert client.post(f"/appeals/{submitted['appeal_id']}/resolve", json={
        'decision': 'accept', 'reviewer': 'QC', 'reason': 'Accepted', 'base_revision': 1}).is_success
    final = client.get(final_url).json()
    shown = client.get('/ui-api/conversations/' + cid).json()['result']
    assert len(shown['appeals']) == 3
    assert shown['scoring'] == final['scoring'] and final['revision'] == 2
    assert shown['decisions']['c6']['reason'] == changed['reason']
    assert shown['decisions']['c6']['evidence_turns'] == [2]
    assert shown['original_scoring'] == original['scoring']
    for row in shown['appeals']:
        if row['id'] != appeal['id']:
            comparison = ws.review_comparison(eid, row['id'])
            assert comparison['before'] == first['scoring'] and comparison['after'] == final['scoring']
    assert ws.store.get_evaluation(eid) == original


def test_legacy_workspace_reviews_migrate_once(workspace):
    ws, client, original = workspace
    eid = original['evaluation_id']
    request = ws.create_appeal(eid, 'c7', 'Please check closing', 'Operator')
    old = dict(request, status='resolved', answer='yes', na_condition_id=None, reviewer='QC',
               resolution='Closing confirmed', resolved_at=request['created_at'])
    with ws.store.connection() as db:
        db.execute("UPDATE ui_appeals SET payload=?,status='resolved' WHERE id=?", (json_text(old), old['id']))
    for _ in range(2):
        ws = Workspace(ws.store)
        final = client.get(f'/evaluations/{eid}/final').json()
        assert final['revision'] == 1 and final['history'][0]['appeal_id'] == request['id']
        assert final['scoring'] == ws.effective_result(ws.result(eid))['scoring']
        assert len(ws.appeals()) == 1


def test_imported_baseline_and_pre_provider_snapshots_keep_native_priority(workspace):
    ws, _, original = workspace
    legacy = deepcopy(original)
    del legacy['settings']['provider']
    legacy['settings']['model'] = 'original-external-model'
    native = ws.native_result(legacy)
    assert native['model'] == {'mode': 'external_api', 'name': 'original-external-model'}
    baseline = dict(native, evaluation_id='baseline-recent-import', origin='baseline', created_at='2999')
    ws.save_result(baseline)
    ordered = ws.results()
    assert [r['evaluation_id'] for r in ordered] == [original['evaluation_id'], baseline['evaluation_id']]
