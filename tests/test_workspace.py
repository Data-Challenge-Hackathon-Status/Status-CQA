"""Product workflows against SQLite and the real evaluator, with an offline provider."""
import copy
import threading
import time

import pytest
from conftest import FakeProvider, provider_response
from fastapi.testclient import TestClient

from cqa.engine import Engine
from cqa.io import load_dialogues, read_json
from cqa.web import create_web_app


@pytest.fixture
def workspace_client(tmp_path, checklist, settings, dialogue, assessment):
    app = create_web_app(tmp_path / 'workspace.db', provider=FakeProvider([]))
    with TestClient(app) as client:
        app.state.store.save_dialogues([(dialogue, dialogue.model_dump(mode='json'))])
        result = Engine(app.state.store, settings, FakeProvider([provider_response(assessment)])).evaluate(
            dialogue, checklist)
        assert result['status'] == 'provisional', result.get('error')
        yield client, app, result


def test_workspace_entry_page_and_shared_api_coexist(workspace_client):
    client, _, _ = workspace_client
    page = client.get('/')
    assert page.status_code == 200
    assert 'src="/assets/app.js"' in page.text
    assert 'id="dialogueList"' in client.get('/classic').text
    assert client.get('/assets/workflows.js').status_code == 200
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/checklists').status_code == 200


def test_import_accepts_all_promised_formats_and_is_atomic(workspace_client):
    client, app, _ = workspace_client
    original = read_json('examples/dialogue.json')
    single = load_dialogues(original)[0][0].model_dump(mode='json')
    for index, wrap in enumerate([lambda x: x, lambda x: [x],
                                 lambda x: {'isSuccess': True, 'data': {'records': [x], 'total_records': 1}}]):
        value = copy.deepcopy(single)
        value['conversation_id'] = f'import-{index}'
        ids = [value['conversation_id']]
        assert client.post('/ui-api/import', json=wrap(value)).json() == {
            'imported': 1, 'added_ids': ids, 'conversation_ids': ids}
        assert client.post('/conversations/import', json=wrap(value)).json() == {
            'imported': 1, 'added_ids': [], 'conversation_ids': ids}
    bad = copy.deepcopy(value)
    bad['transcript'][0]['text'] = 'Different content for the same ID'
    new = {**value, 'conversation_id': 'should-not-be-saved'}
    assert client.post('/ui-api/import', json=[new, bad]).status_code == 409
    assert 'should-not-be-saved' not in {d.conversation_id for d in app.state.store.list_dialogues()}


def test_appeal_changes_effective_score_but_preserves_evidence_and_original(workspace_client):
    client, app, original = workspace_client
    cid, eid = original['conversation_id'], original['evaluation_id']
    detail = client.get('/ui-api/conversations/' + cid).json()
    assert detail['result']['decisions']['c7']['evidence_turns'] == [1, 2, 3, 4, 5]
    assert detail['result']['needs_review'] is True
    request = {'evaluation_id': eid, 'criterion_id': 'c7', 'comment': 'Проверить завершение разговора'}
    response = client.post('/ui-api/appeals', json=request)
    assert response.status_code == 201
    appeal = response.json()
    assert client.post('/ui-api/appeals', json=request).status_code == 409
    resolution = {'answer': 'yes', 'reason': 'Пересмотрено проверяющим по репликам', 'role': 'reviewer'}
    assert client.post('/ui-api/appeals/' + appeal['id'] + '/resolve', json=resolution).status_code == 200
    assert client.post('/ui-api/appeals/' + appeal['id'] + '/resolve', json=resolution).status_code == 409
    result = client.get('/ui-api/conversations/' + cid).json()['result']
    assert result['scoring']['total_score'] == '100.00'
    assert result['original_scoring']['total_score'] == '92.31'
    assert result['original_decisions']['c7']['answer'] == 'no'
    assert result['decisions']['c7']['evidence_turns'] == [1, 2, 3, 4, 5]
    assert app.state.store.get_evaluation(eid) == original
    row = client.get('/ui-api/bootstrap').json()['conversations'][0]
    assert row['score'] == '100.00' and row['reviewed'] and not row['pending_appeals']
    exported = client.post('/ui-api/export', json={'conversation_ids': [cid]}).json()['results'][0]
    assert exported['original_scoring']['total_score'] == '92.31'
    assert exported['scoring']['total_score'] == '100.00'


