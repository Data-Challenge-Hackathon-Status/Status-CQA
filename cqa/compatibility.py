"""An explicit, narrow bridge for technical policy changes, never a hash bypass."""
from copy import deepcopy

from .contracts import Checklist
from .io import fingerprint


def assert_compatible(original: Checklist, candidate: Checklist, mapping: dict | None) -> dict:
    old_hash, new_hash = fingerprint(original), fingerprint(candidate)
    if old_hash == new_hash:
        return {"kind": "identical", "original_hash": old_hash, "candidate_hash": new_hash}
    if not mapping or mapping.get("kind") != "technical_fact_status_only":
        raise ValueError("Другой чек-лист: нужна явная карта совместимости технической политики")
    if mapping.get("original_hash") != old_hash or mapping.get("candidate_hash") != new_hash:
        raise ValueError("Карта совместимости не разрешает эти точные хеши")
    before = Checklist.model_validate(mapping["original_snapshot"])
    after = Checklist.model_validate(mapping["candidate_snapshot"])
    if fingerprint(before) != old_hash or fingerprint(after) != new_hash:
        raise ValueError("Снимки карты совместимости изменены")
    a, b = deepcopy(before.model_dump(mode="json")), deepcopy(after.model_dump(mode="json"))
    b["version"] = a["version"]
    if mapping["criterion_id"] != "c4":
        raise ValueError("Эта карта разрешает только техническую политику c4")
    for left, right in zip(a["criteria"], b["criteria"], strict=True):
        if left["id"] == mapping["criterion_id"]:
            old_suffix, new_suffix = mapping["old_policy_suffix"], mapping["new_policy_suffix"]
            if (not old_suffix.startswith("При отсутствии проверенных материалов")
                    or not new_suffix.startswith("Проверяемость фактов отмечается отдельно")):
                raise ValueError("Нельзя объявить содержательное правило техническим суффиксом")
            if not left["rule"].endswith(old_suffix) or not right["rule"].endswith(new_suffix):
                raise ValueError("Изменение не совпадает с заявленным техническим суффиксом")
            left["rule"] = left["rule"][:-len(old_suffix)]
            right["rule"] = right["rule"][:-len(new_suffix)]
    if a != b or not mapping.get("rationale"):
        raise ValueError("Изменены правила оценки, а не только техническая политика")
    return {"kind": mapping["kind"], "mapping_id": mapping["id"], "mapping_hash": fingerprint(mapping),
            "original_hash": old_hash, "candidate_hash": new_hash}
