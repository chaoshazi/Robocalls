'''通话状态机：各条分支、事件流、录音占位与结果提交。'''

from __future__ import annotations

import unittest

from app.adapters.tables import calls, task_items
from app.errors import Conflict, Forbidden, NotFound, ValidationFailed
from tests.support import ServiceCase, make_agent

FAILURE_STATES = ('no_answer', 'busy', 'power_off', 'invalid_number')


class CallFlowTest(ServiceCase):
    def test_answered_flow(self) -> None:
        task = self.ready_task()
        call = self.make_call()
        self.assertEqual(call['state'], 'answered')
        self.assertEqual(call['state_label'], '通话中')
        self.assertIsNotNone(call['answered_at'])

        hung = self.container.calls.hangup(self.admin, call['id'])
        self.assertEqual(hung['state'], 'ended')
        self.assertIsNone(hung['result_code'])

        done = self.container.calls.complete(
            self.admin, call['id'], {'result_code': 'deal', 'note': '客户要合同'}
        )
        self.assertEqual(done['category'], 'answered')
        self.assertEqual(done['outcome'], 'positive')
        self.assertEqual(done['intent_level'], 'A')
        self.assertEqual(done['result_label'], '成交/强意向')

        item = self.container.store.get(task_items, call['task_item_id'])
        self.assertEqual(item['status'], 'done')
        self.assertEqual(item['result_code'], 'deal')
        self.assertIsNotNone(item['finished_at'])
        self.assertEqual(self.container.tasks.get_task(self.admin, task['id'])['progress']['done'], 1)

    def test_no_answer_returns_item_to_pool(self) -> None:
        self.rebuild(telephony_answer_rate=0.0, telephony_no_answer_seconds=0.0)
        self.ready_task()
        call = self.make_call()
        self.assertIn(call['state'], FAILURE_STATES)
        self.assertIsNotNone(call['completed_at'])
        self.assertEqual(call['category'], 'unanswered')
        item = self.container.store.get(task_items, call['task_item_id'])
        self.assertEqual(item['status'], 'pending')
        self.assertIsNotNone(item['next_attempt_at'])
        self.assertEqual(int(item['attempts']), 1)

    def test_attempts_exhausted_marks_item_done(self) -> None:
        self.rebuild(telephony_answer_rate=0.0, telephony_no_answer_seconds=0.0)
        batch = self.make_batch()
        self.make_task(batch['id'], max_attempts=1)
        call = self.make_call()
        item = self.container.store.get(task_items, call['task_item_id'])
        self.assertEqual(item['status'], 'done')
        self.assertIn(item['result_code'], FAILURE_STATES)

    def test_cancel_while_ringing(self) -> None:
        self.rebuild(telephony_ring_seconds=5.0)
        self.ready_task()
        item = self.container.tasks.next_item(self.admin)
        call = self.container.calls.dial(self.admin, task_item_id=item['id'])
        self.assertEqual(call['state'], 'dialing')
        canceled = self.container.calls.hangup(self.admin, call['id'])
        self.assertEqual(canceled['state'], 'canceled')
        self.assertEqual(canceled['result_code'], 'canceled')
        self.assertEqual(canceled['state_label'], '已取消')

    def test_tick_respects_schedule(self) -> None:
        self.rebuild(telephony_ring_seconds=2.0)
        self.ready_task()
        item = self.container.tasks.next_item(self.admin)
        call = self.container.calls.dial(self.admin, task_item_id=item['id'])
        self.container.tick_once()
        self.assertEqual(self.container.calls.get(self.admin, call['id'])['state'], 'dialing')
        self.backdate_call(call['id'], started_ago=5)
        self.container.tick_once()
        self.assertEqual(self.container.calls.get(self.admin, call['id'])['state'], 'answered')

    def test_events_recorded_in_order(self) -> None:
        self.ready_task()
        call = self.make_call()
        self.container.calls.hangup(self.admin, call['id'])
        events = self.container.calls.events(self.admin, call['id'])
        self.assertEqual([row['state'] for row in events], ['dialing', 'ringing', 'answered', 'ended'])
        self.assertEqual([row['seq'] for row in events], [1, 2, 3, 4])


