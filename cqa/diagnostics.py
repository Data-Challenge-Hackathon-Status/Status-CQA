"""Offline preparation and scoring of artificial diagnostic probes. No model runner."""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from .contracts import Checklist, Settings
from .diagnostic_cases import cases
from .engine import implementation_hash, recalculate
from .experiment import make_job, seal, unseal
from .io import fingerprint, read_json, write_json
from .prompting import PROMPT_VERSION, build_input, response_schema
from .provider import build_request
from .storage import Store, utc_now


def prepare(checklist: Checklist, settings: Settings) -> dict:
    if settings.max_attempts != 1:
        raise ValueError("Диагностика требует одну заранее назначенную попытку")
    probes = []
    for row in cases():
        d, k = row["dialogue"], row["knowledge"]
        request = build_request(settings, build_input(d, checklist, k), response_schema(checklist, k, d),
                                settings.max_output_tokens)
        job = make_job(d, checklist, k, settings, request, PROMPT_VERSION,
                       {"implementation_hash": implementation_hash(), "synthetic_only": True})
        probes.append({"case_id": d.conversation_id, "language": d.language, "family": row["family"],
                       "expectation_basis": row["expectation_basis"], "expected_answers": row["expected_answers"],
                       "expected_claim": row["expected_claim"], "job": job})
    return seal({"schema": "cqa-synthetic-diagnostics-1", "created_at": utc_now(),
        "implementation_hash": implementation_hash(), "checklist_hash": fingerprint(checklist),
        "settings_hash": fingerprint(settings), "label_source": "ai_authored_synthetic_expectations",
        "human_attestation": False, "language_review": "pending_for_all_languages",
        "probes": probes, "proposed_generation_calls": len(probes), "generation_authorized": False,
        "runner_available": False, "max_attempts": 1, "primary_rule": "One predetermined outcome per case, errors retained",
        "limitations": ["Artificial diagnostic probes, not DEV, human labels or organizers' reference.",
                        "Real model has not been run; no accuracy claim.",
                        "Identity disclosure expected flags use an explicitly declared team interpretation.",
                        "C4 scores in critical probes judge observable completeness, not verified product facts.",
                        "No execution command: separate announced budget and frozen model metadata needed before a run.",
                        "These calls are NOT added to the existing 56-call experiment."]})


def summarize(plan: dict, evaluations: list[dict]) -> dict:
    raw = unseal(plan)
    probes = {p["case_id"]: p for p in raw["probes"]}
    index = {}
    for e in evaluations:
        cid = e["conversation_id"]
        if cid in index or cid not in probes:
            raise ValueError("Лишний или повторный исход; нельзя выбрать удачный повтор")
        job = probes[cid]["job"]
        for field in ("dialogue_hash", "checklist_hash", "knowledge_hash", "prompt_version"):
            if e[field] != job[field]:
                raise ValueError("Результат относится к другой версии входа")
        if (fingerprint(e["settings"]) != fingerprint(job["settings"])
                or e["implementation_hash"] != raw["implementation_hash"]):
            raise ValueError("Изменились код или настройки")
        attempts = e.get("attempts", [])
        if len(attempts) > 1 or (attempts and fingerprint(attempts[0]["request"]) != fingerprint(job["request"])):
            raise ValueError("Запрос или число попыток отличаются от плана")
        if e.get("status") in {"completed", "provisional"} and (
                not attempts or not e.get("assessment") or recalculate(e) != e["scoring"]):
            raise ValueError("Принятый исход не воспроизводится")
        index[cid] = e
    groups = defaultdict(lambda: {"cases": 0, "available": 0, "missing_or_failed": 0,
                                  "assertions": 0, "matched": 0, "critical_positive_cases": 0,
                                  "critical_negative_cases": 0, "tp": 0, "tn": 0, "fp": 0, "fn": 0,
                                  "critical_unavailable": 0})
    details = []
    for cid, p in probes.items():
        e = index.get(cid)
        assessment = e["assessment"]["criteria"] if e and e.get("status") in {"completed", "provisional"} else None
        expected = p["expected_answers"]
        matched = sum(assessment[c]["answer"] == a for c, a in expected.items()) if assessment else 0
        claim_expected = p["expected_claim"]
        claim_match = None
        if claim_expected:
            claims = ((assessment[claim_expected["criterion_id"]].get("knowledge_review") or {}).get("external_claims", [])
                      if assessment else [])
            relevant = [c for c in claims if claim_expected["message_id"] in c["message_ids"]]
            # Missing claim or an extra conflicting claim cannot be reported as a successful check.
            claim_match = bool(relevant) and all(c["status"] == claim_expected["status"]
                and c.get("document_relation") == claim_expected["document_relation"] for c in relevant)
            matched += claim_match
        for key in ("all", "language:" + p["language"], "family:" + p["family"],
                    "basis:" + p["expectation_basis"]):
            g = groups[key]
            g["cases"] += 1
            g["available"] += assessment is not None
            g["missing_or_failed"] += assessment is None
            g["assertions"] += len(expected) + (claim_expected is not None)
            g["matched"] += matched
            if "c8" in expected:
                positive = expected["c8"] == "yes"
                g["critical_positive_cases" if positive else "critical_negative_cases"] += 1
                if assessment is None:
                    g["critical_unavailable"] += 1
                else:
                    actual = assessment["c8"]["answer"] == "yes"
                    g[("tp" if actual else "fn") if positive else ("fp" if actual else "tn")] += 1
        details.append({"case_id": cid, "family": p["family"], "available": assessment is not None,
                        "outcome_status": e.get("status") if e else "not_run", "matched": matched,
                        "expected_answers": expected, "actual_answers": {c: assessment[c]["answer"] for c in expected}
                        if assessment else None, "claim_match": claim_match, "error": e.get("error") if e else None})
    for g in groups.values():
        g["assertion_match_rate"] = g["matched"] / g["assertions"] if g["assertions"] else None
        # Zero available model outcomes is absence of a measurement, not measured 0% accuracy.
        if not g["available"]:
            g["assertion_match_rate"] = None
    return {"plan_hash": fingerprint(plan), "reference": raw["label_source"], "human_attestation": False,
            "measurement_available": bool(groups["all"]["available"]), "groups": dict(groups), "cases": details,
            "semantic_evidence_review": "pending; ID validity does not prove the explanation supports its criterion",
            "limitations": raw["limitations"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--settings", default="config/settings.experiment-control.json")
    prep.add_argument("--output", required=True)
    report = sub.add_parser("summarize")
    report.add_argument("plan")
    report.add_argument("--db")
    report.add_argument("--runs")
    report.add_argument("--output", required=True)
    args = parser.parse_args()
    if Path(args.output).exists():
        raise ValueError("Существующий план или отчёт не перезаписывается")
    if args.command == "prepare":
        result = prepare(Checklist.model_validate(read_json("config/checklist.claims-v1.json")),
                         Settings.model_validate(read_json(args.settings)))
    else:
        if bool(args.db) != bool(args.runs):
            raise ValueError("Для сохранённых результатов нужны одновременно --db и --runs")
        evaluations = []
        if args.db:
            store = Store(args.db)
            evaluations = [store.get_evaluation(i) for i in read_json(args.runs)["evaluation_ids"]]
        result = summarize(read_json(args.plan), evaluations)
    write_json(args.output, result)
    print("Сохранено без генераций:", args.output)


if __name__ == "__main__":
    main()