def test_critical_flag_and_invalid_na_do_not_silently_change_total(workspace_client):
    client, _, original = workspace_client
    appeal = client.post('/ui-api/appeals', json={'evaluation_id': original['evaluation_id'],
                         'criterion_id': 'c8', 'comment': 'Проверить возможное нарушение'}).json()
    url = '/ui-api/appeals/' + appeal['id'] + '/resolve'
    assert client.post(url, json={'answer': 'na', 'na_condition_id': 'unknown',
                                 'reason': 'Нет уверенности', 'role': 'reviewer'}).status_code == 409
    assert client.post(url, json={'answer': 'yes', 'reason': 'Нарушение подтверждено',
                                 'role': 'reviewer'}).status_code == 200
    result = client.get('/ui-api/conversations/' + original['conversation_id']).json()['result']
    assert result['scoring']['gross_violation'] is True
    assert result['scoring']['total_score'] == result['original_scoring']['total_score'] == '92.31'


def test_new_criteria_are_versioned_and_require_new_analysis(workspace_client, checklist):
    client, _, original = workspace_client
    updated = checklist.model_dump(mode='json')
    updated['version'] = 'ui-test-2'
    added = copy.deepcopy(updated['criteria'][0])
    added.update(id='new_control', title='Дополнительное правило', rule='Новое требование')
    updated['criteria'].append(added)
    assert client.post('/ui-api/checklists', json=updated).status_code == 201
    changed = copy.deepcopy(updated)
    changed['criteria'][-1]['weight'] = '25'
    assert client.post('/ui-api/checklists', json=changed).status_code == 409
    bootstrap = client.get('/ui-api/bootstrap').json()
    assert bootstrap['active_checklist']['version'] == 'ui-test-2'
    assert bootstrap['conversations'][0]['stale'] is True
    response = client.post('/ui-api/reweight', json={'evaluation_id': original['evaluation_id'],
        'checklist_id': checklist.id, 'checklist_version': 'ui-test-2'})
    assert response.status_code == 422 and 'новый анализ' in response.json()['detail']


def test_weight_only_change_uses_deterministic_recalculation(workspace_client, checklist):
    client, app, original = workspace_client
    updated = checklist.model_dump(mode='json')
    updated['version'] = 'ui-weight-test'
    next(c for c in updated['criteria'] if c['id'] == 'c7')['weight'] = '10'
    assert client.post('/ui-api/checklists', json=updated).status_code == 201
    response = client.post('/ui-api/reweight', json={'evaluation_id': original['evaluation_id'],
        'checklist_id': checklist.id, 'checklist_version': updated['version']})
    assert response.status_code == 200
    assert response.json()['scoring']['total_score'] == '85.71'
    assert response.json()['origin'] == 'recalculated'
    assert app.state.store.get_evaluation(original['evaluation_id']) == original
    assert len(client.get('/ui-api/conversations/' + original['conversation_id']).json()['history']) == 2
    selected = client.post('/ui-api/export', json={
        'conversation_ids': [original['conversation_id']],
        'evaluation_ids': {original['conversation_id']: original['evaluation_id']}})
    assert selected.status_code == 200
    assert selected.json()['results'][0]['scoring']['total_score'] == '92.31'
    assert client.post('/ui-api/export', json={
        'conversation_ids': [original['conversation_id']],
        'evaluation_ids': {'different-dialogue': original['evaluation_id']}}).status_code == 422


def test_submission_keeps_model_answers_after_human_review(workspace_client, dialogue):
    client, app, original = workspace_client
    ws = app.state.workspace
    base = ws.native_result(original)
    results = []
    for index in range(10):
        d = dialogue.model_copy(deep=True)
        d.conversation_id = f'prod-{index}'
        app.state.store.save_dialogues([(d, d.model_dump(mode='json'))])
        r = copy.deepcopy(base)
        r.update(evaluation_id=f'result-{index}', conversation_id=d.conversation_id)
        ws.save_result(r)
        results.append(r)
    appeal = ws.create_appeal('result-0', 'c7', 'Перепроверка', 'Оператор')
    ws.resolve_appeal(appeal['id'], 'yes', None, 'Подтверждено человеком', 'QC')
    payload = client.post('/ui-api/export', json={'conversation_ids': [r['conversation_id'] for r in results],
        'format': 'submission', 'dataset': 'prod', 'team_name': 'Test Team'})
    assert payload.status_code == 200, payload.text
    first = next(r for r in payload.json()['results'] if r['conversation_id'] == 'prod-0')
    assert first['score']['final_score'] == 92.31
    assert next(c for c in first['criteria'] if c['criterion_id'] == 'closure')['value'] is False
    assert set(first) == {'conversation_id', 'status', 'criteria', 'score'}


