'''统计报表：概览、坐席排行、按日趋势、结果与意向分布、任务进度。

口径统一在 SQL 里算，避免前后端各算一套；可见范围跟着角色走（坐席看自己，主管看本团队）。
'''

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.adapters.sql import Store
from app.adapters.tables import audit_logs, blacklist, calls, task_items, tasks, users
from app.contract import (
    CALL_RESULT_LABELS,
    INTENT_LABELS,
    TASK_STATUS_LABELS,
    WRITEBACK_STATUS_LABELS,
)
from app.adapters.tables import writeback_queue
from app.core.clock import days_back, now, shift_minutes, to_iso
from app.core.config import Settings
from app.domain import Actor

BLOCK_ACTIONS = ('block_blacklist', 'block_number_limit')
RANGE_DAYS_DEFAULT = 7


class ReportService:
    def __init__(self, store: Store, settings: Settings, tasks: Any) -> None:
        self.store = store
        self.settings = settings
        self.tasks = tasks

    # ---- 概览 ----
    def overview(self, actor: Actor, *, days: int = RANGE_DAYS_DEFAULT) -> dict[str, Any]:
        conditions = self._range(actor, days)
        total = self._count(calls, conditions)
        answered = self._count(calls, conditions + [calls.c.category == 'answered'])
        talk = self._sum(calls.c.talk_sec, conditions)
        positive = self._count(calls, conditions + [calls.c.outcome == 'positive'])
        today_conditions = self._range(actor, 1)
        today_total = self._count(calls, today_conditions)
        today_answered = self._count(calls, today_conditions + [calls.c.category == 'answered'])

        pending_items = self._count(
            task_items,
            [task_items.c.status == 'pending'],
        )
        my_pending = self._count(
            task_items,
            [task_items.c.status == 'pending', task_items.c.assignee_id == actor.user_id],
        )
        active_tasks = self._count(tasks, [tasks.c.status == 'active'])
        blocks = self._count(audit_logs, [audit_logs.c.action.in_(list(BLOCK_ACTIONS))])
        writeback = {
            status: self._count(writeback_queue, [writeback_queue.c.status == status])
            for status in ('pending', 'sent', 'failed', 'skipped')
        }
        return {
            'days': int(days),
            'total_calls': total,
            'answered': answered,
            'unanswered': total - answered,
            'answer_rate': round(answered / total, 4) if total else 0.0,
            'talk_seconds': talk,
            'avg_talk_seconds': round(talk / answered, 1) if answered else 0.0,
            'positive': positive,
            'positive_rate': round(positive / total, 4) if total else 0.0,
            'today': {
                'total_calls': today_total,
                'answered': today_answered,
                'answer_rate': round(today_answered / today_total, 4) if today_total else 0.0,
            },
            'tasks': {'active': active_tasks},
            'items': {'pending': pending_items, 'mine_pending': my_pending},
            'blocked': blocks,
            'writeback': writeback,
        }

    # ---- 坐席排行 ----
    def agents(self, actor: Actor, *, days: int = RANGE_DAYS_DEFAULT, limit: int = 50) -> dict[str, Any]:
        conditions = self._range(actor, days) + [calls.c.agent_id.isnot(None)]
        stmt = (
            sa.select(
                calls.c.agent_id.label('agent_id'),
                sa.func.count().label('total'),
                sa.func.sum(sa.case((calls.c.category == 'answered', 1), else_=0)).label('answered'),
                sa.func.sum(sa.case((calls.c.outcome == 'positive', 1), else_=0)).label('positive'),
                sa.func.coalesce(sa.func.sum(calls.c.talk_sec), 0).label('talk'),
            )
            .where(*conditions)
            .group_by(calls.c.agent_id)
            .order_by(sa.desc('total'))
            .limit(max(1, int(limit)))
        )
        name_map = {row['id']: row.get('name') or row['id'] for row in self.store.select(users)}
        data = []
        for row in self.store.raw(stmt):
            total = int(row['total'] or 0)
            answered = int(row['answered'] or 0)
            talk = int(row['talk'] or 0)
            agent_id = str(row['agent_id'])
            data.append(
                {
                    'agent_id': agent_id,
                    'agent_name': name_map.get(agent_id, agent_id),
                    'total': total,
                    'answered': answered,
                    'answer_rate': round(answered / total, 4) if total else 0.0,
                    'positive': int(row['positive'] or 0),
                    'talk_seconds': talk,
                    'avg_talk_seconds': round(talk / answered, 1) if answered else 0.0,
                }
            )
        return {'days': int(days), 'data': data}

    # ---- 按日趋势 ----
    def daily(self, actor: Actor, *, days: int = 14) -> dict[str, Any]:
        conditions = self._range(actor, days)
        day_col = sa.func.substr(calls.c.started_at, 1, 10).label('day')
        stmt = (
            sa.select(
                day_col,
                sa.func.count().label('total'),
                sa.func.sum(sa.case((calls.c.category == 'answered', 1), else_=0)).label('answered'),
                sa.func.coalesce(sa.func.sum(calls.c.talk_sec), 0).label('talk'),
            )
            .where(*conditions)
            .group_by(day_col)
            .order_by(day_col)
        )
        found = {str(row['day']): row for row in self.store.raw(stmt)}
        series = []
        for day in days_back(int(days)):
            row = found.get(day)
            total = int(row['total'] or 0) if row else 0
            answered = int(row['answered'] or 0) if row else 0
            series.append(
                {
                    'day': day,
                    'total': total,
                    'answered': answered,
                    'answer_rate': round(answered / total, 4) if total else 0.0,
                    'talk_seconds': int(row['talk'] or 0) if row else 0,
                }
            )
        return {'days': int(days), 'data': series}

    # ---- 结果与意向分布 ----
    def results(self, actor: Actor, *, days: int = 30) -> dict[str, Any]:
        conditions = self._range(actor, days)
        by_result = (
            sa.select(calls.c.result_code.label('code'), sa.func.count().label('n'))
            .where(*conditions, calls.c.result_code.isnot(None))
            .group_by(calls.c.result_code)
            .order_by(sa.desc('n'))
        )
        by_intent = (
            sa.select(calls.c.intent_level.label('code'), sa.func.count().label('n'))
            .where(*conditions, calls.c.intent_level.isnot(None))
            .group_by(calls.c.intent_level)
        )
        by_outcome = (
            sa.select(calls.c.outcome.label('code'), sa.func.count().label('n'))
            .where(*conditions, calls.c.outcome.isnot(None))
            .group_by(calls.c.outcome)
        )
        return {
            'days': int(days),
            'results': [
                {
                    'code': str(row['code']),
                    'label': CALL_RESULT_LABELS.get(str(row['code']), str(row['code'])),
                    'count': int(row['n']),
                }
                for row in self.store.raw(by_result)
            ],
            'intents': [
                {
                    'code': str(row['code']),
                    'label': INTENT_LABELS.get(str(row['code']), str(row['code'])),
                    'count': int(row['n']),
                }
                for row in self.store.raw(by_intent)
            ],
            'outcomes': [
                {'code': str(row['code']), 'count': int(row['n'])} for row in self.store.raw(by_outcome)
            ],
        }

    # ---- 任务进度 ----
    def tasks_progress(self, actor: Actor, *, limit: int = 50) -> dict[str, Any]:
        conditions = [self.tasks._scope(actor)]
        rows = self.store.select(
            tasks, *conditions, order_by='created_at', desc=True, limit=max(1, int(limit))
        )
        progress = self.tasks._progress_map([row['id'] for row in rows])
        data = []
        for row in rows:
            buckets = progress.get(row['id'], {})
            total = int(buckets.get('total', 0))
            done = int(buckets.get('done', 0)) + int(buckets.get('skipped', 0))
            data.append(
                {
                    'id': row['id'],
                    'name': row.get('name'),
                    'status': row.get('status'),
                    'status_label': TASK_STATUS_LABELS.get(str(row.get('status')), str(row.get('status'))),
                    'mode': row.get('mode'),
                    'assignee_id': row.get('assignee_id'),
                    'total': total,
                    'pending': int(buckets.get('pending', 0)),
                    'done': done,
                    'completion_rate': round(done / total, 4) if total else 0.0,
                }
            )
        return {'data': data}

    def compliance(self, actor: Actor, *, days: int = RANGE_DAYS_DEFAULT) -> dict[str, Any]:
        since = to_iso(shift_minutes(now(), -int(days) * 24 * 60))
        blocked = self.store.count(
            audit_logs, audit_logs.c.action.in_(list(BLOCK_ACTIONS)), audit_logs.c.at >= since
        )
        by_action = (
            sa.select(audit_logs.c.action.label('code'), sa.func.count().label('n'))
            .where(audit_logs.c.action.in_(list(BLOCK_ACTIONS)), audit_logs.c.at >= since)
            .group_by(audit_logs.c.action)
        )
        return {
            'days': int(days),
            'blocked': blocked,
            'by_action': [
                {'code': str(row['code']), 'count': int(row['n'])} for row in self.store.raw(by_action)
            ],
            'blacklist_active': self.store.count(blacklist, filters={'is_active': True}),
            'writeback': {
                status: self.store.count(writeback_queue, filters={'status': status})
                for status in WRITEBACK_STATUS_LABELS
            },
        }

    # ---- 内部 ----
    def _range(self, actor: Actor, days: int) -> list[Any]:
        span = max(1, int(days))
        since = to_iso(shift_minutes(now(), -(span - 1) * 24 * 60)).split('T')[0] + 'T00:00:00'
        return [self.tasks_scope(actor), calls.c.started_at >= since]

    def tasks_scope(self, actor: Actor) -> Any:
        if actor.is_admin:
            return sa.true()
        if actor.is_manager:
            return sa.or_(
                calls.c.agent_id == actor.user_id, calls.c.agent_team_id == actor.team_id
            )
        return calls.c.agent_id == actor.user_id

    def _count(self, table: Any, conditions: list) -> int:
        stmt = sa.select(sa.func.count()).select_from(table).where(*conditions)
        return int(self.store.scalar(stmt) or 0)

    def _sum(self, column: Any, conditions: list) -> int:
        stmt = sa.select(sa.func.coalesce(sa.func.sum(column), 0)).where(*conditions)
        return int(self.store.scalar(stmt) or 0)