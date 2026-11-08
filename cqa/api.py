from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .appeals import (
    AppealConflict,
    AppealRequest,
    ResolutionRequest,
    create_appeal,
    final_result,
    list_appeals,
    resolve_appeal,
)
from .contracts import Checklist, Knowledge, Record, Settings
from .engine import Engine, recalculate
from .io import load_dialogues, read_json
from .prompting import PROMPT_VERSION
from .storage import Store


class EvaluationRequest(Record):
    conversation_id: str
    checklist_id: str
    checklist_version: str
    knowledge: Knowledge | None = None


def import_conversations(request: Request, payload: Annotated[dict | list, Body()]):
    try:
        records = load_dialogues(payload)
    except ValidationError as exc:
        error = exc.errors(include_input=False, include_url=False)[0]
        field = ".".join(map(str, error["loc"]))
        if error["type"] == "value_error":
            message = str(error["ctx"]["error"])
        elif error["type"] == "literal_error":
            message = f"Поле {field} допускает значения {error['ctx']['expected']}"
        else:
            message = f"Проверьте поле {field or 'transcript'} в загружаемом диалоге"
        raise HTTPException(422, message) from None
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        added = request.app.state.store.save_dialogues(records)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"imported": len(records), "added_ids": added,
            "conversation_ids": [dialogue.conversation_id for dialogue, _ in records]}


def create_app(db_path="data/cqa.sqlite3", settings_path="config/settings.json",
               checklist_path="config/checklist.claims-v1.json", provider=None, *, interface_path="/"):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(db_path)
        app.state.store.save_checklist(Checklist.model_validate(read_json(checklist_path)))
        yield

    app = FastAPI(title="Freedom CQA — механизм оценки", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.get(interface_path, include_in_schema=False)
    def interface():
        path = Path(__file__).with_name("app.html")
        if not path.exists():
            raise HTTPException(503, "Интерфейс ещё не подготовлен")
        return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "local", "audio_analysis": False,
                "prompt_version": PROMPT_VERSION}

    @app.get("/checklists")
    def list_checklists():
        return app.state.store.list_checklists()

    @app.post("/checklists", status_code=201)
    def save_checklist(value: Checklist):
        try:
            app.state.store.save_checklist(value)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return value

    @app.get("/checklists/{checklist_id}/{version}")
    def get_checklist(checklist_id: str, version: str):
        try:
            return app.state.store.get_checklist(checklist_id, version)
        except KeyError:
            raise HTTPException(404, "Чек-лист не найден") from None

    app.post("/conversations/import")(import_conversations)

    @app.get("/conversations")
    def conversations():
        return [{"conversation_id": d.conversation_id, "language": d.language, "channel": d.channel,
                 "message_count": len(d.transcript)} for d in app.state.store.list_dialogues()]

    @app.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str):
        try:
            return app.state.store.get_dialogue(conversation_id)
        except KeyError:
            raise HTTPException(404, "Диалог не найден") from None

    @app.post("/evaluations")
    def evaluate(value: EvaluationRequest):
        try:
            dialogue = app.state.store.get_dialogue(value.conversation_id)
            checklist = app.state.store.get_checklist(value.checklist_id, value.checklist_version)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        settings = Settings.model_validate(read_json(settings_path))
        return Engine(app.state.store, settings, provider=provider).evaluate(dialogue, checklist, value.knowledge)

    @app.get("/evaluations")
    def evaluations(conversation_id: str | None = None):
        from .cli import summary
        rows = []
        for result in app.state.store.list_evaluations():
            if conversation_id is not None and result["conversation_id"] != conversation_id:
                continue
            row = dict(summary(result), created_at=result["created_at"],
                checklist_id=result["checklist"]["id"], checklist_version=result["checklist"]["version"],
                checklist_hash=result["checklist_hash"], prompt_version=result.get("prompt_version"),
                final_revision=0, final_total_score=None, final_gross_violation=None)
            appeals = list_appeals(app.state.store, result["evaluation_id"])
            row.update(appeal_count=len(appeals), pending_appeals=sum(a["status"] == "pending" for a in appeals))
            if result.get("assessment") and result["status"] in {"completed", "provisional"}:
                try:
                    final = final_result(app.state.store, result["evaluation_id"])
                    row.update(final_revision=final["revision"], final_total_score=final["scoring"]["total_score"],
                               final_gross_violation=final["scoring"]["gross_violation"])
                except ValueError:
                    row["final_error"] = "Сохранённый итог требует проверки целостности"
            rows.append(row)
        return rows

    @app.get("/evaluations/{evaluation_id}")
    def evaluation(evaluation_id: str):
        try:
            return app.state.store.get_evaluation(evaluation_id)
        except KeyError:
            raise HTTPException(404, "Оценка не найдена") from None

    @app.get("/evaluations/{evaluation_id}/recalculate")
    def recalculate_evaluation(evaluation_id: str):
        try:
            return recalculate(app.state.store.get_evaluation(evaluation_id))
        except KeyError:
            raise HTTPException(404, "Оценка не найдена") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    def appeal_action(function, *args):
        try:
            return function(app.state.store, *args)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        except AppealConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/evaluations/{evaluation_id}/final")
    def get_final(evaluation_id: str):
        return appeal_action(final_result, evaluation_id)

    @app.get("/evaluations/{evaluation_id}/appeals")
    def get_appeals(evaluation_id: str):
        return appeal_action(list_appeals, evaluation_id)

    @app.post("/evaluations/{evaluation_id}/appeals", status_code=201)
    def submit_appeal(evaluation_id: str, value: AppealRequest):
        return appeal_action(create_appeal, evaluation_id, value)

    @app.post("/appeals/{appeal_id}/resolve")
    def decide_appeal(appeal_id: str, value: ResolutionRequest):
        return appeal_action(resolve_appeal, appeal_id, value)

    @app.get("/budget")
    def budget():
        return app.state.store.budget_summary()

    return app


app = create_app(db_path=os.environ.get("CQA_DB", "data/cqa.sqlite3"),
    settings_path=os.environ.get("CQA_SETTINGS", "config/settings.json"),
    checklist_path=os.environ.get("CQA_CHECKLIST", "config/checklist.claims-v1.json"))
