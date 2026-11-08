"""Bounded paired experiment with an explicit, unchanged partial human reference."""
from __future__ import annotations

import argparse
import html
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

from .context import context_report
from .contracts import Checklist, Dialogue, Knowledge, Settings
from .engine import Engine, implementation_hash, recalculate
from .experiment import seal, unseal
from .io import fingerprint, json_text, read_json, write_json
from .ollama_provider import OllamaProvider
from .provider import ProviderError, build_request
from .review import _slice_metrics, validate_review
from .storage import Store, utc_now

SCHEMA = "cqa-partial-experiment-1"
EXCLUDED = {("p1-en-004", "c2")}
ARMS = ("A_baseline", "B_reviewed")


def grading_shape(checklist):
    """Semantic instructions may differ; comparable answer scales must not."""
    return {"id": checklist.id, "total_max": str(checklist.total_max), "criteria": [
        {"id": c.id, "kind": c.kind, "weight": str(c.weight), "max_score": str(c.max_score),
         "violation_value": c.violation_value,
         "options": [(o.value, str(o.raw_score)) for o in c.options],
         "na_conditions": [(n.id, n.channels) for n in c.na_conditions]} for c in checklist.criteria]}


def reference_cells(package, review, ids):
    checklist, confirmed, disputes, _ = validate_review(package, review)
    source = {r["conversation_id"]: r for r in package["records"]}
    actual_ids = {cid for cid, row in source.items() if row["dialogue"]["channel"] == "agent chat"}
    if set(ids) != actual_ids or len(ids) != 6 or len(set(ids)) != len(ids):
        raise ValueError("Нужны ровно шесть согласованных чатов")
    confirmed = {key: value for key, value in confirmed.items() if key[0] in actual_ids}
    expected = {(cid, c.id) for cid in ids for c in checklist.criteria} - EXCLUDED
    chat_disputes = {(r["conversation_id"], r["criterion_id"]) for r in disputes if r["conversation_id"] in ids}
    if set(confirmed) != expected or len(confirmed) != 47 or chat_disputes != EXCLUDED:
        raise ValueError("Нужны 47 подтверждений и только спорный p1-en-004/C2")
    return checklist, confirmed


def inspect_model(settings):
    """Metadata only: never performs a warm-up or a generation."""
    provider = OllamaProvider(settings.model_copy(update={"timeout_seconds": 15}))
    info = provider.inspect()
    if not info["model_available"]:
        raise ProviderError("ollama_model_not_installed", retryable=False)
    show = provider._json("POST", "/api/show", {"model": settings.model, "verbose": False})
    return {"checked_at": utc_now(), **info, "parameters_hash": fingerprint(show.get("parameters")),
            "template_hash": fingerprint(show.get("template")), "details": show.get("details"),
            "loaded_models": provider._json("GET", "/api/ps"), "generation_requests": 0}


def expected_model(snapshot, settings):
    selected = next((m for m in snapshot["models"]["models"] if m["name"] == settings.model), None)
    if not selected or not selected.get("digest"):
        raise ValueError("Нет зафиксированной версии весов")
    return {"model": settings.model, "server_version": snapshot["version"]["version"],
            "model_digest": selected["digest"], "quantization": snapshot["details"]["quantization_level"],
            "parameters_hash": fingerprint(snapshot["parameters"]),
            "template_hash": fingerprint(snapshot["template"])}


def check_model(observed, expected):
    for key in ("server_version", "model_digest", "parameters_hash", "template_hash"):
        if observed.get(key) != expected[key]:
            raise ValueError("Изменилась модель или сервер: " + key)
    if (observed.get("details") or {}).get("quantization_level") != expected["quantization"]:
        raise ValueError("Изменилось квантование модели")


