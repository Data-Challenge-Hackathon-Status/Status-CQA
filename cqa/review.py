"""Blind human review and measurements; no model calls and no automatic human labels."""
from __future__ import annotations

import argparse
import math
from collections import Counter
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .contracts import Checklist, Dialogue
from .engine import recalculate
from .io import fingerprint, load_dialogues, read_json, write_json
from .scoring import calculate_answers
from .storage import Store


def build_package(dialogues, checklist, ids, *, tuning_ids, known_exposure=()):
    if not ids or len(set(ids)) != len(ids) or not set(ids) <= set(tuning_ids):
        raise ValueError("Для настройки используйте уникальные ID только из tuning")
    by_id = {d.conversation_id: d for d in dialogues}
    package = {"schema_version": "blind-package-1.0", "checklist": checklist.model_dump(mode="json"),
               "checklist_hash": fingerprint(checklist), "records": []}
    for cid in ids:
        dialogue = by_id[cid]
        package["records"].append({"conversation_id": cid, "dialogue_hash": fingerprint(dialogue),
                                   "known_model_exposure": cid in known_exposure,
                                   "dialogue": dialogue.model_dump(mode="json")})
    package["package_id"] = fingerprint(package)
    return package


def check_package(package):
    raw = {k: v for k, v in package.items() if k != "package_id"}
    if fingerprint(raw) != package["package_id"]:
        raise ValueError("Содержимое пакета разметки изменено")
    checklist = Checklist.model_validate(package["checklist"])
    if fingerprint(checklist) != package["checklist_hash"]:
        raise ValueError("Контрольная сумма чек-листа не совпадает")
    for row in package["records"]:
        if fingerprint(Dialogue.model_validate(row["dialogue"])) != row["dialogue_hash"]:
            raise ValueError("Исходный разговор изменён")
    return checklist


def review_template(package):
    checklist = check_package(package)
    return {"schema_version": "human-review-1.0", "package_id": package["package_id"],
            "label_source": "human_pending", "reviewer": "", "human_attestation": False,
            "reviewed_at": None, "records": [{
                "conversation_id": row["conversation_id"], "dialogue_hash": row["dialogue_hash"],
                "language_confidence": "", "model_exposure": "seen" if row["known_model_exposure"] else "",
                "notes": "", "criteria": {c.id: {"state": "pending", "confirmed_by_human": False,
                    "answer": None, "na_condition_id": None, "reason": "", "evidence_message_ids": [],
                    "evidence_kind": "range", "expected_action": None,
                    "knowledge_scope": "" if c.requires_company_knowledge else "not_applicable",
                    "materials_note": ""} for c in checklist.criteria}
            } for row in package["records"]]}


