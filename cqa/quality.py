from __future__ import annotations

import random
from collections import Counter, defaultdict
from decimal import Decimal

from .contracts import Checklist, Dialogue, ModelAssessment
from .io import fingerprint
from .scoring import calculate


def make_split(dialogues: list[Dialogue], seed: int = 42) -> dict:
    """Freeze a language-balanced split; keep exact transcript duplicates together."""
    if len(dialogues) != 65:
        raise ValueError("Этот план разбиения рассчитан на DEV из 65 диалогов")
    grouped = defaultdict(list)
    for dialogue in dialogues:
        signature = fingerprint([(m.speaker, m.text) for m in dialogue.transcript])
        grouped[signature].append(dialogue)
    duplicates = [g for g in grouped.values() if len(g) > 1]
    if duplicates:
        raise ValueError("Есть точные дубликаты. Сначала объедините их в группы перед независимым разбиением.")
    rng = random.Random(seed)
    pools = defaultdict(list)
    for dialogue in sorted(dialogues, key=lambda d: d.conversation_id):
        pools[(dialogue.channel, dialogue.language)].append(dialogue.conversation_id)
    for ids in pools.values():
        rng.shuffle(ids)
    voice = [d.conversation_id for d in dialogues if d.channel == "voice call"]
    rng.shuffle(voice)
    result = {"seed": seed, "purpose": "Внутренняя проверка, не эталон организаторов",
              "requires_manual_near_duplicate_review": True, "tuning": [], "validation": [],
              "holdout": [], "unlabelled": []}
    for key, n_chat, n_voice in [("holdout", 9, 1), ("validation", 7, 1), ("tuning", 9, 3)]:
        result[key].extend(voice[:n_voice])
        del voice[:n_voice]
        for i in range(n_chat):
            languages = ["RU", "KZ", "EN"]
            preferred = languages[i % 3]
            available = pools[("agent chat", preferred)]
            if not available:
                available = max((v for (c, _), v in pools.items() if c == "agent chat"), key=len)
            result[key].append(available.pop())
    selected = set(result["tuning"] + result["validation"] + result["holdout"])
    result["unlabelled"] = sorted(d.conversation_id for d in dialogues if d.conversation_id not in selected)
    result["dataset_hash"] = fingerprint([d.model_dump(mode="json") for d in sorted(
        dialogues, key=lambda d: d.conversation_id)])
    return result


def annotation_template(dialogues: list[Dialogue], checklist: Checklist, ids: list[str]) -> dict:
    by_id = {d.conversation_id: d for d in dialogues}
    return {"label_source": "human_pending", "checklist_hash": fingerprint(checklist),
            "instructions": "Разметить до просмотра ответа модели. Это внутренняя разметка, не Ground Truth организаторов.",
            "records": [{"conversation_id": i, "language": by_id[i].language,
                         "channel": by_id[i].channel, "assessment": None,
                         "notes": "", "dialogue": by_id[i].model_dump(mode="json")}
                        for i in ids]}


def compare(labels: dict, evaluations: list[dict], checklist: Checklist) -> dict:
    if labels.get("label_source") != "human":
        raise ValueError("Нужна заполненная человеком разметка с label_source=human")
    if labels.get("checklist_hash") != fingerprint(checklist):
        raise ValueError("Разметка относится к другому чек-листу")
    records = labels.get("records", [])
    if not records:
        raise ValueError("Набор ручной разметки пуст")
    label_ids = [r["conversation_id"] for r in records]
    if len(set(label_ids)) != len(label_ids):
        raise ValueError("Диалог повторяется в ручной разметке")
    index = {}
    for evaluation in evaluations:
        if evaluation["checklist_hash"] != fingerprint(checklist):
            raise ValueError("Результаты относятся к другому чек-листу")
        key = evaluation["conversation_id"]
        if key in index:
            raise ValueError("Укажите ровно один запуск на диалог, чтобы не выбирать лучший результат задним числом")
        index[key] = evaluation
    per_criterion = defaultdict(lambda: {"matched": 0, "total": 0})
    groups = defaultdict(lambda: {"matched": 0, "total": 0})
    errors, na, violations = [], Counter(), Counter()
    missing = []
    if set(index) - set(label_ids):
        raise ValueError("Есть запуски для диалогов вне выбранной ручной разметки")
    for row in records:
        if row.get("assessment") is None:
            raise ValueError("Ручная разметка не завершена")
        expected = ModelAssessment.model_validate(row["assessment"])
        expected_score = calculate(expected, checklist)
        evaluation = index.get(row["conversation_id"])
        if not evaluation or not evaluation.get("assessment"):
            missing.append(row["conversation_id"])
            continue
        actual = ModelAssessment.model_validate(evaluation["assessment"])
        actual_score = calculate(actual, checklist)
        for criterion in checklist.criteria:
            a, b = expected.criteria[criterion.id].answer, actual.criteria[criterion.id].answer
            tally = per_criterion[criterion.id]
            tally["total"] += 1
            tally["matched"] += int(a == b)
            for group in (row["language"], row["channel"]):
                groups[group]["total"] += 1
                groups[group]["matched"] += int(a == b)
            if (a == "na") != (b == "na"):
                na["false_na" if b == "na" else "missed_na"] += 1
            if criterion.kind == "flag" and a != b:
                violations["false_positive" if b == criterion.violation_value else "false_negative"] += 1
        if expected_score["total_score"] is not None and actual_score["total_score"] is not None:
            errors.append(abs(Decimal(expected_score["total_score"]) - Decimal(actual_score["total_score"])))
    for tally in [*per_criterion.values(), *groups.values()]:
        tally["exact_match_rate"] = tally["matched"] / tally["total"] if tally["total"] else None
    rates = [v["exact_match_rate"] for v in per_criterion.values() if v["total"]]
    return {"reference": "Внутренняя ручная разметка, не эталон организаторов",
            "macro_exact_match_rate": sum(rates) / len(rates) if rates else None,
            "per_criterion": dict(per_criterion), "groups": dict(groups),
            "total_score_mae": str(sum(errors) / len(errors)) if errors else None,
            "scored_dialogues": len(errors), "missing_or_failed_dialogues": missing,
            "na_errors": dict(na), "violation_errors": dict(violations)}
