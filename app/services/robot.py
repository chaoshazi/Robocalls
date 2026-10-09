'''AI 机器人外呼：话术脚本、机器人任务、会话轮次与人机转接。

机器人不另起一套链路：它复用同一批次、同一任务项、同一通话状态机与同一套合规拦截，
只是把「坐席点击拨号」换成「worker 自动取号」，把「坐席说话」换成「脚本引擎应答」。
'''

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from app.adapters.sql import Store
from app.adapters.tables import (
    calls,
    list_batches,
    list_items,
    robot_sessions,
    robot_tasks,
    scripts,
    task_items,
    tasks,
    users,
)
from app.contract import (
    ACTIVE_CALL_STATES,
    CALL_RESULT_LABELS,
    ROBOT_OUTCOME_LABELS,
    ROBOT_TASK_STATUS_LABELS,
    SCRIPT_STATUSES,
)
from app.core.clock import now_iso, parse_iso
from app.core.config import Settings
from app.core.ids import new_id
from app.domain import Actor
from app.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.robot.engine import ScriptEngine, guess_intent
from app.robot.llm import LlmClient, SimulatedVoice

LOGGER = logging.getLogger(__name__)

SESSION_IDLE_SECONDS = 90
RESULT_FOR_INTENT = {
    'A': 'deal',
    'B': 'interested',
    'C': 'not_interested',
    'D': 'not_interested',
    'none': 'connected',
}
OUTCOME_IN_PROGRESS = 'in_progress'
TRANSFER_FOLLOWUP = '机器人转人工：请回电跟进'


