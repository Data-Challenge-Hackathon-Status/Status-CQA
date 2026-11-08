"""Organizer submission format 1.0, separate from the full audit record."""
from __future__ import annotations

import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from .contracts import Checklist, Dialogue, Record
from .engine import recalculate
from .io import fingerprint, write_json

CRITERIA = ("contact", "discovery", "identification", "consultation", "empathy",
            "dialogue", "closure", "critical")
NULLABLE = {"discovery", "identification", "consultation", "closure"}
SCALES = {"consultation": {0, 5, 10, 15, 20}, "dialogue": {0, 4, 7, 10}}
DEFAULT_MAPPING = dict(zip((f"c{i}" for i in range(1, 9)), CRITERIA, strict=True))


class SubmissionSettings(Record):
    team_name: str = Field(min_length=1)
    criterion_ids: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_MAPPING))

    @model_validator(mode="after")
    def complete_mapping(self):
        if not self.team_name.strip():
            raise ValueError("Нужно настоящее название команды")
        if len(self.criterion_ids) != 8 or set(self.criterion_ids.values()) != set(CRITERIA):
            raise ValueError("В настройках выгрузки нужны восемь уникальных кодов организаторов")
        return self


class SubmissionModel(Record):
    mode: Literal["local", "external_api", "hybrid"]
    name: str = Field(min_length=1)


class SubmissionCriterion(Record):
    criterion_id: Literal["contact", "discovery", "identification", "consultation",
                          "empathy", "dialogue", "closure", "critical"]
    value: StrictBool | StrictInt | None
    rationale: str = Field(min_length=1)
    evidence_turns: list[Annotated[StrictInt, Field(ge=1)]] = Field(min_length=1)

    @model_validator(mode="after")
    def allowed_value(self):
        if not self.rationale.strip():
            raise ValueError("Пустое объяснение")
        if self.value is None:
            if self.criterion_id not in NULLABLE:
                raise ValueError("N/A не разрешён для этого критерия")
        elif self.criterion_id in SCALES:
            if type(self.value) is not int or self.value not in SCALES[self.criterion_id]:
                raise ValueError("Недопустимое значение шкалы")
        elif type(self.value) is not bool:
            raise ValueError("Для этого критерия требуется true или false")
        if len(set(self.evidence_turns)) != len(self.evidence_turns):
            raise ValueError("Номера доказательств повторяются")
        return self


class SubmissionScore(Record):
    final_score: float = Field(strict=True, ge=0, le=100)
    critical_flag: StrictBool

    @model_validator(mode="after")
    def rounded(self):
        value = Decimal(str(self.final_score))
        if value != value.quantize(Decimal("0.01")):
            raise ValueError("Итог должен быть округлён до двух знаков")
        return self


class SuccessfulSubmission(Record):
    conversation_id: str = Field(min_length=1)
    status: Literal["ok"]
    criteria: list[SubmissionCriterion] = Field(min_length=8, max_length=8)
    score: SubmissionScore


class FailedSubmission(Record):
    conversation_id: str = Field(min_length=1)
    status: Literal["error"]
    criteria: list = Field(max_length=0)
    score: None
    error: str = Field(min_length=1)


class Submission(Record):
    schema_version: Literal["1.0"]
    team_name: str = Field(min_length=1)
    model: SubmissionModel
    results: list[Annotated[SuccessfulSubmission | FailedSubmission, Field(discriminator="status")]]


def check_dataset(dialogues: list[Dialogue], dataset: str) -> None:
    ids = [d.conversation_id for d in dialogues]
    if len(set(ids)) != len(ids):
        raise ValueError("В исходном наборе повторяются conversation_id")
    counts = Counter(d.channel for d in dialogues)
    expected = {"dev": {"agent chat": 60, "voice call": 5}, "prod": {"agent chat": 10}}
    if dataset not in expected or dict(counts) != expected[dataset]:
        raise ValueError("DEV должен содержать 60 чатов и 5 звонков, PROD — 10 чатов")


def mapped_criteria(checklist: Checklist, config: SubmissionSettings):
    if {c.id for c in checklist.criteria} != set(config.criterion_ids) or checklist.total_max != 100:
        raise ValueError("Чек-лист не соответствует восьми критериям формата сдачи 1.0")
    mapped = {config.criterion_ids[c.id]: c for c in checklist.criteria}
    for code, criterion in mapped.items():
        kind = "flag" if code == "critical" else "scale" if code in SCALES else "binary"
        maximum = max(SCALES[code]) if code in SCALES else 1
        if criterion.kind != kind or criterion.max_score != maximum:
            raise ValueError(f"{code}: тип или максимум шкалы несовместим с форматом сдачи 1.0")
    return mapped


