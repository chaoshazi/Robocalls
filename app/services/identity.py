'''账号、团队与登录。'''

from __future__ import annotations

from typing import Any

from app.adapters.sql import Store
from app.adapters.tables import teams, users
from app.core.config import Settings
from app.core.ids import new_id
from app.core.security import hash_password, issue_token, verify_password
from app.domain import Actor
from app.errors import AuthError, Conflict, Forbidden, NotFound, ValidationFailed

DEFAULT_TEAM_NAME = '销售一部'


class IdentityService:
    def __init__(self, store: Store, settings: Settings, audit: Any) -> None:
        self.store = store
        self.settings = settings
        self.audit = audit

    # ---- 初始化 ----
    def bootstrap(self) -> dict[str, Any]:
        '''首次启动：建一个默认团队与管理员账号（仅当 users 表为空）。'''
        if self.store.count(users) > 0:
            return {'created': False}
        team = self.store.find_one(teams, name=DEFAULT_TEAM_NAME)
        if team is None:
            team = self.store.insert(
                teams, {'id': new_id('team'), 'name': DEFAULT_TEAM_NAME, 'note': '默认团队'}
            )
        admin = self.store.insert(
            users,
            {
                'id': new_id('user'),
                'name': self.settings.bootstrap_admin_name,
                'email': self.settings.bootstrap_admin_email,
                'password_hash': hash_password(self.settings.bootstrap_admin_password),
                'role': 'admin',
                'team_id': team['id'],
                'is_active': True,
            },
        )
        return {'created': True, 'user_id': admin['id'], 'team_id': team['id']}

    def default_team_id(self) -> str | None:
        team = self.store.find_one(teams, name=DEFAULT_TEAM_NAME)
        return team['id'] if team else None

    # ---- 登录 ----
    def login(self, email: str, password: str) -> dict[str, Any]:
        user = self.store.find_one(users, email=str(email or '').strip().lower())
        if user is None or not verify_password(password, user.get('password_hash') or ''):
            raise AuthError('邮箱或密码不正确')
        if not user.get('is_active', True):
            raise AuthError('账号已停用')
        token = issue_token(
            {
                'sub': user['id'],
                'role': user['role'],
                'team_id': user.get('team_id'),
                'tenant': self.settings.tenant_id,
            },
            self.settings.secret_key,
            self.settings.token_ttl_hours,
        )
        return {'token': token, 'user': self.public_user(user)}

    def actor_for_token(self, token: str) -> Actor:
        from app.core.security import read_token

        payload = read_token(token, self.settings.secret_key)
        if payload is None:
            raise AuthError('凭证无效或已过期')
        user = self.store.get(users, str(payload.get('sub') or ''))
        if user is None:
            raise AuthError('用户不存在')
        if not user.get('is_active', True):
            raise AuthError('账号已停用')
        return Actor(
            user_id=user['id'],
            role=user['role'],
            team_id=user.get('team_id'),
            tenant_id=self.settings.tenant_id,
            display=user.get('name') or user['id'],
        )

    def change_password(self, actor: Actor, old_password: str, new_password: str) -> dict:
        if len(str(new_password or '')) < 8:
            raise ValidationFailed('新密码至少 8 位')
        user = self.store.get(users, actor.user_id)
        if user is None:
            raise NotFound('用户不存在')
        if not verify_password(old_password, user.get('password_hash') or ''):
            raise AuthError('原密码不正确')
        self.store.update(users, actor.user_id, {'password_hash': hash_password(new_password)})
        self.audit.log(actor, 'change_password', object_type='users', object_id=actor.user_id)
        return {'detail': '密码已更新'}

    # ---- 用户 ----
    def list_users(self, actor: Actor) -> list[dict]:
        require_manager(actor)
        rows = self.store.select(users, order_by='created_at', desc=False)
        return [self.public_user(row) for row in rows]

    def create_user(self, actor: Actor, payload: dict) -> dict:
        require_admin(actor)
        email = str(payload.get('email') or '').strip().lower()
        if not email:
            raise ValidationFailed('邮箱必填')
        if self.store.find_one(users, email=email) is not None:
            raise Conflict('邮箱已存在')
        role = str(payload.get('role') or 'agent')
        if role not in ('admin', 'manager', 'agent'):
            raise ValidationFailed('角色不合法')
        password = str(payload.get('password') or '')
        if len(password) < 8:
            raise ValidationFailed('密码至少 8 位')
        team_id = payload.get('team_id') or self.default_team_id()
        row = self.store.insert(
            users,
            {
                'id': new_id('user'),
                'name': str(payload.get('name') or email.split('@')[0]),
                'email': email,
                'password_hash': hash_password(password),
                'role': role,
                'team_id': team_id,
                'is_active': bool(payload.get('is_active', True)),
            },
        )
        self.audit.log(actor, 'create_user', object_type='users', object_id=row['id'], detail={'role': role})
        return self.public_user(row)

    def update_user(self, actor: Actor, user_id: str, payload: dict) -> dict:
        require_admin(actor)
        user = self.store.get(users, user_id)
        if user is None:
            raise NotFound('用户不存在')
        values: dict[str, Any] = {}
        for key in ('name', 'team_id'):
            if key in payload:
                values[key] = payload[key]
        if 'role' in payload:
            if payload['role'] not in ('admin', 'manager', 'agent'):
                raise ValidationFailed('角色不合法')
            values['role'] = payload['role']
        if 'is_active' in payload:
            values['is_active'] = bool(payload['is_active'])
        if payload.get('password'):
            if len(str(payload['password'])) < 8:
                raise ValidationFailed('密码至少 8 位')
            values['password_hash'] = hash_password(str(payload['password']))
        if values:
            self.store.update(users, user_id, values)
        self.audit.log(actor, 'update_user', object_type='users', object_id=user_id, detail={'fields': sorted(values)})
        return self.public_user(self.store.get(users, user_id))

    def user_ids_of_team(self, team_id: str | None) -> list[str]:
        if not team_id:
            return []
        rows = self.store.select(users, filters={'team_id': team_id})
        return [row['id'] for row in rows]

    def user_map(self) -> dict[str, dict]:
        return {row['id']: row for row in self.store.select(users)}

    # ---- 团队 ----
    def list_teams(self, actor: Actor) -> list[dict]:
        return self.store.select(teams, order_by='created_at', desc=False)

    def create_team(self, actor: Actor, payload: dict) -> dict:
        require_admin(actor)
        name = str(payload.get('name') or '').strip()
        if not name:
            raise ValidationFailed('团队名称必填')
        if self.store.find_one(teams, name=name) is not None:
            raise Conflict('团队已存在')
        row = self.store.insert(teams, {'id': new_id('team'), 'name': name, 'note': payload.get('note')})
        self.audit.log(actor, 'create_team', object_type='teams', object_id=row['id'])
        return row

    def update_team(self, actor: Actor, team_id: str, payload: dict) -> dict:
        require_admin(actor)
        if self.store.get(teams, team_id) is None:
            raise NotFound('团队不存在')
        values = {key: payload[key] for key in ('name', 'note') if key in payload}
        if values:
            self.store.update(teams, team_id, values)
        self.audit.log(actor, 'update_team', object_type='teams', object_id=team_id)
        return self.store.get(teams, team_id)

    @staticmethod
    def public_user(row: dict | None) -> dict | None:
        if row is None:
            return None
        return {
            'id': row['id'],
            'name': row.get('name'),
            'email': row.get('email'),
            'role': row.get('role'),
            'team_id': row.get('team_id'),
            'is_active': bool(row.get('is_active', True)),
            'created_at': row.get('created_at'),
            'updated_at': row.get('updated_at'),
        }


def require_admin(actor: Actor) -> None:
    if not actor.is_admin:
        raise Forbidden('需要管理员权限')


def require_manager(actor: Actor) -> None:
    if not actor.is_manager:
        raise Forbidden('需要主管及以上权限')