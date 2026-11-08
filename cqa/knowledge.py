"""Offline, auditable excerpt selection. No web search, embeddings or model calls."""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

from .contracts import Dialogue, Knowledge, Source
from .io import fingerprint, read_json

SELECTION_VERSION = "lexical-topics-1"
TOPICS = (
    ("комисс", "тариф", "fee", "commission", "tariff", "алым"),
    ("вывод", "вывест", "withdraw", "ақша шығ", "сняти"),
    ("отчёт", "отчет", "report", "есеп"),
    ("идентиф", "документ", "kyc", "identif", "citizenship", "граждан", "азамат", "құжат"),
    ("торг", "поручен", "заявк", "order", "trad", "сауда", "өтінім"),
    ("валют", "currenc", "теңге"),
    ("парол", "доступ", "access", "password", "құпия", "дерек"),
    ("консульт", "совет", "advice", "advis", "кеңес"),
    ("контакт", "support", "contact", "қолдау", "байланыс"),
)


def words(text):
    return {w for w in re.findall(r"[^\W\d_]{4,}", text.casefold())}


def topic_ids(text):
    text = text.casefold()
    return {i for i, terms in enumerate(TOPICS) if any(t in text for t in terms)}


def load_bundle(folder: str | Path) -> Knowledge:
    """Validate IDs and original bytes; do not certify legal applicability or quotation meaning."""
    folder = Path(folder).resolve()
    raw = read_json(folder / "company-knowledge.json")
    metadata = read_json(folder / "company-knowledge.metadata.json")
    result = Knowledge.model_validate(raw)
    rows = metadata["sources"]
    if len({r["id"] for r in rows}) != len(rows) or {r["id"] for r in rows} != {s.id for s in result.sources}:
        raise ValueError("ID фрагментов и метаданных должны совпадать без повторов")
    index = {r["id"]: r for r in rows}
    for source in result.sources:
        meta = index[source.id]
        original = (folder / meta["local_evidence"]).resolve()
        if not original.is_relative_to(folder) or not original.is_file():
            raise ValueError("Оригинал источника отсутствует или находится вне пакета")
        if hashlib.sha256(original.read_bytes()).hexdigest() != meta["sha256"]:
            raise ValueError("Контрольная сумма оригинала не совпала: " + source.id)
        if not meta.get("quotes") or not meta.get("legal_entity"):
            raise ValueError("Источник требует цитаты с страницами и юрлицо")
        source.provenance = meta
    result.selection = {"bundle_hash": fingerprint(raw), "metadata_hash": fingerprint(metadata),
                        "bundle_version": result.version, "original_hashes_verified": True,
                        "live_sources_verified": False, "retrieval_version": SELECTION_VERSION}
    return result


def prompt_knowledge(knowledge: Knowledge) -> dict:
    """Full provenance is saved in the snapshot; only source facts go to the evaluator.

    Source-selection questions/DEV identifiers are not factual evidence and are excluded.
    Entire quotes, applicability conditions, limitations and boundaries are preserved.
    """
    result = {"version": knowledge.version, "sources": []}
    for source in knowledge.sources:
        if source.provenance is None:
            result["sources"].append(source.model_dump(mode="json"))
            continue
        p = source.provenance
        fields = ("document_title", "source_url", "sha256", "legal_entity", "country", "jurisdiction",
                  "document_version_or_approval_date", "publication_date", "effective_from", "effective_to", "effective_date_basis",
                  "date_note", "verification", "quotes", "applicability_conditions", "limitations",
                  "use_boundary", "can_alone_prove_operator_error")
        item = {"id": source.id, "title": source.title, "effective_date": source.effective_date,
                "provenance": {k: p[k] for k in fields if k in p}}
        item["editorial_summary"] = p.get("supported_content")
        item["summary_note"] = "Пересказ автора пакета; не отдельный первичный источник. Сверять с цитатами и условиями."
        # Retain limitations, but remove identifiers of development examples from model input.
        for key in ("limitations", "applicability_conditions"):
            if isinstance(item["provenance"].get(key), str):
                item["provenance"][key] = re.sub(r"\bp\d-[a-z]{2}-\d{3}\b", "[пример DEV]",
                                                item["provenance"][key])
        result["sources"].append(item)
    if knowledge.selection is not None:
        result["selection"] = {k: v for k, v in knowledge.selection.items()
                               if k in {"retrieval_version", "case_context", "selected_ids", "excluded",
                                        "limitations", "bundle_version"}}
    return result