def prepare(folder, review=None):
    folder = Path(folder)
    source = read_json(folder / "comparison-protocol.json")
    raw = unseal(source)
    if raw["schema"] != "cqa-comparison-protocol-2" or raw["execution_enabled"]:
        raise ValueError("Нужен сохранённый протокол ожидания согласования")
    package = read_json(folder / "package.snapshot.json")
    review = review or read_json(folder / "human-review.snapshot.json")
    original, confirmed = reference_cells(package, review, raw["selected_chat_ids"])
    if fingerprint(review) != raw["review_snapshot_hash"]:
        raise ValueError("Разметка отличается от согласованного снимка")
    reference = raw["reference_manifest"]
    unseal(reference)
    if fingerprint(reference) != raw["reference_hash"]:
        raise ValueError("Журнал согласования изменён")
    candidate = Checklist.model_validate(raw["candidate_checklist"])
    if fingerprint(candidate) != raw["candidate_checklist_hash"] or grading_shape(original) != grading_shape(candidate):
        raise ValueError("Сопоставление не разрешает заменять шкалы или веса")
    if raw["max_calls"] != 28 or raw["max_elapsed_minutes"] != 45 or raw["max_attempts"] != 1:
        raise ValueError("Разрешён только цикл 28 вызовов / 45 минут / одна попытка")
    if any(raw[k] for k in ("sources_enabled", "alternative_sampling_enabled", "second_c8_pass_enabled")):
        raise ValueError("Дополнительные факторы не разрешены")
    jobs = deepcopy(raw["jobs"])
    settings = Settings.model_validate(jobs[0]["settings"])
    expected = expected_model(raw["model_metadata_snapshot"], settings)
    plan = {"schema": SCHEMA, "created_at": utc_now(), "execution_enabled": True,
        "source_protocol": source, "source_protocol_seal": source["seal"],
        "source_protocol_path": str(folder / "comparison-protocol.json"),
        "implementation_hash": implementation_hash(), "source_implementation_hash": raw["implementation_hash"],
        "code_change_purpose": "Implement partial-reference runner; frozen generation requests remain byte-equivalent.",
        "package": package, "package_id": package["package_id"], "review": review,
        "review_hash": fingerprint(review), "selected_chat_ids": raw["selected_chat_ids"],
        "confirmed_cells": [list(key) for key in sorted(confirmed)],
        "excluded_cells": [list(key) for key in sorted(EXCLUDED)],
        "semantic_comparison": {"kind": "declared_semantic_policy_comparison_not_equivalence",
            "original_snapshot": original.model_dump(mode="json"), "original_hash": fingerprint(original),
            "candidate_snapshot": candidate.model_dump(mode="json"), "candidate_hash": fingerprint(candidate),
            "grading_shape_hash": fingerprint(grading_shape(original)),
            "scope": "Compare frozen A/B instructions against the same explicit human adjudications; no label or hash substitution.",
            "reference_hash": raw["reference_hash"]},
        "jobs": jobs, "schedule": [dict(row, job_id=f'{row["repeat"]}-{row["job_key"]}') for row in raw["schedule"]],
        "max_calls": 28, "max_attempts": 1, "max_elapsed_minutes": 45,
        "model_expected": expected, "primary_repeat": 1, "second_repeat": "stability only",
        "evidence_review_sampling": raw["evidence_review_sampling"],
        "new_sources": False, "new_sampling": False, "extra_c8_pass": False}
    sealed = seal(plan)
    validate_plan(sealed)
    return sealed