def validate_submission(payload: dict, dialogues: list[Dialogue], dataset: str,
                        checklist: Checklist, config: SubmissionSettings) -> dict:
    check_dataset(dialogues, dataset)
    submission = Submission.model_validate(payload)
    if submission.team_name != config.team_name:
        raise ValueError("Название команды не совпадает с настройками")
    ids = [r.conversation_id for r in submission.results]
    if len(ids) != len(set(ids)) or set(ids) != {d.conversation_id for d in dialogues}:
        raise ValueError("Нужна ровно одна запись на каждый исходный conversation_id, без лишних ID")
    mapped = mapped_criteria(checklist, config)
    lengths = {d.conversation_id: len(d.transcript) for d in dialogues}
    channels = {d.conversation_id: d.channel for d in dialogues}
    for result in submission.results:
        if result.status == "error":
            continue
        codes = [c.criterion_id for c in result.criteria]
        if len(set(codes)) != 8 or set(codes) != set(CRITERIA):
            raise ValueError("Каждый из восьми критериев должен встречаться ровно один раз")
        numerator, denominator = Decimal(0), Decimal(0)
        critical = False
        for item in result.criteria:
            criterion = mapped[item.criterion_id]
            if any(n > lengths[result.conversation_id] for n in item.evidence_turns):
                raise ValueError("Доказательство ссылается на несуществующую реплику")
            if item.criterion_id == "critical":
                critical = item.value
                continue
            if item.value is None:
                if not any(n.channels is None or channels[result.conversation_id] in n.channels
                           for n in criterion.na_conditions):
                    raise ValueError("N/A не разрешён выбранной версией чек-листа")
                continue
            raw_score = Decimal(int(item.value))
            if raw_score not in {o.raw_score for o in criterion.options}:
                raise ValueError("Оценка не предусмотрена выбранной версией чек-листа")
            numerator += criterion.weight * raw_score / criterion.max_score
            denominator += criterion.weight
        if denominator <= 0:
            raise ValueError("Нет применимых критериев с положительным весом")
        expected = (100 * numerator / denominator).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if Decimal(str(result.score.final_score)) != expected:
            raise ValueError("Итог не совпадает с пересчётом оценок и N/A")
        if result.score.critical_flag is not critical:
            raise ValueError("critical_flag не совпадает со значением critical")
    return submission.model_dump(mode="json")


def build_submission(evaluations: list[dict], dialogues: list[Dialogue], dataset: str,
                     config: SubmissionSettings) -> dict:
    check_dataset(dialogues, dataset)
    ids = [r["conversation_id"] for r in evaluations]
    if len(set(ids)) != len(ids) or set(ids) != {d.conversation_id for d in dialogues}:
        raise ValueError("Манифест должен содержать один запуск для каждого диалога набора")
    if len({r["checklist_hash"] for r in evaluations}) != 1:
        raise ValueError("Нельзя смешивать версии чек-листа в одной выгрузке")
    checklist = Checklist.model_validate(evaluations[0]["checklist"])
    mapped_criteria(checklist, config)
    by_id = {r["conversation_id"]: r for r in evaluations}
    providers, models, rows = set(), set(), []
    for dialogue in dialogues:
        result = by_id[dialogue.conversation_id]
        if result["dialogue_hash"] != fingerprint(dialogue):
            raise ValueError("Сохранённая оценка относится к другой версии исходного диалога")
        if fingerprint(result["checklist"]) != result["checklist_hash"]:
            raise ValueError("Снимок чек-листа изменён")
        providers.add(result["settings"]["provider"])
        models.add(result["settings"]["model"])
        if result["status"] in {"failed", "running"}:
            rows.append({"conversation_id": dialogue.conversation_id, "status": "error",
                         "criteria": [], "score": None,
                         "error": result.get("error") or "Оценка не завершена."})
            continue
        if result["status"] not in {"completed", "provisional"}:
            raise ValueError("Неизвестный статус запуска")
        score = recalculate(result)
        if result["scoring"] != score:
            raise ValueError("Сохранённые баллы не совпадают с воспроизводимым пересчётом")
        positions = {m.id: i + 1 for i, m in enumerate(dialogue.transcript)}
        items = {}
        for criterion in checklist.criteria:
            decision = result["assessment"]["criteria"][criterion.id]
            answer = decision["answer"]
            option = next((o for o in criterion.options if o.value == answer), None)
            if answer == "na":
                value = None
            elif criterion.kind == "flag":
                value = answer == criterion.violation_value
            elif criterion.kind == "binary":
                value = bool(option.raw_score)
            else:
                if option.raw_score != option.raw_score.to_integral_value():
                    raise ValueError("Формат сдачи требует целочисленную исходную оценку шкалы")
                value = int(option.raw_score)
            turns, notes = set(), [decision["reason"]]
            for evidence in decision["evidence"]:
                turns.update(range(positions[evidence["start_message_id"]],
                                   positions[evidence["end_message_id"]] + 1))
                if evidence["kind"] == "missing_action":
                    notes.append("Ожидалось: " + evidence["expected_action"])
            notes.extend(decision["limitations"])
            code = config.criterion_ids[criterion.id]
            items[code] = {"criterion_id": code, "value": value,
                           "rationale": " ".join(dict.fromkeys(notes)), "evidence_turns": sorted(turns)}
        rows.append({"conversation_id": dialogue.conversation_id, "status": "ok",
                     "criteria": [items[code] for code in CRITERIA],
                     "score": {"final_score": float(score["total_score"]),
                               "critical_flag": score["gross_violation"]}})
    if not providers <= {"ollama", "openai"}:
        raise ValueError("Неизвестный способ запуска модели")
    mode = "hybrid" if len(providers) > 1 else "local" if providers == {"ollama"} else "external_api"
    payload = {"schema_version": "1.0", "team_name": config.team_name,
               "model": {"mode": mode, "name": ", ".join(sorted(models))}, "results": rows}
    return validate_submission(payload, dialogues, dataset, checklist, config)


def read_submission(path: str | Path) -> dict:
    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("JSON содержит повторяющиеся ключи")
            value[key] = item
        return value

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_keys)


def save_submission(path: str | Path, payload: dict) -> None:
    write_json(path, payload)