def select_sources(bundle: Knowledge, dialogue: Dialogue, *, max_sources=4, case_context=None) -> Knowledge:
    if max_sources < 1:
        raise ValueError("max_sources должен быть положительным")
    query = "\n".join(m.text for m in dialogue.transcript if m.speaker in {"client", "operator"})
    context = case_context or {}
    if context and context.get("dialogue_hash") != fingerprint(dialogue):
        raise ValueError("Контекст применимости относится к другому диалогу")
    # Unknown entity stays unknown; explicit Europe is excluded, not silently mapped to FFG.
    europe = "freedom finance europe" in query.casefold() or context.get("legal_entity") == "Freedom Finance Europe Ltd"
    ranked, excluded = [], []
    for source in bundle.sources:
        p = source.provenance or {}
        text = source.title + " " + p.get("supported_content", source.text)
        score = 8 * len(topic_ids(query) & topic_ids(text)) + len(words(query) & words(text))
        reason = None
        if europe and p.get("legal_entity") == "Freedom Finance Global PLC" or context.get("legal_entity") and context["legal_entity"] != p.get("legal_entity"):
            reason = "different_legal_entity"
        elif score == 0:
            reason = "no_lexical_or_topic_match"
        if reason:
            excluded.append({"id": source.id, "reason": reason})
        else:
            ranked.append((score, source.id, source))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    selected = [s for _, _, s in ranked[:max_sources]]
    excluded.extend({"id": s.id, "reason": "top_k_limit", "relevance_score": score}
                    for score, _, s in ranked[max_sources:])
    audit = dict(bundle.selection or {})
    audit.update(retrieval_version=SELECTION_VERSION, case_context=context,
                 observed_dialogue_date=dialogue.transcript[0].timestamp[:10] if dialogue.channel == "voice call" else None,
                 dialogue_hash=fingerprint(dialogue), selected_ids=[s.id for s in selected],
                 ranked_candidates=[{"id": sid, "score": score} for score, sid, _ in ranked],
                 excluded=excluded, limitations=[
                     "Отбор по словам и темам — гипотеза, полнота поиска не подтверждена.",
                     "Даты действия и применимость должны быть проверены отдельно; отсутствие источника не ошибка оператора."])
    return Knowledge(version=bundle.version + "+" + SELECTION_VERSION, sources=selected, selection=audit)


def applicability_errors(source: Source, knowledge: Knowledge, dialogue: Dialogue) -> list[str]:
    """Deterministic necessary conditions. Semantic relevance still needs quality review."""
    p = source.provenance or {}
    ctx = (knowledge.selection or {}).get("case_context", {})
    errors = []
    if not p:
        return ["нет метаданных происхождения и применимости"]
    if (ctx.get("dialogue_hash") != fingerprint(dialogue) or ctx.get("confirmed") is not True
            or not ctx.get("reviewed_by") or not ctx.get("basis")):
        errors.append("контекст применения не подтверждён для этого диалога")
    if not ctx.get("legal_entity") or ctx.get("legal_entity") != p.get("legal_entity"):
        errors.append("не подтверждено совпадение юрлица")
    if source.id not in ctx.get("conditions_confirmed_source_ids", []):
        errors.append("не подтверждены условия и исключения источника")
    try:
        when = date.fromisoformat(ctx.get("date") or "")
        since = date.fromisoformat(p.get("effective_from") or "")
        until = date.fromisoformat(p["effective_to"]) if p.get("effective_to") else None
        if since > when or (until and when > until):
            errors.append("источник вне периода действия")
        if not p.get("effective_date_basis"):
            errors.append("нет основания даты действия редакции")
    except (ValueError, TypeError):
        errors.append("дата диалога или период действия неизвестны")
    if dialogue.channel == "voice call" and ctx.get("date") != dialogue.transcript[0].timestamp[:10]:
        errors.append("дата контекста расходится с исходной датой звонка")
    return errors
