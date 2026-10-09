'''外呼任务与坐席工作台。'''

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request

from app.api.deps import current_actor, get_container
from app.domain import Actor

api_router = APIRouter(prefix='/api/v1', tags=['tasks'])


@api_router.get('/tasks')
def list_tasks(
    request: Request,
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    search: str | None = Query(default=None),
    mine: bool = Query(default=False),
    page: int = Query(default=1),
    page_size: int | None = Query(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).tasks.list_tasks(
        actor, status=status, mode=mode, search=search, mine=mine, page=page, page_size=page_size
    )


@api_router.post('/tasks')
def create_task(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).tasks.create_task(actor, payload or {})


@api_router.get('/tasks/{task_id}')
def get_task(
    request: Request, task_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).tasks.get_task(actor, task_id)


@api_router.patch('/tasks/{task_id}')
def update_task(
    request: Request,
    task_id: str,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).tasks.update_task(actor, task_id, payload or {})


@api_router.delete('/tasks/{task_id}')
def delete_task(
    request: Request, task_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).tasks.delete_task(actor, task_id)


@api_router.post('/tasks/{task_id}/claim')
def claim_task(
    request: Request, task_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).tasks.claim_task(actor, task_id)


@api_router.post('/tasks/{task_id}/release')
def release_task(
    request: Request, task_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).tasks.release_task(actor, task_id)


@api_router.post('/tasks/{task_id}/assign')
def assign_items(
    request: Request,
    task_id: str,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    data = payload or {}
    return get_container(request).tasks.assign_items(
        actor,
        task_id,
        assignee_id=str(data.get('assignee_id') or ''),
        limit=int(data.get('limit') or 50),
    )


@api_router.post('/tasks/{task_id}/generate')
def generate_items(
    request: Request,
    task_id: str,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    data = payload or {}
    container = get_container(request)
    container.tasks.get_task(actor, task_id)
    created = container.tasks.generate_items(actor, task_id, limit=data.get('limit'))
    return {'created': created}


@api_router.get('/tasks/{task_id}/items')
def list_task_items(
    request: Request,
    task_id: str,
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int | None = Query(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).tasks.list_items(
        actor, task_id, status=status, search=search, page=page, page_size=page_size
    )


@api_router.post('/task-items/{item_id}/skip')
def skip_item(
    request: Request, item_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).tasks.skip_item(actor, item_id)


# ---- 坐席工作台 ----
@api_router.get('/workbench/next')
def workbench_next(
    request: Request,
    task_id: str | None = Query(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    container = get_container(request)
    item = container.tasks.next_item(actor, task_id=task_id)
    due = container.tasks.due_count(actor, task_id=task_id)
    return {
        'item': item,
        'due': due,
        # pending 里还没过重呼冷却的：队列看着是空的，其实是在等回拨时间
        'cooling': container.tasks.pending_count(actor, task_id=task_id) - due,
        'active_call': container.calls.active_call(actor),
        'compliance': container.compliance.get_settings(),
    }


@api_router.get('/workbench/summary')
def workbench_summary(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    container = get_container(request)
    return {
        'due': container.tasks.due_count(actor),
        'today_calls': container.compliance.daily_agent_count(actor.user_id),
        'compliance': container.compliance.get_settings(),
        'reports': container.reports.overview(actor, days=1),
    }