def validate_plan(value, *, current_code=True):
    plan = unseal(value)
    if plan.get("schema") != SCHEMA or plan.get("execution_enabled") is not True:
        raise ValueError("Неисполняемый протокол")
    if current_code and plan["implementation_hash"] != implementation_hash():
        raise ValueError("Код изменён: выпустите новый план, не меняя прежний")
    source = unseal(plan["source_protocol"])
    if plan["source_protocol_seal"] != plan["source_protocol"]["seal"]:
        raise ValueError("Изменён источник протокола")
    if fingerprint(plan["review"]) != plan["review_hash"] or plan["review_hash"] != source["review_snapshot_hash"]:
        raise ValueError("Изменена человеческая разметка")
    original, confirmed = reference_cells(plan["package"], plan["review"], plan["selected_chat_ids"])
    if plan["package_id"] != plan["package"]["package_id"]:
        raise ValueError("Изменён пакет")
    if sorted(map(tuple, plan["confirmed_cells"])) != sorted(confirmed) or set(map(tuple, plan["excluded_cells"])) != EXCLUDED:
        raise ValueError("Изменён состав сравнения")
    declaration = plan["semantic_comparison"]
    candidate = Checklist.model_validate(declaration["candidate_snapshot"])
    if (declaration["kind"] != "declared_semantic_policy_comparison_not_equivalence"
            or declaration["original_snapshot"] != original.model_dump(mode="json")
            or declaration["original_hash"] != fingerprint(original)
            or declaration["candidate_hash"] != fingerprint(candidate)
            or declaration["candidate_hash"] != source["candidate_checklist_hash"]
            or grading_shape(original) != grading_shape(candidate)
            or declaration["grading_shape_hash"] != fingerprint(grading_shape(original))):
        raise ValueError("Изменено явное сопоставление политик")
    if (plan["jobs"] != source["jobs"] or len(plan["schedule"]) != 28
            or [{k: v for k, v in row.items() if k != "job_id"} for row in plan["schedule"]] != source["schedule"]
            or plan["max_calls"] != 28 or plan["max_elapsed_minutes"] != 45 or plan["max_attempts"] != 1
            or any(plan[k] for k in ["new_sources", "new_sampling", "extra_c8_pass"])):
        raise ValueError("Изменены согласованные запросы, порядок или лимиты")
    jobs = {j["job_key"]: j for j in plan["jobs"]}
    if len(jobs) != len(plan["jobs"]) or len({r["job_id"] for r in plan["schedule"]}) != 28:
        raise ValueError("Повтор задания")
    sources = {r["conversation_id"]: r for r in plan["package"]["records"]}
    for job in jobs.values():
        objects = {"dialogue": Dialogue.model_validate(job["dialogue"]),
                   "checklist": Checklist.model_validate(job["checklist"]),
                   "knowledge": Knowledge.model_validate(job["knowledge"]),
                   "settings": Settings.model_validate(job["settings"])}
        for name, obj in objects.items():
            if fingerprint(obj) != job[name + "_hash"]:
                raise ValueError("Изменён снимок задания: " + name)
        settings = objects["settings"]
        if settings.max_attempts != 1 or objects["knowledge"].sources or settings.provider != "ollama":
            raise ValueError("Повторные попытки или источники запрещены")
        control = build_request(settings, [{"role": "system", "content": ""}], {}, settings.max_output_tokens)
        if ({k:v for k,v in control.items() if k not in ["messages", "format"]} !=
                {k:v for k,v in job["request"].items() if k not in ["messages", "format"]}):
            raise ValueError("Запрос не соответствует настройкам")
        if not context_report(job["request"], settings)["fits"]:
            raise ValueError("Запрос не помещается")
        if job["population"] == "primary_chat":
            cid = objects["dialogue"].conversation_id
            expected_hash = fingerprint(original) if job["arm"] == "A_baseline" else fingerprint(candidate)
            if (cid not in plan["selected_chat_ids"] or job["dialogue_hash"] != sources[cid]["dialogue_hash"]
                    or job["checklist_hash"] != expected_hash or job["arm"] not in ARMS):
                raise ValueError("Задание не принадлежит объявленному сравнению")
    if plan["model_expected"] != expected_model(source["model_metadata_snapshot"], Settings.model_validate(plan["jobs"][0]["settings"])):
        raise ValueError("Изменена ожидаемая модель")
    for row in plan["schedule"]:
        if row["job_key"] not in jobs or row["job_id"] != f'{row["repeat"]}-{row["job_key"]}':
            raise ValueError("Неверное задание расписания")
    return plan


class PinnedProvider(OllamaProvider):
    def __init__(self, settings, expected):
        super().__init__(settings)
        self.expected = expected

    def inspect(self):
        observed = inspect_model(self.settings)
        check_model(observed, self.expected)
        return observed


