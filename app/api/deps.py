'''依赖注入：容器、配置、操作者身份与权限门禁。'''

from __future__ import annotations

from fastapi import Depends, Header, Request

from app.container import Container
from app.domain import Actor
from app.errors import AuthError, Forbidden


def get_container(request: Request) -> Container:
    container = getattr(request.app.state, 'container', None)
    if container is None:
        raise RuntimeError('容器尚未初始化')
    return container


def _extract_token(authorization: str | None, api_token: str | None) -> str:
    if authorization:
        scheme, _, value = str(authorization).partition(' ')
        if scheme.lower() == 'bearer' and value.strip():
            return value.strip()
    return str(api_token or '').strip()


def current_actor(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
) -> Actor:
    token = _extract_token(authorization, x_api_token)
    if not token:
        raise AuthError('缺少访问凭证')
    return get_container(request).identity.actor_for_token(token)


def require_admin(actor: Actor = Depends(current_actor)) -> Actor:
    if not actor.is_admin:
        raise Forbidden('需要管理员权限')
    return actor


def require_manager(actor: Actor = Depends(current_actor)) -> Actor:
    if not actor.is_manager:
        raise Forbidden('需要主管及以上权限')
    return actor


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host if request.client else None