def validate_review(package, review):
    checklist = check_package(package)
    if review.get("schema_version") != "human-review-1.0" or review.get("package_id") != package["package_id"]:
        raise ValueError("Разметка относится к другому пакету")
    if review.get("label_source") not in {"human_pending", "human"}:
        raise ValueError("Предварительная AI-разметка не является человеческой")
    expected = {r["conversation_id"]: r for r in package["records"]}
    rows = review.get("records", [])
    if len(rows) != len(expected) or {r["conversation_id"] for r in rows} != set(expected):
        raise ValueError("Нужна одна запись на каждый диалог пакета, включая неразмеченные")
    confirmed, disputes, complete = {}, [], []
    for row in rows:
        cid = row["conversation_id"]
        source = expected[cid]
        if row.get("dialogue_hash") != source["dialogue_hash"]:
            raise ValueError("Разметка относится к другой версии диалога")
        messages = {m["id"] for m in source["dialogue"]["transcript"]}
        if set(row["criteria"]) != {c.id for c in checklist.criteria}:
            raise ValueError("Набор критериев в карточке изменён")
        for c in checklist.criteria:
            decision = row["criteria"][c.id]
            state = decision.get("state")
            if state not in {"pending", "disputed", "confirmed"}:
                raise ValueError("Неизвестное состояние разметки")
            if state != "confirmed":
                if decision.get("confirmed_by_human") is not False:
                    raise ValueError("Неподтверждённая оценка не может иметь подтверждение человека")
                if state == "disputed":
                    if not decision.get("reason", "").strip():
                        raise ValueError("Для спорного случая нужно пояснение")
                    disputes.append({"conversation_id": cid, "criterion_id": c.id,
                                     "reason": decision["reason"]})
                continue
            if (decision.get("confirmed_by_human") is not True or review.get("label_source") != "human"
                    or review.get("human_attestation") is not True or not review.get("reviewer", "").strip()):
                raise ValueError("Оценку должен явно подтвердить человек; автоматическое подтверждение запрещено")
            try:
                reviewed_at = datetime.fromisoformat(review["reviewed_at"])
                if reviewed_at.utcoffset() is None:
                    raise ValueError
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Нужна дата подтверждения с часовым поясом") from exc
            if row.get("language_confidence") != "confident":
                raise ValueError("Нельзя подтвердить оценку без уверенного понимания языка")
            if row.get("model_exposure") not in {"seen", "not_seen", "unsure"}:
                raise ValueError("Отметьте, видели ли вы ответ модели")
            if source["known_model_exposure"] and row["model_exposure"] == "not_seen":
                raise ValueError("Для этого примера уже известно знакомство с ответом модели")
            answer = decision.get("answer")
            if answer == "na":
                if decision.get("na_condition_id") not in {n.id for n in c.na_conditions
                        if n.channels is None or source["dialogue"]["channel"] in n.channels}:
                    raise ValueError("N/A требует разрешённого условия")
            elif (answer not in {o.value for o in c.options} or decision.get("na_condition_id") is not None):
                raise ValueError("Недопустимая оценка или лишнее условие N/A")
            refs = decision.get("evidence_message_ids", [])
            if not refs or set(refs) - messages or not decision.get("reason", "").strip():
                raise ValueError("Подтверждение требует объяснения и существующих ссылок на сообщения")
            if decision.get("evidence_kind") not in {"range", "missing_action"}:
                raise ValueError("Неизвестный тип доказательства")
            if decision["evidence_kind"] == "missing_action" and not (decision.get("expected_action") or "").strip():
                raise ValueError("Укажите, какое действие ожидалось в отмеченном участке")
            if c.requires_company_knowledge and answer != "na":
                if decision.get("knowledge_scope") not in {"observable_only", "with_company_sources"}:
                    raise ValueError("Разделите оценку наблюдаемой полноты и проверку продуктовых фактов")
                if decision["knowledge_scope"] == "with_company_sources" and not decision.get("materials_note", "").strip():
                    raise ValueError("Укажите материалы, по которым человек проверил продуктовые факты")
            confirmed[(cid, c.id)] = decision
        if all((cid, c.id) in confirmed for c in checklist.criteria):
            complete.append(cid)
    return checklist, confirmed, disputes, complete


def checked_evaluations(package, evaluations, compatibility=None):
    from .compatibility import assert_compatible
    sources = {r["conversation_id"]: r for r in package["records"]}
    index = {}
    for evaluation in evaluations:
        cid = evaluation["conversation_id"]
        if cid in index or cid not in sources:
            raise ValueError("Нужен один заранее выбранный запуск на диалог пакета; выбор лучшего запрещён")
        if evaluation["dialogue_hash"] != sources[cid]["dialogue_hash"]:
            raise ValueError("Запуск относится к другому диалогу или чек-листу")
        candidate = Checklist.model_validate(evaluation["checklist"])
        if fingerprint(candidate) != evaluation["checklist_hash"]:
            raise ValueError("Хеш чек-листа запуска изменён")
        assert_compatible(Checklist.model_validate(package["checklist"]), candidate, compatibility)
        if evaluation.get("assessment") and recalculate(evaluation) != evaluation.get("scoring"):
            raise ValueError("Баллы сохранённого запуска изменены")
        index[cid] = evaluation
    return index