def worker(plan_path, job_id, directory):
    value = read_json(plan_path)
    plan = validate_plan(value)
    row = next(r for r in plan["schedule"] if r["job_id"] == job_id)
    job = next(j for j in plan["jobs"] if j["job_key"] == row["job_key"])
    settings = Settings.model_validate(job["settings"])
    result = Engine(Store(Path(directory) / "runs.sqlite3"), settings,
                    PinnedProvider(settings, plan["model_expected"])).evaluate(
        Dialogue.model_validate(job["dialogue"]), Checklist.model_validate(job["checklist"]),
        Knowledge.model_validate(job["knowledge"]), prepared=job)
    write_json(Path(directory) / "worker-results" / (job_id + ".json"), result)


def subprocess_job(plan_path, row, directory, timeout):
    """An outer process deadline includes metadata, HTTP reads, validation and storage."""
    directory = Path(directory)
    logs = directory / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / (row["job_id"] + ".txt")).open("wb") as output:
        process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "cqa.partial_experiment", "_worker",
            str(Path(plan_path).resolve()), row["job_id"], str(directory.resolve())],
            stdout=output, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
            return {"state": "interrupted_unknown", "error": "worker_deadline_unknown_server_outcome",
                    "stop_cycle": True}
    result_path = directory / "worker-results" / (row["job_id"] + ".json")
    if code or not result_path.exists():
        return {"state": "failed", "error": f"worker_exit_{code}_without_final_result", "stop_cycle": True}
    result = read_json(result_path)
    return {"state": result["status"], "error": result["error"], "evaluation_id": result["evaluation_id"],
            "elapsed_seconds": result.get("elapsed_seconds"),
            "stop_cycle": result.get("error") in {"ollama_connection_or_timeout", "ollama_version_mismatch"}}


def run(plan_path, directory, *, inspector=inspect_model, executor=subprocess_job, now=time.time):
    value = read_json(plan_path)
    plan = validate_plan(value)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "execution.json"
    state = read_json(state_path) if state_path.exists() else {
        "plan_hash": fingerprint(value), "review_hash": plan["review_hash"], "jobs": [],
        "created_at": utc_now(), "started_epoch": now(), "status": "preflight", "preflight": []}
    if state["plan_hash"] != fingerprint(value) or state["review_hash"] != plan["review_hash"]:
        raise ValueError("Продолжение требует тот же план и разметку")
    scheduled = {r["job_id"]: r for r in plan["schedule"]}
    def save_state():
        completed = {r["job_id"] for r in state["jobs"]}
        state["not_run_jobs"] = [dict(row, state="not_run", reason=state["status"])
                                 for row in plan["schedule"] if row["job_id"] not in completed]
        write_json(state_path, state)
    if len({r["job_id"] for r in state["jobs"]}) != len(state["jobs"]) or any(r["job_id"] not in scheduled for r in state["jobs"]):
        raise ValueError("Журнал исполнения содержит лишние задания")
    interrupted = False
    for record in state["jobs"]:
        if record["state"] == "started":
            record.update(state="interrupted_unknown", error="interrupted_no_automatic_retry")
            interrupted = True
    deadline = state["started_epoch"] + plan["max_elapsed_minutes"] * 60
    if state.get("terminal") or interrupted or now() >= deadline:
        state.update(terminal=True, status="interrupted" if interrupted else state.get("status", "deadline"),
                     unfinished_jobs=28-len(state["jobs"]))
        save_state()
        return state
    write_json(state_path, state)
    try:
        metadata = inspector(Settings.model_validate(plan["jobs"][0]["settings"]))
        check_model(metadata, plan["model_expected"])
        state["preflight"].append({"at": utc_now(), "status": "ok", "metadata": metadata})
    except (ProviderError, ValueError) as exc:
        state["preflight"].append({"at": utc_now(), "status": "failed", "error": getattr(exc, "code", str(exc))})
        state.update(status="blocked_before_generation", unfinished_jobs=28-len(state["jobs"]), terminal=True)
        save_state()
        return state
    state["status"] = "running"
    save_state()
    jobs = {j["job_key"]: j for j in plan["jobs"]}
    for row in plan["schedule"]:
        if any(r["job_id"] == row["job_id"] for r in state["jobs"]):
            continue
        remaining = deadline - now()
        if remaining <= 1:
            state["status"] = "deadline"
            break
        job = jobs[row["job_key"]]
        timeout = min(remaining, job["settings"]["timeout_seconds"] + 45)
        record = dict(row, state="started", started_at=utc_now(), job_hash=fingerprint(job),
                      hard_timeout_seconds=timeout)
        state["jobs"].append(record)
        write_json(state_path, state)  # Reserve before launch; never silently replay an uncertain call.
        started = now()
        try:
            result = executor(plan_path, row, directory, timeout)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            result = {"state": "failed", "error": "executor_" + type(exc).__name__, "stop_cycle": True}
        record.update(result, finished_at=utc_now(), worker_wall_seconds=max(0, now()-started))
        state["elapsed_seconds"] = max(0, now()-state["started_epoch"])
        write_json(state_path, state)
        if result.get("stop_cycle"):
            state["status"] = "stopped_after_uncertain_or_infrastructure_failure"
            break
    else:
        state["status"] = "completed"
    state.update(terminal=True, unfinished_jobs=28-len(state["jobs"]),
                 elapsed_seconds=max(0, now()-state["started_epoch"]))
    save_state()
    return state


