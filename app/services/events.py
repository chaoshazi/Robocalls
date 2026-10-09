'''进程内事件总线：给 SSE 订阅者广播通话状态与任务变更。

单进程部署下够用；换多 worker 时把 publish 换成 Redis 发布订阅即可，订阅端接口不变。
'''

from __future__ import annotations

import asyncio
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


class Subscription:
    def __init__(self, actor: Any, queue: asyncio.Queue, channel: str = 'all') -> None:
        self.actor = actor
        self.queue = queue
        self.channel = channel


class EventBus:
    def __init__(self, *, max_queue: int = 256) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._max_queue = max_queue

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: dict) -> None:
        '''广播事件；队列满了就丢最旧的，绝不阻塞业务线程。'''
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:  # pragma: no cover - 极端竞争下的兜底
                    LOGGER.debug('SSE 队列丢弃事件失败', exc_info=True)


def visible_to(event: dict, actor: Any) -> bool:
    '''事件可见性：坐席只看自己的，主管看本团队的，管理员全看。'''
    if getattr(actor, 'sees_all', False):
        return True
    agent_id = event.get('agent_id')
    team_id = event.get('team_id')
    if getattr(actor, 'is_manager', False):
        if agent_id == actor.user_id:
            return True
        if team_id and team_id == actor.team_id:
            return True
        return not agent_id and not team_id
    if agent_id is None and team_id is None:
        return True
    return agent_id == actor.user_id