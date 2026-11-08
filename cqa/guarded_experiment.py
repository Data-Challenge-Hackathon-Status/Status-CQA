"""One fail-stop 1.7.2 check, max six generations; archived 1.7.1 plans stay readable."""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

from .contracts import Checklist, Dialogue, Knowledge, Settings
from .engine import Engine, implementation_hash, recalculate
from .experiment import make_job, seal, unseal
from .io import fingerprint, json_text, read_json, write_json
from .partial_experiment import PinnedProvider, check_model, grading_shape, inspect_model, reference_cells
from .partial_experiment import validate_plan as validate_previous_plan
from .prompting import PROMPT_VERSION, build_input, response_schema
from .provider import ProviderError, build_request
from .storage import Store, utc_now

SCHEMA = "cqa-guarded-172-1"
LEGACY_SCHEMA = "cqa-guarded-171-1"
ORDER = ("p1-ru-023", "p1-ru-014", "p1-ru-011", "p1-kz-009", "p1-kz-011", "p1-en-004")
VERSION = "cqa-1.7.2"
LEGACY_VERSION = "cqa-1.7.1"
OLD_LIMITATION_INSTRUCTION = (
    "Для unverified объясни, какого подтверждения не хватает, и сохрани limitation также\n"
    "в limitations решения. Не выдумывай наличие или отсутствие внешних утверждений.")
NEW_LIMITATION_INSTRUCTION = (
    "Для unverified обязательно заполни limitation: какого подтверждения не хватает.\n"
    "Не дублируй limitation каждого утверждения в limitations решения: программа добавит\n"
    "точные тексты этих ограничений автоматически. В limitations решения запиши только\n"
    "другие наблюдаемые ограничения; если их нет, передай пустой массив.\n"
    "Не выдумывай наличие или отсутствие внешних утверждений.")


def technical_change():
    return {"kind": "single-source-claim-limitations-172",
            "old_instruction_fragment_hash": fingerprint(OLD_LIMITATION_INSTRUCTION),
            "new_instruction_fragment_hash": fingerprint(NEW_LIMITATION_INSTRUCTION),
            "scope": "Only limitation aggregation instructions and output schema; no grading-rule changes"}


def request_without_schema(request):
    """Ollama receives the same schema both in format and as a system suffix."""
    control = deepcopy(request)
    suffix = "\nВерни только JSON по этой схеме:\n" + json_text(control.pop("format"))
    system = control["messages"][0]
    if system["role"] != "system" or not system["content"].endswith(suffix):
        raise ValueError("Embedded schema differs from the decoding schema")
    system["content"] = system["content"][:-len(suffix)]
    return control


def expected_request_core(prior_request, version):
    """Permit only the literal, declared technical paragraph replacement for 1.7.2."""
    core = request_without_schema(prior_request)
    if version == VERSION:
        instruction = core["messages"][0]["content"]
        if instruction.count(OLD_LIMITATION_INSTRUCTION) != 1 or NEW_LIMITATION_INSTRUCTION in instruction:
            raise ValueError("Historical limitation instruction is missing or ambiguous")
        core["messages"][0]["content"] = instruction.replace(
            OLD_LIMITATION_INSTRUCTION, NEW_LIMITATION_INSTRUCTION, 1)
    elif version != LEGACY_VERSION:
        raise ValueError("Unsupported instruction version")
    return core


def label_projection(review):
    return {(row["conversation_id"], cid): {k: d.get(k) for k in
            ("answer", "na_condition_id", "state", "confirmed_by_human")}
            for row in review["records"] for cid, d in row["criteria"].items()}


