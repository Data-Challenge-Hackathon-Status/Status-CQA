from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from .contracts import Dialogue, parse_timestamp


def json_text(value, *, pretty=False) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"), allow_nan=False)


def fingerprint(value) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json_text(value, pretty=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def message_index(dialogue: Dialogue) -> list[dict]:
    """The submission index counts every role; a message ID is never parsed as a number."""
    return [{"message_id": m.id, "submission_turn": i + 1, "speaker": m.speaker, "timestamp": m.timestamp}
            for i, m in enumerate(dialogue.transcript)]


def load_dialogues(payload) -> list[tuple[Dialogue, dict]]:
    if isinstance(payload, dict) and "isSuccess" in payload:
        if payload["isSuccess"] is not True:
            raise ValueError("API организаторов сообщил об ошибке")
        container = payload.get("data")
        if not isinstance(container, dict) or not isinstance(container.get("records"), list):
            raise ValueError("В ответе организаторов ожидается список data.records")
        records = container["records"]
        if container.get("total_records", len(records)) != len(records):
            raise ValueError("total_records не совпадает с фактическим числом записей")
    elif isinstance(payload, list):
        records = payload
    else:
        records = [payload]
    if not records:
        raise ValueError("Набор диалогов пуст")
    result = []
    ids = set()
    for index, raw in enumerate(records, 1):
        if not isinstance(raw, dict):
            raise TypeError(f"Запись №{index} должна содержать объект диалога")
        if not isinstance(raw.get("transcript"), list):
            raise TypeError(f"В записи №{index} поле transcript должно содержать список реплик")
        if not all(isinstance(m, dict) for m in raw["transcript"]):
            raise ValueError(f"В записи №{index} каждая реплика должна быть объектом")
        data = {k: raw.get(k) for k in ("conversation_id", "channel", "language", "audio_url")}
        data["transcript"] = [dict(m, id=m.get("id") or f"m{i + 1}")
                              for i, m in enumerate(raw["transcript"])]
        dialogue = Dialogue.model_validate(data)
        for message in dialogue.transcript:
            parse_timestamp(message.timestamp, dialogue.channel)
        if dialogue.conversation_id in ids:
            raise ValueError("Повтор conversation_id в одном наборе")
        ids.add(dialogue.conversation_id)
        result.append((dialogue, raw))
    return result