def test_jobs_run_real_engine_and_deduplicate_while_in_progress(tmp_path, dialogue, checklist, assessment):
    gate, started = threading.Event(), threading.Event()

    class BlockingProvider(FakeProvider):
        def evaluate(self, request):
            started.set()
            assert gate.wait(5)
            return super().evaluate(request)

    provider = BlockingProvider([provider_response(assessment)])
    app = create_web_app(tmp_path / 'queue.db', settings_path='config/settings.json',
                         checklist_path='config/checklist.claims-v1.json', provider=provider)
    with TestClient(app) as client:
        app.state.store.save_dialogues([(dialogue, dialogue.model_dump(mode='json'))])
        request = {'conversation_ids': [dialogue.conversation_id],
                   'checklist_id': checklist.id, 'checklist_version': checklist.version}
        first = client.post('/ui-api/jobs', json=request)
        assert first.status_code == 202
        assert started.wait(3)
        try:
            second = client.post('/ui-api/jobs', json=request)
            assert first.json()['jobs'][0]['id'] == second.json()['jobs'][0]['id']
        finally:
            gate.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get('/ui-api/jobs').json()[0]
            if job['status'] in {'completed', 'failed'}:
                break
            time.sleep(.02)
        assert job['status'] == 'completed', job
        result = client.get('/ui-api/conversations/' + dialogue.conversation_id).json()['result']
        assert result['origin'] == 'model' and result['scoring']['total_score'] == '92.31'
        assert len(provider.requests) == 1


def test_local_workspace_persists_and_rejects_cross_origin_writes(tmp_path, dialogue):
    path = tmp_path / 'persistent.db'
    with TestClient(create_web_app(path, provider=FakeProvider([]))) as client:
        assert client.post('/ui-api/import', json=dialogue.model_dump(mode='json'),
                           headers={'Origin': 'https://external.example'}).status_code == 403
        initial = client.get('/ui-api/bootstrap').json()
        assert initial['conversations'] == []
        assert initial['active_checklist']['version'] == '1.2.1'
        assert client.get('/ui-api/model').json()['name'] == 'qwen3:32b'
        assert client.post('/ui-api/import', json=dialogue.model_dump(mode='json')).status_code == 200
        assert client.get('/').status_code == 200
        assert client.get('/assets/app.js').status_code == 200
    with TestClient(create_web_app(path, provider=FakeProvider([]))) as client:
        assert client.get('/ui-api/bootstrap').json()['conversations'][0]['id'] == dialogue.conversation_id
        response = client.post('/ui-api/export', json={'conversation_ids': [dialogue.conversation_id]})
        assert response.status_code == 422


def test_checklist_comparison_is_read_only_and_matches_reweight_guard(workspace_client, checklist):
    client, app, original = workspace_client
    before = {'id': checklist.id, 'version': checklist.version}
    active = client.get('/ui-api/bootstrap').json()['active_checklist']
    calls = app.state.store.budget_summary()['calls']
    draft = checklist.model_dump(mode='json')
    draft['version'] = 'comparison-unsaved'
    draft['criteria'][0]['weight'] = '10.000'
    same = client.post('/ui-api/checklists/compare', json={'before': before, 'draft': draft})
    assert same.status_code == 200 and same.json()['mode'] == 'compatible'
    draft['criteria'][0]['weight'] = '25'
    changed = client.post('/ui-api/checklists/compare', json={'before': before, 'draft': draft}).json()
    assert changed['mode'] == 'recalculate' and changed['counts']['changed'] == 1
    assert changed['criteria'][0]['fields'] == ['weight']
    assert changed['impact']['recalculate'] == 1
    assert client.get('/ui-api/bootstrap').json()['active_checklist'] == active
    assert all(c['version'] != draft['version'] for c in app.state.store.list_checklists())
    draft['notes'] += '\nNew instruction affecting assessment.'
    rules = client.post('/ui-api/checklists/compare', json={'before': before, 'draft': draft}).json()
    assert rules['mode'] == 'reanalyze' and rules['global_fields'] == ['notes']
    assert rules['impact']['reanalyze'] == 1
    assert client.post('/ui-api/checklists', json=draft).status_code == 201
    assert client.post('/ui-api/reweight', json={'evaluation_id': original['evaluation_id'],
        'checklist_id': checklist.id, 'checklist_version': draft['version']}).status_code == 422
    assert app.state.store.budget_summary()['calls'] == calls
    assert client.post('/ui-api/checklists/compare', json={'before': before, 'after': before, 'draft': draft}).status_code == 422


