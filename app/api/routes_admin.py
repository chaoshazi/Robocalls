'''组织与治理：用户、团队、黑名单、合规设置、审计。'''

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request

from app.api.deps import current_actor, get_container, require_admin, require_manager
from app.domain import Actor

api_router = APIRouter(prefix='/api/v1', tags=['admin'])


# ---- 用户与团队 ----
@api_router.get('/users')
def list_users(request: Request, actor: Actor = Depends(require_manager)) -> dict[str, Any]:
    return {'data': get_container(request).identity.list_users(actor)}


@api_router.post('/users')
def create_user(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(require_admin),
) -> dict[str, Any]:
    return get_container(request).identity.create_user(actor, payload or {})


@api_router.patch('/users/{user_id}')
def update_user(
    request: Request,
    user_id: str,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(require_admin),
) -> dict[str, Any]:
    return get_container(request).identity.update_user(actor, user_id, payload or {})


@api_router.get('/teams')
def list_teams(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    return {'data': get_container(request).identity.list_teams(actor)}


@api_router.post('/teams')
def create_team(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(require_admin),
) -> dict[str, Any]:
    return get_container(request).identity.create_team(actor, payload or {})


@api_router.patch('/teams/{team_id}')
def update_team(
    request: Request,
    team_id: str,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(require_admin),
) -> dict[str, Any]:
    return get_container(request).identity.update_team(actor, team_id, payload or {})


# ---- 黑名单 ----
@api_router.get('/blacklist')
def list_blacklist(
    request: Request,
    scope: str | None = Query(default=None),
    search: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    limit: int = Query(default=200),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return {
        'data': get_container(request).compliance.list_blacklist(
            actor, scope=scope, search=search, active_only=active_only, limit=limit
        )
    }


@api_router.post('/blacklist')
def create_blacklist(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(require_manager),
) -> dict[str, Any]:
    return get_container(request).compliance.create_blacklist(actor, payload or {})


@api_router.delete('/blacklist/{entry_id}')
def delete_blacklist(
    request: Request, entry_id: str, actor: Actor = Depends(require_manager)
) -> dict[str, Any]:
    return get_container(request).compliance.remove_blacklist(actor, entry_id)


# ---- 合规设置 ----
@api_router.get('/settings/compliance')
def get_compliance(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    return get_container(request).compliance.get_settings()


@api_router.put('/settings/compliance')
def update_compliance(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(require_manager),
) -> dict[str, Any]:
    return get_container(request).compliance.update_settings(actor, payload or {})


# ---- 审计 ----
@api_router.get('/audit')
def list_audit(
    request: Request,
    object_type: str | None = Query(default=None),
    object_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    limit: int = Query(default=100),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return {
        'data': get_container(request).audit.list(
            actor,
            limit=limit,
            object_type=object_type,
            object_id=object_id,
            action=action,
            actor_id=actor_id,
        )
    }