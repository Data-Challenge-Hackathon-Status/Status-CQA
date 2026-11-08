from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def text_report(result: dict) -> str:
    labels = {"yes": "Да", "no": "Нет", "na": "N/A"}
    lines = ["FREEDOM CQA — ОЦЕНКА ДИАЛОГА", "",
             f"Диалог: {result['conversation_id']}", f"Запуск: {result['evaluation_id']}",
             f"Чек-лист: {result['checklist']['id']} / {result['checklist']['version']}",
             f"Модель: {result['settings']['model']}", f"Статус: {result['status']}"]
    if not result.get("scoring"):
        return "\n".join(lines + [f"Оценка не завершена: {result['error']}", "Итог не рассчитан."]) + "\n"
    score = result["scoring"]
    lines += [f"Итог: {score['total_score']} / {score['total_max']}",
              "Грубое нарушение: " + ("обнаружено" if score["gross_violation"] else "не обнаружено")]
    if result.get("billing_mode") == "external_compute":
        lines += ["Стоимость: аренда сервера и хранение оплачиваются отдельно в Brev; по токенам не рассчитана.",
                  "Лимит запросов программы не останавливает арендованный сервер."]
    else:
        lines += [f"Стоимость по полученным данным usage: ${result['estimated_cost_usd']}"]
    if result["billing_uncertain"] and result.get("billing_mode") != "external_compute":
        lines += ["У части попыток расход неизвестен; в локальном бюджете сохранён резерв."]
    if result["needs_review"]:
        lines += ["", "ПРЕДВАРИТЕЛЬНО: продуктовые факты не полностью проверены по материалам компании."]
    if result["limitations"]:
        lines += ["", "Ограничения:"] + ["- " + x for x in result["limitations"]]
    messages = {m["id"]: m for m in result["dialogue"]["transcript"]}
    for row in score["criteria"]:
        decision = result["assessment"]["criteria"][row["criterion_id"]]
        points = (str(Decimal(row["points"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                  if row["points"] is not None else "—")
        lines += ["", f"{row['criterion_id']}. {row['title']}",
                  f"Ответ: {labels.get(row['answer'], row['answer'])}; вклад после N/A: {points}",
                  f"Обоснование: {decision['reason']}"]
        if decision["na_condition_id"]:
            lines += ["Условие N/A: " + decision["na_condition_id"]]
        if review := decision.get("knowledge_review"):
            lines += ["Покрытие запроса: " + review["coverage"]]
            lines += ["Проверяемость фактов: " + decision["knowledge_status"]]
            for fact in review["observed_facts"]:
                lines += ["Наблюдение в этом диалоге: " + fact["statement"]
                          + " [" + ", ".join(fact["message_ids"]) + "]"]
            for claim in review["external_claims"]:
                lines += ["Внешнее утверждение (" + claim["status"] + "): " + claim["statement"]]
                if claim.get("document_relation"):
                    lines += ["Отношение к тексту документа: " + claim["document_relation"]]
                if basis := claim.get("contradiction_basis"):
                    lines += [f"Основание опровержения ({basis['kind']}, {basis['source_id']}): «{basis['source_quote']}»",
                              "Несовместимость: " + basis["explanation"]]
                if claim.get("source_ids"):
                    lines += ["Источники: " + ", ".join(claim["source_ids"])]
                if claim["limitation"]:
                    lines += ["Ограничение проверки: " + claim["limitation"]]
            for source in result.get("knowledge", {}).get("sources", []):
                if source["id"] not in decision.get("source_ids", []):
                    continue
                provenance = source.get("provenance") or {}
                pages = ", ".join(str(q["pdf_page"]) for q in provenance.get("quotes", []))
                lines += [f"Источник {source['id']}: {source['title']}; PDF-страницы: {pages or 'не указаны'}",
                          "Юрлицо: " + str(provenance.get("legal_entity") or "не подтверждено"),
                          "Начало действия: " + str(provenance.get("effective_from") or "не подтверждено")]
                if provenance.get("source_url"):
                    lines += ["Сохранённый адрес: " + provenance["source_url"]]
        for evidence in decision["evidence"]:
            start, end = messages[evidence["start_message_id"]], messages[evidence["end_message_id"]]
            lines += [f"Основание: {start['id']} ({start['timestamp']}) — {end['id']} ({end['timestamp']})"]
            if evidence["quote"]:
                lines += ["Цитата: «" + evidence["quote"] + "»"]
            if evidence["expected_action"]:
                lines += ["Ожидалось: " + evidence["expected_action"]]
    lines += ["", "ИСХОДНЫЙ ДИАЛОГ"]
    for message in result["dialogue"]["transcript"]:
        lines += [f"[{message['id']}] {message['timestamp']} | {message['speaker']} | {message['text']}"]
    return "\n".join(lines) + "\n"
