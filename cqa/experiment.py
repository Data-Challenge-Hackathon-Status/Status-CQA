"""Prepare offline first. `run` is explicit and gated on actual human review."""
from __future__ import annotations

import argparse
import time
from copy import deepcopy
from pathlib import Path

from .compatibility import assert_compatible
from .context import context_report, fit_knowledge
from .contracts import Checklist, Dialogue, Knowledge, Settings
from .engine import Engine, implementation_hash, recalculate
from .io import fingerprint, read_json, write_json
from .knowledge import load_bundle, select_sources
from .ollama_provider import OllamaProvider
from .prompting import PROMPT_VERSION, build_input, response_schema
from .provider import ProviderError, build_request
from .review import check_package, compare_review, stability, validate_review
from .storage import Store, utc_now


def seal(value):
    return dict(value, seal=fingerprint(value))


def unseal(value):
    raw = {k: v for k, v in value.items() if k != "seal"}
    if fingerprint(raw) != value.get("seal"):
        raise ValueError("Зафиксированный файл изменён")
    return raw


def make_job(dialogue, checklist, knowledge, settings, request, prompt_version, origin):
    budget = context_report(request, settings)
    if not budget["fits"]:
        raise ValueError("Запрос не помещается: " + dialogue.conversation_id)
    return {"dialogue": dialogue.model_dump(mode="json"), "dialogue_hash": fingerprint(dialogue),
            "checklist": checklist.model_dump(mode="json"), "checklist_hash": fingerprint(checklist),
            "knowledge": knowledge.model_dump(mode="json"), "knowledge_hash": fingerprint(knowledge),
            "settings": settings.model_dump(mode="json"), "settings_hash": fingerprint(settings),
            "request": request, "prompt_version": prompt_version, "prompt_origin": origin,
            "context_preflight": budget}


def prepare(package, split, baseline_runs, bundle, checklist, control, candidate, compatibility, metadata):
    old = check_package(package)
    assert_compatible(old, checklist, compatibility)
    ids = [r["conversation_id"] for r in package["records"]]
    if not ids or not set(ids) <= set(split["tuning"]):
        raise ValueError("Подготовка этого диагностического опыта допускает только tuning")
    if control.max_attempts != 1 or candidate.max_attempts != 1:
        raise ValueError("В сравнении нет автоматических повторных попыток")
    # A/B/C share decoding; C/D share everything except the declared sampling fields.
    a, b = control.model_dump(mode="json"), candidate.model_dump(mode="json")
    sampling = {"ollama_temperature", "ollama_top_p", "ollama_top_k", "ollama_min_p"}
    if any(a.get(k) is None or b.get(k) is None for k in sampling):
        raise ValueError("Все четыре параметра выборки должны быть явными")
    if {k: v for k, v in a.items() if k not in sampling} != {k: v for k, v in b.items() if k not in sampling}:
        raise ValueError("Профили различаются не только параметрами выборки")
    selected = next((m for m in metadata["models"]["models"] if m["name"] == control.model), None)
    if (metadata["version"]["version"] != control.ollama_version or not selected or not selected.get("digest")
            or metadata["details"].get("quantization_level") != "Q4_K_M"):
        raise ValueError("Нужны проверенные метаданные прежней модели и версии")
    baselines = {r["conversation_id"]: r for r in baseline_runs}
    if len(baselines) != len(baseline_runs) or set(baselines) != set(ids):
        raise ValueError("Нужен ровно один заранее выбранный baseline на каждый ID")
    jobs = []
    for row in package["records"]:
        dialogue = Dialogue.model_validate(row["dialogue"])
        previous = baselines[dialogue.conversation_id]
        if (previous["dialogue_hash"] != fingerprint(dialogue) or previous["checklist_hash"] != fingerprint(old)
                or previous["prompt_version"] != "cqa-1.3.0" or recalculate(previous) != previous["scoring"]):
            raise ValueError("Исходный запуск изменён или относится к другой версии")
        original_request = previous["attempts"][0]["request"]
        original_metadata = previous["attempts"][0].get("provider_metadata") or {}
        if original_metadata.get("model_digest") != selected["digest"]:
            raise ValueError("Модель отличается от исторического запуска")
        no_knowledge = Knowledge()
        selected_knowledge, _ = fit_knowledge(dialogue, checklist, select_sources(bundle, dialogue), control)
        for arm in ("A_baseline", "B_instructions", "C_knowledge", "D_sampling"):
            settings = candidate if arm == "D_sampling" else control
            current_checklist = old if arm == "A_baseline" else checklist
            knowledge = selected_knowledge if arm in {"C_knowledge", "D_sampling"} else no_knowledge
            if arm == "A_baseline":
                request = deepcopy(original_request)
                request["options"] = build_request(control, [{"role": "system", "content": ""}], {},
                                                    control.max_output_tokens)["options"]
                origin = {"baseline_evaluation_id": previous["evaluation_id"],
                          "baseline_implementation_hash": previous["implementation_hash"],
                          "original_request_hash": fingerprint(original_request),
                          "change": "Only options made explicit; saved messages and schema replayed verbatim."}
                version = previous["prompt_version"]
            else:
                request = build_request(settings, build_input(dialogue, current_checklist, knowledge),
                                        response_schema(current_checklist, knowledge, dialogue), settings.max_output_tokens)
                origin, version = {"implementation_hash": implementation_hash()}, PROMPT_VERSION
            job = make_job(dialogue, current_checklist, knowledge, settings, request, version, origin)
            jobs.append(dict(job, arm=arm, conversation_id=dialogue.conversation_id))
    schedule = []
    # Counterbalance arm order across dialogs; reverse in round 2. Never select by score.
    arms = ["A_baseline", "B_instructions", "C_knowledge", "D_sampling"]
    for repeat in (1, 2):
        for i, cid in enumerate(ids):
            order = arms[i % 4:] + arms[:i % 4]
            if repeat == 2:
                order = list(reversed(order))
            for arm in order:
                schedule.append({"conversation_id": cid, "arm": arm, "repeat": repeat,
                                 "seed": control.ollama_seed, "job_id": f"{repeat}-{cid}-{arm}"})
    return seal({"schema": "cqa-frozen-experiment-1", "created_at": utc_now(),
        "implementation_hash": implementation_hash(), "package_id": package["package_id"],
        "package": package, "split_hash": fingerprint(split), "compatibility": compatibility,
        "selected_tuning_ids": ids, "model": control.model, "model_digest": selected["digest"],
        "server_version": control.ollama_version, "quantization": metadata["details"]["quantization_level"],
        "model_parameters_hash": fingerprint(metadata["parameters"]), "model_template_hash": fingerprint(metadata["template"]),
        "jobs": jobs, "schedule": schedule, "max_generation_calls": len(schedule), "max_attempts": 1,
        "repeats": 2, "seeds": [control.ollama_seed, control.ollama_seed], "primary_repeat": 1,
        "primary_population": "agent chat", "voice_role": "separate diagnostic slice; no calls in organizer control set",
        "primary_rule": "All first-round scheduled outcomes, including errors. Never replace with second round.",
        "max_wall_minutes": 120,
        "time_estimate": "Исторически ~1 мин/диалог; ориентир 1–2 часа, новая длина входа и thinking не измерены.",
        "purpose": "Diagnostic tuning only; not a general accuracy estimate and not organizers' Ground Truth.",
        "factor_contrasts": {"A_to_B": f"instruction/schema/fact-policy bundle 1.3 to {PROMPT_VERSION}, no sources",
                             "B_to_C": "source selection and provenance, same policy and sampling",
                             "C_to_D": "explicit sampling profile only"},
        "limits": ["Known exposure in cards must be preserved; p1-ru-023 is not blind.",
                   "Knowledge author selected material using DEV; cannot claim independent holdout knowledge selection.",
                   "Source effective dates unknown; factual correctness cannot be established with current package.",
                   "Repeated seed is not a guarantee of reproducibility; only same-seed stability is measured.",
                   "Validation for selection, holdout once after freezing winner; neither included in this experiment."]})


