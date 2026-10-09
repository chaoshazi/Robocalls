'''合规：黑名单、免打扰时段、拨打频次与号码脱敏。'''

from __future__ import annotations

import unittest
from datetime import timedelta

from app.core.clock import now
from app.errors import Blocked, Forbidden, ValidationFailed
from tests.support import ServiceCase, make_agent


class BlacklistTest(ServiceCase):
    def test_phone_blacklist_blocks_dial(self) -> None:
        self.ready_task()
        self.container.compliance.create_blacklist(
            self.admin, {'scope': 'phone', 'phone': '13800000001', 'reason': '客户投诉'}
        )
        item = self.container.tasks.next_item(self.admin)
        with self.assertRaises(Blocked) as ctx:
            self.container.calls.dial(self.admin, task_item_id=item['id'])
        self.assertEqual(ctx.exception.code, 'blacklisted')

    def test_blacklist_normalizes_phone(self) -> None:
        entry = self.container.compliance.create_blacklist(
            self.admin, {'scope': 'phone', 'phone': '+86 138-0000-0001'}
        )
        self.assertEqual(entry['value'], '13800000001')
        self.assertIsNotNone(self.container.compliance.match_blacklist(phone='13800000001'))

    def test_customer_blacklist_blocks_crm_item(self) -> None:
        self.ready_task()
        self.container.compliance.create_blacklist(
            self.admin, {'scope': 'customer', 'crm_record_id': 'lead-0001', 'reason': '内部名单'}
        )
        item = [row for row in self.container.tasks.list_items(
            self.admin, self.container.tasks.list_tasks(self.admin)['data'][0]['id']
        )['data'] if row.get('crm_record_id') == 'lead-0001'][0]
        with self.assertRaises(Blocked):
            self.container.calls.dial(self.admin, task_item_id=item['id'])

    def test_duplicate_and_removal(self) -> None:
        entry = self.container.compliance.create_blacklist(
            self.admin, {'scope': 'phone', 'phone': '13800000002'}
        )
        with self.assertRaises(ValidationFailed):
            self.container.compliance.create_blacklist(
                self.admin, {'scope': 'phone', 'phone': '13800000002'}
            )
        self.container.compliance.remove_blacklist(self.admin, entry['id'])
        self.assertIsNone(self.container.compliance.match_blacklist(phone='13800000002'))
        self.assertEqual(len(self.container.compliance.list_blacklist(self.admin)), 0)

    def test_agent_cannot_manage_blacklist(self) -> None:
        agent = make_agent(self.container, name='坐席', email='bl@example.com')
        with self.assertRaises(Forbidden):
            self.container.compliance.create_blacklist(agent, {'scope': 'phone', 'phone': '13800000003'})


class WindowTest(ServiceCase):
    def test_dnd_window_blocks(self) -> None:
        moment = now()
        start = (moment - timedelta(minutes=30)).strftime('%H:%M')
        end = (moment + timedelta(minutes=30)).strftime('%H:%M')
        self.rebuild(compliance_dnd_start=start, compliance_dnd_end=end)
        self.ready_task()
        with self.assertRaises(Blocked) as ctx:
            self.container.calls.dial(self.admin, phone='13800000001')
        self.assertEqual(ctx.exception.code, 'dnd_window')

    def test_outside_dnd_allows(self) -> None:
        moment = now()
        start = (moment + timedelta(hours=1)).strftime('%H:%M')
        end = (moment + timedelta(hours=2)).strftime('%H:%M')
        self.rebuild(compliance_dnd_start=start, compliance_dnd_end=end)
        self.ready_task()
        call = self.container.calls.dial(self.admin, phone='13800000001')
        self.assertEqual(call['state'], 'dialing')

    def test_task_window_blocks(self) -> None:
        moment = now()
        start = (moment + timedelta(hours=1)).strftime('%H:%M')
        end = (moment + timedelta(hours=2)).strftime('%H:%M')
        batch = self.make_batch()
        self.make_task(
            batch['id'], dial_window_start=start, dial_window_end=end
        )
        item = self.container.tasks.next_item(self.admin)
        with self.assertRaises(Blocked) as ctx:
            self.container.calls.dial(self.admin, task_item_id=item['id'])
        self.assertEqual(ctx.exception.code, 'task_window')


class LimitTest(ServiceCase):
    def test_daily_limit_blocks_second_dial(self) -> None:
        self.rebuild(compliance_daily_limit=1)
        self.ready_task()
        first = self.container.calls.dial(self.admin, phone='13800000001')
        self.container.calls.hangup(self.admin, first['id'])
        with self.assertRaises(Blocked) as ctx:
            self.container.calls.dial(self.admin, phone='13800000002')
        self.assertEqual(ctx.exception.code, 'daily_limit')
        self.assertEqual(self.container.compliance.daily_agent_count(self.admin.user_id), 1)

    def test_per_number_limit_blocks_repeat(self) -> None:
        self.rebuild(compliance_per_number_daily_limit=1)
        self.ready_task()
        first = self.container.calls.dial(self.admin, phone='13800000001')
        self.container.tick_once()
        self.container.calls.hangup(self.admin, first['id'])
        with self.assertRaises(Blocked) as ctx:
            self.container.calls.dial(self.admin, phone='13800000001')
        self.assertEqual(ctx.exception.code, 'number_limit')

    def test_canceled_calls_do_not_count_towards_number_limit(self) -> None:
        self.rebuild(compliance_per_number_daily_limit=1, telephony_ring_seconds=5.0)
        self.ready_task()
        call = self.container.calls.dial(self.admin, phone='13800000001')
        self.container.calls.hangup(self.admin, call['id'])
        self.assertEqual(self.container.compliance.daily_number_count('13800000001'), 0)


class SettingsAndMaskingTest(ServiceCase):
    def test_manager_updates_settings_agent_cannot(self) -> None:
        manager = make_agent(self.container, name='主管', email='mgr@example.com', role='manager')
        agent = make_agent(self.container, name='坐席', email='ag@example.com')
        updated = self.container.compliance.update_settings(manager, {'daily_limit': 42})
        self.assertEqual(updated['daily_limit'], 42)
        self.assertEqual(updated['source'], 'runtime')
        with self.assertRaises(Forbidden):
            self.container.compliance.update_settings(agent, {'daily_limit': 7})
        with self.assertRaises(ValidationFailed):
            self.container.compliance.update_settings(manager, {'dnd_start': '99:99'})

    def test_display_phone_masks_and_audits(self) -> None:
        agent = make_agent(self.container, name='坐席', email='mask@example.com')
        self.assertEqual(
            self.container.compliance.display_phone('13800000001', agent), '138****0001'
        )
        before = len(self.container.audit.list(self.admin, limit=200))
        revealed = self.container.compliance.display_phone('13800000001', self.admin)
        self.assertEqual(revealed, '13800000001')
        actions = [
            row['action'] for row in self.container.audit.list(self.admin, limit=50)
        ]
        self.assertIn('view_full_phone', actions)
        self.assertGreater(len(self.container.audit.list(self.admin, limit=200)), before)


if __name__ == '__main__':
    unittest.main()