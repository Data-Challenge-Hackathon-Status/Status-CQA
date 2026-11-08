from __future__ import annotations

from .contracts import Checklist, Dialogue, Knowledge, ModelAssessment


class AssessmentError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_assessment(assessment: ModelAssessment, dialogue: Dialogue,
                        checklist: Checklist, knowledge: Knowledge, *, strict_sources=True,
                        require_contradiction_basis=False, require_operator_flag_evidence=False,
                        legacy_operator_flags=False) -> None:
    errors = []
    expected = {c.id for c in checklist.criteria}
    actual = set(assessment.criteria)
    if expected != actual:
        errors.append(f"Набор критериев не совпадает: пропущены {sorted(expected-actual)}, "
                      f"лишние {sorted(actual-expected)}")
    messages = {m.id: m for m in dialogue.transcript}
    positions = {m.id: i for i, m in enumerate(dialogue.transcript)}
    sources = {s.id for s in knowledge.sources}
    for criterion in checklist.criteria:
        if criterion.id not in assessment.criteria:
            continue
        value = assessment.criteria[criterion.id]
        prefix = criterion.id + ": "
        if value.answer == "na":
            if value.na_condition_id not in {x.id for x in criterion.na_conditions
                                            if x.channels is None or dialogue.channel in x.channels}:
                errors.append(prefix + "N/A не разрешён или условие неизвестно")
            if strict_sources and (value.knowledge_status != "not_needed" or value.source_ids):
                errors.append(prefix + "N/A не содержит проверки продуктовых фактов или источников")
        else:
            if value.answer not in {x.value for x in criterion.options}:
                errors.append(prefix + "недопустимая оценка")
            if value.na_condition_id is not None:
                errors.append(prefix + "для применимого критерия na_condition_id должен быть null")
        if value.knowledge_status in {"supported", "contradicted"} and not value.source_ids:
            errors.append(prefix + "подтверждение фактов требует source_ids")
        if set(value.source_ids) - sources:
            errors.append(prefix + "неизвестный источник компании")
        if strict_sources and value.knowledge_status == "not_needed" and value.source_ids:
            errors.append(prefix + "not_needed несовместим со ссылками на проверяемые продуктовые источники")
        review = value.knowledge_review
        if review is not None:
            if not criterion.requires_company_knowledge or value.answer == "na":
                errors.append(prefix + "knowledge_review только для применимого критерия с проверкой знаний")
            if criterion.max_observed_facts is not None:
                facts = review.observed_facts
                if len(facts) > criterion.max_observed_facts:
                    errors.append(prefix + "превышен предел числа наблюдений")
                unique = {(" ".join(f.statement.split()), frozenset(f.message_ids)) for f in facts}
                if len(unique) != len(facts):
                    errors.append(prefix + "повторяется одно и то же наблюдение с теми же репликами")
            for fact in review.observed_facts:
                if not fact.statement.strip() or set(fact.message_ids) - set(messages):
                    errors.append(prefix + "наблюдаемый факт пуст или ссылается на неизвестную реплику")
            referenced_sources = set()
            unverified_claims = []
            for claim in review.external_claims:
                if not claim.statement.strip() or set(claim.message_ids) - set(messages):
                    errors.append(prefix + "внешнее утверждение пусто или ссылается на неизвестную реплику")
                if any(messages[m].speaker != "operator" for m in claim.message_ids if m in messages):
                    errors.append(prefix + "внешнее утверждение должно относиться к реплике оператора")
                if set(claim.source_ids) - sources:
                    errors.append(prefix + "внешнее утверждение ссылается на неизвестный источник")
                referenced_sources.update(claim.source_ids)
                if require_contradiction_basis:
                    if claim.document_relation is None:
                        errors.append(prefix + "требуется отношение утверждения к документу")
                    if claim.document_relation in {"supports", "contradicts"} and not claim.source_ids:
                        errors.append(prefix + "отношение к документу требует источника")
                    basis = claim.contradiction_basis
                    if claim.document_relation == "contradicts" or claim.status == "contradicted":
                        if basis is None:
                            errors.append(prefix + "прямое опровержение требует contradiction_basis")
                        else:
                            source = next((s for s in knowledge.sources if s.id == basis.source_id), None)
                            if source is None or basis.source_id not in claim.source_ids:
                                errors.append(prefix + "основание опровержения ссылается не на источник утверждения")
                            else:
                                # Metadata text is editorial; only the supplied original excerpts count.
                                quotes = ([q.get("text", "") for q in source.provenance.get("quotes", [])]
                                          if source.provenance else [source.text])
                                normalized = " ".join(basis.source_quote.split())
                                if not normalized or not any(normalized in " ".join(q.split()) for q in quotes):
                                    errors.append(prefix + "цитата опровержения отсутствует в выдержках источника")
                            if not basis.explanation.strip():
                                errors.append(prefix + "нужно объяснить несовместимость утверждений")
                    elif basis is not None:
                        errors.append(prefix + "основание опровержения несовместимо с document_relation")
                if claim.status in {"supported", "contradicted"} and not claim.source_ids:
                    errors.append(prefix + "подтверждённое внешнее утверждение требует источника")
                if claim.status in {"supported", "contradicted"}:
                    relation = "supports" if claim.status == "supported" else "contradicts"
                    if claim.document_relation is not None and claim.document_relation != relation:
                        errors.append(prefix + "статус утверждения расходится с отношением к документу")
                    for source in knowledge.sources:
                        if source.id in claim.source_ids and (strict_sources or source.provenance
                                                             or claim.status == "contradicted"):
                            from .knowledge import applicability_errors
                            errors.extend(prefix + e for e in applicability_errors(source, knowledge, dialogue))
                if claim.status == "unverified":
                    unverified_claims.append(claim)
                    if not claim.limitation or not claim.limitation.strip():
                        errors.append(prefix + "непроверенное утверждение требует ограничения")
                    elif claim.limitation not in value.limitations:
                        errors.append(prefix + "ограничение утверждения должно сохраняться в limitations")
            contradicted = any(c.status == "contradicted" for c in review.external_claims)
            expected_status = ("unverified" if unverified_claims else "contradicted" if contradicted
                               else "supported" if review.external_claims else "not_needed")
            if value.knowledge_status != expected_status:
                errors.append(prefix + "knowledge_status не соответствует проверке утверждений")
            if set(value.source_ids) != referenced_sources:
                errors.append(prefix + "source_ids не совпадают с источниками утверждений")
            if not review.coverage.strip():
                errors.append(prefix + "нужно описать покрытие запроса отдельно от проверки фактов")
        elif criterion.requires_company_knowledge and value.answer != "na":
            # Conservative legacy policy: old saved records retain their original meaning.
            if value.knowledge_status == "not_needed":
                errors.append(prefix + "not_needed требует явного knowledge_review без внешних утверждений")
            if not knowledge.sources and value.knowledge_status != "unverified":
                errors.append(prefix + "без источников компании требуется unverified")
        if (review is None and value.knowledge_status in {"supported", "contradicted"}
                and (strict_sources or value.knowledge_status == "contradicted"
                     or any(s.provenance for s in knowledge.sources))):
            errors.append(prefix + "для проверки применимости утверждений требуется knowledge_review")
        if value.knowledge_status == "unverified" and not value.limitations:
            errors.append(prefix + "укажи ограничение непроверенных фактов")
        if (require_operator_flag_evidence and criterion.kind == "flag" and value.answer == criterion.violation_value
                and (criterion.flag_evidence_mode == "operator_action" or legacy_operator_flags)):
            supported_range = any(e.kind != "missing_action" and e.start_message_id in positions
                and e.end_message_id in positions and any(m.speaker == "operator" for m in dialogue.transcript[
                    positions[e.start_message_id]:positions[e.end_message_id]+1]) for e in value.evidence)
            if not supported_range:
                errors.append(prefix + "положительный флаг требует участка с действием оператора")
        for evidence in value.evidence:
            start, end = evidence.start_message_id, evidence.end_message_id
            if start not in messages or end not in messages:
                errors.append(prefix + "несуществующая ссылка на сообщение")
                continue
            if positions[start] > positions[end]:
                errors.append(prefix + "начало диапазона позже конца")
            if evidence.kind == "quote":
                if start != end or not evidence.quote or evidence.quote not in messages[start].text:
                    errors.append(prefix + "цитата должна точно встречаться в одном указанном сообщении")
                if evidence.expected_action is not None:
                    errors.append(prefix + "quote не содержит expected_action")
            elif evidence.quote is not None:
                errors.append(prefix + "для диапазона/пропуска quote должен быть null")
            if evidence.kind == "missing_action":
                if not evidence.expected_action or not evidence.expected_action.strip():
                    errors.append(prefix + "для пропуска требуется expected_action")
            elif evidence.expected_action is not None:
                errors.append(prefix + "expected_action только для missing_action")
    if errors:
        raise AssessmentError(errors)