class RobotService:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        audit: Any,
        batches: Any,
        tasks: Any,
        calls: Any,
        llm: LlmClient | None = None,
        voice: SimulatedVoice | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.audit = audit
        self.batches = batches
        self.tasks = tasks
        self.calls = calls
        self.llm = llm or LlmClient(settings)
        self.voice = voice or SimulatedVoice()

    # ---- 话术脚本 ----
    def list_scripts(self, actor: Actor) -> dict[str, Any]:
        rows = self.store.select(scripts, order_by='updated_at', desc=True, limit=200)
        return {'data': [self.public_script(row) for row in rows]}

    def create_script(self, actor: Actor, payload: dict) -> dict:
        if not actor.is_manager:
            raise Forbidden('需要主管及以上权限')
        name = str(payload.get('name') or '').strip()
        if not name:
            raise ValidationFailed('脚本名称必填')
        content = payload.get('content') or {}
        if not isinstance(content, dict) or not content.get('nodes'):
            raise ValidationFailed('脚本内容至少要有一个节点（content.nodes）')
        status = str(payload.get('status') or 'draft')
        if status not in SCRIPT_STATUSES:
            raise ValidationFailed('脚本状态不合法')
        row = self.store.insert(
            scripts,
            {
                'id': new_id('script'),
                'name': name,
                'content': content,
                'status': status,
                'version': 1,
                'note': payload.get('note'),
                'created_by': actor.user_id,
            },
        )
        self.audit.log(actor, 'create_script', object_type='scripts', object_id=row['id'])
        return self.public_script(row)

    def update_script(self, actor: Actor, script_id: str, payload: dict) -> dict:
        if not actor.is_manager:
            raise Forbidden('需要主管及以上权限')
        row = self.store.get(scripts, script_id)
        if row is None:
            raise NotFound('脚本不存在')
        values: dict[str, Any] = {}
        if payload.get('name'):
            values['name'] = str(payload['name']).strip()
        if payload.get('note') is not None:
            values['note'] = payload['note']
        if payload.get('status'):
            if payload['status'] not in SCRIPT_STATUSES:
                raise ValidationFailed('脚本状态不合法')
            values['status'] = payload['status']
        if payload.get('content') is not None:
            if not isinstance(payload['content'], dict):
                raise ValidationFailed('content 必须是对象')
            values['content'] = payload['content']
            values['version'] = int(row.get('version') or 1) + 1
        if values:
            self.store.update(scripts, script_id, values)
        self.audit.log(actor, 'update_script', object_type='scripts', object_id=script_id)
        return self.public_script(self.store.get(scripts, script_id))

    # ---- 机器人任务 ----
    def list_robot_tasks(self, actor: Actor, *, status: str | None = None) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if status:
            filters['status'] = status
        rows = self.store.select(
            robot_tasks, filters=filters, order_by='created_at', desc=True, limit=200
        )
        return {'data': [self.public_robot_task(row) for row in rows]}

    def create_robot_task(self, actor: Actor, payload: dict) -> dict:
        if not actor.is_manager:
            raise Forbidden('需要主管及以上权限')
        name = str(payload.get('name') or '').strip()
        if not name:
            raise ValidationFailed('机器人任务名称必填')
        script = self.store.get(scripts, str(payload.get('script_id') or ''))
        if script is None:
            raise NotFound('话术脚本不存在')
        batch = self.store.get(list_batches, str(payload.get('batch_id') or ''))
        if batch is None:
            raise NotFound('名单批次不存在')
        concurrency = max(1, int(payload.get('concurrency') or self.settings.robot_concurrency))
        backing = self.tasks.create_task(
            actor,
            {
                'name': '[机器人] ' + name,
                'batch_id': batch['id'],
                'mode': 'robot',
                'status': 'draft',
                'priority': payload.get('priority') or 'normal',
                'team_id': payload.get('team_id') or actor.team_id,
                'max_attempts': int(payload.get('max_attempts') or 2),
                'dial_window_start': payload.get('dial_window_start'),
                'dial_window_end': payload.get('dial_window_end'),
                'note': '由机器人任务自动生成',
            },
        )
        row = self.store.insert(
            robot_tasks,
            {
                'id': new_id('robot'),
                'name': name,
                'script_id': script['id'],
                'batch_id': batch['id'],
                'backing_task_id': backing['id'],
                'team_id': payload.get('team_id') or actor.team_id,
                'status': 'draft',
                'concurrency': concurrency,
                'dial_window_start': payload.get('dial_window_start'),
                'dial_window_end': payload.get('dial_window_end'),
                'total': int((backing.get('progress') or {}).get('total') or 0),
                'note': payload.get('note'),
                'created_by': actor.user_id,
            },
        )
        self.audit.log(
            actor,
            'create_robot_task',
            object_type='robot_tasks',
            object_id=row['id'],
            detail={'script_id': script['id'], 'batch_id': batch['id']},
        )
        if payload.get('autostart'):
            return self.start(actor, row['id'])
        return self.public_robot_task(self.store.get(robot_tasks, row['id']))

    def start(self, actor: Actor, robot_task_id: str) -> dict:
        return self._switch(actor, robot_task_id, running=True)

    def pause(self, actor: Actor, robot_task_id: str) -> dict:
        return self._switch(actor, robot_task_id, running=False)

    def _switch(self, actor: Actor, robot_task_id: str, *, running: bool) -> dict:
        if not actor.is_manager:
            raise Forbidden('需要主管及以上权限')
        row = self.store.get(robot_tasks, robot_task_id)
        if row is None:
            raise NotFound('机器人任务不存在')
        self.tasks.update_task(actor, self._backing(row), {'status': 'active' if running else 'paused'})
        values: dict[str, Any] = {'status': 'running' if running else 'paused'}
        if running and not row.get('started_at'):
            values['started_at'] = now_iso()
        self.store.update(robot_tasks, robot_task_id, values)
        self.audit.log(
            actor,
            'start_robot_task' if running else 'pause_robot_task',
            object_type='robot_tasks',
            object_id=robot_task_id,
        )
        return self.public_robot_task(self.store.get(robot_tasks, robot_task_id))

    # ---- 会话 ----
    def list_sessions(self, actor: Actor, robot_task_id: str) -> dict[str, Any]:
        rows = self.store.select(
            robot_sessions,
            filters={'robot_task_id': robot_task_id},
            order_by='created_at',
            desc=True,
            limit=200,
        )
        return {'data': [self.public_session(row) for row in rows]}

    def get_session(self, actor: Actor, session_id: str) -> dict:
        return self.public_session(self._load_session(session_id))

    def turn(self, actor: Actor, session_id: str, *, text: str) -> dict:
        '''客户说了一句，机器人回一句；这一轮就写回会话与通话记录。'''
        session = self._load_session(session_id)
        call = self.store.get(calls, session.get('call_id') or '')
        if call is None or call.get('state') != 'answered':
            raise Conflict('这通电话当前不在通话中，无法继续对话')
        customer_text = str(text or '').strip()
        if not customer_text:
            raise ValidationFailed('客户发言不能为空')
        engine = ScriptEngine(self._script_content(session))
        variables = self._variables(call)
        reply = engine.respond(
            node_id=session.get('node_id'), customer_text=customer_text, variables=variables
        )
        say = reply.say
        if self.llm.enabled and not reply.end:
            polished = self.llm.complete(
                prompt=engine.prompt(transcript=session.get('transcript') or [], variables=variables)
            )
            if polished:
                say = polished
                reply.used_llm = True
        transcript = list(session.get('transcript') or [])
        transcript.append({'role': 'customer', 'text': customer_text, 'at': now_iso()})
        transcript.append(
            {
                'role': 'robot',
                'text': say,
                'at': now_iso(),
                'node': reply.next_node,
                'llm': reply.used_llm,
            }
        )
        intent = reply.intent or session.get('intent_level')
        outcome = 'transferred' if reply.transfer else ('completed' if reply.end else OUTCOME_IN_PROGRESS)
        self.store.update(
            robot_sessions,
            session_id,
            {
                'node_id': reply.next_node,
                'turn_count': int(session.get('turn_count') or 0) + 1,
                'intent_level': intent,
                'outcome': outcome,
                'transcript': transcript,
            },
        )
        self.voice.turn(say=say)
        if reply.transfer:
            return self.transfer(actor, session_id)
        if reply.end:
            self._close(session_id, outcome='completed')
        return self.get_session(actor, session_id)

    def transfer(self, actor: Actor, session_id: str, *, assignee_id: str | None = None) -> dict:
        '''转人工：把人重新派回坐席队列，并让机器人这通电话收尾。'''
        session = self._load_session(session_id)
        call = self.store.get(calls, session.get('call_id') or '')
        target = str(assignee_id or '').strip() or self._default_agent(call)
        # 先让机器人这通电话收尾（收尾会把任务项置为已完成），再把任务项打回坐席队列
        self._close(session_id, outcome='transferred', followup=TRANSFER_FOLLOWUP)
        if call and call.get('task_item_id'):
            values: dict[str, Any] = {'next_attempt_at': None, 'attempts': 0, 'status': 'pending'}
            if target:
                values['assignee_id'] = target
            self.store.update(task_items, call['task_item_id'], values)
        detail = self.get_session(actor, session_id)
        detail['assigned_to'] = target
        return detail

    def close_idle(self) -> int:
        '''持续没人应话的会话自动收尾，避免通话挂着不放。'''
        rows = self.store.select(
            robot_sessions,
            filters={'outcome': OUTCOME_IN_PROGRESS},
            order_by='updated_at',
            desc=False,
            limit=50,
        )
        closed = 0
        moment = parse_iso(now_iso())
        for row in rows:
            updated = parse_iso(row.get('updated_at'))
            if updated is None or (moment - updated).total_seconds() < SESSION_IDLE_SECONDS:
                continue
            self._close(row['id'], outcome='aborted')
            closed += 1
        return closed

    def summary(self, actor: Actor) -> dict[str, Any]:
        total = self.store.count(robot_sessions)
        by_outcome = {
            outcome: self.store.count(robot_sessions, filters={'outcome': outcome})
            for outcome in ('completed', 'transferred', 'aborted', OUTCOME_IN_PROGRESS)
        }
        by_intent = {
            level: self.store.count(robot_sessions, filters={'intent_level': level})
            for level in ('A', 'B', 'C', 'D', 'none')
        }
        turns = (
            self.store.scalar(sa.select(sa.func.coalesce(sa.func.sum(robot_sessions.c.turn_count), 0))) or 0
        )
        return {
            'sessions': int(total),
            'running_tasks': self.store.count(robot_tasks, filters={'status': 'running'}),
            'robot_calls': self.store.count(calls, calls.c.robot_task_id.isnot(None)),
            'avg_turns': round(float(turns) / total, 2) if total else 0.0,
            'by_outcome': by_outcome,
            'by_intent': by_intent,
        }

    # ---- 工作循环 ----
    def run_once(self) -> dict[str, Any]:
        stats = {'dialed': 0, 'sessions': 0, 'closed': 0}
        for row in self.store.select(robot_tasks, filters={'status': 'running'}, limit=20):
            stats['dialed'] += self._dial_round(row)
            stats['sessions'] += self._open_sessions(row)
        stats['closed'] = self.close_idle()
        return stats

    def _dial_round(self, row: dict) -> int:
        backing_id = self._backing(row)
        slots = max(1, int(row.get('concurrency') or 1))
        busy = {
            str(call.get('agent_id'))
            for call in self.store.select(
                calls,
                calls.c.robot_task_id == row['id'],
                calls.c.state.in_(list(ACTIVE_CALL_STATES)),
            )
        }
        dialed = 0
        for index in range(slots):
            actor = self._slot_actor(row, index)
            if actor.user_id in busy:
                continue
            item = self._claim_item(backing_id, actor.user_id)
            if item is None:
                break
            try:
                self.calls.dial(actor, task_item_id=item['id'], robot_task_id=row['id'])
            except Exception as error:
                LOGGER.info('机器人拨号被拦下或失败：%s', error)
                self.store.update(task_items, item['id'], {'assignee_id': None, 'status': 'pending'})
                break
            dialed += 1
        return dialed

    def _open_sessions(self, row: dict) -> int:
        opened = 0
        engine = ScriptEngine(self._content_by_id(row.get('script_id')))
        answered = self.store.select(
            calls, calls.c.robot_task_id == row['id'], calls.c.state == 'answered', limit=50
        )
        for call in answered:
            if self.store.find_one(robot_sessions, call_id=call['id']) is not None:
                continue
            variables = self._variables(call)
            opening = engine.opening(variables)
            self.store.insert(
                robot_sessions,
                {
                    'id': new_id('session'),
                    'robot_task_id': row['id'],
                    'call_id': call['id'],
                    'list_item_id': call.get('list_item_id'),
                    'phone_masked': call.get('phone_masked'),
                    'node_id': engine.first_node(),
                    'turn_count': 0,
                    'intent_level': None,
                    'outcome': OUTCOME_IN_PROGRESS,
                    'transcript': [
                        {'role': 'robot', 'text': opening, 'at': now_iso(), 'node': engine.first_node()}
                    ],
                    'summary': None,
                },
            )
            self.voice.start(opening=opening)
            opened += 1
        return opened

    def _claim_item(self, backing_task_id: str, agent_id: str) -> dict | None:
        items = self.store.select(
            task_items,
            task_items.c.task_id == backing_task_id,
            task_items.c.status == 'pending',
            task_items.c.assignee_id.is_(None),
            order_by='created_at',
            desc=False,
            limit=1,
        )
        if not items:
            return None
        self.store.update(task_items, items[0]['id'], {'assignee_id': agent_id})
        return items[0]

    def _close(self, session_id: str, *, outcome: str, followup: str | None = None) -> dict | None:
        session = self.store.get(robot_sessions, session_id)
        if session is None:
            return None
        call = self.store.get(calls, session.get('call_id') or '')
        transcript = list(session.get('transcript') or [])
        intent = session.get('intent_level') or guess_intent(transcript)
        summary = self._summary_text(transcript)
        self.store.update(
            robot_sessions, session_id, {'outcome': outcome, 'intent_level': intent, 'summary': summary}
        )
        if call is not None:
            actor = self._system_actor(call)
            if call.get('state') in ('dialing', 'ringing', 'answered'):
                try:
                    self.calls.hangup(actor, call['id'])
                except Exception:
                    LOGGER.info('机器人收尾挂断失败：%s', call['id'], exc_info=True)
            fresh = self.store.get(calls, call['id']) or call
            if not fresh.get('completed_at'):
                try:
                    self.calls.complete(
                        actor,
                        call['id'],
                        {
                            'result_code': RESULT_FOR_INTENT.get(str(intent), 'connected'),
                            'intent_level': str(intent),
                            'note': summary,
                            'followup_subject': followup,
                            'followup_priority': 'high' if followup else None,
                        },
                    )
                except Exception:
                    LOGGER.info('机器人结果落库失败：%s', call['id'], exc_info=True)
        self._bump(session.get('robot_task_id'), transferred=outcome == 'transferred')
        return self.store.get(robot_sessions, session_id)

    def _bump(self, robot_task_id: str | None, *, transferred: bool) -> None:
        if not robot_task_id:
            return
        row = self.store.get(robot_tasks, robot_task_id)
        if row is None:
            return
        values: dict[str, Any] = {'done': int(row.get('done') or 0) + 1}
        if transferred:
            values['transferred'] = int(row.get('transferred') or 0) + 1
        self.store.update(robot_tasks, robot_task_id, values)

    # ---- 内部 ----
    def _content_by_id(self, script_id: str | None) -> dict:
        if not script_id:
            return {}
        row = self.store.get(scripts, str(script_id))
        return dict(row.get('content') or {}) if row else {}

    def _script_content(self, session: dict) -> dict:
        row = self.store.get(robot_tasks, session.get('robot_task_id') or '')
        return self._content_by_id(row.get('script_id') if row else None)

    def _variables(self, call: dict) -> dict[str, Any]:
        item = self.store.get(list_items, call.get('list_item_id') or '')
        return {
            'name': (item or {}).get('contact_name') or (item or {}).get('name') or '您',
            'company': (item or {}).get('company') or '',
            'phone': call.get('phone_masked') or '',
        }

    def _default_agent(self, call: dict | None) -> str:
        if not call:
            return ''
        team_id = call.get('agent_team_id')
        if not team_id:
            return ''
        rows = self.store.select(users, filters={'team_id': team_id, 'role': ('agent', 'manager')})
        return str(rows[0]['id']) if rows else ''

    @staticmethod
    def _slot_actor(row: dict, index: int) -> Actor:
        return Actor(
            user_id='robot-' + str(row.get('id')) + '-s' + str(index),
            role='agent',
            team_id=row.get('team_id'),
            tenant_id='default',
            display='AI 机器人',
        )

    @staticmethod
    def _system_actor(call: dict) -> Actor:
        return Actor(
            user_id=str(call.get('agent_id') or 'robot-system'),
            role='agent',
            team_id=call.get('agent_team_id'),
            tenant_id='default',
            display='AI 机器人',
        )

    def _backing(self, row: dict) -> str:
        value = str(row.get('backing_task_id') or '')
        if not value:
            raise NotFound('机器人任务缺少对应的外呼任务，请重建')
        return value

    def _load_session(self, session_id: str) -> dict:
        row = self.store.get(robot_sessions, session_id)
        if row is None:
            raise NotFound('机器人会话不存在')
        return row

    @staticmethod
    def _summary_text(transcript: list[dict]) -> str:
        parts = []
        for turn in transcript[-6:]:
            who = '客户' if str(turn.get('role')) == 'customer' else '机器人'
            parts.append(who + '：' + str(turn.get('text') or ''))
        return ' / '.join(parts)

    def public_script(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        data = dict(row)
        engine = ScriptEngine(data.get('content') or {})
        data['node_count'] = len(engine.nodes)
        return data

    def public_robot_task(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        data = dict(row)
        data['status_label'] = ROBOT_TASK_STATUS_LABELS.get(
            str(row.get('status')), str(row.get('status'))
        )
        return data

    def public_session(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        data = dict(row)
        data['outcome_label'] = ROBOT_OUTCOME_LABELS.get(str(row.get('outcome')), str(row.get('outcome')))
        data['result_label'] = CALL_RESULT_LABELS.get(
            RESULT_FOR_INTENT.get(str(row.get('intent_level')), ''), ''
        )
        return data


def active_states() -> tuple[str, ...]:
    return ACTIVE_CALL_STATE_LIST