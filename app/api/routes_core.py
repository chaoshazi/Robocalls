'''健康检查、登录与元数据。'''

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request

from app import __version__
from app.adapters.tables import users
from app.api.deps import client_ip, current_actor, get_container
from app.contract import meta_payload
from app.domain import Actor

health_router = APIRouter(tags=['health'])
auth_router = APIRouter(prefix='/api/auth', tags=['auth'])
api_router = APIRouter(prefix='/api/v1', tags=['wahu'])


@health_router.get('/health')
def health(request: Request) -> dict[str, Any]:
    container = get_container(request)
    payload: dict[str, Any] = {'version': __version__, 'service': '外呼系统'}
    payload.update(container.health())
    return payload


@auth_router.post('/login')
def login(request: Request, payload: dict[str, Any] = Body(default=None)) -> dict[str, Any]:
    container = get_container(request)
    data = payload or {}
    result = container.identity.login(
        str(data.get('email') or ''), str(data.get('password') or '')
    )
    container.audit.log(
        container.identity.actor_for_token(result['token']),
        'login',
        object_type='users',
        object_id=result['user']['id'],
        ip=client_ip(request),
    )
    return result


@auth_router.get('/me')
def me(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    container = get_container(request)
    user = container.store.get(users, actor.user_id)
    return {'user': container.identity.public_user(user)}


@auth_router.post('/password')
def change_password(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    data = payload or {}
    return get_container(request).identity.change_password(
        actor, str(data.get('old_password') or ''), str(data.get('new_password') or '')
    )


@api_router.get('/meta')
def meta(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    payload = meta_payload()
    payload['tenant_id'] = actor.tenant_id
    payload['me'] = {
        'id': actor.user_id,
        'name': actor.display,
        'role': actor.role,
        'team_id': actor.team_id,
    }
    return payload