def checked_results(plan, state, directory):
    jobs = {j["job_key"]: j for j in plan["jobs"]}
    results = {}
    db_path = Path(directory) / "runs.sqlite3"
    store = Store(db_path) if db_path.exists() else None
    for record in state["jobs"]:
        if not record.get("evaluation_id"):
            continue
        if store is None:
            raise ValueError("Нет базы сохранённых результатов")
        result = store.get_evaluation(record["evaluation_id"])
        job = jobs[record["job_key"]]
        for field in ("dialogue_hash", "checklist_hash", "knowledge_hash", "prompt_version"):
            if result[field] != job[field]:
                raise ValueError("Результат относится к другому заданию")
        if result["settings"] != job["settings"] or result["prepared_job_hash"] != fingerprint(job):
            raise ValueError("Результат относится к другим настройкам")
        if result["implementation_hash"] != plan["implementation_hash"]:
            raise ValueError("Результат получен другой программой")
        if len(result["attempts"]) > 1 or any(a["request"] != job["request"] for a in result["attempts"]):
            raise ValueError("Незапланированный запрос или повтор")
        for attempt in result["attempts"]:
            metadata = attempt.get("provider_metadata")
            if metadata and metadata.get("model_digest") != plan["model_expected"]["model_digest"]:
                raise ValueError("Результат получен другой моделью")
        if result.get("assessment") and recalculate(result) != result["scoring"]:
            raise ValueError("Сохранённые баллы изменены")
        results[record["job_id"]] = result
    return results


