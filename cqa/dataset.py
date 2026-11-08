"""Resume a whole supplied dataset and write a checked organizer submission."""
from __future__ import annotations

import time
from pathlib import Path

from .contracts import Checklist, Knowledge, Settings
from .engine import Engine
from .io import fingerprint, read_json, write_json
from .prompting import PROMPT_VERSION
from .storage import Store
from .submission import SubmissionSettings, build_submission, check_dataset, save_submission


def evaluate_dataset(store: Store, settings: Settings, records: list, checklist: Checklist,
                     knowledge: Knowledge, config: SubmissionSettings, *, dataset: str,
                     runs_path: str | Path, output: str | Path, max_minutes: float,
                     resume=False, retry_errors=False, provider=None, clock=time.monotonic, report=None):
    if max_minutes <= 0:
        raise ValueError("Время обработки должно быть положительным")
    if retry_errors and not resume:
        raise ValueError("Повтор ошибок требует --resume")
    dialogues = [d for d, _ in records]
    check_dataset(dialogues, dataset)
    store.save_dialogues(records)
    runs_path = Path(runs_path)
    signature = {"dataset": dataset, "dialogues_hash": fingerprint([d.model_dump(mode="json") for d in dialogues]),
                 "settings_hash": fingerprint(settings), "checklist_hash": fingerprint(checklist),
                 "knowledge_hash": fingerprint(knowledge), "prompt_version": PROMPT_VERSION}
    selected = {}
    if runs_path.exists():
        if not resume:
            raise ValueError("Манифест уже существует: для продолжения используйте --resume")
        manifest = read_json(runs_path)
        if manifest.get("signature") != signature:
            raise ValueError("Набор, модель, запрос или критерии изменились; нужен новый файл --runs")
        for evaluation_id in manifest["evaluation_ids"]:
            result = store.get_evaluation(evaluation_id)
            if result["conversation_id"] in selected:
                raise ValueError("В манифесте повторяется conversation_id")
            selected[result["conversation_id"]] = result
        if set(selected) - {d.conversation_id for d in dialogues}:
            raise ValueError("Манифест содержит диалог из другого набора")
        for dialogue in dialogues:
            result = selected.get(dialogue.conversation_id)
            if result and (result["dialogue_hash"] != fingerprint(dialogue)
                           or result["checklist_hash"] != signature["checklist_hash"]
                           or result["knowledge_hash"] != signature["knowledge_hash"]
                           or fingerprint(result["settings"]) != signature["settings_hash"]
                           or result["prompt_version"] != PROMPT_VERSION):
                raise ValueError("Сохранённый запуск не соответствует текущей конфигурации")
    deadline = clock() + max_minutes * 60
    engine = Engine(store, settings, provider=provider)
    for dialogue in dialogues:
        previous = selected.get(dialogue.conversation_id)
        if previous and previous["status"] != "running" and not (retry_errors and previous["status"] == "failed"):
            continue
        if clock() >= deadline:
            result = engine.fail_without_call(dialogue, checklist, "dataset_time_limit_exceeded", knowledge)
        else:
            result = engine.evaluate(dialogue, checklist, knowledge)
        selected[dialogue.conversation_id] = result
        write_json(runs_path, {"signature": signature,
                              "evaluation_ids": [selected[d.conversation_id]["evaluation_id"]
                                                 for d in dialogues if d.conversation_id in selected]})
        if report:
            report(result)
    results = [selected[d.conversation_id] for d in dialogues]
    payload = build_submission(results, dialogues, dataset, config)
    save_submission(output, payload)
    return payload
