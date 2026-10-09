'''AI 机器人：话术脚本、机器人任务、会话轮次与转人工。'''

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request

from app.api.deps import current_actor, get_container
from app.domain import Actor

api_router = APIRouter(prefix='/api/v1', tags=['robot'])


# ---- 话术脚本 ----
@api_router.get('/scripts')
def list_scripts(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    return get_container(request).robot.list_scripts(actor)


@api_router.post('/scripts')
def create_script(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).robot.create_script(actor, payload or {})


@api_router.patch('/scripts/{script_id}')
def update_script(
    request: Request,
    script_id: str,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).robot.update_script(actor, script_id, payload or {})


# ---- 机器人任务 ----
@api_router.get('/robot-tasks')
def list_robot_tasks(
    request: Request,
    status: str | None = Query(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).robot.list_robot_tasks(actor, status=status)


@api_router.post('/robot-tasks')
def create_robot_task(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).robot.create_robot_task(actor, payload or {})


@api_router.post('/robot-tasks/{robot_task_id}/start')
def start_robot_task(
    request: Request, robot_task_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).robot.start(actor, robot_task_id)


@api_router.post('/robot-tasks/{robot_task_id}/pause')
def pause_robot_task(
    request: Request, robot_task_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).robot.pause(actor, robot_task_id)


@api_router.get('/robot-tasks/{robot_task_id}/sessions')
def list_sessions(
    request: Request, robot_task_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).robot.list_sessions(actor, robot_task_id)


# ---- 会话 ----
@api_router.get('/robot-sessions/{session_id}')
def get_session(
    request: Request, session_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).robot.get_session(actor, session_id)


@api_router.post('/robot-sessions/{session_id}/turn')
def robot_turn(
    request: Request,
    session_id: str,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    data = payload or {}
    return get_container(request).robot.turn(actor, session_id, text=str(data.get('text') or ''))


@api_router.post('/robot-sessions/{session_id}/transfer')
def robot_transfer(
    request: Request,
    session_id: str,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    data = payload or {}
    assignee = data.get('assignee_id')
    return get_container(request).robot.transfer(
        actor, session_id, assignee_id=str(assignee) if assignee else None
    )


@api_router.get('/robot/summary')
def robot_summary(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    return get_container(request).robot.summary(actor)