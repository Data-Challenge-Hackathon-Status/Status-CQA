"""Deterministic comparisons for the local workspace; no model calls."""
from __future__ import annotations

from decimal import Decimal, localcontext

from .contracts import Checklist


def checklist_comparison(before: Checklist, after: Checklist) -> dict:
    """Compare validated values by criterion ID, including every assessment field.

    Version labels and criterion order do not invalidate answers. Any change to
    instructions (including checklist notes) does. Decimal equality avoids
    treating 10 and 10.0 as different weights.
    """
    old = {c.id: c for c in before.criteria}
    new = {c.id: c for c in after.criteria}
    rows = []
    for key in [*new, *(key for key in old if key not in new)]:
        a, b = old.get(key), new.get(key)
        fields = []
        if a and b:
            fields = [field for field in type(a).model_fields
                      if field != 'id' and getattr(a, field) != getattr(b, field)]
        rows.append({
            'id': key, 'status': 'added' if not a else 'removed' if not b else 'changed' if fields else 'unchanged',
            'fields': fields,
            'before': a.model_dump(mode='json') if a else None,
            'after': b.model_dump(mode='json') if b else None,
        })
    global_fields = [key for key in ('title', 'notes', 'total_max') if getattr(before, key) != getattr(after, key)]
    reordered = list(old) != list(new) and set(old) == set(new)
    rules_changed = any(r['status'] in {'added', 'removed'} or set(r['fields']) - {'weight'} for r in rows)
    rules_changed = bool(rules_changed or set(global_fields) & {'title', 'notes'})
    scoring_changed = 'total_max' in global_fields or any('weight' in r['fields'] for r in rows)
    mode = 'reanalyze' if rules_changed else 'recalculate' if scoring_changed else 'compatible'
    return {
        'before': before.model_dump(mode='json'), 'after': after.model_dump(mode='json'),
        'criteria': rows, 'global_fields': global_fields, 'reordered': reordered,
        'mode': mode, 'can_reweight': not rules_changed,
        'counts': {status: sum(r['status'] == status for r in rows)
                   for status in ('added', 'removed', 'changed', 'unchanged')},
    }


def _different(a, b):
    return (Decimal(a) != Decimal(b)) if a is not None and b is not None else a != b


def _delta(a, b):
    if a is None or b is None:
        return None
    with localcontext() as context:
        context.prec = 40
        return str(Decimal(b) - Decimal(a))


def assessment_comparison(checklist: dict, before: dict, after: dict | None) -> dict:
    """Keep absence of a decision distinct from a zero; expose N/A side effects."""
    rows = []
    left = {r['criterion_id']: r for r in before['scoring']['criteria']}
    right = {r['criterion_id']: r for r in after['scoring']['criteria']} if after else {}
    for criterion in checklist['criteria']:
        key = criterion['id']
        a = {**before['decisions'][key], **left[key]}
        b = {**after['decisions'][key], **right[key]} if after else None
        for decision in (a, b):
            if decision is not None:
                decision['na_condition'] = next((n['description'] for n in criterion['na_conditions']
                                                if n['id'] == decision.get('na_condition_id')), None)
        answer_changed = bool(b and (a['answer'], a.get('na_condition_id')) !=
                              (b['answer'], b.get('na_condition_id')))
        reason_changed = bool(b and a['reason'] != b['reason'])
        weight_changed = bool(b and _different(a['effective_weight'], b['effective_weight']))
        points_changed = bool(b and _different(a['points'], b['points']))
        rows.append({'id': key, 'title': criterion['title'], 'kind': criterion['kind'],
                     'before': a, 'after': b, 'answer_changed': answer_changed,
                     'reason_changed': reason_changed, 'weight_changed': weight_changed,
                     'points_changed': points_changed,
                     'changed': answer_changed or reason_changed or weight_changed or points_changed,
                     'points_delta': _delta(a['points'], b['points']) if b else None})
    return {'before': before['scoring'], 'after': after['scoring'] if after else None,
            'score_delta': _delta(before['scoring']['total_score'], after['scoring']['total_score']) if after else None,
            'critical_changed': bool(after and before['scoring']['gross_violation'] != after['scoring']['gross_violation']),
            'criteria': rows}