def _operation_metrics(evaluations, planned_dialogues):
    """Attempt time and end-to-end elapsed time are different measurements."""
    complete_attempt_totals, known_attempt_times, processing_times = [], [], []
    all_attempts = []
    for evaluation in evaluations:
        attempts = evaluation.get("attempts", [])
        all_attempts.extend(attempts)
        timings = []
        for attempt in attempts:
            try:
                start = datetime.fromisoformat(attempt["started_at"])
                end = datetime.fromisoformat(attempt["finished_at"])
                seconds = (end - start).total_seconds()
                if start.utcoffset() is None or end.utcoffset() is None or seconds < 0:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            timings.append(seconds)
        known_attempt_times.extend(timings)
        if attempts and len(timings) == len(attempts):
            complete_attempt_totals.append(sum(timings))
        elapsed = evaluation.get("elapsed_seconds")
        if type(elapsed) in {int, float} and math.isfinite(elapsed) and elapsed >= 0:
            processing_times.append(elapsed)
    return {"evaluations": len(evaluations), "planned_dialogues": planned_dialogues,
        "missing_evaluations": planned_dialogues - len(evaluations), "attempts": len(all_attempts),
        "failures_by_code": dict(Counter(e["error"] for e in evaluations if e.get("error"))),
        "format_or_evidence_invalid_attempts": sum(bool(a.get("errors")) and a.get("response") is not None
                                                  for a in all_attempts),
        # Preserve the historical fields: their unit is fully timed evaluations' attempts,
        # not the elapsed duration of the complete evaluation pipeline.
        "elapsed_seconds_available": len(complete_attempt_totals),
        "total_attempt_seconds": sum(complete_attempt_totals) if complete_attempt_totals else None,
        "mean_attempt_seconds_per_evaluation": (sum(complete_attempt_totals) / len(complete_attempt_totals)
                                                if complete_attempt_totals else None),
        "attempt_time": {"recorded_attempts": len(all_attempts), "timed_attempts": len(known_attempt_times),
            "missing_timed_attempts": len(all_attempts) - len(known_attempt_times),
            "evaluations_with_complete_attempt_timing": len(complete_attempt_totals),
            "evaluations_without_complete_attempt_timing": len(evaluations) - len(complete_attempt_totals),
            "total_known_attempt_seconds": sum(known_attempt_times) if known_attempt_times else None},
        "processing_time": {"source": "elapsed_seconds", "measured_evaluations": len(processing_times),
            "missing_measured_evaluations": len(evaluations) - len(processing_times),
            "planned_dialogues_without_measurement": planned_dialogues - len(processing_times),
            "total_seconds": sum(processing_times) if processing_times else None,
            "mean_seconds": sum(processing_times) / len(processing_times) if processing_times else None}}