def prepare(previous, review, checklist, *, code_commit=None):
    old = validate_previous_plan(previous, current_code=False)
    if PROMPT_VERSION != VERSION:
        raise ValueError("This authorization is for instruction version 1.7.2 only")
    original, confirmed = reference_cells(old["package"], review, ORDER)
    if label_projection(review) != label_projection(old["review"]):
        raise ValueError("The confirmed labels differ from the authorized 47-cell reference")
    if (fingerprint(checklist) != old["semantic_comparison"]["candidate_hash"]
            or grading_shape(original) != grading_shape(checklist)):
        raise ValueError("The checklist or comparable grading scale changed")
    old_jobs = {j["dialogue"]["conversation_id"]: j for j in old["jobs"]
                if j["arm"] == "B_reviewed" and j["population"] == "primary_chat"}
    jobs = []
    for cid in ORDER:
        prior = old_jobs[cid]
        dialogue, settings = Dialogue.model_validate(prior["dialogue"]), Settings.model_validate(prior["settings"])
        knowledge = Knowledge()
        request = build_request(settings, build_input(dialogue, checklist, knowledge),
                                response_schema(checklist, knowledge, dialogue), settings.max_output_tokens)
        job = make_job(dialogue, checklist, knowledge, settings, request, VERSION,
                       {"previous_job_hash": fingerprint(prior),
                        "change": "1.7.2 deterministic limitation aggregation; grading rules unchanged"})
        jobs.append(dict(job, job_key="C_fixed-" + cid, arm="C_fixed", population="primary_chat"))
    value = seal({"schema": SCHEMA, "created_at": utc_now(), "execution_enabled": True,
        "code_commit": code_commit, "implementation_hash": implementation_hash(),
        "previous_plan": previous, "previous_plan_hash": fingerprint(previous),
        "previous_review_hash": old["review_hash"], "package": old["package"],
        "review": review, "review_hash": fingerprint(review), "selected_chat_ids": list(ORDER),
        "confirmed_cells": [list(k) for k in sorted(confirmed)], "excluded_cells": [["p1-en-004", "c2"]],
        "candidate_checklist": checklist.model_dump(mode="json"), "checklist_hash": fingerprint(checklist),
        "prompt_version": VERSION, "technical_change": technical_change(),
        "model_expected": old["model_expected"], "jobs": jobs,
        "schedule": [{"job_id": "1-" + j["job_key"], "job_key": j["job_key"], "repeat": 1,
                      "seed": j["settings"]["ollama_seed"]} for j in jobs],
        "max_calls": 6, "max_attempts": 1, "max_elapsed_minutes": 15,
        "stop_on_any_failure": True, "new_sources": False, "new_sampling": False,
        "extra_c8_pass": False, "stability_measured": False})
    validate_plan(value)
    return value


def validate_plan(value, *, current_code=True):
    plan = unseal(value)
    versions = {SCHEMA: VERSION, LEGACY_SCHEMA: LEGACY_VERSION}
    version = versions.get(plan.get("schema"))
    if (version is None or plan.get("execution_enabled") is not True
            or plan["prompt_version"] != version):
        raise ValueError("Unexpected guarded protocol")
    if version == VERSION and plan.get("technical_change") != technical_change():
        raise ValueError("Declared technical change differs from the authorization")
    if current_code and (version != VERSION or implementation_hash() != plan["implementation_hash"]
                         or PROMPT_VERSION != VERSION):
        raise ValueError("Runtime changed after freezing the plan")
    old = validate_previous_plan(plan["previous_plan"], current_code=False)
    if (fingerprint(plan["previous_plan"]) != plan["previous_plan_hash"]
            or old["review_hash"] != plan["previous_review_hash"] or old["package"] != plan["package"]
            or old["model_expected"] != plan["model_expected"]):
        raise ValueError("Historical comparison changed")
    original, confirmed = reference_cells(plan["package"], plan["review"], ORDER)
    if (fingerprint(plan["review"]) != plan["review_hash"]
            or label_projection(plan["review"]) != label_projection(old["review"])
            or plan["confirmed_cells"] != [list(k) for k in sorted(confirmed)]
            or plan["excluded_cells"] != [["p1-en-004", "c2"]]):
        raise ValueError("Human reference changed")
    checklist = Checklist.model_validate(plan["candidate_checklist"])
    if (fingerprint(checklist) != plan["checklist_hash"]
            or plan["checklist_hash"] != old["semantic_comparison"]["candidate_hash"]
            or grading_shape(original) != grading_shape(checklist)):
        raise ValueError("Checklist changed")
    if (plan["selected_chat_ids"] != list(ORDER) or len(plan["jobs"]) != 6
            or plan["max_calls"] != 6 or plan["max_attempts"] != 1 or plan["max_elapsed_minutes"] != 15
            or plan["stop_on_any_failure"] is not True or plan["stability_measured"] is not False
            or any(plan[k] for k in ("new_sources", "new_sampling", "extra_c8_pass"))):
        raise ValueError("Authorization limits changed")
    old_jobs = {j["dialogue"]["conversation_id"]: j for j in old["jobs"]
                if j["arm"] == "B_reviewed" and j["population"] == "primary_chat"}
    for cid, job in zip(ORDER, plan["jobs"]):
        prior = old_jobs[cid]
        dialogue = Dialogue.model_validate(job["dialogue"])
        settings = Settings.model_validate(job["settings"])
        knowledge = Knowledge.model_validate(job["knowledge"])
        for key, obj in (("dialogue", dialogue), ("settings", settings),
                         ("knowledge", knowledge), ("checklist", checklist)):
            if fingerprint(obj) != job[key + "_hash"]:
                raise ValueError("Job snapshot changed: " + key)
        if (dialogue.conversation_id != cid or job["dialogue"] != prior["dialogue"]
                or job["settings"] != prior["settings"] or job["checklist"] != prior["checklist"]
                or knowledge.sources or settings.provider != "ollama" or settings.max_attempts != 1
                or job["prompt_version"] != version or job["arm"] != "C_fixed"
                or job["population"] != "primary_chat" or job["job_key"] != "C_fixed-" + cid
                or job["prompt_origin"]["previous_job_hash"] != fingerprint(prior)):
            raise ValueError("Job differs from authorized source")
        # After a later code version, archived requests still remain inspectable.
        if current_code:
            expected = build_request(settings, build_input(dialogue, checklist, knowledge),
                                     response_schema(checklist, knowledge, dialogue), settings.max_output_tokens)
            if job["request"] != expected:
                raise ValueError("Frozen request does not match the current 1.7.2 implementation")
        if request_without_schema(job["request"]) != expected_request_core(prior["request"], version):
            raise ValueError("Only the declared technical limitation paragraph and output schema may change")
    expected_schedule = [{"job_id": "1-" + j["job_key"], "job_key": j["job_key"], "repeat": 1,
                          "seed": j["settings"]["ollama_seed"]} for j in plan["jobs"]]
    if plan["schedule"] != expected_schedule:
        raise ValueError("Order or number of attempts changed")
    return plan


