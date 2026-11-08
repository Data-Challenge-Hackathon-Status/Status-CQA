"""Preflight context accounting; never truncates messages or source conditions."""
from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from pathlib import Path

from .contracts import Settings
from .io import json_text


@lru_cache(maxsize=4)
def _tokenizer(path, sha256, mtime_ns):
    from tokenizers import Tokenizer
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("Контрольная сумма токенизатора не совпала")
    tokenizer = Tokenizer.from_str(raw.decode("utf-8"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def context_report(request: dict, settings: Settings) -> dict:
    size = len(json_text(request).encode("utf-8"))
    result = {"request_bytes": size, "byte_limit": settings.max_input_bytes,
              "fits": size <= settings.max_input_bytes, "exact_server_token_count": False}
    if settings.provider != "ollama":
        return result
    texts = [m["role"] + "\n" + m["content"] for m in request["messages"]]
    if settings.context_tokenizer_path:
        path = Path(settings.context_tokenizer_path).resolve()
        tokenizer = _tokenizer(str(path), settings.context_tokenizer_sha256, path.stat().st_mtime_ns)
        content_count = sum(len(tokenizer.encode(t, add_special_tokens=False).ids) for t in texts)
        method = "official_qwen_content_tokenizer_plus_10_percent_and_template_margin"
        estimate = math.ceil(content_count * 1.1) + 512
    else:
        # Conservative byte-based fallback, explicitly not an exact tokenizer count.
        content_count = None
        estimate = sum(len(t.encode("utf-8")) for t in texts) + 512
        method = "utf8_byte_bound_plus_template_margin"
    output = request["options"]["num_predict"]
    safety = settings.context_safety_tokens or 1024
    needed = estimate + output + safety
    result.update(method=method, content_tokens=content_count, estimated_input_tokens=estimate,
                  tokenizer_sha256=settings.context_tokenizer_sha256, output_reserve=output,
                  output_includes_thinking_and_answer=True, safety_tokens=safety,
                  context_limit=request["options"]["num_ctx"], estimated_total=needed,
                  fits=result["fits"] and needed <= request["options"]["num_ctx"],
                  limitation="Это оценка: сервер использует свой шаблон и GGUF-токенизатор. Обрезание запрещено.")
    return result


def fit_knowledge(dialogue, checklist, knowledge, settings):
    """Remove whole lowest-ranked excerpts only, and record every exclusion."""
    from .prompting import build_input, response_schema
    from .provider import build_request
    selected = knowledge.model_copy(deep=True)
    while True:
        request = build_request(settings, build_input(dialogue, checklist, selected),
                                response_schema(checklist, selected, dialogue), settings.max_output_tokens)
        report = context_report(request, settings)
        if report["fits"]:
            return selected, report
        if not selected.sources:
            raise ValueError("Диалог с инструкциями, схемой и резервом не помещается; ничего не обрезано")
        removed = selected.sources.pop()
        if selected.selection is None:
            selected.selection = {"excluded": []}
        selected.selection.setdefault("excluded", []).append({"id": removed.id, "reason": "context_budget"})
        selected.selection["selected_ids"] = [s.id for s in selected.sources]