class PinnedProvider(OllamaProvider):
    def __init__(self, settings, plan, **kwargs):
        super().__init__(settings, **kwargs)
        self.plan = plan

    def inspect(self):
        metadata = super().inspect()
        if metadata["model_digest"] != self.plan["model_digest"]:
            raise ProviderError("experiment_model_digest_changed", retryable=False)
        return metadata


def run_plan(plan, review, directory):
    plan = unseal(plan)
    if plan.get("schema") != "cqa-frozen-experiment-1":
        raise ValueError("Этот протокол не разрешён для запуска данным обработчиком")
    directory = Path(directory)
    if implementation_hash() != plan["implementation_hash"]:
        raise ValueError("Код изменён после подготовки; нужен новый план, старый не заменять")
    _, _, _, complete = validate_review(plan["package"], review)
    if set(complete) != set(plan["selected_tuning_ids"]):
        raise ValueError("Сначала нужны подтверждённые человеком все восемь критериев всех карточек")
    # Start no calls until the entire frozen plan and source snapshots have been checked.
    jobs = {(j["conversation_id"], j["arm"]): j for j in plan["jobs"]}
    for job in jobs.values():
        if not context_report(job["request"], Settings.model_validate(job["settings"]))["fits"]:
            raise ValueError("Контекст больше не помещается")
    settings = Settings.model_validate(plan["jobs"][0]["settings"])
    provider = PinnedProvider(settings, plan)
    provider.inspect()
    show = provider._json("POST", "/api/show", {"model": settings.model, "verbose": False})
    if (fingerprint(show.get("parameters")) != plan["model_parameters_hash"]
            or fingerprint(show.get("template")) != plan["model_template_hash"]):
        raise ValueError("Шаблон или параметры модели изменились")
    state_path = directory / "execution.json"
    state = read_json(state_path) if state_path.exists() else {
        "plan_hash": fingerprint(plan), "review_hash": fingerprint(review), "jobs": [], "elapsed_seconds": 0,
        "wall_budget_spent": 0}
    if state["plan_hash"] != fingerprint(plan) or state["review_hash"] != fingerprint(review):
        raise ValueError("Продолжение требует тот же план и ту же разметку")
    for record in state["jobs"]:
        if record["state"] == "started" and not record.get("evaluation_id"):
            record.update(state="interrupted_unknown", error="interrupted_no_automatic_retry")
    write_json(state_path, state)
    store = Store(directory / "runs.sqlite3")
    started = time.monotonic()
    for row in plan["schedule"]:
        if any(r["job_id"] == row["job_id"] for r in state["jobs"]):
            continue  # Includes failed or interrupted calls: no unplanned retry.
        job = jobs[(row["conversation_id"], row["arm"])]
        settings = Settings.model_validate(job["settings"])
        reserved_seconds = settings.timeout_seconds + 30  # Includes version/digest inspection.
        if state["wall_budget_spent"] + reserved_seconds > plan["max_wall_minutes"] * 60:
            break
        call_started = time.monotonic()
        record = dict(row, state="started", started_at=utc_now())
        state["jobs"].append(record)
        # A crash consumes the reserved allowance and the scheduled attempt; never silently replay it.
        state["wall_budget_spent"] += reserved_seconds
        write_json(state_path, state)
        result = Engine(store, settings, provider=PinnedProvider(settings, plan)).evaluate(
            Dialogue.model_validate(job["dialogue"]), Checklist.model_validate(job["checklist"]),
            Knowledge.model_validate(job["knowledge"]), prepared=job)
        record.update(state=result["status"], evaluation_id=result["evaluation_id"], error=result["error"])
        state["wall_budget_spent"] += time.monotonic() - call_started - reserved_seconds
        write_json(state_path, state)
    state["elapsed_seconds"] += time.monotonic() - started
    state["unfinished_jobs"] = len(plan["schedule"]) - len(state["jobs"])
    write_json(state_path, state)
    return state