def _slice_metrics(checklist, confirmed, index, ids):
    """Count only confirmed references; missing outcomes never become true negatives."""
    criteria = {c.id: c for c in checklist.criteria}
    tallies = {c.id: {"confirmed": 0, "prediction_available": 0, "matched": 0} for c in checklist.criteria}
    confusion = {"criterion_ids": [c.id for c in checklist.criteria if c.kind == "flag"],
        "confirmed_positive": 0, "confirmed_negative": 0, "confirmed_not_applicable": 0,
        "available_predictions": 0, "missing_predictions": 0, "missing_positive": 0, "missing_negative": 0,
        "tp": 0, "tn": 0, "fp": 0, "fn": 0}
    na = {"false_na": 0, "missed_na": 0}
    keys = [key for key in confirmed if key[0] in ids]
    missing_ids = set()
    for cid, criterion_id in keys:
        reference = confirmed[(cid, criterion_id)]["answer"]
        tally, criterion = tallies[criterion_id], criteria[criterion_id]
        tally["confirmed"] += 1
        assessment = index.get(cid, {}).get("assessment")
        actual = assessment["criteria"][criterion_id]["answer"] if assessment else None
        if actual is None:
            missing_ids.add(cid)
        else:
            tally["prediction_available"] += 1
            tally["matched"] += actual == reference
            na["false_na"] += actual == "na" and reference != "na"
            na["missed_na"] += reference == "na" and actual != "na"
        if criterion.kind == "flag":
            if reference == "na":
                confusion["confirmed_not_applicable"] += 1
                continue
            positive = reference == criterion.violation_value
            confusion["confirmed_positive" if positive else "confirmed_negative"] += 1
            if actual is None:
                confusion["missing_predictions"] += 1
                confusion["missing_positive" if positive else "missing_negative"] += 1
            else:
                confusion["available_predictions"] += 1
                predicted_positive = actual == criterion.violation_value
                confusion[("tp" if predicted_positive else "fn") if positive else
                          ("fp" if predicted_positive else "tn")] += 1
    for tally in tallies.values():
        tally["missing_predictions"] = tally["confirmed"] - tally["prediction_available"]
        tally["exact_match_rate"] = tally["matched"] / tally["confirmed"] if tally["confirmed"] else None
    evaluations = [index[cid] for cid in sorted(ids) if cid in index]
    available = sum(t["prediction_available"] for t in tallies.values())
    matched = sum(t["matched"] for t in tallies.values())
    return {"package_dialogues": len(ids), "confirmed_dialogues": len({cid for cid, _ in keys}),
        "confirmed_criteria": len(keys), "available_predictions": available, "missing_predictions": len(keys) - available,
        "matched": matched, "exact_match_rate": matched / len(keys) if keys else None,
        "per_criterion": tallies, "na_errors": na, "violation_confusion": confusion,
        "missing_or_failed_dialogues": sorted(missing_ids),
        "outcomes": {"evaluations_received": len(evaluations), "missing_evaluations": len(ids) - len(evaluations),
            "accepted_evaluations": sum(bool(e.get("assessment")) for e in evaluations),
            "failed_evaluations": sum(e.get("status") == "failed" for e in evaluations),
            "incomplete_response_evaluations": sum(e.get("error") == "incomplete_model_response" for e in evaluations),
            "unfinished_evaluations": sum(e.get("status") not in {"completed", "provisional", "failed"}
                                          for e in evaluations)},
        "operations": _operation_metrics(evaluations, len(ids))}


