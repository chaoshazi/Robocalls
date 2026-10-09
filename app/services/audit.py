'''审计：谁在什么时候对什么对象做了什么。

号码全号查看、合规拦截、任务分派、CRM 回写都会留痕；列表接口按角色收窄。
'''

from __future__ import annotations

from typing import Any

from app.adapters.sql import Store
from app.adapters.tables import audit_logs
from app.core.clock import now_iso
from app.core.ids import new_id


class AuditService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def log(
        self,
        actor: Any,
        action: str,
        *,
        object_type: str | None = None,
        object_id: str | None = None,
        detail: dict | None = None,
        ip: str | None = None,
    ) -> dict:
        row = {
            'id': new_id('audit'),
            'at': now_iso(),
            'actor_id': getattr(actor, 'user_id', None) if actor else None,
            'actor_name': getattr(actor, 'display', None) if actor else None,
            'actor_role': getattr(actor, 'role', None) if actor else None,
            'action': action,
            'object_type': object_type,
            'object_id': object_id,
            'detail': detail or {},
            'ip': ip,
        }
        return self.store.insert(audit_logs, row)

    def list(
        self,
        actor: Any,
        *,
        limit: int = 100,
        object_type: str | None = None,
        object_id: str | None = None,
        action: str | None = None,
        actor_id: str | None = None,
    ) -> list[dict]:
        filters: dict[str, Any] = {}
        if object_type:
            filters['object_type'] = object_type
        if object_id:
            filters['object_id'] = object_id
        if action:
            filters['action'] = action
        # 管理员看全部；其余人只能看自己造成的记录
        if not getattr(actor, 'sees_all', False):
            filters['actor_id'] = actor.user_id
        elif actor_id:
            filters['actor_id'] = actor_id
        return self.store.select(
            audit_logs,
            filters=filters,
            order_by='at',
            desc=True,
            limit=max(1, min(int(limit), 500)),
        )