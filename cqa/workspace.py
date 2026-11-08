"""Local product workflows. Model policies and original evaluations stay untouched."""
from __future__ import annotations

import copy
import json
from uuid import uuid4

from .appeals import record_workspace_decision
from .contracts import Checklist
from .io import fingerprint, json_text
from .scoring import calculate_answers
from .storage import Store, utc_now
from .submission import DEFAULT_MAPPING, Submission, SubmissionSettings, validate_submission
from .workspace_compare import assessment_comparison, checklist_comparison


class Workspace:
    def __init__(self, store: Store):
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ui_results
                  (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ui_appeals
                  (id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL, criterion_id TEXT NOT NULL,
                   status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS ui_one_pending_appeal
                  ON ui_appeals(evaluation_id, criterion_id) WHERE status='pending';
                CREATE TABLE IF NOT EXISTS ui_jobs
                  (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ui_preferences (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)
            # Versions of the standalone UI kept reviewer decisions only in ui_appeals.
            # Preserve their original IDs/dates and append eligible native reviews once.
            db.execute('BEGIN IMMEDIATE')
            old_reviews = [json.loads(row[0]) for row in db.execute("""
                SELECT u.payload FROM ui_appeals u JOIN evaluations e ON e.id=u.evaluation_id
                WHERE u.status='resolved' AND NOT EXISTS (SELECT 1 FROM appeals a WHERE a.id=u.id)
            """)]
            for appeal in self.resolution_order(old_reviews):
                try:
                    self.record_native_review(db, appeal)
                except (KeyError, ValueError) as exc:
                    raise ValueError(f"Не удалось перенести решение {appeal['id']} для оценки "
                                     f"{appeal['evaluation_id']}: {exc}") from exc
                db.execute("UPDATE ui_appeals SET payload=? WHERE id=?", (json_text(appeal), appeal['id']))

    def preference(self, key, default=None):
        with self.store.connection() as db:
            row = db.execute("SELECT payload FROM ui_preferences WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_preference(self, key, value):
        with self.store.connection() as db:
            db.execute("INSERT INTO ui_preferences VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload",
                       (key, json_text(value)))

    def save_result(self, result):
        with self.store.connection() as db:
            db.execute("INSERT INTO ui_results VALUES (?,?,?)", (
                result['evaluation_id'], result['conversation_id'], json_text(result)))

    def seed_baseline(self, payload, checklist: Checklist):
        """Import a validated, identified submission; never pretend it is a fresh inference."""
        submission = Submission.model_validate(payload)
        records = {d.conversation_id: d for d in self.store.list_dialogues()}
        selected = [records[r.conversation_id] for r in submission.results]
        dataset = 'dev' if len(selected) == 65 else 'prod'
        config = SubmissionSettings(team_name=submission.team_name)
        validate_submission(payload, selected, dataset, checklist, config)
        batch_hash = fingerprint(payload)
        if self.preference('baseline:' + batch_hash):
            return
        reverse = {v: k for k, v in DEFAULT_MAPPING.items()}
        for record in submission.results:
            r = record.model_dump(mode='json')
            decisions = {}
            if r['status'] == 'ok':
                for item in r['criteria']:
                    key = reverse[item['criterion_id']]
                    criterion = next(c for c in checklist.criteria if c.id == key)
                    value = item['value']
                    answer = ('na' if value is None else ('yes' if value else 'no')
                              if type(value) is bool else str(value))
                    decisions[key] = {
                        'answer': answer, 'reason': item['rationale'],
                        'na_condition_id': criterion.na_conditions[0].id if answer == 'na' else None,
                        'evidence_turns': item['evidence_turns'], 'knowledge_status': None,
                        'limitations': [], 'source_ids': [],
                    }
            result = {
                'evaluation_id': 'baseline-' + batch_hash[:12] + '-' + r['conversation_id'],
                'conversation_id': r['conversation_id'], 'created_at': utc_now(),
                'status': 'completed' if r['status'] == 'ok' else 'failed',
                'origin': 'baseline', 'source_hash': batch_hash,
                'checklist': checklist.model_dump(mode='json'),
                'model': submission.model.model_dump(mode='json'),
                'decisions': decisions, 'error': r.get('error'), 'limitations': [],
                'elapsed_seconds': None, 'estimated_cost_usd': None, 'needs_review': False,
            }
            with self.store.connection() as db:
                db.execute('INSERT OR IGNORE INTO ui_results VALUES (?,?,?)', (
                    result['evaluation_id'], result['conversation_id'], json_text(result)))
        self.set_preference('baseline:' + batch_hash, True)

    @staticmethod
    def native_decisions(dialogue, criteria):
        indexes = {m['id']: i + 1 for i, m in enumerate(dialogue['transcript'])}
        decisions = {}
        for key, decision in criteria.items():
            turns = set()
            for evidence in decision['evidence']:
                start = indexes.get(evidence['start_message_id'])
                end = indexes.get(evidence['end_message_id'])
                if start and end:
                    turns.update(range(start, end + 1))
            decisions[key] = {**decision, 'evidence_turns': sorted(turns)}
        return decisions

    def native_result(self, raw):
        decisions = self.native_decisions(raw['dialogue'], (raw.get('assessment') or {}).get('criteria', {}))
        settings = raw['settings']
        return {
            'evaluation_id': raw['evaluation_id'], 'conversation_id': raw['conversation_id'],
            'created_at': raw['created_at'], 'status': raw['status'], 'origin': 'model',
            'checklist': raw['checklist'],
            # The first engine used only the external API, before provider was stored.
            'model': {'mode': 'local' if settings.get('provider', 'openai') == 'ollama' else 'external_api',
                      'name': settings['model']},
            'decisions': decisions, 'error': raw.get('error'), 'limitations': raw.get('limitations', []),
            'elapsed_seconds': raw.get('elapsed_seconds'), 'estimated_cost_usd': raw.get('estimated_cost_usd'),
            'needs_review': raw.get('needs_review', False), 'prompt_version': raw.get('prompt_version'),
            'knowledge_sources': (raw.get('knowledge') or {}).get('sources', []),
        }

    def results(self):
        with self.store.connection() as db:
            result = [json.loads(r[0]) for r in db.execute('SELECT payload FROM ui_results')]
        result += [self.native_result(r) for r in self.store.list_evaluations()]
        # A baseline timestamp records import time, not when its judgments were made.
        return sorted(result, key=lambda r: (r['origin'] != 'baseline', r['created_at']), reverse=True)

    def result(self, evaluation_id):
        with self.store.connection() as db:
            row = db.execute('SELECT payload FROM ui_results WHERE id=?', (evaluation_id,)).fetchone()
        return json.loads(row[0]) if row else self.native_result(self.store.get_evaluation(evaluation_id))

    def appeals(self):
        with self.store.connection() as db:
            rows = self.review_rows(db)
        return sorted(rows, key=lambda a: a['created_at'], reverse=True)

    def review_rows(self, db, evaluation_id=None):
        clause = '' if evaluation_id is None else ' WHERE evaluation_id=?'
        args = () if evaluation_id is None else (evaluation_id,)
        rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM ui_appeals' + clause, args)]
        # Product proposals can change several criteria and their original evidence at once.
        # Show the accepted revision as individual review cards sharing the same before/after snapshot.
        query = """
            SELECT a.payload, e.payload, r.payload, previous.payload
            FROM appeals a JOIN evaluations e ON e.id=a.evaluation_id
            JOIN final_revisions r ON r.evaluation_id=e.id AND r.revision=json_extract(a.payload,'$.resolution.final_revision')
            LEFT JOIN final_revisions previous ON previous.evaluation_id=e.id AND previous.revision=r.revision-1
            WHERE a.status='accepted' AND NOT EXISTS(SELECT 1 FROM ui_appeals u WHERE u.id=a.id)
        """
        if evaluation_id is not None:
            query += ' AND a.evaluation_id=?'
        for proposal, evaluation, revision, previous in db.execute(query, args):
            item, source, final = map(json.loads, (proposal, evaluation, revision))
            previous = json.loads(previous) if previous else source
            before = {'decisions': self.native_decisions(source['dialogue'], previous['assessment']['criteria']),
                      'scoring': previous['scoring']}
            after = {'decisions': self.native_decisions(source['dialogue'], final['assessment']['criteria']),
                     'scoring': final['scoring']}
            for key in item['changes']:
                old, new = before['decisions'][key], after['decisions'][key]
                card_id = item['appeal_id'] if len(item['changes']) == 1 else item['appeal_id'] + ':' + key
                rows.append({'id': card_id, 'evaluation_id': item['evaluation_id'], 'criterion_id': key,
                             'conversation_id': source['conversation_id'], 'checklist_version': source['checklist']['version'],
                             'checklist_id': source['checklist']['id'], 'comment': item['reason'],
                             'actor': item['reviewer'], 'created_at': item['created_at'], 'status': 'resolved',
                             'original_answer': old['answer'], 'original_reason': old['reason'],
                             'original_na_condition_id': old.get('na_condition_id'), 'answer': new['answer'],
                             'na_condition_id': new.get('na_condition_id'), 'resolved_decision': new,
                             'resolution': final['reason'], 'reviewer': final['reviewer'],
                             'resolved_at': final['created_at'], 'resolution_sequence': final['revision'],
                             'comparison': {'before': before, 'after': after}})
        return rows

    def effective_result(self, result, appeals=None):
        result = copy.deepcopy(result)
        result['original_decisions'] = copy.deepcopy(result['decisions'])
        related = [a for a in (self.appeals() if appeals is None else appeals)
                   if a['evaluation_id'] == result['evaluation_id']]
        result['appeals'] = related
        if result['status'] not in {'completed', 'provisional'}:
            result['scoring'] = result['original_scoring'] = None
            return result
        checklist = Checklist.model_validate(result['checklist'])

        def score(decisions):
            return calculate_answers({k: d['answer'] for k, d in decisions.items()}, checklist,
                                     {k: d.get('na_condition_id') for k, d in decisions.items()})

        result['original_scoring'] = score(result['decisions'])
        for appeal in self.resolution_order(related):
            if appeal['status'] == 'resolved':
                decision = result['decisions'][appeal['criterion_id']]
                decision.update(appeal.get('resolved_decision') or {
                    'answer': appeal['answer'], 'na_condition_id': appeal['na_condition_id'], 'reason': appeal['resolution']})
                decision['reviewed_by'] = appeal['reviewer']
        result['scoring'] = score(result['decisions'])
        result['reviewed'] = any(a['status'] == 'resolved' for a in related)
        return result

    @staticmethod
    def resolution_order(appeals):
        # Legacy decisions precede newly sequenced ones. New decisions are
        # sequenced within the same SQLite transaction as their audit snapshots.
        return sorted(appeals, key=lambda a: (a.get('resolution_sequence', 0),
                                             a.get('resolved_at', ''), a['id']))

    @staticmethod
    def assessment_snapshot(result):
        return copy.deepcopy({'decisions': result['decisions'], 'scoring': result['scoring']})

    def record_native_review(self, db, appeal):
        revision, decision = record_workspace_decision(db, appeal)
        dialogue = self.store.get_dialogue(appeal['conversation_id'])
        key = appeal['criterion_id']
        appeal['resolution_sequence'] = revision
        appeal['resolved_decision'] = self.native_decisions(dialogue.model_dump(mode='json'), {key: decision})[key]
        if appeal.get('comparison'):
            appeal['comparison']['after']['decisions'][key].update(appeal['resolved_decision'])

    def review_comparison(self, evaluation_id, appeal_id=None):
        source = self.result(evaluation_id)
        if source['status'] not in {'completed', 'provisional'}:
            raise ValueError('Для сравнения нужна завершённая оценка')
        related = [a for a in self.appeals() if a['evaluation_id'] == evaluation_id]
        resolved = [a for a in self.resolution_order(related) if a['status'] == 'resolved']
        selected = next((a for a in related if a['id'] == appeal_id), None)
        if appeal_id and selected is None:
            raise KeyError('Апелляция не относится к этой оценке')
        original = self.effective_result(source, appeals=[])
        basis = 'original_to_current'
        if selected and selected['status'] == 'resolved':
            if selected.get('comparison'):
                before, after = selected['comparison']['before'], selected['comparison']['after']
                basis = 'recorded'
            else:
                index = next(i for i, a in enumerate(resolved) if a['id'] == appeal_id)
                before = self.assessment_snapshot(self.effective_result(source, appeals=resolved[:index]))
                after = self.assessment_snapshot(self.effective_result(source, appeals=resolved[:index + 1]))
                basis = 'reconstructed'
        elif selected:
            before = self.assessment_snapshot(self.effective_result(source, appeals=resolved))
            after, basis = None, 'pending'
        else:
            before = self.assessment_snapshot(original)
            after = self.assessment_snapshot(self.effective_result(source, appeals=resolved)) if resolved else None
        return {**assessment_comparison(source['checklist'], before, after),
                'evaluation_id': evaluation_id, 'conversation_id': source['conversation_id'],
                'checklist': {'id': source['checklist']['id'], 'version': source['checklist']['version']},
                'basis': basis, 'appeal': selected, 'appeals': related,
                'pending_count': sum(a['status'] == 'pending' for a in related),
                'resolved_count': len(resolved)}

    def compare_checklists(self, before, after):
        comparison = checklist_comparison(before, after)
        latest = {}
        for result in self.results():
            if result['status'] != 'running':
                latest.setdefault(result['conversation_id'], result)
        impact = {key: 0 for key in ('current', 'recalculate', 'reanalyze', 'unrated', 'failed')}
        cache = {}
        for dialogue in self.store.list_dialogues():
            result = latest.get(dialogue.conversation_id)
            if result is None:
                impact['unrated'] += 1
            elif result['status'] not in {'completed', 'provisional'}:
                impact['failed'] += 1
            elif result['checklist'] == after.model_dump(mode='json'):
                impact['current'] += 1
            else:
                key = fingerprint(result['checklist'])
                if key not in cache:
                    cache[key] = checklist_comparison(Checklist.model_validate(result['checklist']), after)['can_reweight']
                impact['recalculate' if cache[key] else 'reanalyze'] += 1
        return {**comparison, 'impact': impact}

    def create_appeal(self, evaluation_id, criterion_id, comment, actor):
        result = self.effective_result(self.result(evaluation_id))
        if result['status'] not in {'completed', 'provisional'} or criterion_id not in result['decisions']:
            raise ValueError('Можно оспорить только критерий завершённой оценки')
        if not comment.strip() or len(comment) > 5000:
            raise ValueError('Добавьте аргумент апелляции (до 5000 символов)')
        appeal = {
            'id': str(uuid4()), 'evaluation_id': evaluation_id, 'criterion_id': criterion_id,
            'conversation_id': result['conversation_id'], 'checklist_version': result['checklist']['version'],
            'checklist_id': result['checklist']['id'],
            'comment': comment.strip(), 'actor': actor, 'created_at': utc_now(), 'status': 'pending',
            'original_answer': result['decisions'][criterion_id]['answer'],
            'original_reason': result['decisions'][criterion_id]['reason'],
            'original_na_condition_id': result['decisions'][criterion_id].get('na_condition_id'),
        }
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute("SELECT id FROM ui_appeals WHERE evaluation_id=? AND criterion_id=? AND status='pending'",
                                  (evaluation_id, criterion_id)).fetchone()
            if existing:
                raise ValueError('По этому критерию уже есть открытая апелляция')
            db.execute('INSERT INTO ui_appeals VALUES (?,?,?,?,?)',
                       (appeal['id'], evaluation_id, criterion_id, 'pending', json_text(appeal)))
        return appeal

    def resolve_appeal(self, appeal_id, answer, condition, reason, reviewer):
        if not reason.strip() or len(reason) > 5000:
            raise ValueError('Укажите основание решения (до 5000 символов)')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM ui_appeals WHERE id=?', (appeal_id,)).fetchone()
            if row is None:
                raise KeyError('Апелляция не найдена')
            appeal = json.loads(row[0])
            if appeal['status'] != 'pending':
                raise ValueError('Решение уже сохранено. Обновите страницу')
            related = self.review_rows(db, appeal['evaluation_id'])
            result = self.effective_result(self.result(appeal['evaluation_id']), related)
            before = self.assessment_snapshot(result)
            criterion = next(c for c in result['checklist']['criteria'] if c['id'] == appeal['criterion_id'])
            dialogue = self.store.get_dialogue(result['conversation_id'])
            if answer == 'na' and not any(c['id'] == condition and
                    (not c.get('channels') or dialogue.channel in c['channels']) for c in criterion['na_conditions']):
                raise ValueError('N/A не разрешён для этого критерия и канала')
            condition = condition if answer == 'na' else None
            result['decisions'][appeal['criterion_id']].update(
                answer=answer, na_condition_id=condition, reason=reason.strip(), reviewed_by=reviewer)
            checklist = Checklist.model_validate(result['checklist'])
            result['scoring'] = calculate_answers({k: d['answer'] for k, d in result['decisions'].items()}, checklist,
                               {k: d.get('na_condition_id') for k, d in result['decisions'].items()})
            appeal.update(status='resolved', answer=answer, na_condition_id=condition,
                          resolution=reason.strip(), reviewer=reviewer, resolved_at=utc_now(),
                          resolution_sequence=max((a.get('resolution_sequence', 0) for a in related), default=0) + 1,
                          comparison={'before': before, 'after': self.assessment_snapshot(result)})
            if db.execute('SELECT 1 FROM evaluations WHERE id=?', (appeal['evaluation_id'],)).fetchone():
                self.record_native_review(db, appeal)
            db.execute("UPDATE ui_appeals SET status='resolved', payload=? WHERE id=?", (json_text(appeal), appeal_id))
        return appeal

    def reweight(self, evaluation_id, checklist):
        source = self.result(evaluation_id)
        if source['status'] not in {'completed', 'provisional'}:
            raise ValueError('Для пересчёта нужен завершённый результат')
        old = Checklist.model_validate(source['checklist'])
        if not checklist_comparison(old, checklist)['can_reweight']:
            raise ValueError('Изменились правила, типы или критерии. Запустите новый анализ')
        self.store.save_checklist(checklist)
        result = copy.deepcopy(source)
        # Reweight original model answers; human decisions remain tied to their original evaluation.
        result.update(evaluation_id=str(uuid4()), created_at=utc_now(), origin='recalculated',
                      derived_from=evaluation_id, checklist=checklist.model_dump(mode='json'))
        result['limitations'] = [*result.get('limitations', []),
            'Пересчитаны исходные ответы. Решения по апелляциям хранятся в первоначальной оценке.']
        self.save_result(result)
        return self.effective_result(result)

    def export_submission(self, results, dataset, team_name):
        if not results:
            raise ValueError('Нет результатов для выгрузки')
        if len({fingerprint(r['checklist']) for r in results}) != 1:
            raise ValueError('Выгрузка требует одной версии чек-листа для всех выбранных диалогов')
        checklist = Checklist.model_validate(results[0]['checklist'])
        entries = []
        names = sorted({r['model']['name'] for r in results})
        modes = {r['model']['mode'] for r in results}
        for result in results:
            if result['status'] not in {'completed', 'provisional'}:
                entries.append({'conversation_id': result['conversation_id'], 'status': 'error',
                                'criteria': [], 'score': None, 'error': result.get('error') or 'Оценка не завершена'})
                continue
            # Submission contains original model answers, not silent human replacements.
            result = self.effective_result(result, appeals=[])
            if result['scoring']['total_score'] is None:
                raise ValueError('Нет применимых критериев с положительным весом для JSON 1.0')
            criteria = []
            for c in checklist.criteria:
                if c.id not in DEFAULT_MAPPING:
                    raise ValueError('Пользовательские критерии выгружаются в рабочий отчёт, не в JSON 1.0')
                d = result['decisions'][c.id]
                value = None if d['answer'] == 'na' else (d['answer'] == 'yes') if c.kind != 'scale' else int(d['answer'])
                criteria.append({'criterion_id': DEFAULT_MAPPING[c.id], 'value': value,
                                 'rationale': d['reason'], 'evidence_turns': d['evidence_turns']})
            entries.append({'conversation_id': result['conversation_id'], 'status': 'ok', 'criteria': criteria,
                            'score': {'final_score': float(result['scoring']['total_score']),
                                      'critical_flag': result['scoring']['gross_violation']}})
        payload = {'schema_version': '1.0', 'team_name': team_name,
                   'model': {'mode': next(iter(modes)) if len(modes) == 1 else 'hybrid', 'name': ', '.join(names)},
                   'results': entries}
        dialogues = [self.store.get_dialogue(r['conversation_id']) for r in results]
        return validate_submission(payload, dialogues, dataset, checklist, SubmissionSettings(team_name=team_name))