def compare_review(package, review, evaluations, semantic=None, compatibility=None):
    checklist, confirmed, disputes, complete = validate_review(package, review)
    index = checked_evaluations(package, evaluations, compatibility)
    tallies = {c.id: {"matched": 0, "confirmed": 0, "prediction_available": 0} for c in checklist.criteria}
    na, flags, missing = Counter(), Counter(), set()
    for (cid, criterion_id), decision in confirmed.items():
        tally = tallies[criterion_id]
        tally["confirmed"] += 1
        evaluation = index.get(cid)
        if not evaluation or not evaluation.get("assessment"):
            missing.add(cid)
            continue
        actual = evaluation["assessment"]["criteria"][criterion_id]["answer"]
        expected = decision["answer"]
        tally["prediction_available"] += 1
        tally["matched"] += actual == expected
        if (actual == "na") != (expected == "na"):
            na["false_na" if actual == "na" else "missed_na"] += 1
        criterion = next(c for c in checklist.criteria if c.id == criterion_id)
        if criterion.kind == "flag" and actual != expected:
            flags["false_positive" if actual == criterion.violation_value else "false_negative"] += 1
    for tally in tallies.values():
        tally["exact_match_rate"] = tally["matched"] / tally["confirmed"] if tally["confirmed"] else None
    rates = [v["exact_match_rate"] for v in tallies.values() if v["confirmed"]]
    errors, score_errors = [], {}
    for cid in complete:
        actual = index.get(cid)
        if not actual or not actual.get("assessment"):
            continue
        decisions = {c.id: confirmed[(cid, c.id)] for c in checklist.criteria}
        expected = calculate_answers({k: d["answer"] for k, d in decisions.items()}, checklist,
                                     {k: d["na_condition_id"] for k, d in decisions.items()})
        if expected["total_score"] is not None and actual["scoring"]["total_score"] is not None:
            score_errors[cid] = abs(Decimal(expected["total_score"]) - Decimal(actual["scoring"]["total_score"]))
            errors.append(score_errors[cid])
    blind = {r["conversation_id"] for r in review["records"] if r.get("model_exposure") == "not_seen"}
    knowledge_scopes = {c.id: dict(Counter("not_applicable" if d["answer"] == "na" else d["knowledge_scope"]
                         for (_, criterion_id), d in confirmed.items() if criterion_id == c.id))
                        for c in checklist.criteria if c.requires_company_knowledge}
    report = {"reference": "Подтверждённая внутренняя человеческая разметка, не эталон организаторов",
              "human_confirmed_dialogues": len(complete), "human_confirmed_criteria": len(confirmed),
              "blind_confirmed_criteria": sum(cid in blind for cid, _ in confirmed),
              "knowledge_reference_scopes": knowledge_scopes,
              "per_criterion": tallies, "na_errors": dict(na), "violation_errors": dict(flags),
              "macro_exact_match_rate": sum(rates) / len(rates) if rates else None,
              "total_score_mae": str(sum(errors) / len(errors)) if errors else None,
              "scored_dialogues": len(errors), "missing_or_failed_dialogues": sorted(missing),
              "disputed_cases": disputes,
              "semantic_evidence": {"checked": 0, "supported": 0, "unsupported": 0, "uncertain": 0}}
    from .compatibility import assert_compatible
    report["checklist_compatibility"] = [assert_compatible(
        checklist, Checklist.model_validate(e["checklist"]), compatibility) for e in evaluations]
    report["per_language"] = {}
    for language in ("RU", "KZ", "EN"):
        ids = {r["conversation_id"] for r in package["records"] if r["dialogue"]["language"] == language}
        keys = [key for key in confirmed if key[0] in ids]
        available = [key for key in keys if index.get(key[0], {}).get("assessment")]
        matched = sum(index[cid]["assessment"]["criteria"][criterion]["answer"] == confirmed[(cid, criterion)]["answer"]
                      for cid, criterion in available)
        report["per_language"][language] = {"package_dialogues": len(ids),
            "complete_human_dialogues": len(ids & set(complete)), "confirmed_criteria": len(keys),
            "available_predictions": len(available), "matched": matched,
            "exact_match_rate": matched / len(keys) if keys else None}
    report["per_channel"] = {}
    for channel in ("agent chat", "voice call"):
        ids = {r["conversation_id"] for r in package["records"] if r["dialogue"]["channel"] == channel}
        differences = [v for cid, v in score_errors.items() if cid in ids]
        metrics = _slice_metrics(checklist, confirmed, index, ids)
        metrics.update(scored_dialogues=len(differences), complete_human_dialogues=len(ids & set(complete)),
            total_score_mae=str(sum(differences) / len(differences)) if differences else None,
            semantic_evidence={"checked": 0, "supported": 0, "unsupported": 0, "uncertain": 0})
        metrics["per_language"] = {}
        for language in ("RU", "KZ", "EN"):
            language_ids = {r["conversation_id"] for r in package["records"]
                            if r["dialogue"]["language"] == language} & ids
            metrics["per_language"][language] = _slice_metrics(checklist, confirmed, index, language_ids)
        report["per_channel"][channel] = metrics
    report["operations"] = _operation_metrics(evaluations, len(package["records"]))
    if semantic is not None:
        if (semantic.get("review_hash") != fingerprint(review) or semantic.get("label_source") != "human"
                or semantic.get("human_attestation") is not True or not semantic.get("reviewer", "").strip()):
            raise ValueError("Проверку смысла доказательств должен подтвердить человек для этой разметки")
        seen = set()
        for row in semantic["records"]:
            key = (row["conversation_id"], row["criterion_id"])
            if key in seen or key not in confirmed:
                raise ValueError("Повтор или неподтверждённый критерий в проверке доказательств")
            seen.add(key)
            actual = index.get(key[0])
            if (not actual or row["evaluation_id"] != actual["evaluation_id"]
                    or row["assessment_hash"] != fingerprint(actual["assessment"])
                    or row["model_decision"] != actual["assessment"]["criteria"][key[1]]):
                raise ValueError("Проверка доказательств относится к другой оценке модели")
            status = row["support"]
            if status == "pending":
                continue
            if (status not in {"supported", "unsupported", "uncertain"}
                    or row.get("confirmed_by_human") is not True or not row.get("reason", "").strip()):
                raise ValueError("Нужны подтверждение человека и объяснение смысловой проверки")
            report["semantic_evidence"][status] += 1
            report["semantic_evidence"]["checked"] += 1
            channel = next(r["dialogue"]["channel"] for r in package["records"] if r["conversation_id"] == key[0])
            report["per_channel"][channel]["semantic_evidence"][status] += 1
            report["per_channel"][channel]["semantic_evidence"]["checked"] += 1
    return report