def summarize(plan, review, directory):
    plan = unseal(plan)
    state = read_json(Path(directory) / "execution.json")
    if state["plan_hash"] != fingerprint(plan):
        raise ValueError("Исполнение относится к другому плану")
    store = Store(Path(directory) / "runs.sqlite3")
    results = {}
    for arm in ("A_baseline", "B_instructions", "C_knowledge", "D_sampling"):
        rounds = [[store.get_evaluation(r["evaluation_id"]) for r in state["jobs"]
                   if r["arm"] == arm and r["repeat"] == rep and r.get("evaluation_id")] for rep in (1, 2)]
        metrics = compare_review(plan["package"], review, rounds[0], compatibility=plan["compatibility"])
        metrics["scheduled_primary_dialogues"] = len(plan["selected_tuning_ids"])
        metrics["missing_primary_outcomes"] = sorted(set(plan["selected_tuning_ids"]) -
                                                     {r["conversation_id"] for r in rounds[0]})
        if len(rounds[0]) == len(rounds[1]) == len(plan["selected_tuning_ids"]):
            metrics["stability"] = stability(*rounds)
        else:
            metrics["stability"] = {"available": False, "reason": "Не все заранее назначенные повторы завершены"}
        results[arm] = metrics
    return {"plan_hash": fingerprint(plan), "review_hash": fingerprint(review), "arms": results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--package", default="outputs/quality-v1/review/package.json")
    prep.add_argument("--split", default="data/split.json")
    prep.add_argument("--baseline-runs", default="outputs/quality-v1/baseline/selected-runs.json")
    prep.add_argument("--db", default="data/cqa.sqlite3")
    prep.add_argument("--bundle", required=True)
    prep.add_argument("--metadata", required=True)
    prep.add_argument("--output", required=True)
    for name in ("run", "summarize"):
        item = sub.add_parser(name)
        item.add_argument("plan")
        item.add_argument("--review", required=True)
        item.add_argument("--directory", required=True)
    args = p.parse_args()
    if args.command == "prepare":
        if Path(args.output).exists():
            raise ValueError("Старый план не перезаписывается: выберите новый путь")
        store = Store(args.db)
        plan = prepare(read_json(args.package), read_json(args.split),
            [store.get_evaluation(i) for i in read_json(args.baseline_runs)["evaluation_ids"]],
            load_bundle(args.bundle), Checklist.model_validate(read_json("config/checklist.claims-v1.json")),
            Settings.model_validate(read_json("config/settings.experiment-control.json")),
            Settings.model_validate(read_json("config/settings.experiment-qwen-thinking.json")),
            read_json("config/checklist-policy-compatibility.json"), read_json(args.metadata))
        write_json(args.output, plan)
        print("План подготовлен без генераций. Максимум запросов:", plan["max_generation_calls"])
    elif args.command == "run":
        run_plan(read_json(args.plan), read_json(args.review), args.directory)
    else:
        result = summarize(read_json(args.plan), read_json(args.review), args.directory)
        output = Path(args.directory) / ("comparison-" + fingerprint(result)[:12] + ".json")
        write_json(output, result)
        print(output)


if __name__ == "__main__":
    main()
