'''合规：黑名单 / 免打扰时段 / 拨打频次 / 号码脱敏。

原则是「拦下来并说清楚为什么」，任何一次拦截都会写审计，坐席与主管在报表里能看到拦截量。
'''

from __future__ import annotations

from typing import Any

from app.adapters.sql import Store
from app.adapters.tables import blacklist, calls, settings_table, tasks
from app.core.clock import in_window, minutes_of_day, now, today_str
from app.core.config import Settings
from app.core.ids import new_id
from app.core.phone import mask_phone, normalize_phone
from app.domain import Actor
from app.errors import Blocked, Forbidden, NotFound, ValidationFailed

COMPLIANCE_KEY = 'compliance'


class ComplianceService:
    def __init__(self, store: Store, settings: Settings, audit: Any) -> None:
        self.store = store
        self.settings = settings
        self.audit = audit

    # ---- 设置 ----
    def defaults(self) -> dict[str, Any]:
        return {
            'dnd_start': self.settings.compliance_dnd_start,
            'dnd_end': self.settings.compliance_dnd_end,
            'daily_limit': self.settings.compliance_daily_limit,
            'per_number_daily_limit': self.settings.compliance_per_number_daily_limit,
            'mask_phone': self.settings.compliance_mask_phone,
        }

    def get_settings(self) -> dict[str, Any]:
        merged = self.defaults()
        row = self.store.find_one(settings_table, key=COMPLIANCE_KEY)
        if row and isinstance(row.get('value'), dict):
            merged.update({key: value for key, value in row['value'].items() if value is not None})
        merged['source'] = 'runtime' if row else 'env'
        return merged

    def update_settings(self, actor: Actor, payload: dict) -> dict[str, Any]:
        if not actor.is_manager:
            raise Forbidden('需要主管及以上权限')
        current = self.get_settings()
        allowed = ('dnd_start', 'dnd_end', 'daily_limit', 'per_number_daily_limit', 'mask_phone')
        for key in allowed:
            if key in payload and payload[key] is not None:
                current[key] = payload[key]
        # 只落库覆盖项，环境变量仍是最初的默认值
        override = {key: current[key] for key in allowed}
        _validate_window(str(override['dnd_start']), str(override['dnd_end']))
        row = self.store.find_one(settings_table, key=COMPLIANCE_KEY)
        if row is None:
            self.store.insert(
                settings_table,
                {'key': COMPLIANCE_KEY, 'value': override, 'updated_by': actor.user_id},
            )
        else:
            self.store.update_where(
                settings_table,
                [settings_table.c.key == COMPLIANCE_KEY],
                {'value': override, 'updated_by': actor.user_id},
            )
        self.audit.log(
            actor, 'update_compliance', object_type='settings', object_id=COMPLIANCE_KEY, detail=override
        )
        return self.get_settings()

    # ---- 黑名单 ----
    def list_blacklist(
        self,
        actor: Actor,
        *,
        scope: str | None = None,
        search: str | None = None,
        active_only: bool = True,
        limit: int = 200,
    ) -> list[dict]:
        filters: dict[str, Any] = {}
        if scope:
            filters['scope'] = scope
        if active_only:
            filters['is_active'] = True
        return self.store.select(
            blacklist,
            filters=filters,
            order_by='created_at',
            desc=True,
            limit=max(1, min(int(limit), 500)),
            search=search,
            search_fields=('phone', 'value', 'reason', 'crm_record_id'),
        )

    def create_blacklist(self, actor: Actor, payload: dict) -> dict:
        if not actor.is_manager:
            raise Forbidden('需要主管及以上权限')
        scope = str(payload.get('scope') or 'phone')
        if scope not in ('phone', 'customer'):
            raise ValidationFailed('scope 只能是 phone 或 customer')
        phone = normalize_phone(payload.get('phone') or '')
        crm_record_id = str(payload.get('crm_record_id') or '').strip()
        if scope == 'phone' and not phone:
            raise ValidationFailed('号码不能为空')
        if scope == 'customer' and not crm_record_id:
            raise ValidationFailed('客户 ID 不能为空')
        value = phone if scope == 'phone' else crm_record_id
        if self.store.find_one(blacklist, scope=scope, value=value, is_active=True) is not None:
            raise ValidationFailed('该条目已在黑名单中')
        row = self.store.insert(
            blacklist,
            {
                'id': new_id('blacklist'),
                'scope': scope,
                'phone': phone or None,
                'crm_record_id': crm_record_id or None,
                'value': value,
                'reason': str(payload.get('reason') or '').strip(),
                'created_by': actor.user_id,
                'is_active': True,
                'expires_at': payload.get('expires_at'),
            },
        )
        self.audit.log(
            actor, 'create_blacklist', object_type='blacklist', object_id=row['id'], detail={'scope': scope, 'value': value}
        )
        return row

    def remove_blacklist(self, actor: Actor, entry_id: str) -> dict:
        if not actor.is_manager:
            raise Forbidden('需要主管及以上权限')
        row = self.store.get(blacklist, entry_id)
        if row is None:
            raise NotFound('黑名单条目不存在')
        self.store.update(blacklist, entry_id, {'is_active': False})
        self.audit.log(actor, 'remove_blacklist', object_type='blacklist', object_id=entry_id)
        return self.store.get(blacklist, entry_id)

    def match_blacklist(self, *, phone: str, crm_record_id: str | None = None) -> dict | None:
        normalized = normalize_phone(phone)
        if normalized:
            hit = self.store.find_one(blacklist, scope='phone', value=normalized, is_active=True)
            if hit:
                return hit
        if crm_record_id:
            hit = self.store.find_one(
                blacklist, scope='customer', value=str(crm_record_id), is_active=True
            )
            if hit:
                return hit
        return None

    # ---- 拦截 ----
    def daily_agent_count(self, agent_id: str) -> int:
        return self.store.count(
            calls, calls.c.started_at.like(today_str() + '%'), filters={'agent_id': agent_id}
        )

    def daily_number_count(self, phone: str) -> int:
        normalized = normalize_phone(phone)
        return self.store.count(
            calls,
            calls.c.started_at.like(today_str() + '%'),
            calls.c.state != 'canceled',
            filters={'phone': normalized},
        )

    def ensure_dialable(
        self,
        actor: Actor,
        *,
        phone: str,
        crm_record_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        '''任何一条不满足就抛 Blocked；调用方负责把原因写给用户。'''
        config = self.get_settings()
        hit = self.match_blacklist(phone=phone, crm_record_id=crm_record_id)
        if hit:
            self.audit.log(
                actor,
                'block_blacklist',
                object_type='blacklist',
                object_id=hit['id'],
                detail={'phone': mask_phone(normalize_phone(phone)), 'scope': hit['scope']},
            )
            raise Blocked(
                '该号码或客户在黑名单中，禁止外呼',
                code='blacklisted',
                extra={'blacklist_id': hit['id'], 'reason': hit.get('reason')},
            )

        moment = minutes_of_day(now())
        start = _clock(str(config['dnd_start']))
        end = _clock(str(config['dnd_end']))
        if in_window(moment, start, end):
            raise Blocked(
                '当前处于免打扰时段（' + str(config['dnd_start']) + '–' + str(config['dnd_end']) + '），禁止外呼',
                code='dnd_window',
                extra={'dnd_start': config['dnd_start'], 'dnd_end': config['dnd_end']},
            )

        if task_id:
            task = self.store.get(tasks, task_id)
            if task and (task.get('dial_window_start') or task.get('dial_window_end')):
                window_start = _clock(str(task.get('dial_window_start') or '00:00'))
                window_end = _clock(str(task.get('dial_window_end') or '23:59'))
                if not in_window(moment, window_start, window_end):
                    raise Blocked(
                        '任务设置了拨打时段 '
                        + str(task.get('dial_window_start'))
                        + '–'
                        + str(task.get('dial_window_end')),
                        code='task_window',
                    )

        used = self.daily_agent_count(actor.user_id)
        limit = int(config['daily_limit'] or 0)
        if limit and used >= limit:
            raise Blocked(
                '今日拨打已达上限（' + str(limit) + ' 通）',
                code='daily_limit',
                extra={'used': used, 'limit': limit},
            )

        per_number = int(config['per_number_daily_limit'] or 0)
        if per_number:
            times = self.daily_number_count(phone)
            if times >= per_number:
                self.audit.log(
                    actor,
                    'block_number_limit',
                    object_type='calls',
                    detail={'phone': mask_phone(normalize_phone(phone)), 'times': times},
                )
                raise Blocked(
                    '该号码今日已被拨打 ' + str(times) + ' 次，达到上限',
                    code='number_limit',
                    extra={'times': times, 'limit': per_number},
                )

    # ---- 展示 ----
    def display_phone(self, phone: str, actor: Actor, *, reveal_reason: str = '查看全号') -> str:
        '''默认脱敏；管理员可看全号，但每次查看都留审计。'''
        config = self.get_settings()
        if not config.get('mask_phone', True):
            return str(phone)
        if actor.is_admin:
            self.audit.log(
                actor,
                'view_full_phone',
                object_type='calls',
                detail={'phone_masked': mask_phone(str(phone)), 'reason': reveal_reason},
            )
            return str(phone)
        return mask_phone(str(phone))


def _clock(value: str) -> int:
    from app.core.config import parse_clock

    try:
        return parse_clock(value)
    except ValueError as error:
        # 配置错误要变成 422，而不是让 500 冒到用户面前
        raise ValidationFailed('时间格式必须是 HH:MM：' + str(value)) from error


def _validate_window(start: str, end: str) -> None:
    _clock(start)
    _clock(end)