def evidence_template(package, review, evaluations, compatibility=None):
    _, confirmed, _, _ = validate_review(package, review)
    if not confirmed:
        raise ValueError("Сначала человек должен подтвердить хотя бы одну оценку без ответа модели")
    index = checked_evaluations(package, evaluations, compatibility)
    rows = []
    for cid, criterion_id in confirmed:
        actual = index.get(cid)
        if actual and actual.get("assessment"):
            rows.append({"conversation_id": cid, "criterion_id": criterion_id,
                         "evaluation_id": actual["evaluation_id"],
                         "assessment_hash": fingerprint(actual["assessment"]),
                         "model_decision": deepcopy(actual["assessment"]["criteria"][criterion_id]),
                         "support": "pending", "confirmed_by_human": False, "reason": ""})
    return {"label_source": "human_pending", "human_attestation": False, "reviewer": "",
            "review_hash": fingerprint(review), "records": rows,
            "review_questions": ["Какое требование именно этого критерия подтверждает объяснение?",
                "Доказывают ли указанные реплики действие или его отсутствие, с учётом роли и порядка?",
                "Не перенесён ли штраф из другого критерия без отдельного основания?",
                "Соответствуют ли частичный балл или N/A конкретной ступени или условию?",
                "Не объявлено ли отсутствие подтверждения в документах доказательством ошибки?"]}


