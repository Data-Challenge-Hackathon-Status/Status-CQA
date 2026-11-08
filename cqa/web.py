"""Run the local, buildless CQA workspace: python -m cqa.web --help."""
from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, model_validator

from .api import create_app, import_conversations
from .contracts import Checklist, Knowledge, Record, Settings
from .engine import Engine
from .io import fingerprint, json_text, load_dialogues, read_json
from .storage import utc_now
from .workspace import Workspace
from .workspace_compare import checklist_comparison

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / 'web_assets'
PRODUCT_DB = 'outputs/product-demo/cqa-1.2.1.sqlite3'
PRODUCT_SETTINGS = 'config/settings.product.json'
PRODUCT_CHECKLIST = 'config/checklist.review-v4.1.json'


class AppealRequest(Record):
    evaluation_id: str
    criterion_id: str
    comment: str = Field(min_length=1, max_length=5000)
    actor: str = Field(default='Оператор', min_length=1, max_length=100)


class ResolutionRequest(Record):
    answer: str
    na_condition_id: str | None = None
    reason: str = Field(min_length=1, max_length=5000)
    role: Literal['reviewer']
    reviewer: str = Field(default='Проверяющий', min_length=1, max_length=100)


class JobRequest(Record):
    conversation_ids: list[str] = Field(min_length=1, max_length=100)
    checklist_id: str
    checklist_version: str
    knowledge: Knowledge | None = None


class ReweightRequest(Record):
    evaluation_id: str
    checklist_id: str
    checklist_version: str


class ExportRequest(Record):
    conversation_ids: list[str] = Field(min_length=1, max_length=1000)
    evaluation_ids: dict[str, str] = Field(default_factory=dict)
    format: Literal['report', 'submission'] = 'report'
    dataset: Literal['dev', 'prod'] = 'dev'
    team_name: str = Field(default='Status', min_length=1, max_length=100)


class ChecklistRef(Record):
    id: str
    version: str


class ChecklistCompareRequest(Record):
    before: ChecklistRef
    after: ChecklistRef | None = None
    draft: Checklist | None = None

    @model_validator(mode='after')
    def one_target(self):
        if (self.after is None) == (self.draft is None):
            raise ValueError('Выберите сохранённую версию или черновик')
        return self