def worker(plan_path, job_id, directory, *, validator=None):
    value = read_json(plan_path)
    plan = (validator or validate_plan)(value)
    directory = Path(directory)
    state = read_json(directory / "execution.json")
    if (state["plan_hash"] != fingerprint(value) or state.get("terminal")
            or state["jobs"][-1]["job_id"] != job_id or state["jobs"][-1]["state"] != "started"
            or time.time() >= state["started_epoch"] + 900):
        raise ValueError("No active reservation for this exact frozen request")
    row = next(r for r in plan["schedule"] if r["job_id"] == job_id)
    job = next(j for j in plan["jobs"] if j["job_key"] == row["job_key"])
    settings = Settings.model_validate(job["settings"])
    result = Engine(Store(directory / "runs.sqlite3"), settings,
                    PinnedProvider(settings, plan["model_expected"])).evaluate(
        Dialogue.model_validate(job["dialogue"]), Checklist.model_validate(job["checklist"]),
        Knowledge.model_validate(job["knowledge"]), prepared=job)
    write_json(directory / "worker-results" / (job_id + ".json"), result)


def subprocess_job(plan_path, row, directory, timeout, *, worker_module="cqa.guarded_experiment"):
    directory = Path(directory)
    logs = directory / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / (row["job_id"] + ".txt")).open("xb") as output:
        process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", worker_module, "_worker",
            str(Path(plan_path).resolve()), row["job_id"], str(directory.resolve())],
            stdout=output, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Windows venv Python may launch a child interpreter. Kill the tree,
            # not only its launcher; an uncertain remote outcome must never be retried.
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=output, stderr=subprocess.STDOUT, timeout=10, check=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
            else:
                process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            return {"state": "interrupted_unknown", "error": "worker_deadline_unknown_server_outcome",
                    "accepted": False}
    path = directory / "worker-results" / (row["job_id"] + ".json")
    if code or not path.exists():
        return {"state": "failed", "error": f"worker_exit_{code}_without_final_result", "accepted": False}
    result = read_json(path)
    accepted = bool(result.get("assessment")) and result["error"] is None and result["status"] in {
        "completed", "provisional"}
    if accepted and recalculate(result) != result["scoring"]:
        raise ValueError("Saved calculation changed")
    return {"state": result["status"], "error": result["error"], "accepted": accepted,
            "evaluation_id": result["evaluation_id"], "elapsed_seconds": result.get("elapsed_seconds")}


def call_count(directory):
    path = Path(directory) / "runs.sqlite3"
    if not path.exists():
        return 0
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]


