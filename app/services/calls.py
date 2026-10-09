'''外呼通话：状态机推进、事件流、录音占位与结果提交。

状态机不用后台线程，而是「按计划到点即迁移」：
拨号时线路适配器给出一份 (state, at_ms) 计划，节拍器每次 tick 检查当前时间是否越过了下一步，
越过就迁移、写事件、推送 SSE。好处是每一跳都可被直接调用与断言，测试不依赖 sleep 竞争。
'''

from __future__ import annotations

import logging
import threading
import wave
from datetime import timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.adapters.sql import Store
from app.adapters.tables import call_events, calls, list_items, task_items, tasks, users
from app.contract import (
    ACTIVE_CALL_STATES,
    CALL_RESULT_CATEGORY,
    CALL_RESULT_LABELS,
    CALL_RESULT_OUTCOME,
    CALL_STATE_LABELS,
    CALL_STATES,
    CATEGORY_LABELS,
    INTENT_LABELS,
    OUTCOME_LABELS,
    default_intent_for,
)
from app.core.clock import now, now_iso, parse_iso, to_iso
from app.core.config import Settings
from app.core.ids import new_id
from app.core.phone import mask_phone, validate_phone
from app.domain import Actor
from app.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.telephony.base import TelephonyProvider

LOGGER = logging.getLogger(__name__)

TERMINAL_FAILURE_STATES = ('no_answer', 'busy', 'power_off', 'invalid_number', 'failed')
TERMINAL_STATES = TERMINAL_FAILURE_STATES + ('ended', 'canceled')
TICK_LIMIT = 300
MAX_TALK_SECONDS = 1800
RECORDING_MAX_SECONDS = 120
SILENCE_FRAME = b'\x80'
_advance_lock = threading.Lock()