def summarize(value, directory):
    plan = validate_plan(value, current_code=False)
    state = read_json(Path(directory) / "execution.json")
    if state["plan_hash"] != fingerprint(value) or state["review_hash"] != plan["review_hash"]:
        raise ValueError("Журнал относится к другому опыту")
    results = checked_results(plan, state, directory)
    checklist, confirmed = reference_cells(plan["package"], plan["review"], plan["selected_chat_ids"])
    ids = set(plan["selected_chat_ids"])
    report = {"schema": "cqa-partial-comparison-1", "plan_hash": fingerprint(value),
        "reference": "47 подтверждённых внутренних решений на шести чатах; не эталон организаторов",
        "review_hash": plan["review_hash"], "excluded_cells": plan["excluded_cells"],
        "semantic_comparison": plan["semantic_comparison"], "execution": state,
        "arms": {}, "separate_diagnostics": [], "voice": "Not scheduled; separate from primary chat metrics",
        "human_evidence_review": {"checked": 0, "note": "Pending human review, never inferred from answer agreement"}}
    primary = {}
    for arm in ARMS:
        rounds = [{r["conversation_id"]: r for row in plan["schedule"]
                   if row["repeat"] == rep and row["job_key"].startswith(arm + "-")
                   and (r := results.get(row["job_id"])) is not None} for rep in (1, 2)]
        primary[arm] = rounds[0]
        metrics = _slice_metrics(checklist, confirmed, rounds[0], ids)
        metrics["planned_cell_completion_adjusted_rate"] = metrics["exact_match_rate"]
        metrics["available_prediction_match_rate"] = (metrics["matched"] / metrics["available_predictions"]
                                                       if metrics["available_predictions"] else None)
        metrics["exact_match_rate"] = metrics["available_prediction_match_rate"]
        for tally in metrics["per_criterion"].values():
            tally["planned_cell_completion_adjusted_rate"] = tally["exact_match_rate"]
            tally["exact_match_rate"] = (tally["matched"] / tally["prediction_available"]
                                         if tally["prediction_available"] else None)
        metrics["denominator_note"] = "47 planned confirmed cells; missing/failed are not substituted by repeat 2"
        same, pairs, missing = 0, 0, 0
        disagreements = []
        for (cid, criterion) in confirmed:
            a, b = (run.get(cid, {}).get("assessment") for run in rounds)
            if not a or not b:
                missing += 1
                continue
            pairs += 1
            x, y = a["criteria"][criterion]["answer"], b["criteria"][criterion]["answer"]
            same += x == y
            if x != y:
                disagreements.append({"conversation_id": cid, "criterion_id": criterion, "first": x, "second": y})
        metrics["stability"] = {"planned_confirmed_pairs": 47, "available_pairs": pairs,
            "missing_or_failed_pairs": missing, "matched": same, "rate": same/pairs if pairs else None,
            "disagreements": disagreements, "meaning": "Same-seed repeat stability, not correctness"}
        report["arms"][arm] = metrics
    jobs = {j["job_key"]: j for j in plan["jobs"]}
    for row in plan["schedule"]:
        job = jobs[row["job_key"]]
        if job["population"] == "primary_chat":
            continue
        result = results.get(row["job_id"])
        report["separate_diagnostics"].append({"job_id": row["job_id"], "population": job["population"],
            "conversation_id": job["dialogue"]["conversation_id"], "expected_c6": job.get("expected_c6"),
            "reference": job.get("reference", "Synthetic by construction; not human accuracy"),
            "result": result, "status": next((r["state"] for r in state["jobs"] if r["job_id"] == row["job_id"]), "not_run")})
    selected = {(r["conversation_id"], r["criterion_id"])
                for r in plan["evidence_review_sampling"]["preselected_cells"]}
    for (cid, criterion) in confirmed:
        left, right = (primary[arm].get(cid, {}).get("assessment") for arm in ARMS)
        if left and right and left["criteria"][criterion]["answer"] != right["criteria"][criterion]["answer"]:
            selected.add((cid, criterion))
        if criterion == "c8" and any(a and a["criteria"][criterion]["answer"] == "yes" for a in (left,right)):
            selected.add((cid, criterion))
    package_rows = {r["conversation_id"]: r for r in plan["package"]["records"]}
    evidence = {"label_source": "human_pending", "human_attestation": False, "reviewer": "",
        "plan_hash": fingerprint(value), "review_hash": plan["review_hash"], "records": []}
    for cid, criterion in sorted(selected):
        for arm in ARMS:
            result = primary[arm].get(cid)
            if not result or not result.get("assessment"):
                continue
            evidence["records"].append({"conversation_id": cid, "criterion_id": criterion, "arm": arm,
                "evaluation_id": result["evaluation_id"], "assessment_hash": fingerprint(result["assessment"]),
                "human_reference": confirmed[(cid, criterion)],
                "model_decision": result["assessment"]["criteria"][criterion],
                "dialogue": package_rows[cid]["dialogue"],
                "support": "pending", "confirmed_by_human": False, "reason": ""})
    return report, evidence


