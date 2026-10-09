'''事件总线与可见性：SSE 推什么、谁能看到。'''

from __future__ import annotations

import asyncio
import unittest

from app.domain import Actor
from app.services.events import EventBus, visible_to


class EventBusTest(unittest.TestCase):
    def test_fanout_to_all_subscribers(self) -> None:
        bus = EventBus()
        first = bus.subscribe()
        second = bus.subscribe()
        self.assertEqual(bus.subscriber_count, 2)
        bus.publish({'type': 'call', 'call_id': 'c1'})
        self.assertEqual(first.get_nowait()['call_id'], 'c1')
        self.assertEqual(second.get_nowait()['call_id'], 'c1')

    def test_unsubscribe_stops_delivery(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()
        bus.unsubscribe(queue)
        bus.publish({'type': 'call'})
        self.assertEqual(queue.qsize(), 0)
        self.assertEqual(bus.subscriber_count, 0)

    def test_full_queue_drops_oldest(self) -> None:
        bus = EventBus(max_queue=2)
        queue = bus.subscribe()
        for index in range(4):
            bus.publish({'seq': index})
        self.assertEqual(queue.qsize(), 2)
        self.assertEqual(queue.get_nowait()['seq'], 2)
        self.assertEqual(queue.get_nowait()['seq'], 3)

    def test_no_subscriber_is_noop(self) -> None:
        bus = EventBus()
        bus.publish({'type': 'call'})

    def test_subscribe_returns_asyncio_queue(self) -> None:
        self.assertIsInstance(EventBus().subscribe(), asyncio.Queue)


class VisibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = Actor(user_id='u1', role='agent', team_id='t1', tenant_id='default')
        self.manager = Actor(user_id='u9', role='manager', team_id='t1', tenant_id='default')
        self.admin = Actor(user_id='u0', role='admin', team_id='t1', tenant_id='default')

    def test_agent_sees_only_own_events(self) -> None:
        self.assertTrue(visible_to({'agent_id': 'u1', 'team_id': 't1'}, self.agent))
        self.assertFalse(visible_to({'agent_id': 'u2', 'team_id': 't1'}, self.agent))

    def test_manager_sees_team(self) -> None:
        self.assertTrue(visible_to({'agent_id': 'u2', 'team_id': 't1'}, self.manager))
        self.assertFalse(visible_to({'agent_id': 'u3', 'team_id': 't2'}, self.manager))

    def test_admin_sees_everything(self) -> None:
        self.assertTrue(visible_to({'agent_id': 'u3', 'team_id': 't2'}, self.admin))

    def test_scopeless_event_visible_to_all(self) -> None:
        self.assertTrue(visible_to({'type': 'task'}, self.agent))


if __name__ == '__main__':
    unittest.main()