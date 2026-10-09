'''SSE 事件流：通话状态与任务变更实时推到坐席工作台。'''

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import current_actor, get_container
from app.core.clock import now_iso
from app.domain import Actor
from app.services.events import visible_to

api_router = APIRouter(prefix='/api/v1', tags=['stream'])

HEARTBEAT_SECONDS = 15


@api_router.get('/stream')
async def stream(request: Request, actor: Actor = Depends(current_actor)) -> StreamingResponse:
    container = get_container(request)
    queue = container.events.subscribe()

    async def generate():
        try:
            hello = {'type': 'hello', 'at': now_iso(), 'me': {'id': actor.user_id, 'role': actor.role}}
            yield _frame(hello)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ': keep-alive\n\n'
                    continue
                if not visible_to(event, actor):
                    continue
                yield _frame(event)
        finally:
            container.events.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )


def _frame(payload: dict[str, Any]) -> str:
    return 'data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'