@pytest.mark.parametrize('field,value', [
    ('rule', 'Changed rule'), ('section', 'Changed section'),
    ('channel_rules', {'voice call': 'Changed voice rule'}),
    ('requires_company_knowledge', True),
])
def test_semantic_criterion_changes_require_analysis(checklist, field, value):
    from cqa.contracts import Checklist
    from cqa.workspace_compare import checklist_comparison
    data = checklist.model_dump(mode='json')
    data['criteria'][0][field] = value
    result = checklist_comparison(checklist, Checklist.model_validate(data))
    assert result['mode'] == 'reanalyze' and not result['can_reweight']
    assert result['criteria'][0]['fields'] == [field]


@pytest.mark.parametrize('criterion_id,field', [('c4', 'max_observed_facts'), ('c8', 'flag_evidence_mode')])
def test_optional_rule_changes_require_analysis_in_both_directions(criterion_id, field):
    from cqa.contracts import Checklist
    from cqa.workspace_compare import checklist_comparison

    current = Checklist.model_validate(read_json('config/checklist.review-v4.1.json'))
    earlier = current.model_copy(deep=True)
    setattr(next(c for c in earlier.criteria if c.id == criterion_id), field, None)
    for before, after in [(earlier, current), (current, earlier)]:
        result = checklist_comparison(before, after)
        row = next(r for r in result['criteria'] if r['id'] == criterion_id)
        assert result['mode'] == 'reanalyze' and row['fields'] == [field]


def test_comparison_detects_added_removed_scale_and_na_changes(checklist):
    from cqa.contracts import Checklist
    from cqa.workspace_compare import checklist_comparison
    data = checklist.model_dump(mode='json')
    added = copy.deepcopy(data['criteria'][0]); added['id'] = 'new_rule'
    data['criteria'] = [*data['criteria'][1:], added]
    data['criteria'][0]['na_conditions'][0]['channels'] = ['voice call']
    data['criteria'][2]['options'][0]['description'] += ' More exact conditions.'
    result = checklist_comparison(checklist, Checklist.model_validate(data))
    by_id = {row['id']: row for row in result['criteria']}
    assert by_id['c1']['status'] == 'removed' and by_id['new_rule']['status'] == 'added'
    assert 'na_conditions' in by_id['c2']['fields'] and 'options' in by_id['c4']['fields']
    assert result['mode'] == 'reanalyze'
    reordered = checklist.model_copy(deep=True)
    reordered.criteria.reverse()
    result = checklist_comparison(checklist, reordered)
    assert result['reordered'] and result['mode'] == 'compatible' and result['counts']['changed'] == 0


def test_review_comparison_records_specific_decisions_and_na_side_effects(workspace_client):
    client, app, original = workspace_client
    eid = original['evaluation_id']; ws = app.state.workspace
    first = ws.create_appeal(eid, 'c2', 'Need clarification in this example', 'Operator')
    pending = client.get(f'/ui-api/evaluations/{eid}/review-comparison', params={'appeal_id': first['id']}).json()
    assert pending['after'] is None and pending['basis'] == 'pending'
    ws.resolve_appeal(first['id'], 'yes', None, 'The criterion applies', 'QC')
    comparison = client.get(f'/ui-api/evaluations/{eid}/review-comparison', params={'appeal_id': first['id']}).json()
    assert comparison['basis'] == 'recorded' and comparison['after']['total_score'] == '93.75'
    c1 = next(row for row in comparison['criteria'] if row['id'] == 'c1')
    assert c1['weight_changed'] and c1['points_changed'] and not c1['answer_changed']
    assert c1['before']['reason'] == c1['after']['reason']
    second = ws.create_appeal(eid, 'c2', 'Review the applicability again', 'Operator')
    ws.resolve_appeal(second['id'], 'na', 'enough_information_initially', 'The initial context is sufficient', 'QC')
    # An earlier comparison remains exactly as recorded after a later appeal.
    assert client.get(f'/ui-api/evaluations/{eid}/review-comparison', params={'appeal_id': first['id']}).json()['after'] == comparison['after']
    current = client.get(f'/ui-api/evaluations/{eid}/review-comparison').json()
    assert current['after']['total_score'] == current['before']['total_score'] == '92.31'
    assert current['score_delta'] == '0.00' and current['resolved_count'] == 2
    assert app.state.store.get_evaluation(eid) == original
    assert client.get(f'/ui-api/evaluations/{eid}/review-comparison', params={'appeal_id':'different-appeal'}).status_code == 404


