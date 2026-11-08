from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .contracts import Checklist, Dialogue
from .io import fingerprint, json_text


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class BudgetExceeded(ValueError):
    pass


class Store:
    def __init__(self, path: str | Path = "data/cqa.sqlite3"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS checklists (
                id TEXT NOT NULL, version TEXT NOT NULL, hash TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(id,version));
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, hash TEXT NOT NULL, payload TEXT NOT NULL, original TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL,
                charge_ceiling TEXT NOT NULL, actual_cost TEXT, state TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS appeals (
                id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL,
                created_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS appeals_by_evaluation ON appeals(evaluation_id, created_at);
            CREATE TABLE IF NOT EXISTS final_revisions (
                evaluation_id TEXT NOT NULL, revision INTEGER NOT NULL,
                created_at TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(evaluation_id, revision));
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(calls)")}
            if "billing_mode" not in columns:
                db.execute("ALTER TABLE calls ADD COLUMN billing_mode TEXT NOT NULL DEFAULT 'api_tokens'")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def save_checklist(self, checklist: Checklist):
        digest = fingerprint(checklist)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT hash FROM checklists WHERE id=? AND version=?",
                             (checklist.id, checklist.version)).fetchone()
            if row and row["hash"] != digest:
                raise ValueError("Эта версия чек-листа уже сохранена с другим содержимым. Измените version.")
            db.execute("INSERT OR IGNORE INTO checklists VALUES (?,?,?,?)",
                       (checklist.id, checklist.version, digest, json_text(checklist)))

    def get_checklist(self, checklist_id: str, version: str) -> Checklist:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM checklists WHERE id=? AND version=?",
                             (checklist_id, version)).fetchone()
        if not row:
            raise KeyError("Чек-лист не найден")
        return Checklist.model_validate_json(row["payload"])

    def list_checklists(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT id,version,hash FROM checklists ORDER BY id,version")]

    def save_dialogues(self, records: list[tuple[Dialogue, dict]]) -> list[str]:
        added = []
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for dialogue, original in records:
                row = db.execute("SELECT hash FROM conversations WHERE id=?",
                                 (dialogue.conversation_id,)).fetchone()
                digest = fingerprint(dialogue)
                if row and row["hash"] != digest:
                    raise ValueError("conversation_id уже существует с другим содержимым: "
                                     + dialogue.conversation_id)
                if row is None:
                    db.execute("INSERT INTO conversations VALUES (?,?,?,?)",
                               (dialogue.conversation_id, digest, json_text(dialogue), json_text(original)))
                    added.append(dialogue.conversation_id)
        return added

    def get_dialogue(self, conversation_id: str) -> Dialogue:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            raise KeyError("Диалог не найден")
        return Dialogue.model_validate_json(row["payload"])

    def list_dialogues(self):
        with self.connection() as db:
            return [Dialogue.model_validate_json(r["payload"])
                    for r in db.execute("SELECT payload FROM conversations ORDER BY id")]

    def save_evaluation(self, value: dict):
        with self.connection() as db:
            db.execute("INSERT INTO evaluations VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                       (value["evaluation_id"], value["created_at"], json_text(value)))

    def get_evaluation(self, evaluation_id: str):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
        if not row:
            raise KeyError("Результат не найден")
        return json.loads(row["payload"])

    def list_evaluations(self):
        with self.connection() as db:
            return [json.loads(r["payload"]) for r in db.execute(
                "SELECT payload FROM evaluations ORDER BY created_at DESC")]

    def reserve_call(self, evaluation_id: str, amount: Decimal, limit: Decimal | None, request: dict,
                     *, billing_mode="api_tokens", call_limit=None) -> str:
        call_id = str(uuid4())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            used = sum((Decimal(r[0]) for r in db.execute("SELECT charge_ceiling FROM calls")), Decimal(0))
            if billing_mode == "external_compute":
                calls = db.execute("SELECT COUNT(*) FROM calls WHERE billing_mode='external_compute'").fetchone()[0]
                if call_limit is None or calls >= call_limit:
                    raise BudgetExceeded("Лимит запросов к арендованному серверу исчерпан")
            elif limit is None or used + amount > limit:
                raise BudgetExceeded("Локальный бюджет исчерпан: новый запрос не отправлен")
            db.execute("INSERT INTO calls (id,evaluation_id,charge_ceiling,actual_cost,state,payload,billing_mode) "
                       "VALUES (?,?,?,?,?,?,?)",
                       (call_id, evaluation_id, str(amount), None, "reserved", json_text(request), billing_mode))
        return call_id

    def finish_call(self, call_id: str, *, cost: Decimal | None, state: str, payload: dict):
        with self.connection() as db:
            row = db.execute("SELECT charge_ceiling,payload FROM calls WHERE id=?", (call_id,)).fetchone()
            # Unknown network outcomes retain their full reservation: usage may have been billed.
            ceiling = str(cost) if cost is not None else row["charge_ceiling"]
            merged = {"request": json.loads(row["payload"]), **payload}
            db.execute("UPDATE calls SET charge_ceiling=?,actual_cost=?,state=?,payload=? WHERE id=?",
                       (ceiling, str(cost) if cost is not None else None, state, json_text(merged), call_id))

    def budget_summary(self):
        with self.connection() as db:
            all_rows = list(db.execute("SELECT charge_ceiling,actual_cost,state,billing_mode FROM calls"))
        rows = [r for r in all_rows if r["billing_mode"] == "api_tokens"]
        external_calls = len(all_rows) - len(rows)
        return {"accounted_usd": str(sum((Decimal(r["charge_ceiling"]) for r in rows), Decimal(0))),
                "estimated_usage_cost_usd": str(sum((Decimal(r["actual_cost"])
                    for r in rows if r["actual_cost"] is not None), Decimal(0))),
                "calls": len(all_rows), "uncertain_calls": sum(r["actual_cost"] is None for r in rows),
                "external_compute_calls": external_calls, "external_compute_cost_usd": None,
                "external_compute_note": "Аренда и хранение оплачиваются отдельно в Brev; лимит запросов не останавливает сервер."}
