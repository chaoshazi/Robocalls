'''统计报表。'''

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import current_actor, get_container
from app.domain import Actor

api_router = APIRouter(prefix='/api/v1/reports', tags=['reports'])


@api_router.get('/overview')
def overview(
    request: Request, days: int = Query(default=7), actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).reports.overview(actor, days=days)


@api_router.get('/agents')
def agents(
    request: Request, days: int = Query(default=7), actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).reports.agents(actor, days=days)


@api_router.get('/daily')
def daily(
    request: Request, days: int = Query(default=14), actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).reports.daily(actor, days=days)


@api_router.get('/results')
def results(
    request: Request, days: int = Query(default=30), actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).reports.results(actor, days=days)


@api_router.get('/tasks')
def tasks_progress(
    request: Request, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).reports.tasks_progress(actor)


@api_router.get('/compliance')
def compliance(
    request: Request, days: int = Query(default=7), actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).reports.compliance(actor, days=days)