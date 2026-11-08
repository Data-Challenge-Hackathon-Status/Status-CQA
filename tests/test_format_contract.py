"""Offline JSON-schema conformance, not measured model quality or repaired saved answers."""
import hashlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from cqa.contracts import Checklist, Knowledge, ModelAssessment, Settings
from cqa.engine import VALIDATION_POLICY, Engine, _validation_options, recalculate
from cqa.experiment import make_job
from cqa.io import fingerprint, load_dialogues, read_json
from cqa.prompting import PROMPT_VERSION, build_input, response_schema
from cqa.provider import ProviderResponse, build_request
from cqa.storage import Store
from cqa.validation import AssessmentError, validate_assessment

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'config/checklist.review-v3.json').is_file())


@pytest.fixture
def inputs():
    checklist = Checklist.model_validate(read_json(ROOT / 'config/checklist.review-v3.json'))
    dialogue = load_dialogues(read_json(ROOT / 'examples/dialogue.json'))[0][0]
    return checklist, dialogue


def valid_answer(checklist):
    result = {'criteria': {}}
    for criterion in checklist.criteria:
        result['criteria'][criterion.id] = {
            'answer': criterion.options[0].value, 'reason': 'Искусственный пример структуры.',
            'na_condition_id': None, 'source_ids': [], 'knowledge_status': 'not_needed', 'limitations': [],
            'knowledge_review': None,
            'evidence': [{'kind': 'range', 'start_message_id': 'm3', 'end_message_id': 'm3',
                          'quote': None, 'expected_action': None}]}
        if criterion.requires_company_knowledge:
            result['criteria'][criterion.id]['knowledge_review'] = {
                'coverage': 'Наблюдаемое содержание ответа.',
                'observed_facts': [{'statement': 'Оператор ответил.', 'message_ids': ['m3']}],
                'external_claims': []}
    return result


def add_claim(answer):
    decision = answer['criteria']['c4']
    decision['knowledge_status'] = 'unverified'
    decision['limitations'] = ['Нет источника для проверки.']
    decision['knowledge_review']['external_claims'] = [{
        'statement': 'Учебное продуктовое утверждение.', 'message_ids': ['m3'], 'status': 'unverified',
        'source_ids': [], 'limitation': decision['limitations'][0], 'document_relation': 'not_established',
        'contradiction_basis': None}]
    return decision


def validator(inputs, knowledge=None):
    checklist, dialogue = inputs
    schema = response_schema(checklist, knowledge or Knowledge(), dialogue)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.mark.parametrize('criterion', ['c1', 'c4'])
@pytest.mark.parametrize('wrong_id', ['m3', ':rule', 'invented-source'])
def test_empty_knowledge_rejects_source_ids(inputs, criterion, wrong_id):
    data = valid_answer(inputs[0])
    data['criteria'][criterion]['source_ids'] = [wrong_id]
    with pytest.raises(ValidationError):
        validator(inputs).validate(data)


def test_both_empty_knowledge_states_are_valid_without_changing_score(inputs):
    data = valid_answer(inputs[0])
    validator(inputs).validate(data)
    before = data['criteria']['c4']['answer']
    add_claim(data)
    validator(inputs).validate(data)
    assert data['criteria']['c4']['answer'] == before


@pytest.mark.parametrize('bad_state', ['unverified_empty', 'not_needed_with_claim', 'empty_claim_limitation',
                                     'supported_claim', 'contradiction_without_sources', 'claim_source'])
def test_incoherent_claim_states_are_impossible_in_schema(inputs, bad_state):
    data = valid_answer(inputs[0])
    d = add_claim(data)
    claim = d['knowledge_review']['external_claims'][0]
    if bad_state == 'unverified_empty':
        d['knowledge_review']['external_claims'] = []
    elif bad_state == 'not_needed_with_claim':
        d['knowledge_status'] = 'not_needed'
    elif bad_state == 'empty_claim_limitation':
        claim['limitation'] = ''
    elif bad_state == 'supported_claim':
        claim['status'] = 'supported'
    elif bad_state == 'contradiction_without_sources':
        claim['document_relation'] = 'contradicts'
    else:
        claim['source_ids'] = ['m3']
    with pytest.raises(ValidationError):
        validator(inputs).validate(data)