def stability(round_a, round_b):
    def unique(rows):
        result = {r["conversation_id"]: r for r in rows}
        if len(result) != len(rows):
            raise ValueError("В раунде повторяются диалоги")
        return result
    left, right = unique(round_a), unique(round_b)
    if not left or set(left) != set(right):
        raise ValueError("Для сравнения нужны одинаковые непустые списки диалогов")
    same, total, complete_same, score_diffs, na, flags, unavailable = Counter(), Counter(), 0, [], 0, 0, []
    for cid, a in left.items():
        b = right[cid]
        if a["evaluation_id"] == b["evaluation_id"]:
            raise ValueError("Один сохранённый ответ нельзя выдавать за независимый повтор")
        for field in ("dialogue_hash", "checklist_hash", "knowledge_hash", "settings", "prompt_version",
                      "implementation_hash"):
            if a[field] != b[field]:
                raise ValueError("Стабильность измеряется только внутри одной конфигурации")
        da = {(x.get("provider_metadata") or {}).get("model_digest") for x in a["attempts"]}
        db = {(x.get("provider_metadata") or {}).get("model_digest") for x in b["attempts"]}
        if da != db:
            raise ValueError("Версия весов модели изменилась между повторами")
        if (a["attempts"] and b["attempts"]
                and fingerprint(a["attempts"][0]["request"]) != fingerprint(b["attempts"][0]["request"])):
            raise ValueError("Запросы к модели различаются между повторами")
        if not a.get("assessment") or not b.get("assessment"):
            unavailable.append(cid)
            continue
        recalculate(a)
        recalculate(b)
        matches = []
        checklist = Checklist.model_validate(a["checklist"])
        for c in checklist.criteria:
            x, y = a["assessment"]["criteria"][c.id]["answer"], b["assessment"]["criteria"][c.id]["answer"]
            total[c.id] += 1
            same[c.id] += x == y
            matches.append(x == y)
            na += (x == "na") != (y == "na")
            flags += c.kind == "flag" and x != y
        complete_same += all(matches)
        x, y = a["scoring"]["total_score"], b["scoring"]["total_score"]
        if x is not None and y is not None:
            score_diffs.append(abs(Decimal(x) - Decimal(y)))
    denominator = sum(total.values())
    return {"measures": "Стабильность, не правильность", "dialogues_planned": len(left),
            "all_answers_identical": complete_same, "missing_or_failed_dialogues": unavailable,
            "criterion_matches": sum(same.values()), "criterion_pairs": denominator,
            "agreement_rate": sum(same.values()) / denominator if denominator else None,
            "per_criterion": {k: {"matched": same[k], "pairs": n} for k, n in total.items()},
            "na_disagreements": na, "critical_disagreements": flags,
            "mean_absolute_score_difference": str(sum(score_diffs) / len(score_diffs)) if score_diffs else None}


def write_cards(package, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "package.json", package)
    write_json(directory / "review-template.json", review_template(package))
    template = Path(__file__).with_name("review.html").read_text(encoding="utf-8")
    from .io import json_text
    data = json_text({"package": package, "template": review_template(package)}).replace("<", "\\u003c")
    (directory / "cards.html").write_text(template.replace("__REVIEW_DATA__", data), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Карточки и измерения качества без запросов к модели")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--input", required=True)
    build.add_argument("--plan", required=True)
    build.add_argument("--split", default="data/split.json")
    build.add_argument("--checklist", default="config/checklist.claims-v1.json")
    build.add_argument("--output", required=True)
    for command in ("compare", "evidence-template"):
        item = sub.add_parser(command)
        item.add_argument("package")
        item.add_argument("review")
        item.add_argument("--runs", required=True)
        item.add_argument("--db", default="data/cqa.sqlite3")
        item.add_argument("--output", required=True)
        item.add_argument("--compatibility")
        if command == "compare":
            item.add_argument("--semantic")
    args = parser.parse_args()
    if args.command == "build":
        plan = read_json(args.plan)
        package = build_package([d for d, _ in load_dialogues(read_json(args.input))],
                                Checklist.model_validate(read_json(args.checklist)), plan["selected_tuning_ids"],
                                tuning_ids=read_json(args.split)["tuning"],
                                known_exposure=plan.get("known_human_model_exposure", []))
        write_cards(package, args.output)
    else:
        store = Store(args.db)
        evaluations = [store.get_evaluation(i) for i in read_json(args.runs)["evaluation_ids"]]
        package, review = read_json(args.package), read_json(args.review)
        compatibility = read_json(args.compatibility) if args.compatibility else None
        if args.command == "compare":
            result = compare_review(package, review, evaluations,
                                    read_json(args.semantic) if args.semantic else None, compatibility)
        else:
            result = evidence_template(package, review, evaluations, compatibility)
        if Path(args.output).exists():
            raise ValueError("Файл уже существует: выберите новый путь, старый эксперимент не перезаписывается")
        write_json(args.output, result)
    print("Готово:", args.output)


if __name__ == "__main__":
    main()
