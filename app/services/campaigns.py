'''外呼任务与任务项：指派、领取、退回、跳过，以及未接之后的重呼回池。'''

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.adapters.sql import Store
from app.adapters.tables import calls, list_batches, list_items, task_items, tasks, users
from app.contract import ITEM_STATUS_LABELS, PRIORITY_LABELS, TASK_MODE_LABELS, TASK_STATUS_LABELS
from app.core.clock import now, now_iso, parse_iso, shift_minutes, to_iso
from app.core.config import Settings
from app.core.ids import new_id
from app.core.phone import mask_phone
from app.domain import Actor
from app.errors import Conflict, Forbidden, NotFound, ValidationFailed

PRIORITY_RANK = {'high': 0, 'normal': 1, 'low': 2}
COOLDOWN_MINUTES = 15
AUTO_CLAIM_BATCH = 20
TASK_SCOPES = ('draft', 'active', 'paused', 'finished', 'canceled')


class TaskService:
    def __init__(self, store: Store, settings: Settings, audit: Any) -> None:
        self.store = store
        self.settings = settings
        self.audit = audit

    # ---- 任务 ----
    def list_tasks(
        self,
        actor: Actor,
        *,
        status: str | None = None,
        mode: str | None = None,
        search: str | None = None,
        mine: bool = False,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        size = self._page_size(page_size)
        offset = (max(1, int(page)) - 1) * size
        conditions = [self._scope(actor)]
        if mine:
            conditions.append(tasks.c.assignee_id == actor.user_id)
        filters: dict[str, Any] = {}
        if status:
            filters['status'] = status
        if mode:
            filters['mode'] = mode
        rows = self.store.select(
            tasks,
            *conditions,
            filters=filters,
            order_by='created_at',
            desc=True,
            limit=size,
            offset=offset,
            search=search,
            search_fields=('name', 'note'),
        )
        total = self.store.count(tasks, *conditions, filters=filters)
        progress = self._progress_map([row['id'] for row in rows])
        return {
            'data': [self.public_task(row, progress.get(row['id'], {})) for row in rows],
            'total': total,
            'page': max(1, int(page)),
            'page_size': size,
        }

    def get_task(self, actor: Actor, task_id: str) -> dict:
        task = self.store.get(tasks, task_id)
        if task is None:
            raise NotFound('任务不存在')
        self._assert_visible(actor, task)
        progress = self._progress_map([task_id]).get(task_id, {})
        return self.public_task(task, progress)

    def create_task(self, actor: Actor, payload: dict) -> dict:
        if not actor.is_manager:
            raise Forbidden('需要主管及以上权限')
        name = str(payload.get('name') or '').strip()
        if not name:
            raise ValidationFailed('任务名称必填')
        mode = str(payload.get('mode') or 'preview')
        if mode not in ('preview', 'robot'):
            raise ValidationFailed('mode 只能是 preview 或 robot')
        priority = str(payload.get('priority') or 'normal')
        if priority not in PRIORITY_RANK:
            raise ValidationFailed('优先级不合法')
        batch = None
        if payload.get('batch_id'):
            batch = self.store.get(list_batches, str(payload['batch_id']))
            if batch is None:
                raise NotFound('名单批次不存在')
        assignee_id = payload.get('assignee_id')
        if assignee_id and self.store.get(users, str(assignee_id)) is None:
            raise NotFound('被指派的坐席不存在')
        _validate_window(payload.get('dial_window_start'), payload.get('dial_window_end'))
        status = str(payload.get('status') or 'draft')
        if status not in TASK_SCOPES:
            raise ValidationFailed('任务状态不合法')
        task = self.store.insert(
            tasks,
            {
                'id': new_id('task'),
                'name': name,
                'batch_id': batch['id'] if batch else None,
                'mode': mode,
                'status': status,
                'priority': priority,
                'assignee_id': assignee_id,
                'team_id': payload.get('team_id') or actor.team_id,
                'max_attempts': max(1, int(payload.get('max_attempts') or 3)),
                'dial_window_start': payload.get('dial_window_start'),
                'dial_window_end': payload.get('dial_window_end'),
                'note': payload.get('note'),
                'created_by': actor.user_id,
            },
        )
        created = self.generate_items(actor, task['id']) if batch else 0
        self.audit.log(
            actor,
            'create_task',
            object_type='tasks',
            object_id=task['id'],
            detail={'batch_id': task['batch_id'], 'items': created},
        )
        progress = self._progress_map([task['id']]).get(task['id'], {})
        return self.public_task(self.store.get(tasks, task['id']), progress)

    def update_task(self, actor: Actor, task_id: str, payload: dict) -> dict:
        task = self._load_manageable(actor, task_id)
        values: dict[str, Any] = {}
        for key in ('name', 'note', 'priority', 'assignee_id', 'team_id', 'mode'):
            if key in payload and payload[key] is not None:
                values[key] = payload[key]
        if 'priority' in values and values['priority'] not in PRIORITY_RANK:
            raise ValidationFailed('优先级不合法')
        if 'mode' in values and values['mode'] not in ('preview', 'robot'):
            raise ValidationFailed('mode 只能是 preview 或 robot')
        if payload.get('max_attempts') is not None:
            values['max_attempts'] = max(1, int(payload['max_attempts']))
        if 'dial_window_start' in payload or 'dial_window_end' in payload:
            start = payload.get('dial_window_start', task.get('dial_window_start'))
            end = payload.get('dial_window_end', task.get('dial_window_end'))
            _validate_window(start, end)
            values['dial_window_start'] = start
            values['dial_window_end'] = end
        if payload.get('status'):
            status = str(payload['status'])
            if status not in TASK_SCOPES:
                raise ValidationFailed('任务状态不合法')
            values['status'] = status
        if values:
            self.store.update(tasks, task_id, values)
        if values.get('status') in ('finished', 'canceled'):
            self._close_pending_items(task_id)
        self.audit.log(
            actor,
            'update_task',
            object_type='tasks',
            object_id=task_id,
            detail={'fields': sorted(values)},
        )
        progress = self._progress_map([task_id]).get(task_id, {})
        return self.public_task(self.store.get(tasks, task_id), progress)

    def delete_task(self, actor: Actor, task_id: str) -> dict:
        self._load_manageable(actor, task_id)
        item_rows = self.store.select(task_items, filters={'task_id': task_id})
        item_ids = [row['id'] for row in item_rows]
        if item_ids and self.store.count(calls, filters={'task_item_id': item_ids}) > 0:
            raise Conflict('该任务已经产生通话记录，不能删除，请改为「已取消」')
        for row in item_rows:
            self._free_list_item(row['list_item_id'])
        self.store.delete_where(task_items, [task_items.c.task_id == task_id])
        self.store.delete(tasks, task_id)
        self.audit.log(actor, 'delete_task', object_type='tasks', object_id=task_id)
        return {'detail': '已删除', 'id': task_id}

    def claim_task(self, actor: Actor, task_id: str) -> dict:
        task = self._load_manageable_claim(actor, task_id)
        values: dict[str, Any] = {'assignee_id': actor.user_id}
        if task.get('status') == 'draft':
            values['status'] = 'active'
        self.store.update(tasks, task_id, values)
        self.store.update_where(
            task_items,
            [task_items.c.task_id == task_id, task_items.c.status == 'pending'],
            {'assignee_id': actor.user_id},
        )
        self.audit.log(actor, 'claim_task', object_type='tasks', object_id=task_id)
        progress = self._progress_map([task_id]).get(task_id, {})
        return self.public_task(self.store.get(tasks, task_id), progress)

    def release_task(self, actor: Actor, task_id: str) -> dict:
        task = self.store.get(tasks, task_id)
        if task is None:
            raise NotFound('任务不存在')
        if task.get('assignee_id') != actor.user_id and not actor.is_manager:
            raise Forbidden('只能退回自己领取的任务')
        self.store.update(tasks, task_id, {'assignee_id': None, 'status': 'draft'})
        self.store.update_where(
            task_items,
            [task_items.c.task_id == task_id, task_items.c.status == 'pending'],
            {'assignee_id': None},
        )
        self.audit.log(actor, 'release_task', object_type='tasks', object_id=task_id)
        progress = self._progress_map([task_id]).get(task_id, {})
        return self.public_task(self.store.get(tasks, task_id), progress)

    # ---- 任务项 ----
    def list_items(
        self,
        actor: Actor,
        task_id: str,
        *,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        self.get_task(actor, task_id)
        size = self._page_size(page_size)
        offset = (max(1, int(page)) - 1) * size
        filters: dict[str, Any] = {'task_id': task_id}
        if status:
            filters['status'] = status
        rows = self.store.select(
            task_items, filters=filters, order_by='created_at', desc=False, limit=size, offset=offset
        )
        total = self.store.count(task_items, filters=filters)
        merged = self._merge(rows, actor)
        if search:
            needle = str(search).strip().lower()
            merged = [
                row
                for row in merged
                if needle in str(row.get('phone') or '').lower()
                or needle in str(row.get('customer_name') or '').lower()
                or needle in str(row.get('company') or '').lower()
            ]
        return {'data': merged, 'total': total, 'page': max(1, int(page)), 'page_size': size}

    def next_item(self, actor: Actor, *, task_id: str | None = None) -> dict | None:
        '''取下一个：先看我名下待呼，空了再从我负责 / 本团队的任务里自动领一批。'''
        if task_id:
            self.get_task(actor, task_id)
        candidate = self._pick_candidate(actor, task_id=task_id)
        if candidate is not None:
            return candidate
        if self._auto_claim(actor, task_id=task_id):
            return self._pick_candidate(actor, task_id=task_id)
        return None

    def pending_count(self, actor: Actor, *, task_id: str | None = None) -> int:
        '''名下所有待呼（不分是否已过重呼冷却）。'''
        conditions = [task_items.c.status == 'pending', task_items.c.assignee_id == actor.user_id]
        if task_id:
            conditions.append(task_items.c.task_id == task_id)
        return self.store.count(task_items, *conditions)

    def due_count(self, actor: Actor, *, task_id: str | None = None) -> int:
        conditions = [task_items.c.status == 'pending', task_items.c.assignee_id == actor.user_id]
        if task_id:
            conditions.append(task_items.c.task_id == task_id)
        rows = self.store.select(task_items, *conditions)
        return len([row for row in rows if self._ready(row)])

    def assign_items(self, actor: Actor, task_id: str, *, assignee_id: str, limit: int = 50) -> dict:
        self._load_manageable(actor, task_id)
        if self.store.get(users, assignee_id) is None:
            raise NotFound('坐席不存在')
        rows = self.store.select(
            task_items,
            task_items.c.task_id == task_id,
            task_items.c.status == 'pending',
            task_items.c.assignee_id.is_(None),
            order_by='created_at',
            desc=False,
            limit=max(1, int(limit)),
        )
        ids = [row['id'] for row in rows]
        if ids:
            self.store.update_where(task_items, [task_items.c.id.in_(ids)], {'assignee_id': assignee_id})
        self.audit.log(
            actor,
            'assign_items',
            object_type='tasks',
            object_id=task_id,
            detail={'assignee_id': assignee_id, 'count': len(ids)},
        )
        return {'assigned': len(ids)}

    def skip_item(self, actor: Actor, item_id: str) -> dict:
        item = self._load_item(actor, item_id)
        if item.get('status') == 'in_progress':
            raise Conflict('通话中的任务项不能跳过')
        self.store.update(task_items, item_id, {'status': 'skipped', 'finished_at': now_iso()})
        self.audit.log(actor, 'skip_item', object_type='task_items', object_id=item_id)
        customer = self._customer_map([item]).get(item['list_item_id'])
        return self.public_item(self.store.get(task_items, item_id), customer, actor)

    def generate_items(self, actor: Actor, task_id: str, *, limit: int | None = None) -> int:
        task = self.store.get(tasks, task_id)
        if task is None:
            raise NotFound('任务不存在')
        batch_id = task.get('batch_id')
        if not batch_id:
            return 0
        available = self.store.select(
            list_items,
            list_items.c.batch_id == batch_id,
            list_items.c.status == 'available',
            order_by='created_at',
            desc=False,
            limit=int(limit) if limit else None,
        )
        if not available:
            return 0
        rows = [
            {
                'id': new_id('titem'),
                'task_id': task_id,
                'list_item_id': item['id'],
                'assignee_id': task.get('assignee_id'),
                'status': 'pending',
                'priority': task.get('priority') or 'normal',
                'attempts': 0,
            }
            for item in available
        ]
        self.store.insert_many(task_items, rows)
        self.store.update_where(
            list_items,
            [list_items.c.id.in_([item['id'] for item in available])],
            {'status': 'assigned'},
        )
        return len(rows)

    # ---- 通话联动 ----
    def on_call_started(self, call: dict) -> None:
        item_id = call.get('task_item_id')
        if item_id:
            item = self.store.get(task_items, item_id)
            if item:
                self.store.update(
                    task_items,
                    item_id,
                    {
                        'status': 'in_progress',
                        'attempts': int(item.get('attempts') or 0) + 1,
                        'last_call_id': call['id'],
                        'claimed_at': now_iso(),
                        'assignee_id': item.get('assignee_id') or call.get('agent_id'),
                    },
                )
        list_item_id = call.get('list_item_id')
        if list_item_id:
            item = self.store.get(list_items, list_item_id)
            if item:
                self.store.update(
                    list_items,
                    list_item_id,
                    {
                        'status': 'called',
                        'attempts': int(item.get('attempts') or 0) + 1,
                        'last_call_id': call['id'],
                    },
                )

    def on_call_finished(self, call: dict, *, answered: bool) -> None:
        item_id = call.get('task_item_id')
        if not item_id or answered:
            # 接通后等坐席提交结果，由 complete_item 收尾
            return
        item = self.store.get(task_items, item_id)
        if item is None:
            return
        task = self.store.get(tasks, item.get('task_id')) or {}
        attempts = int(item.get('attempts') or 0)
        values: dict[str, Any] = {
            'result_code': call.get('state'),
            'intent_level': 'none',
            'last_call_id': call['id'],
        }
        if attempts < int(task.get('max_attempts') or 3):
            values['status'] = 'pending'
            values['next_attempt_at'] = to_iso(shift_minutes(now(), COOLDOWN_MINUTES))
        else:
            values['status'] = 'done'
            values['finished_at'] = now_iso()
        self.store.update(task_items, item_id, values)

    def complete_item(self, item_id: str, call: dict) -> None:
        self.store.update(
            task_items,
            item_id,
            {
                'status': 'done',
                'result_code': call.get('result_code'),
                'intent_level': call.get('intent_level'),
                'finished_at': now_iso(),
                'last_call_id': call['id'],
            },
        )
        if call.get('list_item_id'):
            self.store.update(
                list_items,
                call['list_item_id'],
                {'status': 'closed', 'last_result': call.get('result_code')},
            )

    # ---- 内部 ----
    def _pick_candidate(self, actor: Actor, *, task_id: str | None = None) -> dict | None:
        conditions = [task_items.c.status == 'pending', task_items.c.assignee_id == actor.user_id]
        if task_id:
            conditions.append(task_items.c.task_id == task_id)
        rows = self.store.select(task_items, *conditions, order_by='created_at', desc=False, limit=200)
        ready = [row for row in rows if self._ready(row)]
        if not ready:
            return None
        ready.sort(
            key=lambda row: (
                PRIORITY_RANK.get(str(row.get('priority') or 'normal'), 1),
                str(row.get('created_at') or ''),
            )
        )
        item = ready[0]
        task = self.store.get(tasks, item['task_id']) or {}
        if task.get('status') in ('paused', 'canceled', 'finished'):
            return None
        customer = self._customer_map([item]).get(item['list_item_id'])
        return self.public_item(item, customer, actor)

    def _auto_claim(self, actor: Actor, *, task_id: str | None = None) -> int:
        my_tasks = self.store.select(
            tasks,
            sa.or_(
                tasks.c.assignee_id == actor.user_id,
                sa.and_(tasks.c.assignee_id.is_(None), tasks.c.team_id == actor.team_id),
            ),
            tasks.c.status == 'active',
        )
        if task_id:
            my_tasks = [row for row in my_tasks if row['id'] == task_id]
        claimed = 0
        for task in my_tasks:
            free = self.store.select(
                task_items,
                task_items.c.task_id == task['id'],
                task_items.c.status == 'pending',
                task_items.c.assignee_id.is_(None),
                order_by='created_at',
                desc=False,
                limit=AUTO_CLAIM_BATCH,
            )
            if not free:
                continue
            self.store.update_where(
                task_items,
                [task_items.c.id.in_([row['id'] for row in free])],
                {'assignee_id': actor.user_id},
            )
            claimed += len(free)
        return claimed

    def _ready(self, row: dict) -> bool:
        next_at = parse_iso(row.get('next_attempt_at'))
        if next_at is None:
            return True
        return parse_iso(now_iso()) >= next_at

    def _close_pending_items(self, task_id: str) -> None:
        for row in self.store.select(task_items, filters={'task_id': task_id, 'status': 'pending'}):
            self.store.update(task_items, row['id'], {'status': 'skipped', 'finished_at': now_iso()})
            self._free_list_item(row['list_item_id'])

    def _free_list_item(self, list_item_id: str) -> None:
        item = self.store.get(list_items, list_item_id)
        if item and item.get('status') == 'assigned':
            self.store.update(list_items, list_item_id, {'status': 'available'})

    def _load_manageable(self, actor: Actor, task_id: str) -> dict:
        task = self.store.get(tasks, task_id)
        if task is None:
            raise NotFound('任务不存在')
        if actor.is_admin:
            return task
        if actor.is_manager and task.get('team_id') in (None, actor.team_id):
            return task
        if task.get('assignee_id') == actor.user_id:
            return task
        if task.get('assignee_id') is None and task.get('team_id') == actor.team_id:
            return task
        raise Forbidden('需要主管权限，或只能管理自己领取的任务')

    def _load_manageable_claim(self, actor: Actor, task_id: str) -> dict:
        task = self.store.get(tasks, task_id)
        if task is None:
            raise NotFound('任务不存在')
        if task.get('assignee_id') and task['assignee_id'] != actor.user_id:
            raise Conflict('任务已被他人领取')
        if actor.is_admin:
            return task
        allowed = task.get('team_id') in (None, actor.team_id) or task.get('assignee_id') == actor.user_id
        if not allowed:
            raise Forbidden('该任务不属于你的团队')
        return task

    def _load_item(self, actor: Actor, item_id: str) -> dict:
        item = self.store.get(task_items, item_id)
        if item is None:
            raise NotFound('任务项不存在')
        if actor.is_manager:
            return item
        if item.get('assignee_id') not in (None, actor.user_id):
            raise Forbidden('该任务项不属于你')
        return item

    def _assert_visible(self, actor: Actor, task: dict) -> None:
        if actor.is_admin:
            return
        if task.get('assignee_id') == actor.user_id:
            return
        if task.get('team_id') in (None, actor.team_id):
            return
        raise Forbidden('无权查看该任务')

    def _scope(self, actor: Actor) -> Any:
        if actor.is_admin:
            return sa.true()
        if actor.is_manager:
            team_user_ids = self._team_user_ids(actor.team_id)
            clauses = [tasks.c.team_id == actor.team_id, tasks.c.assignee_id == actor.user_id]
            if team_user_ids:
                clauses.append(tasks.c.assignee_id.in_(team_user_ids))
            return sa.or_(*clauses)
        return sa.or_(
            tasks.c.assignee_id == actor.user_id,
            sa.and_(tasks.c.team_id == actor.team_id, tasks.c.assignee_id.is_(None)),
        )

    def _team_user_ids(self, team_id: str | None) -> list[str]:
        if not team_id:
            return []
        return [row['id'] for row in self.store.select(users, filters={'team_id': team_id})]

    def _progress_map(self, task_ids: list[str]) -> dict[str, dict[str, int]]:
        if not task_ids:
            return {}
        stmt = (
            sa.select(
                task_items.c.task_id.label('task_id'),
                task_items.c.status.label('status'),
                sa.func.count().label('n'),
            )
            .where(task_items.c.task_id.in_(task_ids))
            .group_by(task_items.c.task_id, task_items.c.status)
        )
        out: dict[str, dict[str, int]] = {task_id: {} for task_id in task_ids}
        for row in self.store.raw(stmt):
            buckets = out.setdefault(str(row['task_id']), {})
            buckets[str(row['status'])] = int(row['n'])
        for buckets in out.values():
            buckets['total'] = sum(
                buckets.get(key, 0) for key in ('pending', 'in_progress', 'done', 'skipped')
            )
        return out

    def _customer_map(self, rows: list[dict]) -> dict[str, dict]:
        ids = [row['list_item_id'] for row in rows if row.get('list_item_id')]
        if not ids:
            return {}
        items = self.store.select(list_items, filters={'id': ids})
        return {row['id']: row for row in items}

    def _merge(self, rows: list[dict], actor: Actor) -> list[dict]:
        customers = self._customer_map(rows)
        return [self.public_item(row, customers.get(row.get('list_item_id') or ''), actor) for row in rows]

    def public_item(self, row: dict, customer: dict | None, actor: Actor | None = None) -> dict:
        item = dict(row)
        customer = customer or {}
        phone = str(customer.get('phone') or '')
        # 列表一律脱敏；看全号只有通话详情一条路（管理员，且写审计）
        item['phone'] = mask_phone(phone)
        item['phone_masked'] = mask_phone(phone)
        item['customer_name'] = customer.get('name')
        item['company'] = customer.get('company')
        item['contact_name'] = customer.get('contact_name')
        item['crm_object'] = customer.get('crm_object')
        item['crm_record_id'] = customer.get('crm_record_id')
        item['last_result'] = customer.get('last_result')
        item['status_label'] = ITEM_STATUS_LABELS.get(str(row.get('status')), str(row.get('status')))
        item['priority_label'] = PRIORITY_LABELS.get(str(row.get('priority')), str(row.get('priority')))
        return item

    def public_task(self, row: dict, progress: dict | None) -> dict:
        task = dict(row)
        task['status_label'] = TASK_STATUS_LABELS.get(str(row.get('status')), str(row.get('status')))
        task['mode_label'] = TASK_MODE_LABELS.get(str(row.get('mode')), str(row.get('mode')))
        task['priority_label'] = PRIORITY_LABELS.get(str(row.get('priority')), str(row.get('priority')))
        buckets = progress or {}
        task['progress'] = {
            'total': int(buckets.get('total', 0)),
            'pending': int(buckets.get('pending', 0)),
            'in_progress': int(buckets.get('in_progress', 0)),
            'done': int(buckets.get('done', 0)),
            'skipped': int(buckets.get('skipped', 0)),
        }
        return task

    def _page_size(self, value: int | None) -> int:
        size = int(value or self.settings.default_page_size)
        return max(1, min(size, int(self.settings.max_page_size)))


def _validate_window(start: Any, end: Any) -> None:
    from app.core.config import parse_clock

    for value in (start, end):
        if not value:
            continue
        try:
            parse_clock(str(value))
        except ValueError as error:
            raise ValidationFailed('拨打时段必须是 HH:MM：' + str(value)) from error