def test_nonknowledge_and_na_cannot_claim_external_verification(inputs):
    data = valid_answer(inputs[0])
    knowledge = Knowledge.model_validate({'sources': [{'id': 'doc-1', 'title': 'Тест', 'text': 'Тест'}]})
    validate = validator(inputs, knowledge)
    d = data['criteria']['c2']
    d.update(answer='na', na_condition_id='enough_information_initially')
    validate.validate(data)
    d['source_ids'] = ['doc-1']
    with pytest.raises(ValidationError):
        validate.validate(data)
    d['source_ids'] = []
    data['criteria']['c1']['knowledge_status'] = 'unverified'
    with pytest.raises(ValidationError):
        validate.validate(data)


def test_source_ids_with_real_knowledge_are_bounded_not_disabled(inputs):
    data = valid_answer(inputs[0])
    d = add_claim(data)
    knowledge = Knowledge.model_validate({'sources': [{'id': 'doc-1', 'title': 'Тест', 'text': 'Тест'}]})
    d['source_ids'] = ['doc-1']
    d['knowledge_review']['external_claims'][0]['source_ids'] = ['doc-1']
    validate = validator(inputs, knowledge)
    validate.validate(data)
    d['source_ids'] = ['unknown']
    with pytest.raises(ValidationError):
        validate.validate(data)


def test_exact_limitation_copy_remains_post_validation_requirement(inputs):
    data = valid_answer(inputs[0])
    d = add_claim(data)
    d['limitations'] = ['Другой текст ограничения.']
    validator(inputs).validate(data)
    with pytest.raises(AssessmentError, match='ограничение утверждения должно сохраняться'):
        validate_assessment(ModelAssessment.model_validate(data), inputs[1], inputs[0], Knowledge(),
                            require_contradiction_basis=True)


def test_mutable_scale_and_channel_na_still_control_schema(inputs):
    checklist, _dialogue = inputs
    c = checklist.criteria[5]
    c.options[0].value = 'custom-low'
    data = valid_answer(checklist)
    validator(inputs).validate(data)
    data['criteria'][c.id]['answer'] = 'made-up'
    with pytest.raises(ValidationError):
        validator(inputs).validate(data)
    data = valid_answer(checklist)
    data['criteria']['c2'].update(answer='na', na_condition_id='made-up')
    with pytest.raises(ValidationError):
        validator(inputs).validate(data)


def test_prepared_170_retains_strict_validation_and_recalculation(inputs, tmp_path):
    from tokenizers import Tokenizer, models, pre_tokenizers

    checklist, dialogue = inputs
    raw = read_json(ROOT / 'config/settings.experiment-control.json')
    tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    token_path = tmp_path / 'synthetic-tokenizer.json'
    tokenizer.save(str(token_path))
    raw['context_tokenizer_path'] = str(token_path)
    raw['context_tokenizer_sha256'] = hashlib.sha256(token_path.read_bytes()).hexdigest()
    settings = Settings.model_validate(raw)
    answer = valid_answer(checklist)
    text = ModelAssessment.model_validate(answer).model_dump_json()
    class FakeProvider:
        def evaluate(self, request):
            return ProviderResponse(raw={'usage': {'input_tokens': 1, 'output_tokens': 1}},
                                    text=text, status='completed', refusal=False)
    request = build_request(settings, build_input(dialogue, checklist, Knowledge()),
                            response_schema(checklist, Knowledge(), dialogue), settings.max_output_tokens)
    job = make_job(dialogue, checklist, Knowledge(), settings, request, 'cqa-1.7.0', {'offline': True})
    result = Engine(Store(tmp_path / 'runs.db'), settings, FakeProvider()).evaluate(
        dialogue, checklist, Knowledge(), prepared=job)
    assert PROMPT_VERSION == 'cqa-1.7.2'
    assert result['prompt_version'] == 'cqa-1.7.0' and result['validation_policy'] == VALIDATION_POLICY
    assert result['assessment'] and recalculate(result) == result['scoring']
    for version in ['cqa-1.7.0', 'cqa-1.7.1', 'cqa-1.7.2']:
        assert _validation_options({'prompt_version': version})['require_contradiction_basis']


def test_live_prior_results_still_recalculate(inputs):
    folder = ROOT / 'outputs/quality-v3/comparison-20261108-01/worker-results'
    paths = sorted(p for p in folder.glob('*.json') if '-A_baseline-' in p.name)
    if not paths:
        pytest.skip('Local saved runs are deliberately not part of the repository')
    for path in paths:
        result = read_json(path)
        if result.get('assessment'):
            assert recalculate(result) == result['scoring']
            assert fingerprint(Checklist.model_validate(result['checklist'])) == result['checklist_hash']