def test_concurrent_appeals_snapshot_a_serial_history_and_survive_reopen(workspace_client):
    from concurrent.futures import ThreadPoolExecutor

    from cqa.storage import Store
    from cqa.workspace import Workspace
    _, app, original = workspace_client
    ws = app.state.workspace; eid = original['evaluation_id']
    appeals = [ws.create_appeal(eid, key, 'Review this criterion', 'Operator') for key in ('c7', 'c8')]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda a: ws.resolve_appeal(a['id'], 'yes', None, 'Confirmed by reviewer', 'QC'), appeals))
    ordered = sorted(results, key=lambda a: a['resolution_sequence'])
    assert [a['resolution_sequence'] for a in ordered] == [1, 2]
    assert ordered[0]['comparison']['after'] == ordered[1]['comparison']['before']
    reopened = Workspace(Store(app.state.store.path))
    result = reopened.review_comparison(eid)
    assert result['after']['total_score'] == '100.00' and result['after']['gross_violation']
    critical = next(a for a in results if a['criterion_id'] == 'c8')
    critical_diff = reopened.review_comparison(eid, critical['id'])
    assert critical_diff['critical_changed'] and critical_diff['score_delta'] == '0.00'


def test_legacy_appeal_comparison_and_pending_on_older_evaluation(workspace_client):
    from cqa.io import json_text
    from cqa.storage import utc_now
    client, app, original = workspace_client
    ws = app.state.workspace; eid = original['evaluation_id']
    appeal = ws.create_appeal(eid, 'c7', 'Review closing', 'Operator')
    resolved = ws.resolve_appeal(appeal['id'], 'yes', None, 'Closing confirmed', 'QC')
    resolved.pop('comparison'); resolved.pop('resolution_sequence')
    with app.state.store.connection() as db:
        db.execute('UPDATE ui_appeals SET payload=? WHERE id=?', (json_text(resolved), appeal['id']))
    legacy = ws.review_comparison(eid, appeal['id'])
    assert legacy['basis'] == 'reconstructed' and legacy['after']['total_score'] == '100.00'
    pending = ws.create_appeal(eid, 'c8', 'Review critical flag', 'Operator')
    newer = ws.native_result(original)
    newer.update(evaluation_id='newer-evaluation', created_at=utc_now())
    ws.save_result(newer)
    row = client.get('/ui-api/bootstrap').json()['conversations'][0]
    assert row['evaluation_id'] == 'newer-evaluation'
    assert row['pending_appeals'] == 1 and row['review_evaluation_id'] == pending['evaluation_id']
    detail = client.get('/ui-api/conversations/'+row['id'],params={'evaluation_id':eid}).json()
    assert detail['result']['evaluation_id'] == eid


def test_comparison_keeps_unscorable_total_distinct_from_zero(checklist):
    from cqa.scoring import calculate_answers
    from cqa.workspace_compare import assessment_comparison
    c = checklist.model_copy(deep=True)
    c.criteria = [x for x in c.criteria if x.id in {'c2','c8'}]
    before_decisions = {key:{'answer':value,'reason':'Original','na_condition_id':None} for key,value in [('c2','yes'),('c8','no')]}
    after_decisions = copy.deepcopy(before_decisions)
    after_decisions['c2'].update(answer='na',na_condition_id='enough_information_initially')
    def snapshot(decisions):
        return {'decisions':decisions,'scoring':calculate_answers({k:d['answer'] for k,d in decisions.items()},c,{k:d['na_condition_id'] for k,d in decisions.items()})}
    result = assessment_comparison(c.model_dump(mode='json'),snapshot(before_decisions),snapshot(after_decisions))
    assert result['before']['total_score'] == '100.00'
    assert result['after']['total_score'] is None and result['score_delta'] is None
