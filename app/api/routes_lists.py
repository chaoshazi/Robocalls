'''名单批次、CRM 对接与回写队列。'''

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, Query, Request, UploadFile

from app.api.deps import current_actor, get_container
from app.domain import Actor

api_router = APIRouter(prefix='/api/v1', tags=['lists'])


# ---- 批次 ----
@api_router.get('/batches')
def list_batches(
    request: Request,
    search: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int | None = Query(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).batches.list_batches(
        actor, search=search, page=page, page_size=page_size
    )


@api_router.get('/batches/{batch_id}')
def get_batch(
    request: Request, batch_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).batches.get_batch(actor, batch_id)


@api_router.get('/batches/{batch_id}/items')
def list_batch_items(
    request: Request,
    batch_id: str,
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int | None = Query(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).batches.list_items(
        actor, batch_id, status=status, search=search, page=page, page_size=page_size
    )


@api_router.post('/batches/from-crm')
def create_batch_from_crm(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).batches.create_from_crm(actor, payload or {})


@api_router.post('/batches/import')
async def import_batch(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    note: str | None = Form(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    content = await file.read()
    return get_container(request).batches.import_file(
        actor, filename=file.filename or '', content=content, name=name, note=note
    )


@api_router.delete('/batches/{batch_id}')
def delete_batch(
    request: Request, batch_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).batches.delete_batch(actor, batch_id)


# ---- CRM ----
@api_router.get('/crm/health')
def crm_health(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    container = get_container(request)
    payload = container.gateway.health()
    payload['configured_mode'] = container.settings.crm_mode
    return payload


@api_router.post('/crm/sync')
def crm_sync(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    data = payload or {}
    objects = data.get('objects')
    return get_container(request).batches.sync_crm(
        actor,
        objects=[str(item) for item in objects] if objects else None,
        limit=int(data.get('limit') or 500),
    )


# ---- 回写队列 ----
@api_router.get('/writeback')
def list_writeback(
    request: Request,
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    call_id: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int | None = Query(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).writeback.list(
        actor, status=status, kind=kind, call_id=call_id, page=page, page_size=page_size
    )


@api_router.post('/writeback/retry')
def retry_writeback(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    data = payload or {}
    entry_id = data.get('id')
    return get_container(request).writeback.retry(actor, str(entry_id) if entry_id else None)