def write_report(directory, report, evidence):
    directory = Path(directory)
    write_json(directory / "comparison.json", report)
    write_json(directory / "evidence-review.pending.json", evidence)
    cards = []
    for i, row in enumerate(evidence["records"]):
        cards.append(f'<article><h3>{html.escape(row["conversation_id"])} · {row["criterion_id"].upper()} · '
                     f'{row["arm"]}</h3><p>Оценка человека: {html.escape(row["human_reference"]["answer"])}</p>'
                     f'<pre>{html.escape(json_text(row["model_decision"], pretty=True))}</pre>'
                     f'<details><summary>Исходный разговор</summary><pre>'
                     f'{html.escape(json_text(row["dialogue"]["transcript"], pretty=True))}</pre></details>'
                     f'<label>Доказательство <select data-index="{i}" data-field="support">'
                     '<option value="pending">Не проверено</option><option value="supported">Обосновано</option>'
                     '<option value="unsupported">Не обосновано</option><option value="uncertain">Спорно</option></select></label>'
                     f'<textarea data-index="{i}" data-field="reason" placeholder="Ваше объяснение"></textarea></article>')
    data = json_text(evidence).replace('<', '\\u003c')
    body = '<!doctype html><meta charset="utf-8"><title>CQA · Проверка объяснений</title><style>' \
        'body{font:16px system-ui;max-width:1100px;margin:36px auto;padding:0 20px;background:#f5f6fa;color:#182536}' \
        'article{background:white;padding:22px;margin:18px 0;border:1px solid #dbe2ea;border-radius:14px}' \
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}textarea{display:block;width:95%;min-height:75px;margin-top:12px}' \
        'button,input,select{font:inherit;padding:9px}h1{font-size:28px}</style><h1>Проверка объяснений A/B</h1>' \
        '<p>Совпадение оценки не доказывает верность объяснения. Проверьте требование, роли, порядок и ссылки.</p>' \
        '<p>Здесь первый повтор; ответы человека не изменяются этим файлом. Проверяются только выбранные объяснения.</p>' \
        '<label>Проверяющий <input id="reviewer"></label> <button id="save">Скачать проверку</button><p id="status"></p>'
    script = '<script>const data=' + data + ';document.addEventListener("change",e=>{const t=e.target;if(t.dataset.index!==undefined){' \
        'const r=data.records[Number(t.dataset.index)];r[t.dataset.field]=t.value;r.confirmed_by_human=r.support!=="pending"&&!!r.reason.trim()}});' \
        'document.querySelector("#save").onclick=()=>{data.reviewer=document.querySelector("#reviewer").value.trim();' \
        'if(!data.reviewer||data.records.some(r=>r.support!=="pending"&&!r.reason.trim())){' \
        'document.querySelector("#status").textContent="Укажите имя и пояснения для проверенных пунктов";return}' \
        'data.human_attestation=true;data.label_source="human";data.reviewed_at=new Date().toISOString();' \
        'const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));' \
        'a.download="cqa-evidence-review.json";a.click();URL.revokeObjectURL(a.href)};</script>'
    (directory / "evidence-review.html").write_text(body + ''.join(cards) + script, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("folder")
    prep.add_argument("--output", required=True)
    check = sub.add_parser("inspect")
    check.add_argument("--settings", default="config/settings.experiment-control.json")
    check.add_argument("--output", required=True)
    for command in ("run", "summarize"):
        p = sub.add_parser(command)
        p.add_argument("plan")
        p.add_argument("--directory", required=True)
    work = sub.add_parser("_worker")
    work.add_argument("plan")
    work.add_argument("job_id")
    work.add_argument("directory")
    args = parser.parse_args()
    if args.command == "prepare":
        if Path(args.output).exists():
            raise ValueError("Нельзя заменить существующий план")
        value = prepare(args.folder)
        write_json(args.output, value)
        print(json_text({"plan": args.output, "seal": value["seal"], "confirmed_cells": 47, "max_calls": 28}))
    elif args.command == "inspect":
        write_json(args.output, inspect_model(Settings.model_validate(read_json(args.settings))))
    elif args.command == "_worker":
        worker(args.plan, args.job_id, args.directory)
    elif args.command == "run":
        state = run(args.plan, args.directory)
        report, evidence = summarize(read_json(args.plan), args.directory)
        write_report(args.directory, report, evidence)
        print(json_text({"status": state["status"], "jobs": len(state["jobs"]), "unfinished": state["unfinished_jobs"]}))
    else:
        report, evidence = summarize(read_json(args.plan), args.directory)
        write_report(args.directory, report, evidence)
        print(json_text({"report": str(Path(args.directory) / "comparison.json"), "pending_evidence": len(evidence["records"])}))


if __name__ == "__main__":
    main()
