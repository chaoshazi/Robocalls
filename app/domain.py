'''领域对象：操作者身份。'''

from __future__ import annotations

from dataclasses import dataclass

ROLE_ADMIN = 'admin'
ROLE_MANAGER = 'manager'
ROLE_AGENT = 'agent'


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: str
    team_id: str | None
    tenant_id: str
    display: str = ''

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_manager(self) -> bool:
        return self.role in (ROLE_ADMIN, ROLE_MANAGER)

    @property
    def sees_all(self) -> bool:
        return self.is_admin