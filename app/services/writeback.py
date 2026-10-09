'''CRM 回写队列：只追加 activities / notes / tasks，不改 CRM 任何业务字段。

每条回写都带确定性的 Idempotency-Key，重放不会写重；失败进队列重试并留痕，
名单条目没有 CRM 归属时直接标 skipped，把「为什么没回写」写清楚而不是悄悄丢掉。
'''

from __future__ import annotations

from typing import Any

from app.adapters.sql import Store
from app.adapters.tables import writeback_queue
from app.contract import CALL_RESULT_LABELS
from app.core.clock import now_iso, parse_iso
from app.core.config import Settings
from app.core.ids import new_id
from app.core.phone import mask_phone
from app.domain import Actor
from app.errors import NotFound

MAX_ATTEMPTS = 10


class WritebackService:
    def __init__(self, store: Store, settings: Settings, audit: Any, gateway: Any) -> None:
        self.store = store
        self.settings = settings
        self.audit = audit
        self.gateway = gateway

    # ---- 入队 ----
    def enqueue_for_call(self, call: dict, *, list_item: dict | None, followup: dict | None = None) -> list[dict]:
        '''一通电话结束后：一条通话活动 + 可选备注 + 可选跟进任务。'''
        crm_object = (list_item or {}).get('crm_object')
        crm_record_id = (list_item or {}).get('crm_record_id')
        rows: list[dict] = []
        base = {
            'call_id': call['id'],
            'list_item_id': call.get('list_item_id'),
            'crm_object': crm_object,
            'crm_record_id': crm_record_id,
        }
        has_target = bool(crm_object and crm_record_id)
        # 说明白「为什么这条没回写」：手动拨号没有名单条目，导入名单没有 CRM 归属
        if list_item is None:
            skip_reason = '手动拨号，没有关联名单条目'
        elif not has_target:
            skip_reason = '名单条目没有关联 CRM 记录（本地导入）'
        else:
            skip_reason = ''
        rows.append(
            self._enqueue(
                'activity',
                call_id=call['id'],
                crm_object=crm_object,
                crm_record_id=crm_record_id,
                payload={
                    'kind': 'call',
                    'subject': _subject(call),
                    'content': (call.get('note') or '').strip() or _auto_content(call),
                    'target_id': crm_record_id or None,
                    'occurred_at': call.get('ended_at') or call.get('started_at'),
                },
                skip_reason=skip_reason,
                list_item_id=call.get('list_item_id'),
            )
        )
        note = (call.get('note') or '').strip()
        if note:
            rows.append(
                self._enqueue(
                    'note',
                    call_id=call['id'],
                    crm_object=crm_object,
                    crm_record_id=crm_record_id,
                    payload={'target_id': crm_record_id, 'content': note},
                    skip_reason=skip_reason,
                    list_item_id=call.get('list_item_id'),
                )
            )
        if followup and (followup.get('subject') or '').strip():
            rows.append(
                self._enqueue(
                    'task',
                    call_id=call['id'],
                    crm_object=crm_object,
                    crm_record_id=crm_record_id,
                    payload={
                        'subject': str(followup['subject']).strip(),
                        'due_at': followup.get('due_at'),
                        'target_id': crm_record_id or None,
                        'priority': followup.get('priority') or 'normal',
                        'status': 'open',
                    },
                    skip_reason=skip_reason,
                    list_item_id=call.get('list_item_id'),
                )
            )
        return rows

    def _enqueue(
        self,
        kind: str,
        *,
        call_id: str,
        crm_object: str | None,
        crm_record_id: str | None,
        payload: dict,
        skip_reason: str = '',
        list_item_id: str | None = None,
    ) -> dict:
        key = 'wahu-' + str(call_id) + '-' + kind
        existing = self.store.find_one(writeback_queue, idempotency_key=key)
        if existing:
            return existing
        row = self.store.insert(
            writeback_queue,
            {
                'id': new_id('writeback'),
                'kind': kind,
                'idempotency_key': key,
                'crm_object': crm_object,
                'crm_record_id': crm_record_id,
                'call_id': call_id,
                'list_item_id': list_item_id,
                'payload': payload,
                'status': 'skipped' if skip_reason else 'pending',
                'attempts': 0,
                'last_error': skip_reason or None,
            },
        )
        return row

    # ---- 出队 ----
    def drain(self, limit: int = 20) -> dict[str, int]:
        '''把到点的待发送项推到 CRM；失败按退避重试，超过上限转 failed 等人工重推。'''
        stats = {'sent': 0, 'failed': 0, 'skipped': 0, 'pending_left': 0}
        rows = self.store.select(
            writeback_queue,
            filters={'status': ('pending', 'failed')},
            order_by='created_at',
            desc=False,
            limit=max(1, int(limit)),
        )
        for row in rows:
            if int(row.get('attempts') or 0) >= MAX_ATTEMPTS:
                continue
            if not self._due(row):
                stats['pending_left'] += 1
                continue
            target = _crm_object_for(row)
            if not target or not row.get('payload'):
                self.store.update(
                    writeback_queue,
                    row['id'],
                    {'status': 'skipped', 'last_error': '缺少回写目标'},
                )
                stats['skipped'] += 1
                continue
            try:
                self.gateway.create_record(target, row['payload'], row['idempotency_key'])
            except Exception as error:
                attempts = int(row.get('attempts') or 0) + 1
                self.store.update(
                    writeback_queue,
                    row['id'],
                    {
                        'status': 'failed',
                        'attempts': attempts,
                        'last_error': str(error)[:500],
                    },
                )
                stats['failed'] += 1
            else:
                self.store.update(
                    writeback_queue,
                    row['id'],
                    {'status': 'sent', 'attempts': int(row.get('attempts') or 0) + 1, 'sent_at': now_iso(), 'last_error': None},
                )
                stats['sent'] += 1
        return stats

    def retry(self, actor: Actor, entry_id: str | None = None) -> dict:
        '''人工重推：把 failed 打回 pending；不给 id 就全量打回。'''
        conditions = [writeback_queue.c.status == 'failed']
        if entry_id:
            row = self.store.get(writeback_queue, entry_id)
            if row is None:
                raise NotFound('回写记录不存在')
            conditions.append(writeback_queue.c.id == entry_id)
        count = self.store.update_where(
            writeback_queue, conditions, {'status': 'pending', 'attempts': 0, 'last_error': None}
        )
        self.audit.log(
            actor, 'retry_writeback', object_type='writeback_queue', object_id=entry_id, detail={'count': count}
        )
        return {'requeued': count}

    def list(
        self,
        actor: Actor,
        *,
        status: str | None = None,
        kind: str | None = None,
        call_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        size = max(1, min(int(page_size or self.settings.default_page_size), int(self.settings.max_page_size)))
        filters: dict[str, Any] = {}
        if status:
            filters['status'] = status
        if kind:
            filters['kind'] = kind
        if call_id:
            filters['call_id'] = call_id
        rows = self.store.select(
            writeback_queue,
            filters=filters,
            order_by='created_at',
            desc=True,
            limit=size,
            offset=(max(1, int(page)) - 1) * size,
        )
        total = self.store.count(writeback_queue, filters=filters)
        summary = {
            state: self.store.count(writeback_queue, filters={'status': state})
            for state in ('pending', 'sent', 'failed', 'skipped')
        }
        return {
            'data': [_public(row) for row in rows],
            'total': total,
            'page': max(1, int(page)),
            'page_size': size,
            'summary': summary,
        }

    def _due(self, row: dict) -> bool:
        attempts = int(row.get('attempts') or 0)
        if attempts == 0:
            return True
        updated = parse_iso(row.get('updated_at'))
        if updated is None:
            return True
        wait = min(300.0, 15.0 * (2 ** (attempts - 1)))
        return (parse_iso(now_iso()) - updated).total_seconds() >= wait


def _crm_object_for(row: dict) -> str | None:
    kind = str(row.get('kind') or '')
    if kind == 'activity':
        return 'activities'
    if kind == 'note':
        return 'notes'
    if kind == 'task':
        return 'tasks'
    return None


def _subject(call: dict) -> str:
    label = CALL_RESULT_LABELS.get(str(call.get('result_code') or ''), '外呼')
    masked = call.get('phone_masked') or mask_phone(str(call.get('phone') or ''))
    seconds = int(call.get('talk_sec') or 0)
    return '外呼 ' + str(masked) + ' · ' + str(label) + ' · ' + str(seconds) + '秒'


def _auto_content(call: dict) -> str:
    label = CALL_RESULT_LABELS.get(str(call.get('result_code') or ''), '未填写结果')
    return (
        '外呼系统自动记录：结果 '
        + str(label)
        + '，意向 '
        + str(call.get('intent_level') or 'none')
        + '，通话 '
        + str(int(call.get('talk_sec') or 0))
        + ' 秒。'
    )


def _public(row: dict) -> dict:
    data = dict(row)
    data['kind_label'] = {
        'activity': '通话活动',
        'note': '跟进备注',
        'task': '跟进任务',
    }.get(str(row.get('kind')), str(row.get('kind')))
    return data


def kinds() -> tuple[str, ...]:
    return WRITEBACK_KINDS