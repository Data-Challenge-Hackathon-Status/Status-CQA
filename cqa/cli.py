from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .contracts import Checklist, Knowledge, Settings
from .dataset import evaluate_dataset
from .engine import Engine, recalculate
from .io import json_text, load_dialogues, read_json, write_json
from .provider import ProviderError, create_provider
from .quality import annotation_template, compare, make_split
from .reporting import text_report
from .storage import Store
from .submission import (
    SubmissionSettings,
    build_submission,
    read_submission,
    save_submission,
    validate_submission,
)

SUBMISSION_CHECKLISTS = {"dev": "config/checklist.claims-v1.json",
                         "prod": "config/checklist.review-v4.1.json"}


def summary(result: dict) -> dict:
    return {"evaluation_id": result["evaluation_id"], "conversation_id": result["conversation_id"],
            "status": result["status"], "total_score": (result.get("scoring") or {}).get("total_score"),
            "gross_violation": (result.get("scoring") or {}).get("gross_violation"),
            "needs_review": result["needs_review"], "estimated_cost_usd": result["estimated_cost_usd"],
            "billing_uncertain": result["billing_uncertain"],
            "billing_mode": result.get("billing_mode", "api_tokens"),
            "attempts": len(result["attempts"]), "error": result["error"]}


def parser():
    p = argparse.ArgumentParser(description="Freedom CQA: оценка диалогов с проверяемыми доказательствами")
    p.add_argument("--db", default="data/cqa.sqlite3")
    p.add_argument("--settings", help="Профиль модели. Для evaluate-set PROD по умолчанию settings.brev.prod.json")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Проверка доступа без платной генерации")
    imp = sub.add_parser("import-data")
    imp.add_argument("path")
    check = sub.add_parser("save-checklist")
    check.add_argument("path", nargs="?", default="config/checklist.claims-v1.json")
    sub.add_parser("list")
    sub.add_parser("budget")
    ev = sub.add_parser("evaluate")
    ev.add_argument("conversation_id")
    ev.add_argument("--checklist", default="config/checklist.claims-v1.json")
    ev.add_argument("--knowledge")
    ev.add_argument("--knowledge-bundle", help="Папка company-knowledge.json, metadata и evidence")
    ev.add_argument("--output")
    batch = sub.add_parser("batch")
    batch.add_argument("conversation_ids", nargs="+")
    batch.add_argument("--checklist", default="config/checklist.claims-v1.json")
    batch.add_argument("--knowledge")
    batch.add_argument("--knowledge-bundle")
    batch.add_argument("--output", required=True, help="JSON-манифест запусков для сравнения качества")
    report = sub.add_parser("report")
    report.add_argument("evaluation_id")
    report.add_argument("--output")
    report.add_argument("--text", action="store_true", help="Читаемый отчёт вместо технического JSON")
    re = sub.add_parser("recalculate")
    re.add_argument("evaluation_id")
    split = sub.add_parser("split")
    split.add_argument("--output", default="data/split.json")
    split.add_argument("--seed", type=int, default=42)
    labels = sub.add_parser("annotation-template")
    labels.add_argument("--split", default="data/split.json")
    labels.add_argument("--part", choices=["tuning", "validation", "holdout"], required=True)
    labels.add_argument("--checklist", default="config/checklist.claims-v1.json")
    labels.add_argument("--output", required=True)
    cmp = sub.add_parser("compare")
    cmp.add_argument("labels")
    cmp.add_argument("runs", help="Манифест batch с evaluation_ids")
    cmp.add_argument("--checklist", default="config/checklist.claims-v1.json")
    cmp.add_argument("--output")
    export = sub.add_parser("export-results", help="Выгрузка в формат сдачи организаторов 1.0")
    export.add_argument("runs", help="Манифест batch с одним запуском на каждый исходный диалог")
    export.add_argument("--input", required=True, help="Исходный ответ API организаторов")
    export.add_argument("--dataset", choices=["dev", "prod"], required=True)
    export.add_argument("--submission-config", default="config/submission.json")
    export.add_argument("--output", help="По умолчанию results/<dataset>/results.json")
    verify = sub.add_parser("validate-results", help="Проверка файла перед commit и push")
    verify.add_argument("path")
    verify.add_argument("--input", required=True)
    verify.add_argument("--dataset", choices=["dev", "prod"], required=True)
    verify.add_argument("--checklist", help="По умолчанию текущая версия для выбранного DEV/PROD")
    verify.add_argument("--submission-config", default="config/submission.json")
    complete = sub.add_parser("evaluate-set", help="Обработать весь DEV/PROD и подготовить файл сдачи")
    complete.add_argument("input", help="Сохранённый исходный ответ API организаторов")
    complete.add_argument("--dataset", choices=["dev", "prod"], required=True)
    complete.add_argument("--checklist", help="По умолчанию текущая версия для выбранного DEV/PROD")
    complete.add_argument("--knowledge")
    complete.add_argument("--submission-config", default="config/submission.json")
    complete.add_argument("--runs", help="По умолчанию outputs/<dataset>-runs.json")
    complete.add_argument("--output", help="По умолчанию results/<dataset>/results.json")
    complete.add_argument("--max-minutes", type=float, help="Не начинать новые оценки после лимита; PROD 40, DEV 180")
    complete.add_argument("--resume", action="store_true", help="Продолжить тот же запуск без повторения готовых оценок")
    complete.add_argument("--retry-errors", action="store_true", help="При продолжении заново обработать ошибки")
    return p


