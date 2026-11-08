"""Human appeals are append-only revisions; original model evaluations stay unchanged."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Literal
from uuid import uuid4

from pydantic import Field

from .contracts import Checklist, Decision, Dialogue, Knowledge, ModelAssessment, Record
from .engine import _validation_options, recalculate
from .io import fingerprint, json_text
from .scoring import calculate
from .storage import utc_now
from .validation import validate_assessment


class AppealConflict(ValueError):
    pass


class AppealRequest(Record):
    reviewer: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=8000)
    base_revision: int = Field(ge=0, strict=True)
    changes: dict[str, Decision] = Field(min_length=1)


class ResolutionRequest(Record):
    reviewer: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=8000)
    decision: Literal["accept", "reject"]
    base_revision: int = Field(ge=0, strict=True)


def _nonempty(value):
    if not value.reviewer.strip() or not value.reason.strip():
        raise ValueError("Укажите автора и содержательное обоснование")


def _evaluation(db, evaluation_id):
    row = db.execute("SELECT payload FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
    if row is None:
        raise KeyError("Оценка не найдена")
    result = json.loads(row["payload"])
    if result.get("status") not in {"completed", "provisional"} or not result.get("assessment"):
        raise ValueError("Апелляция доступна только для сохранённой завершённой оценки")
    if recalculate(result) != result.get("scoring"):
        raise ValueError("Исходный результат не проходит проверку целостности")
    return result


def _final(db, result):
    history = [json.loads(r["payload"]) for r in db.execute(
        "SELECT payload FROM final_revisions WHERE evaluation_id=? ORDER BY revision",
        (result["evaluation_id"],))]
    if any(r["original_evaluation_hash"] != fingerprint(result) for r in history):
        raise AppealConflict("Исходная оценка изменилась после апелляции")
    latest = history[-1] if history else None
    return {"evaluation_id": result["evaluation_id"], "revision": latest["revision"] if latest else 0,
        "source": "human_appeal" if latest else "model", "checklist_hash": result["checklist_hash"],
        "original": {"assessment": result["assessment"], "scoring": result["scoring"],
                     "checklist_hash": result["checklist_hash"]},
        "assessment": latest["assessment"] if latest else result["assessment"],
        "scoring": latest["scoring"] if latest else result["scoring"],
        "appeal_id": latest["appeal_id"] if latest else None, "history": history}


def final_result(store, evaluation_id):
    with store.connection() as db:
        return _final(db, _evaluation(db, evaluation_id))


def _proposal(result, final, changes):
    checklist = Checklist.model_validate(result["checklist"])
    if set(changes) - {c.id for c in checklist.criteria}:
        raise ValueError("В апелляции указан неизвестный критерий")
    assessment = deepcopy(final["assessment"])
    for criterion_id, decision in changes.items():
        if not decision.reason.strip():
            raise ValueError("Каждому изменению нужно обоснование")
        assessment["criteria"][criterion_id] = decision.model_dump(mode="json")
    parsed = ModelAssessment.model_validate(assessment)
    options = _validation_options(result)
    # Respect new editable flag policies; older flag criteria retain their action-evidence requirement.
    options.update(require_operator_flag_evidence=True,
                   legacy_operator_flags=result.get("prompt_version") in {"cqa-1.3.0", "cqa-1.4.0", "cqa-1.6.0"})
    validate_assessment(parsed, Dialogue.model_validate(result["dialogue"]), checklist,
                        Knowledge.model_validate(result["knowledge"]), **options)
    return parsed.model_dump(mode="json"), calculate(parsed, checklist)


def _save_proposal(db, result, final, value, appeal_id, created_at, *, allow_confirmation=False):
    _nonempty(value)
    if final["revision"] != value.base_revision:
        raise AppealConflict("Итог уже изменился. Обновите карточку перед отправкой апелляции")
    proposed_assessment, proposed_scoring = _proposal(result, final, value.changes)
    if not allow_confirmation and proposed_assessment == final["assessment"]:
        raise ValueError("Апелляция не содержит изменения оценки, обоснования или доказательства")
    item = {"appeal_id": appeal_id, "evaluation_id": result["evaluation_id"], "created_at": created_at,
        "status": "pending", **value.model_dump(mode="json"),
        "original_evaluation_hash": fingerprint(result), "checklist_hash": result["checklist_hash"],
        "base_assessment_hash": fingerprint(final["assessment"]),
        "proposed_assessment": proposed_assessment, "proposed_scoring": proposed_scoring,
        "resolution": None}
    db.execute("INSERT INTO appeals VALUES (?,?,?,?,?)", (appeal_id, result["evaluation_id"],
               created_at, item["status"], json_text(item)))
    return item


def create_appeal(store, evaluation_id, value: AppealRequest):
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        result = _evaluation(db, evaluation_id)
        return _save_proposal(db, result, _final(db, result), value, str(uuid4()), utc_now())


def list_appeals(store, evaluation_id):
    with store.connection() as db:
        if db.execute("SELECT 1 FROM evaluations WHERE id=?", (evaluation_id,)).fetchone() is None:
            raise KeyError("Оценка не найдена")
        return [json.loads(r["payload"]) for r in db.execute(
            "SELECT payload FROM appeals WHERE evaluation_id=? ORDER BY created_at", (evaluation_id,))]


def _save_resolution(db, result, final, item, value, created):
    _nonempty(value)
    if item["status"] != "pending":
        raise AppealConflict("Решение по этой апелляции уже сохранено")
    if fingerprint(result) != item["original_evaluation_hash"]:
        raise AppealConflict("Исходная оценка изменилась после отправки апелляции")
    if value.base_revision != final["revision"]:
        raise AppealConflict("Итог уже изменился. Обновите карточку перед решением")
    if value.decision == "accept" and (item["base_revision"] != final["revision"]
            or item["base_assessment_hash"] != fingerprint(final["assessment"])):
        raise AppealConflict("Эта апелляция основана на устаревшем итоге. Создайте новую апелляцию")
    revision = final["revision"]
    if value.decision == "accept":
        changes = {key: Decision.model_validate(decision) for key, decision in item["changes"].items()}
        assessment, scoring = _proposal(result, final, changes)
        revision += 1
        record = {"revision": revision, "created_at": created, "source": "human_appeal",
            "appeal_id": item["appeal_id"], "reviewer": value.reviewer, "reason": value.reason,
            "original_evaluation_hash": fingerprint(result), "checklist_hash": result["checklist_hash"],
            "assessment": assessment, "scoring": scoring}
        db.execute("INSERT INTO final_revisions VALUES (?,?,?,?)",
            (item["evaluation_id"], revision, created, json_text(record)))
    item["status"] = "accepted" if value.decision == "accept" else "rejected"
    item["resolution"] = {**value.model_dump(mode="json"), "created_at": created,
                          "final_revision": revision}
    db.execute("UPDATE appeals SET status=?,payload=? WHERE id=?",
               (item["status"], json_text(item), item["appeal_id"]))
    return item


def resolve_appeal(store, appeal_id, value: ResolutionRequest):
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT payload FROM appeals WHERE id=?", (appeal_id,)).fetchone()
        if row is None:
            raise KeyError("Апелляция не найдена")
        item = json.loads(row["payload"])
        result = _evaluation(db, item["evaluation_id"])
        return _save_resolution(db, result, _final(db, result), item, value, utc_now())


def record_workspace_decision(db, appeal):
    """Commit the reviewer's concrete decision to the product ledger in the caller's transaction."""
    result = _evaluation(db, appeal["evaluation_id"])
    final = _final(db, result)
    key = appeal["criterion_id"]
    decision = dict(final["assessment"]["criteria"][key], answer=appeal["answer"],
                    na_condition_id=appeal["na_condition_id"], reason=appeal["resolution"])
    if decision["answer"] == "na":
        decision.update(knowledge_status="not_needed", knowledge_review=None, source_ids=[], limitations=[])
    request = AppealRequest(reviewer=appeal["actor"], reason=appeal["comment"],
                            base_revision=final["revision"], changes={key: decision})
    item = _save_proposal(db, result, final, request, appeal["id"], appeal["created_at"], allow_confirmation=True)
    resolution = ResolutionRequest(reviewer=appeal["reviewer"], reason=appeal["resolution"],
                                   decision="accept", base_revision=final["revision"])
    saved = _save_resolution(db, result, final, item, resolution, appeal["resolved_at"])
    return saved["resolution"]["final_revision"], item["proposed_assessment"]["criteria"][key]
