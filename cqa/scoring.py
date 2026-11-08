from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

from .contracts import Checklist, ModelAssessment


def calculate(assessment: ModelAssessment, checklist: Checklist) -> dict:
    return calculate_answers({k: d.answer for k, d in assessment.criteria.items()}, checklist,
                             {k: d.na_condition_id for k, d in assessment.criteria.items()})


def calculate_answers(answers: dict[str, str], checklist: Checklist,
                      na_conditions: dict[str, str | None]) -> dict:
    """The same arithmetic for model decisions and explicitly confirmed human answers."""
    if set(answers) != {c.id for c in checklist.criteria}:
        raise ValueError("Нельзя считать неполный результат")
    with localcontext() as context:
        context.prec = 40
        applicable_weight = sum((c.weight for c in checklist.criteria
                                 if c.kind != "flag" and answers[c.id] != "na"), Decimal(0))
        total = Decimal(0)
        rows, sections, violations = [], {}, []
        for criterion in checklist.criteria:
            answer = answers[criterion.id]
            option = next((o for o in criterion.options if o.value == answer), None)
            if answer == "na":
                if not criterion.na_conditions or na_conditions.get(criterion.id) not in {
                    n.id for n in criterion.na_conditions
                }:
                    raise ValueError("Недопустимый N/A")
            elif option is None:
                raise ValueError("Недопустимая оценка")
            effective = points = None
            if answer != "na" and criterion.kind != "flag" and applicable_weight > 0:
                effective = checklist.total_max * criterion.weight / applicable_weight
                points = effective * option.raw_score / criterion.max_score
                total += points
                sections[criterion.section] = sections.get(criterion.section, Decimal(0)) + points
            if criterion.kind == "flag" and answer == criterion.violation_value:
                violations.append(criterion.id)
            rows.append({"criterion_id": criterion.id, "title": criterion.title,
                         "answer": answer, "raw_score": str(option.raw_score) if option else None,
                         "max_score": str(criterion.max_score), "base_weight": str(criterion.weight),
                         "effective_weight": str(effective) if effective is not None else None,
                         "points": str(points) if points is not None else None})
        return {"total_score": str(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                if applicable_weight > 0 else None,
                "total_max": str(checklist.total_max), "applicable_weight": str(applicable_weight),
                "criteria": rows, "sections": {k: str(v) for k, v in sections.items()},
                "gross_violation": bool(violations), "violation_criteria": violations,
                "rounding": "ROUND_HALF_UP; only final total is rounded"}