class CallGuardsTest(ServiceCase):
    def test_only_one_active_call_per_agent(self) -> None:
        self.ready_task()
        self.container.calls.dial(self.admin, phone='13800000001')
        with self.assertRaises(Conflict):
            self.container.calls.dial(self.admin, phone='13800000002')

    def test_complete_before_hangup_conflict(self) -> None:
        self.ready_task()
        call = self.make_call()
        with self.assertRaises(Conflict):
            self.container.calls.complete(self.admin, call['id'], {'result_code': 'deal'})

    def test_hangup_twice_conflict(self) -> None:
        self.ready_task()
        call = self.make_call()
        self.container.calls.hangup(self.admin, call['id'])
        with self.assertRaises(Conflict):
            self.container.calls.hangup(self.admin, call['id'])

    def test_cannot_dial_finished_item(self) -> None:
        self.ready_task()
        call = self.make_call()
        self.container.calls.hangup(self.admin, call['id'])
        self.container.calls.complete(self.admin, call['id'], {'result_code': 'deal'})
        with self.assertRaises(Conflict):
            self.container.calls.dial(self.admin, task_item_id=call['task_item_id'])

    def test_invalid_phone_rejected(self) -> None:
        with self.assertRaises(ValidationFailed):
            self.container.calls.dial(self.admin, phone='123')

    def test_unknown_result_code_rejected(self) -> None:
        self.ready_task()
        call = self.make_call()
        self.container.calls.hangup(self.admin, call['id'])
        with self.assertRaises(ValidationFailed):
            self.container.calls.complete(self.admin, call['id'], {'result_code': 'wat'})

    def test_manual_dial_without_task_item(self) -> None:
        call = self.container.calls.dial(self.admin, phone='13800000001')
        self.assertIsNone(call['task_item_id'])
        self.assertEqual(call['phone_masked'], '138****0001')

    def test_missing_call_not_found(self) -> None:
        with self.assertRaises(NotFound):
            self.container.calls.get(self.admin, 'call-nope')


class RecordingAndVisibilityTest(ServiceCase):
    def test_recording_placeholder_created(self) -> None:
        self.ready_task()
        call = self.make_call()
        self.backdate_call(call['id'], answered_ago=5)
        hung = self.container.calls.hangup(self.admin, call['id'])
        self.assertGreaterEqual(int(hung['talk_sec']), 4)
        self.assertEqual(hung['recording_status'], 'ready')
        path, filename = self.container.calls.recording_path(self.admin, call['id'])
        self.assertTrue(path.exists())
        self.assertEqual(filename, call['id'] + '.wav')
        self.assertGreater(path.stat().st_size, 100)

    def test_recording_disabled(self) -> None:
        self.rebuild(recording_enabled=False)
        self.ready_task()
        call = self.make_call()
        hung = self.container.calls.hangup(self.admin, call['id'])
        self.assertEqual(hung['recording_status'], 'none')
        with self.assertRaises(NotFound):
            self.container.calls.recording_path(self.admin, call['id'])

    def test_agent_sees_masked_admin_sees_full(self) -> None:
        agent = make_agent(self.container, name='坐席', email='call-agent@example.com')
        call = self.container.calls.dial(agent, phone='13800000001')
        self.container.tick_once()
        masked = self.container.calls.list(agent)['data'][0]
        self.assertEqual(masked['phone'], '138****0001')

        revealed = self.container.calls.get(self.admin, call['id'])
        self.assertEqual(revealed['phone'], '13800000001')
        actions = {row['action'] for row in self.container.audit.list(self.admin, limit=50)}
        self.assertIn('view_full_phone', actions)

    def test_agent_cannot_read_other_call(self) -> None:
        agent = make_agent(self.container, name='坐席A', email='c1@example.com')
        other = make_agent(self.container, name='坐席B', email='c2@example.com')
        call = self.container.calls.dial(agent, phone='13800000001')
        with self.assertRaises(Forbidden):
            self.container.calls.get(other, call['id'])

    def test_summary_counts(self) -> None:
        self.ready_task()
        call = self.make_call()
        self.container.calls.hangup(self.admin, call['id'])
        self.container.calls.complete(self.admin, call['id'], {'result_code': 'deal'})
        summary = self.container.calls.list(self.admin)['summary']
        self.assertEqual(summary['total'], 1)
        self.assertEqual(summary['answered'], 1)
        self.assertEqual(summary['answer_rate'], 1.0)
        self.assertEqual(summary['positive'], 1)

    def test_auto_hangup_on_timeout(self) -> None:
        import app.services.calls as calls_module

        original = calls_module.MAX_TALK_SECONDS
        calls_module.MAX_TALK_SECONDS = 1
        try:
            self.ready_task()
            call = self.make_call()
            self.backdate_call(call['id'], answered_ago=5)
            stats = self.container.tick_once()['calls']
            self.assertEqual(stats['auto_hangup'], 1)
            self.assertEqual(self.container.calls.get(self.admin, call['id'])['state'], 'ended')
        finally:
            calls_module.MAX_TALK_SECONDS = original

    def test_json_plan_persisted(self) -> None:
        self.ready_task()
        call = self.make_call()
        row = self.container.store.get(calls, call['id'])
        self.assertEqual([step['state'] for step in row['plan']], ['dialing', 'ringing', 'answered'])


if __name__ == '__main__':
    unittest.main()