def create_web_app(db_path=PRODUCT_DB, settings_path=PRODUCT_SETTINGS,
                   checklist_path=PRODUCT_CHECKLIST, dataset_path=None,
                   baseline_path=None, audio_dir=None, provider=None):
    settings_path, checklist_path = Path(settings_path), Path(checklist_path)
    app = create_app(db_path, settings_path, checklist_path, provider, interface_path='/classic')
    base_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with base_lifespan(app):
            workspace = app.state.workspace = Workspace(app.state.store)
            default = Checklist.model_validate(read_json(checklist_path))
            if workspace.preference('active_checklist') is None:
                workspace.set_preference('active_checklist', {'id': default.id, 'version': default.version})
            if dataset_path:
                app.state.store.save_dialogues(load_dialogues(read_json(dataset_path)))
            if baseline_path:
                baseline_checklist = Checklist.model_validate(read_json(ROOT / 'config/checklist.1.0.0.json'))
                app.state.store.save_checklist(baseline_checklist)
                workspace.seed_baseline(read_json(baseline_path), baseline_checklist)
            # Candidates are available without silently activating a different assessment policy.
            for name in ['checklist.review-v3.json', 'checklist.voice-v1.json']:
                file = ROOT / 'config' / name
                if file.exists():
                    app.state.store.save_checklist(Checklist.model_validate(read_json(file)))
            with app.state.store.connection() as db:
                for row in db.execute("SELECT id,payload FROM ui_jobs WHERE status IN ('queued','running')").fetchall():
                    value = json.loads(row['payload'])
                    value.update(status='interrupted', error='Сервер перезапущен. Запустите оценку повторно.')
                    db.execute('UPDATE ui_jobs SET status=?,payload=? WHERE id=?',
                               ('interrupted', json_text(value), row['id']))
            app.state.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='cqa-ui')
            yield
            app.state.executor.shutdown(wait=False, cancel_futures=True)

    app.router.lifespan_context = lifespan

    @app.middleware('http')
    async def local_safety(request: Request, call_next):
        if request.method in {'POST', 'PUT', 'DELETE', 'PATCH'}:
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': 'Запрос разрешён только из локального интерфейса'}, status_code=403)
            try:
                size = int(request.headers.get('content-length', '0'))
            except ValueError:
                return JSONResponse({'detail': 'Некорректный размер запроса'}, status_code=400)
            if size > 15_000_000:
                return JSONResponse({'detail': 'Максимальный размер JSON — 15 МБ'}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    def workspace():
        return app.state.workspace

    def model_state():
        settings = Settings.model_validate(read_json(settings_path))
        state = {'name': settings.model, 'provider': settings.provider, 'ready': False,
                 'timeout_seconds': settings.timeout_seconds, 'detail': '',
                 'billing': 'Аренда сервера учитывается отдельно' if settings.provider == 'ollama'
                            else 'Стоимость учитывается по использованию API'}
        if provider is not None:
            state.update(ready=True, detail='Провайдер передан приложению')
        elif settings.provider == 'ollama':
            try:
                with httpx.Client(timeout=1.5, trust_env=False) as client:
                    response = client.get(settings.base_url.rstrip('/') + '/api/tags')
                    response.raise_for_status()
                    names = {m.get('name') for m in response.json().get('models', [])}
                    state['ready'] = settings.model in names
                    state['detail'] = 'Модель доступна' if state['ready'] else 'Модель не загружена на сервере'
            except (httpx.HTTPError, ValueError):
                state['detail'] = 'Нет подключения к Ollama. Подключите SSH-туннель из инструкции запуска.'
        else:
            state['ready'] = bool(os.environ.get('OPENAI_API_KEY'))
            state['detail'] = 'Ключ настроен; доступность проверяется при запуске' if state['ready'] else 'Ключ API не настроен на сервере'
        return state

    @app.get('/ui-api/model')
    def model():
        return model_state()

    app.post('/ui-api/import')(import_conversations)

    @app.get('/ui-api/bootstrap')
    def bootstrap():
        ws = workspace()
        appeals = ws.appeals()
        latest = {}
        for result in ws.results():
            if result['conversation_id'] not in latest and result['status'] != 'running':
                latest[result['conversation_id']] = ws.effective_result(result, appeals)
        items = []
        active = ws.preference('active_checklist')
        for dialogue in app.state.store.list_dialogues():
            first = next((m.text for m in dialogue.transcript if m.speaker == 'client'), dialogue.transcript[0].text)
            result = latest.get(dialogue.conversation_id)
            score = result.get('scoring') if result else None
            pending = [a for a in appeals if a['conversation_id'] == dialogue.conversation_id and a['status'] == 'pending']
            items.append({'id': dialogue.conversation_id, 'language': dialogue.language,
                          'channel': dialogue.channel, 'message_count': len(dialogue.transcript), 'preview': first,
                          'evaluation_id': result['evaluation_id'] if result else None,
                          'score': score['total_score'] if score else None,
                          'critical': bool(score and score['gross_violation']),
                          'status': result['status'] if result else 'unrated',
                          'origin': result['origin'] if result else None,
                          'version': result['checklist']['version'] if result else None,
                          'needs_review': bool(result and result.get('needs_review')),
                          'pending_appeals': len(pending),
                          'review_evaluation_id': pending[0]['evaluation_id'] if pending else None,
                          'reviewed': bool(result and result.get('reviewed')),
                          'stale': bool(result and (result['checklist']['id'], result['checklist']['version']) !=
                                        (active['id'], active['version'])),
                          'criteria': score['criteria'] if score else []})
        lists = [app.state.store.get_checklist(x['id'], x['version']).model_dump(mode='json')
                 for x in app.state.store.list_checklists()]
        return {'conversations': items, 'appeals': appeals, 'checklists': lists,
                'active_checklist': active, 'jobs': jobs(), 'budget': app.state.store.budget_summary()}

    @app.get('/ui-api/conversations/{conversation_id}')
    def detail(conversation_id: str, evaluation_id: str | None = None):
        try:
            dialogue = app.state.store.get_dialogue(conversation_id)
            history = [r for r in workspace().results() if r['conversation_id'] == conversation_id]
            result = next((r for r in history if r['evaluation_id'] == evaluation_id), None) if evaluation_id else (
                next((r for r in history if r['status'] != 'running'), None))
            if evaluation_id and result is None:
                raise KeyError('Версия оценки не найдена')
            compatibility = None
            if result:
                active = workspace().preference('active_checklist')
                target = app.state.store.get_checklist(active['id'], active['version'])
                comparison = checklist_comparison(Checklist.model_validate(result['checklist']), target)
                compatibility = {'target': active, 'can_reweight': comparison['can_reweight'], 'mode': comparison['mode']}
            audio = None
            if (audio_dir and re.fullmatch(r'[A-Za-z0-9_-]+', conversation_id)
                    and (Path(audio_dir) / (conversation_id + '.mp3')).is_file()):
                audio = '/ui-api/audio/' + conversation_id
            return {'dialogue': dialogue.model_dump(mode='json'), 'audio': audio,
                    'result': workspace().effective_result(result) if result else None,
                    'compatibility': compatibility,
                    'history': [{'id': r['evaluation_id'], 'created_at': r['created_at'], 'status': r['status'],
                                 'origin': r['origin'], 'version': r['checklist']['version']} for r in history]}
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.get('/ui-api/audio/{conversation_id}')
    def audio(conversation_id: str):
        if not audio_dir or not re.fullmatch(r'[A-Za-z0-9_-]+', conversation_id):
            raise HTTPException(404, 'Запись не найдена')
        path = Path(audio_dir) / (conversation_id + '.mp3')
        if not path.is_file():
            raise HTTPException(404, 'Запись не найдена')
        return FileResponse(path, media_type='audio/mpeg')

    @app.post('/ui-api/appeals', status_code=201)
    def appeal(value: AppealRequest):
        try:
            return workspace().create_appeal(value.evaluation_id, value.criterion_id, value.comment, value.actor)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post('/ui-api/appeals/{appeal_id}/resolve')
    def resolve(appeal_id: str, value: ResolutionRequest):
        try:
            return workspace().resolve_appeal(appeal_id, value.answer, value.na_condition_id, value.reason, value.reviewer)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get('/ui-api/evaluations/{evaluation_id}/review-comparison')
    def review_comparison(evaluation_id: str, appeal_id: str | None = None):
        try:
            return workspace().review_comparison(evaluation_id, appeal_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post('/ui-api/checklists/compare')
    def compare_checklists(value: ChecklistCompareRequest):
        try:
            before = app.state.store.get_checklist(value.before.id, value.before.version)
            after = value.draft or app.state.store.get_checklist(value.after.id, value.after.version)
            return workspace().compare_checklists(before, after)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post('/ui-api/checklists', status_code=201)
    def save_checklist(value: Checklist):
        try:
            app.state.store.save_checklist(value)
            workspace().set_preference('active_checklist', {'id': value.id, 'version': value.version})
            return value
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post('/ui-api/checklists/activate')
    def activate(value: dict):
        try:
            c = app.state.store.get_checklist(value['id'], value['version'])
            workspace().set_preference('active_checklist', {'id': c.id, 'version': c.version})
            return {'id': c.id, 'version': c.version}
        except (KeyError, TypeError):
            raise HTTPException(404, 'Версия чек-листа не найдена') from None

    @app.post('/ui-api/reweight')
    def reweight(value: ReweightRequest):
        try:
            c = app.state.store.get_checklist(value.checklist_id, value.checklist_version)
            return workspace().reweight(value.evaluation_id, c)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    def save_job(job):
        with app.state.store.connection() as db:
            db.execute('UPDATE ui_jobs SET status=?,payload=? WHERE id=?', (job['status'], json_text(job), job['id']))

    def run_job(job, dialogue, checklist, settings, knowledge):
        job.update(status='running', started_at=utc_now())
        save_job(job)
        try:
            result = Engine(app.state.store, settings, provider=provider).evaluate(dialogue, checklist, knowledge)
            job.update(status='completed' if result['status'] in {'completed', 'provisional'} else 'failed',
                       evaluation_id=result['evaluation_id'], error=result.get('error'))
        except Exception as exc:  # noqa: BLE001 -- A worker must persist failure instead of leaving a running job.
            job.update(status='failed', error='Не удалось выполнить анализ: ' + type(exc).__name__)
        job['finished_at'] = utc_now()
        save_job(job)

    @app.get('/ui-api/jobs')
    def jobs():
        with app.state.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM ui_jobs ORDER BY rowid DESC LIMIT 200')]

    @app.post('/ui-api/jobs', status_code=202)
    def queue(value: JobRequest):
        availability = model_state()
        if not availability['ready']:
            raise HTTPException(503, availability['detail'])
        try:
            c = app.state.store.get_checklist(value.checklist_id, value.checklist_version)
            dialogues = [app.state.store.get_dialogue(i) for i in dict.fromkeys(value.conversation_ids)]
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        settings = Settings.model_validate(read_json(settings_path))
        added, todo = [], []
        with app.state.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for dialogue in dialogues:
                key = fingerprint([dialogue.model_dump(mode='json'), c.model_dump(mode='json'),
                                   settings.model_dump(mode='json'), value.knowledge.model_dump(mode='json') if value.knowledge else None])
                existing = [json.loads(r[0]) for r in db.execute(
                    "SELECT payload FROM ui_jobs WHERE conversation_id=? AND status IN ('queued','running')", (dialogue.conversation_id,))]
                match = next((j for j in existing if j['request_hash'] == key), None)
                if match:
                    added.append(match)
                    continue
                job = {'id': str(uuid4()), 'conversation_id': dialogue.conversation_id, 'status': 'queued',
                       'created_at': utc_now(), 'checklist_id': c.id, 'version': c.version,
                       'request_hash': key, 'model': settings.model, 'evaluation_id': None, 'error': None}
                db.execute('INSERT INTO ui_jobs VALUES (?,?,?,?)', (job['id'], dialogue.conversation_id, 'queued', json_text(job)))
                added.append(job)
                todo.append((job, dialogue))
        for job, dialogue in todo:
            app.state.executor.submit(run_job, job, dialogue, c, settings, value.knowledge)
        return {'jobs': added}

    @app.post('/ui-api/export')
    def export(value: ExportRequest):
        latest = {}
        for r in workspace().results():
            if (r['status'] != 'running' and r['conversation_id'] in value.conversation_ids
                    and r['conversation_id'] not in latest):
                latest[r['conversation_id']] = r
        if not set(value.evaluation_ids) <= set(value.conversation_ids):
            raise HTTPException(422, 'Версии оценок должны относиться к выбранным диалогам')
        for cid, eid in value.evaluation_ids.items():
            try:
                result = workspace().result(eid)
            except KeyError:
                raise HTTPException(404, 'Выбранная оценка не найдена') from None
            if result['conversation_id'] != cid or result['status'] == 'running':
                raise HTTPException(422, 'Выбранная оценка не подходит для этого диалога')
            latest[cid] = result
        if set(latest) != set(value.conversation_ids):
            raise HTTPException(422, 'В выбранном наборе есть диалоги без результатов')
        try:
            if value.format == 'submission':
                return workspace().export_submission(list(latest.values()), value.dataset, value.team_name)
            return {'report_version': 'cqa-workspace-1', 'exported_at': utc_now(),
                    'note': 'Рабочий отчёт: исходные оценки, пересмотр и история. Не формат сдачи 1.0.',
                    'results': [workspace().effective_result(r) for r in latest.values()]}
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from None

    app.mount('/assets', StaticFiles(directory=STATIC), name='workspace-assets')

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(STATIC / 'index.html')

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description='Локальное рабочее пространство CQA.')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--db', default=os.environ.get('CQA_DB', PRODUCT_DB))
    parser.add_argument('--settings', default=os.environ.get('CQA_SETTINGS', PRODUCT_SETTINGS))
    parser.add_argument('--checklist', default=os.environ.get('CQA_CHECKLIST', PRODUCT_CHECKLIST))
    parser.add_argument('--dataset', help='Путь к invoke.json; исходный файл не изменяется')
    parser.add_argument('--baseline', help='Путь к сохранённому results/dev/results.json')
    parser.add_argument('--audio-dir', help='Папка с MP3, названными по conversation_id')
    args = parser.parse_args()
    app = create_web_app(args.db, args.settings, args.checklist, args.dataset, args.baseline, args.audio_dir)
    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