class CallService:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        audit: Any,
        provider: TelephonyProvider,
        events: Any,
        compliance: Any,
        writeback: Any,
        tasks: Any,
    ) -> None:
        self.store = store
        self.settings = settings
        self.audit = audit
        self.provider = provider
        # 注意：属性不能叫 events，否则会盖住下面的 events() 查询方法
        self.bus = events
        self.compliance = compliance
        self.writeback = writeback
        self.tasks = tasks

    # ---- 拨号 ----
    def dial(
        self,
        actor: Actor,
        *,
        task_item_id: str | None = None,
        phone: str | None = None,
        crm_object: str | None = None,
        crm_record_id: str | None = None,
        robot_task_id: str | None = None,
    ) -> dict:
        if self._active_call(actor.user_id):
            raise Conflict('你还有一通未结束的电话，先挂断再拨下一通')

        task_item: dict | None = None
        list_item: dict | None = None
        task: dict | None = None
        target_phone = str(phone or '').strip()

        if task_item_id:
            task_item = self.store.get(task_items, task_item_id)
            if task_item is None:
                raise NotFound('任务项不存在')
            if not actor.is_manager and task_item.get('assignee_id') not in (None, actor.user_id):
                raise Forbidden('该任务项不属于你')
            if task_item.get('status') in ('done', 'skipped'):
                raise Conflict('该任务项已处理完成')
            if task_item.get('status') == 'in_progress':
                raise Conflict('该任务项正在通话中')
            task = self.store.get(tasks, task_item['task_id']) or {}
            list_item = self.store.get(list_items, task_item['list_item_id'])
            target_phone = str((list_item or {}).get('phone') or '')
        else:
            ok, normalized, reason = validate_phone(target_phone)
            if not ok:
                raise ValidationFailed('号码不合法：' + str(reason))
            target_phone = normalized

        if not target_phone:
            raise ValidationFailed('号码为空，无法拨号')

        crm_object = crm_object or (list_item or {}).get('crm_object')
        crm_record_id = crm_record_id or (list_item or {}).get('crm_record_id')
        self.compliance.ensure_dialable(
            actor,
            phone=target_phone,
            crm_record_id=crm_record_id,
            task_id=task.get('id') if task else None,
        )

        call_id = new_id('call')
        plan = self.provider.dial(call_id=call_id, phone=target_phone)
        if plan.webhook_driven:
            # 真实线路：状态由网关回调驱动，本地不排时间轴；节拍器只做超时兜底
            steps: list[dict] = []
        else:
            steps = [{'state': step.state, 'at_ms': int(step.at_ms)} for step in plan.steps]
        started = now()
        next_at = to_iso(started + timedelta(milliseconds=steps[1]['at_ms'])) if len(steps) > 1 else None
        call = self.store.insert(
            calls,
            {
                'id': call_id,
                'task_item_id': task_item_id,
                'task_id': task.get('id') if task else None,
                'list_item_id': (list_item or {}).get('id'),
                'agent_id': actor.user_id,
                'agent_team_id': actor.team_id,
                'robot_task_id': robot_task_id,
                'phone': target_phone,
                'phone_masked': mask_phone(target_phone),
                'direction': 'outbound',
                'provider': self.provider.name,
                'provider_call_id': plan.provider_call_id,
                'state': 'dialing',
                'category': None,
                'outcome': None,
                'intent_level': None,
                'started_at': now_iso(),
                'plan': steps,
                'step_index': 1 if len(steps) > 1 else 0,
                'next_at': next_at,
                'recording_status': 'none',
            },
        )
        self._event(call_id, 'dial', 'dialing', {'provider': self.provider.name, 'plan': steps})
        if task_item is not None:
            self.tasks.on_call_started(call)
        self.audit.log(
            actor,
            'dial',
            object_type='calls',
            object_id=call_id,
            detail={'phone_masked': call['phone_masked'], 'task_id': call.get('task_id')},
        )
        self._publish(call)
        return self.public_call(self.store.get(calls, call_id), actor)

    # ---- 挂断 ----
    def hangup(self, actor: Actor, call_id: str, *, reason: str = 'agent') -> dict:
        call = self._load_call(actor, call_id)
        if call['state'] in TERMINAL_STATES:
            raise Conflict('通话已经结束')
        self.provider.hangup(call_id=call_id, provider_call_id=str(call.get('provider_call_id') or ''))
        if call['state'] == 'answered':
            updated = self._finish_answered(call, reason=reason)
        else:
            updated = self._finish_unanswered(call, final_state='canceled', reason=reason)
        self.audit.log(actor, 'hangup', object_type='calls', object_id=call_id, detail={'reason': reason})
        return self.public_call(updated, actor)

    # ---- 提交结果 ----
    def complete(self, actor: Actor, call_id: str, payload: dict) -> dict:
        call = self._load_call(actor, call_id)
        if call['state'] not in TERMINAL_STATES:
            raise Conflict('通话还没结束，先挂断再提交结果')
        result_code = str(payload.get('result_code') or '').strip()
        if result_code not in CALL_RESULT_CATEGORY:
            raise ValidationFailed('结果码不合法：' + result_code)
        intent = str(payload.get('intent_level') or '').strip() or default_intent_for(result_code)
        if intent not in INTENT_LABELS:
            raise ValidationFailed('意向等级不合法：' + intent)
        note = str(payload.get('note') or '').strip()
        followup_subject = str(payload.get('followup_subject') or '').strip()
        values: dict[str, Any] = {
            'result_code': result_code,
            'category': CALL_RESULT_CATEGORY.get(result_code, 'unanswered'),
            'outcome': CALL_RESULT_OUTCOME.get(result_code, 'none'),
            'intent_level': intent,
            'note': note or None,
            'completed_at': now_iso(),
        }
        if followup_subject:
            values['followup_subject'] = followup_subject
            values['followup_due_at'] = payload.get('followup_due_at')
            values['followup_priority'] = payload.get('followup_priority') or 'normal'
        self.store.update(calls, call_id, values)
        call = self.store.get(calls, call_id)
        if call.get('task_item_id'):
            self.tasks.complete_item(call['task_item_id'], call)
        list_item = self.store.get(list_items, call['list_item_id']) if call.get('list_item_id') else None
        followup = (
            {
                'subject': followup_subject,
                'due_at': payload.get('followup_due_at'),
                'priority': payload.get('followup_priority') or 'normal',
            }
            if followup_subject
            else None
        )
        self.writeback.enqueue_for_call(call, list_item=list_item, followup=followup)
        self.audit.log(
            actor,
            'complete_call',
            object_type='calls',
            object_id=call_id,
            detail={'result_code': result_code, 'intent_level': intent, 'followup': bool(followup)},
        )
        self._publish(call)
        return self.public_call(call, actor)

    # ---- 查询 ----
    def get(self, actor: Actor, call_id: str) -> dict:
        call = self._load_call(actor, call_id)
        return self.public_call(call, actor, reveal=True, audit_reveal=True)

    def list(
        self,
        actor: Actor,
        *,
        state: str | None = None,
        result_code: str | None = None,
        category: str | None = None,
        intent_level: str | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
        day: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        size = self._page_size(page_size)
        offset = (max(1, int(page)) - 1) * size
        conditions = [self._scope(actor)]
        if state:
            conditions.append(calls.c.state == state)
        if result_code:
            conditions.append(calls.c.result_code == result_code)
        if category:
            conditions.append(calls.c.category == category)
        if intent_level:
            conditions.append(calls.c.intent_level == intent_level)
        if agent_id:
            conditions.append(calls.c.agent_id == agent_id)
        if task_id:
            conditions.append(calls.c.task_id == task_id)
        if day:
            conditions.append(calls.c.started_at.like(str(day) + '%'))
        if search:
            needle = '%' + str(search).strip() + '%'
            conditions.append(
                sa.or_(calls.c.phone.like(needle), calls.c.note.like(needle), calls.c.id.like(needle))
            )
        rows = self.store.select(
            calls, *conditions, order_by='started_at', desc=True, limit=size, offset=offset
        )
        total = self.store.count(calls, *conditions)
        summary = self._summary(conditions)
        names = self._agent_names([row.get('agent_id') for row in rows])
        return {
            'data': [
                self.public_call(row, actor, agent_name=names.get(str(row.get('agent_id') or '')))
                for row in rows
            ],
            'total': total,
            'page': max(1, int(page)),
            'page_size': size,
            'summary': summary,
        }

    def events(self, actor: Actor, call_id: str) -> list[dict]:
        self._load_call(actor, call_id)
        rows = self.store.select(
            call_events, filters={'call_id': call_id}, order_by='seq', desc=False, limit=200
        )
        for row in rows:
            row['state_label'] = CALL_STATE_LABELS.get(str(row.get('state')), str(row.get('state') or ''))
        return rows

    def recording_target(self, actor: Actor, call_id: str) -> dict[str, Any]:
        '''录音去哪取。

        - 模拟线路：本机生成的等长静音占位文件（方便验证链路）；
        - 真实线路：录音在线路厂商那边，直接跳转过去，绝不在本地伪造一个静音文件冒充录音。
        '''
        call = self._load_call(actor, call_id)
        url = str(call.get('recording_url') or '')
        if not url or call.get('recording_status') != 'ready':
            raise NotFound('该通话没有录音')
        if self.provider.name != 'simulated' and not url.startswith('/api/'):
            return {'kind': 'redirect', 'url': url}
        path = Path(self.settings.recording_path) / (call_id + '.wav')
        if not path.exists():
            if self.provider.name != 'simulated':
                raise NotFound('录音不在本机，请访问线路提供的地址：' + url)
            self._write_placeholder(path, int(call.get('recording_seconds') or 0))
        return {'kind': 'file', 'path': path, 'filename': call_id + '.wav'}

    def recording_path(self, actor: Actor, call_id: str) -> tuple[Path, str]:
        '''本地录音文件（模拟线路用）。真实线路请走 recording_target 拿跳转地址。'''
        target = self.recording_target(actor, call_id)
        if target['kind'] != 'file':
            raise NotFound('录音在线路厂商那边，请访问：' + str(target.get('url')))
        return target['path'], target['filename']

    # ---- 节拍 ----
    def tick(self) -> dict[str, int]:
        rows = self.store.select(
            calls,
            calls.c.state.in_(list(ACTIVE_CALL_STATES)),
            order_by='started_at',
            desc=False,
            limit=TICK_LIMIT,
        )
        stats = {'advanced': 0, 'auto_hangup': 0, 'provider_timeout': 0}
        for row in rows:
            try:
                if self.advance(row):
                    stats['advanced'] += 1
            except Exception:  # 单通电话推进失败不能拖垮整个节拍
                LOGGER.exception('推进通话失败 %s', row.get('id'))
        timeout_ms = max(1, int(self.settings.telephony_timeout_seconds)) * 1000
        for row in rows:
            fresh = self.store.get(calls, row['id'])
            if fresh is None or fresh.get('state') not in ACTIVE_CALL_STATES:
                continue
            if fresh.get('state') == 'answered':
                if self._talk_seconds(fresh) >= MAX_TALK_SECONDS:
                    self._finish_answered(fresh, reason='timeout')
                    stats['auto_hangup'] += 1
                continue
            # 回调驱动的通话：网关一直不回调就判失败，别让它永远挂在「拨号中」
            if not fresh.get('plan') and self._elapsed_ms(fresh) >= timeout_ms:
                LOGGER.warning('线路回调超时，通话判失败：%s', fresh.get('id'))
                self._apply_state(fresh, 'failed', int(fresh.get('step_index') or 0), reason='provider_timeout')
                stats['provider_timeout'] += 1
        return stats

    def advance(self, call: dict) -> bool:
        '''按计划把到点的状态迁移一次推进到底；返回是否发生了变化。'''
        with _advance_lock:
            fresh = self.store.get(calls, call['id'])
            if not fresh or fresh.get('state') not in ACTIVE_CALL_STATES:
                return False
            steps = list(fresh.get('plan') or [])
            index = int(fresh.get('step_index') or 0)
            changed = False
            while index < len(steps):
                step = steps[index]
                if int(step.get('at_ms') or 0) > self._elapsed_ms(fresh):
                    break
                index += 1
                changed = True
                fresh = self._apply_state(fresh, str(step.get('state')), index) or fresh
                if fresh.get('state') not in ACTIVE_CALL_STATES:
                    break
            return changed

    # ---- 内部：状态迁移 ----
    def _apply_state(self, call: dict, state: str, index: int, *, reason: str = 'provider') -> dict | None:
        if state not in CALL_STATES:
            raise ValidationFailed('未知通话状态：' + str(state))
        values: dict[str, Any] = {'state': state, 'step_index': index, 'next_at': None}
        if state == 'answered':
            values['answered_at'] = now_iso()
            values['ring_sec'] = self._elapsed_ms(call) // 1000
        elif state in TERMINAL_FAILURE_STATES:
            values['ended_at'] = now_iso()
            values['ended_reason'] = reason
            values['duration_sec'] = self._elapsed_ms(call) // 1000
            values['result_code'] = state
            values['category'] = CALL_RESULT_CATEGORY.get(state, 'unanswered')
            values['outcome'] = CALL_RESULT_OUTCOME.get(state, 'none')
            values['intent_level'] = 'none'
            values['completed_at'] = now_iso()
        self.store.update(calls, call['id'], values)
        fresh = self.store.get(calls, call['id'])
        self._event(call['id'], state, state, {'at_ms': self._elapsed_ms(call)})
        if state in TERMINAL_FAILURE_STATES:
            self._finish_unanswered(fresh, final_state=state, reason='provider')
        else:
            self._publish(fresh)
        return self.store.get(calls, call['id'])

    def _finish_answered(self, call: dict, *, reason: str) -> dict:
        talk = self._talk_seconds(call)
        values = {
            'state': 'ended',
            'ended_at': now_iso(),
            'ended_reason': reason,
            'duration_sec': self._elapsed_ms(call) // 1000,
            'talk_sec': talk,
            'next_at': None,
        }
        recording = self._prepare_recording(call, talk)
        values.update(recording)
        self.store.update(calls, call['id'], values)
        fresh = self.store.get(calls, call['id'])
        self._event(call['id'], 'ended', 'ended', {'reason': reason, 'talk_sec': talk})
        self.tasks.on_call_finished(fresh, answered=True)
        self.audit.log(None, 'call_ended', object_type='calls', object_id=call['id'], detail={'reason': reason})
        self._publish(fresh)
        return fresh

    def _finish_unanswered(self, call: dict, *, final_state: str, reason: str) -> dict:
        if final_state == 'canceled':
            self.store.update(
                calls,
                call['id'],
                {
                    'state': 'canceled',
                    'ended_at': now_iso(),
                    'ended_reason': reason,
                    'duration_sec': self._elapsed_ms(call) // 1000,
                    'result_code': 'canceled',
                    'category': CALL_RESULT_CATEGORY.get('canceled', 'unanswered'),
                    'outcome': CALL_RESULT_OUTCOME.get('canceled', 'none'),
                    'intent_level': 'none',
                    'completed_at': now_iso(),
                },
            )
        fresh = self.store.get(calls, call['id'])
        if final_state == 'canceled':
            self._event(call['id'], 'canceled', 'canceled', {'reason': reason})
        self.tasks.on_call_finished(fresh, answered=False)
        list_item = self.store.get(list_items, fresh['list_item_id']) if fresh.get('list_item_id') else None
        self.writeback.enqueue_for_call(fresh, list_item=list_item, followup=None)
        self._publish(fresh)
        return fresh

    def _prepare_recording(self, call: dict, talk_seconds: int) -> dict:
        if self.provider.name != 'simulated':
            # 真实线路的录音由网关提供，回调里带 recording_url 才标 ready；
            # 这里绝不能用静音占位文件冒充真实录音。
            return {'recording_status': 'none', 'recording_seconds': 0, 'recording_url': None}
        if not self.settings.recording_enabled or talk_seconds <= 0:
            return {'recording_status': 'none', 'recording_seconds': 0, 'recording_url': None}
        seconds = min(max(1, int(talk_seconds)), RECORDING_MAX_SECONDS)
        path = Path(self.settings.recording_path) / (str(call['id']) + '.wav')
        try:
            self._write_placeholder(path, seconds)
        except OSError:
            LOGGER.warning('写入录音占位文件失败：%s', path, exc_info=True)
            return {
                'recording_status': 'missing',
                'recording_seconds': seconds,
                'recording_url': '/api/v1/calls/' + str(call['id']) + '/recording',
            }
        return {
            'recording_status': 'ready',
            'recording_seconds': seconds,
            'recording_url': '/api/v1/calls/' + str(call['id']) + '/recording',
        }

    @staticmethod
    def _write_placeholder(path: Path, seconds: int) -> None:
        '''生成一段静音 WAV 当录音占位：能播放、时长对得上，内容不是真录音。'''
        path.parent.mkdir(parents=True, exist_ok=True)
        frames = SILENCE_FRAME * int(8000 * max(1, seconds))
        with wave.open(str(path), 'wb') as handle:
            handle.setnchannels(1)
            handle.setsampwidth(1)
            handle.setframerate(8000)
            handle.writeframes(frames)

    # ---- 内部：辅助 ----
    def _event(self, call_id: str, event: str, state: str, detail: dict | None = None) -> None:
        seq = int(self.store.count(call_events, filters={'call_id': call_id})) + 1
        self.store.insert(
            call_events,
            {
                'id': new_id('cevent'),
                'call_id': call_id,
                'seq': seq,
                'at': now_iso(),
                'event': event,
                'state': state,
                'detail': detail or {},
            },
        )

    def _publish(self, call: dict) -> None:
        self.bus.publish(
            {
                'type': 'call',
                'call_id': call.get('id'),
                'state': call.get('state'),
                'state_label': CALL_STATE_LABELS.get(str(call.get('state')), ''),
                'result_code': call.get('result_code'),
                'result_label': CALL_RESULT_LABELS.get(str(call.get('result_code') or ''), ''),
                'agent_id': call.get('agent_id'),
                'team_id': call.get('agent_team_id'),
                'task_id': call.get('task_id'),
                'phone_masked': call.get('phone_masked'),
                'talk_sec': call.get('talk_sec'),
                'at': now_iso(),
            }
        )

    def by_provider_call_id(self, provider_call_id: str) -> dict | None:
        if not provider_call_id:
            return None
        return self.store.find_one(calls, provider_call_id=str(provider_call_id))

    def apply_provider_event(
        self,
        *,
        provider_call_id: str,
        state: str,
        result_code: str | None = None,
        talk_sec: int | None = None,
        recording_url: str | None = None,
        detail: dict | None = None,
    ) -> dict:
        '''真实线路回调：网关给的状态落到同一套状态机上。

        幂等：已经结束的通话收到迟到或重复的回调，直接返回现状，不改结果。
        '''
        call = self.by_provider_call_id(provider_call_id)
        if call is None:
            raise NotFound('找不到对应的通话：' + str(provider_call_id))
        if call['state'] in TERMINAL_STATES:
            # 已经结束：迟到或重复的回调不再改状态，但线路给的时长与录音是权威数据，必须吸收。
            # 典型场景：坐席先点挂断，线路随后回调真实通话时长与录音地址。
            details = self._line_details(talk_sec, recording_url)
            if details:
                self.store.update(calls, call['id'], details)
                self.audit.log(
                    None,
                    'provider_callback_late',
                    object_type='calls',
                    object_id=call['id'],
                    detail={'state': state, 'talk_sec': talk_sec, 'has_recording': bool(recording_url)},
                )
            return self.store.get(calls, call['id'])
        if state not in ('ringing', 'answered', 'hangup', 'canceled') and state not in TERMINAL_FAILURE_STATES:
            raise ValidationFailed('无法识别的线路状态：' + str(state))
        index = int(call.get('step_index') or 0)
        if state == 'ringing':
            self.store.update(calls, call['id'], {'state': 'ringing'})
            self._event(call['id'], 'ringing', 'ringing', detail)
            self._publish(self.store.get(calls, call['id']))
        elif state == 'answered':
            self._apply_state(call, 'answered', index)
        elif state == 'hangup':
            if call['state'] == 'answered':
                self._finish_answered(call, reason='provider')
            else:
                # 没接通就挂断，用网关给的结果码收尾，没给就记「已取消」
                self._apply_state(call, str(result_code or 'canceled'), index)
        else:
            self._apply_state(call, state, index)
        details = self._line_details(talk_sec, recording_url)
        if details:
            self.store.update(calls, call['id'], details)
        fresh = self.store.get(calls, call['id'])
        self.audit.log(
            None,
            'provider_callback',
            object_type='calls',
            object_id=call['id'],
            detail={
                'provider_call_id': provider_call_id,
                'state': state,
                'result_code': result_code,
                'talk_sec': talk_sec,
            },
        )
        return fresh

    @staticmethod
    def _line_details(talk_sec: int | None, recording_url: str | None) -> dict[str, Any]:
        '''线路回调里带的权威数据：真实通话时长与录音地址。'''
        values: dict[str, Any] = {}
        if talk_sec is not None:
            values['talk_sec'] = max(0, int(talk_sec))
        if recording_url:
            values.update(
                {
                    'recording_url': recording_url,
                    'recording_status': 'ready',
                    'recording_seconds': max(0, int(talk_sec or 0)),
                }
            )
        return values

    def active_call(self, actor: Actor) -> dict | None:
        '''当前坐席正在进行中的通话（没有就返回 None）。'''
        row = self._active_call(actor.user_id)
        return self.public_call(row, actor) if row else None

    def _active_call(self, agent_id: str) -> dict | None:
        rows = self.store.select(
            calls,
            calls.c.agent_id == agent_id,
            calls.c.state.in_(list(ACTIVE_CALL_STATES)),
            limit=1,
        )
        return rows[0] if rows else None

    def _load_call(self, actor: Actor, call_id: str) -> dict:
        call = self.store.get(calls, call_id)
        if call is None:
            raise NotFound('通话记录不存在')
        if actor.is_admin:
            return call
        if call.get('agent_id') == actor.user_id:
            return call
        if actor.is_manager and call.get('agent_team_id') == actor.team_id:
            return call
        raise Forbidden('无权查看该通话')

    def _scope(self, actor: Actor) -> Any:
        if actor.is_admin:
            return sa.true()
        if actor.is_manager:
            return sa.or_(
                calls.c.agent_id == actor.user_id, calls.c.agent_team_id == actor.team_id
            )
        return calls.c.agent_id == actor.user_id

    def _summary(self, conditions: list) -> dict[str, Any]:
        total = self.store.scalar(sa.select(sa.func.count()).select_from(calls).where(*conditions)) or 0
        answered = (
            self.store.scalar(
                sa.select(sa.func.count())
                .select_from(calls)
                .where(*conditions, calls.c.category == 'answered')
            )
            or 0
        )
        talk = (
            self.store.scalar(sa.select(sa.func.sum(calls.c.talk_sec)).select_from(calls).where(*conditions))
            or 0
        )
        positive = (
            self.store.scalar(
                sa.select(sa.func.count())
                .select_from(calls)
                .where(*conditions, calls.c.outcome == 'positive')
            )
            or 0
        )
        total_int = int(total)
        return {
            'total': total_int,
            'answered': int(answered),
            'unanswered': total_int - int(answered),
            'answer_rate': round(int(answered) / total_int, 4) if total_int else 0.0,
            'talk_seconds': int(talk),
            'avg_talk_seconds': round(int(talk) / int(answered), 1) if int(answered) else 0.0,
            'positive': int(positive),
        }

    def _talk_seconds(self, call: dict) -> int:
        answered_at = parse_iso(call.get('answered_at'))
        if answered_at is None:
            return 0
        ended_at = parse_iso(call.get('ended_at')) or parse_iso(now_iso())
        return max(0, int((ended_at - answered_at).total_seconds()))

    def _elapsed_ms(self, call: dict) -> int:
        started = parse_iso(call.get('started_at'))
        if started is None:
            return 0
        return max(0, int((parse_iso(now_iso()) - started).total_seconds() * 1000))

    def _page_size(self, value: int | None) -> int:
        size = int(value or self.settings.default_page_size)
        return max(1, min(size, int(self.settings.max_page_size)))

    def _agent_names(self, agent_ids: list[Any]) -> dict[str, str]:
        '''一次查出这批通话的坐席姓名，避免列表里逐行查库。'''
        ids = sorted({str(value) for value in agent_ids if value})
        if not ids:
            return {}
        rows = self.store.select(users, filters={'id': ids})
        return {str(row['id']): str(row.get('name') or row['id']) for row in rows}

    def _agent_name(self, agent_id: Any) -> str:
        if not agent_id:
            return ''
        row = self.store.get(users, str(agent_id))
        return str(row.get('name') or agent_id) if row else str(agent_id)

    def public_call(
        self,
        row: dict | None,
        actor: Actor,
        *,
        reveal: bool = False,
        audit_reveal: bool = False,
        agent_name: str | None = None,
    ) -> dict:
        call = dict(row or {})
        full = str(call.get('phone') or '')
        masked = str(call.get('phone_masked') or mask_phone(full))
        show_full = bool(reveal and actor.is_admin)
        if show_full and audit_reveal:
            self.compliance.display_phone(full, actor, reveal_reason='查看通话详情全号')
        call['phone_masked'] = masked
        call['phone'] = full if show_full else masked
        call['state_label'] = CALL_STATE_LABELS.get(str(call.get('state')), str(call.get('state') or ''))
        call['result_label'] = CALL_RESULT_LABELS.get(str(call.get('result_code') or ''), '')
        call['category_label'] = CATEGORY_LABELS.get(str(call.get('category') or ''), '')
        call['outcome_label'] = OUTCOME_LABELS.get(str(call.get('outcome') or ''), '')
        call['intent_label'] = INTENT_LABELS.get(str(call.get('intent_level') or ''), '')
        call['agent_name'] = (
            agent_name if agent_name is not None else self._agent_name(call.get('agent_id'))
        )
        return call