def run(args):
    if args.settings is None:
        is_control_run = args.command == "evaluate-set" and args.dataset == "prod"
        args.settings = "config/settings.brev.prod.json" if is_control_run else "config/settings.json"
    if args.command == "doctor":
        settings = Settings.model_validate(read_json(args.settings))
        provider = create_provider(settings.model_copy(update={"timeout_seconds": 30}))
        if settings.provider == "ollama":
            info = provider.inspect()
            print(json_text({"provider": "ollama", "api_access": True, "configured_model": settings.model,
                             **info, "generation_tested": False,
                             "billing": "Аренда сервера оплачивается отдельно в Brev"}, pretty=True))
            return 0 if info["model_available"] else 1
        models = provider.available_models()
        print(json_text({"key_configured": True, "api_access": True, "configured_model": settings.model,
                         "model_available": settings.model in models,
                         "text_model_candidates": [m for m in models if m.startswith(("gpt-6", "gpt-5", "gpt-4.1"))]}, pretty=True))
        return 0
    store = Store(args.db)
    if args.command == "evaluate-set":
        payload = evaluate_dataset(
            store, Settings.model_validate(read_json(args.settings)), load_dialogues(read_json(args.input)),
            Checklist.model_validate(read_json(args.checklist or SUBMISSION_CHECKLISTS[args.dataset])),
            Knowledge.model_validate(read_json(args.knowledge)) if args.knowledge else Knowledge(),
            SubmissionSettings.model_validate(read_json(args.submission_config)), dataset=args.dataset,
            runs_path=args.runs or f"outputs/{args.dataset}-runs.json",
            output=args.output or f"results/{args.dataset}/results.json",
            max_minutes=args.max_minutes if args.max_minutes is not None else (40 if args.dataset == "prod" else 180),
            resume=args.resume, retry_errors=args.retry_errors,
            report=lambda r: print(json_text(summary(r)), flush=True))
        statuses = dict(Counter(r["status"] for r in payload["results"]))
        print(json_text({"file": args.output or f"results/{args.dataset}/results.json", "statuses": statuses}))
        return 1 if statuses.get("error") else 0
    elif args.command in {"export-results", "validate-results"}:
        dialogues = [d for d, _ in load_dialogues(read_json(args.input))]
        config = SubmissionSettings.model_validate(read_json(args.submission_config))
        if args.command == "export-results":
            results = [store.get_evaluation(i) for i in read_json(args.runs)["evaluation_ids"]]
            payload = build_submission(results, dialogues, args.dataset, config)
            output = args.output or f"results/{args.dataset}/results.json"
            save_submission(output, payload)
        else:
            output = args.path
            payload = validate_submission(read_submission(output), dialogues, args.dataset,
                                          Checklist.model_validate(read_json(
                                              args.checklist or SUBMISSION_CHECKLISTS[args.dataset])), config)
        print(json_text({"file": str(Path(output).resolve()), "schema_version": payload["schema_version"],
                         "records": len(payload["results"]),
                         "statuses": dict(Counter(r["status"] for r in payload["results"]))}, pretty=True))
    elif args.command == "import-data":
        records = load_dialogues(read_json(args.path))
        store.save_dialogues(records)
        print(json_text({"imported": len(records), "languages": dict(Counter(d.language for d, _ in records)),
                         "channels": dict(Counter(d.channel for d, _ in records))}, pretty=True))
    elif args.command == "save-checklist":
        c = Checklist.model_validate(read_json(args.path))
        store.save_checklist(c)
        print(json_text({"saved": c.id, "version": c.version, "criteria": len(c.criteria)}))
    elif args.command == "list":
        print(json_text([{"id": d.conversation_id, "language": d.language,
                          "channel": d.channel, "messages": len(d.transcript)}
                         for d in store.list_dialogues()], pretty=True))
    elif args.command == "budget":
        print(json_text(store.budget_summary(), pretty=True))
    elif args.command in {"evaluate", "batch"}:
        checklist = Checklist.model_validate(read_json(args.checklist))
        settings = Settings.model_validate(read_json(args.settings))
        knowledge = Knowledge.model_validate(read_json(args.knowledge)) if args.knowledge else Knowledge()
        if args.knowledge and args.knowledge_bundle:
            raise ValueError("Выберите --knowledge или --knowledge-bundle")
        from .context import fit_knowledge
        from .knowledge import load_bundle, select_sources
        bundle = load_bundle(args.knowledge_bundle) if args.knowledge_bundle else None
        engine = Engine(store, settings)
        ids = [args.conversation_id] if args.command == "evaluate" else args.conversation_ids
        # Resolve all IDs before any billable request.
        dialogues = [store.get_dialogue(i) for i in ids]
        results = []
        for dialogue in dialogues:
            selected = knowledge
            if bundle is not None:
                selected, _ = fit_knowledge(dialogue, checklist, select_sources(bundle, dialogue), settings)
            result = engine.evaluate(dialogue, checklist, selected)
            results.append(result)
            print(json_text(summary(result), pretty=True), flush=True)
            if args.command == "batch":
                write_json(args.output, {"evaluation_ids": [r["evaluation_id"] for r in results]})
        if args.command == "evaluate" and args.output:
            write_json(args.output, results[0])
        return 1 if any(r["status"] == "failed" for r in results) else 0
    elif args.command in {"report", "recalculate"}:
        result = store.get_evaluation(args.evaluation_id)
        if getattr(args, "text", False):
            text = text_report(result)
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                print("Сохранено: " + str(path.resolve()))
            else:
                print(text)
            return 0
        value = recalculate(result) if args.command == "recalculate" else result
        if getattr(args, "output", None):
            write_json(args.output, value)
            print("Сохранено: " + str(Path(args.output).resolve()))
        else:
            print(json_text(value, pretty=True))
    elif args.command == "split":
        if Path(args.output).exists():
            raise ValueError("Разбиение уже зафиксировано. Используйте другой путь для нового эксперимента.")
        value = make_split(store.list_dialogues(), args.seed)
        write_json(args.output, value)
        print(json_text({k: len(value[k]) for k in ("tuning", "validation", "holdout", "unlabelled")}))
    elif args.command == "annotation-template":
        if Path(args.output).exists():
            raise ValueError("Файл разметки уже существует; перезапись запрещена")
        value = annotation_template(store.list_dialogues(), Checklist.model_validate(read_json(args.checklist)),
                                    read_json(args.split)[args.part])
        write_json(args.output, value)
        print("Создан пустой шаблон ручной разметки: " + str(Path(args.output).resolve()))
    elif args.command == "compare":
        results = [store.get_evaluation(i) for i in read_json(args.runs)["evaluation_ids"]]
        value = compare(read_json(args.labels), results, Checklist.model_validate(read_json(args.checklist)))
        if args.output:
            write_json(args.output, value)
        print(json_text(value, pretty=True))
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        return run(parser().parse_args())
    except ProviderError as exc:
        print("Доступ к модели: " + exc.code, file=sys.stderr)
        return 1
    except (ValueError, KeyError, OSError) as exc:
        print("Ошибка: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