def run(plan_path, directory, *, inspector=inspect_model, executor=subprocess_job, now=time.time, validator=None,
        continue_response_errors=False):
    validator = validator or validate_plan
    value = read_json(plan_path)
    plan = validator(value)
    if continue_response_errors and plan.get("stop_on_any_failure") is not False:
        raise ValueError("This frozen plan requires stopping on the first failed answer.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "execution.json"
    if state_path.exists():
        state = read_json(state_path)
        if state["plan_hash"] != fingerprint(value):
            raise ValueError("Existing execution belongs to another plan")
        if not state.get("terminal"):
            for record in state["jobs"]:
                if record["state"] == "started":
                    record.update(state="interrupted_unknown", error="interrupted_no_retry", accepted=False)
            state.update(terminal=True, status="interrupted_no_resume", unfinished_jobs=6-len(state["jobs"]),
                         elapsed_seconds=max(0, now()-state["started_epoch"]))
            state["not_run_jobs"] = [dict(r, state="not_run", reason=state["status"])
                for r in plan["schedule"] if r["job_id"] not in {j["job_id"] for j in state["jobs"]}]
            write_json(state_path, state)
        return state
    if (directory / "runs.sqlite3").exists() or (directory / "worker-results").exists() or (directory / "logs").exists():
        raise ValueError("A new cycle requires a new execution directory")
    state = {"plan_hash": fingerprint(value), "review_hash": plan["review_hash"], "created_at": utc_now(),
             "started_epoch": now(), "status": "preflight", "jobs": [], "preflight": [], "terminal": False}
    deadline = state["started_epoch"] + 900

    def save():
        state["elapsed_seconds"] = max(0, now()-state["started_epoch"])
        done = {j["job_id"] for j in state["jobs"]}
        state["not_run_jobs"] = [dict(r, state="not_run", reason=state["status"])
                                 for r in plan["schedule"] if r["job_id"] not in done]
        state["unfinished_jobs"] = len(state["not_run_jobs"])
        state["accepted_jobs"] = sum(j.get("accepted") is True for j in state["jobs"])
        state["recorded_calls"] = call_count(directory)
        write_json(state_path, state)

    save()
    try:
        metadata = inspector(Settings.model_validate(plan["jobs"][0]["settings"]))
        check_model(metadata, plan["model_expected"])
        state["preflight"].append({"at": utc_now(), "status": "ok", "metadata": metadata})
    except (ProviderError, ValueError, OSError) as exc:
        state["preflight"].append({"at": utc_now(), "status": "failed", "error": getattr(exc, "code", str(exc))})
        state.update(status="blocked_before_generation", terminal=True)
        save()
        return state
    state["status"] = "running"
    save()
    jobs = {j["job_key"]: j for j in plan["jobs"]}
    for row in plan["schedule"]:
        remaining = deadline - now()
        if remaining <= 1:
            state["status"] = "deadline"
            break
        try:
            validator(read_json(plan_path))
            if fingerprint(read_json(plan_path)) != state["plan_hash"]:
                raise ValueError("Plan changed during execution")
            if call_count(directory) >= 6:
                raise ValueError("Six-call authorization exhausted")
        except (ValueError, OSError) as exc:
            state.update(status="stopped_before_next_call", stop_error=str(exc))
            break
        remaining = deadline - now()
        if remaining <= 1:
            state["status"] = "deadline"
            break
        timeout = min(remaining, jobs[row["job_key"]]["settings"]["timeout_seconds"] + 45)
        record = dict(row, state="started", started_at=utc_now(), hard_timeout_seconds=timeout,
                      job_hash=fingerprint(jobs[row["job_key"]]))
        state["jobs"].append(record)
        save()  # Reserve before launch; failed and uncertain attempts must never be replayed.
        started = now()
        try:
            outcome = executor(plan_path, row, directory, timeout)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            outcome = {"state": "failed", "error": "executor_" + type(exc).__name__, "accepted": False}
        outcome["accepted"] = (outcome.get("accepted") is True and outcome.get("error") is None
                               and outcome.get("state") in {"completed", "provisional"})
        record.update(outcome, finished_at=utc_now(), worker_wall_seconds=max(0, now()-started))
        save()
        if (outcome.get("accepted") is not True or outcome.get("error") is not None
                or outcome.get("state") not in {"completed", "provisional"}):
            if (continue_response_errors and outcome.get("evaluation_id") and outcome.get("state") == "failed"
                    and outcome.get("error") in {"invalid_model_response", "incomplete_model_response"}):
                continue
            state["status"] = "stopped_after_failure"
            break
    else:
        state["status"] = ("completed" if all(row.get("accepted") for row in state["jobs"])
                           else "completed_with_rejections")
    state["terminal"] = True
    save()
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("previous_plan")
    p.add_argument("--review", default="outputs/quality-v2/human-review.json")
    p.add_argument("--checklist", default="config/checklist.review-v3.json")
    p.add_argument("--code-commit")
    p.add_argument("--output", required=True)
    r = commands.add_parser("run")
    r.add_argument("plan")
    r.add_argument("--directory", required=True)
    w = commands.add_parser("_worker")
    w.add_argument("plan")
    w.add_argument("job_id")
    w.add_argument("directory")
    args = parser.parse_args()
    if args.command == "prepare":
        if Path(args.output).exists():
            raise ValueError("Cannot overwrite an existing frozen plan")
        value = prepare(read_json(args.previous_plan), read_json(args.review),
                        Checklist.model_validate(read_json(args.checklist)), code_commit=args.code_commit)
        write_json(args.output, value)
        print(json_text({"seal": value["seal"], "calls": 6, "confirmed_cells": 47}))
    elif args.command == "_worker":
        worker(args.plan, args.job_id, args.directory)
    else:
        state = run(args.plan, args.directory)
        print(json_text({k: state[k] for k in ("status", "accepted_jobs", "recorded_calls", "unfinished_jobs")}))


if __name__ == "__main__":
    main()
