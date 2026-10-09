'''CRM 回写：幂等、失败重试、无归属跳过。'''

from __future__ import annotations

import unittest

from app.errors import NotFound
from tests.support import ServiceCase, csv_bytes


class WritebackTest(ServiceCase):
    def full_call(self, *, result_code: str = 'deal', note: str = '客户要方案', followup: str | None = '明天回访') -> dict:
        call = self.make_call()
        self.container.calls.hangup(self.admin, call['id'])
        payload = {'result_code': result_code, 'note': note}
        if followup:
            payload['followup_subject'] = followup
            payload['followup_priority'] = 'high'
        return self.container.calls.complete(self.admin, call['id'], payload)

    def test_enqueues_three_rows_and_sends(self) -> None:
        self.ready_task()
        self.full_call()
        rows = self.container.writeback.list(self.admin)['data']
        kinds = sorted(row['kind'] for row in rows)
        self.assertEqual(kinds, ['activity', 'note', 'task'])

        stats = self.container.writeback.drain()
        self.assertEqual(stats['sent'], 3)
        created = self.container.gateway.created_records()
        self.assertEqual(len(created), 3)
        activity = [row for row in created if row.get('kind') == 'call'][0]
        self.assertIn('外呼', activity['subject'])
        self.assertEqual(activity['target_id'], 'lead-0001')
        note = [row for row in created if 'content' in row and row.get('target_id')][-1]
        self.assertEqual(note['content'], '客户要方案')

    def test_no_note_and_no_followup_still_writes_activity(self) -> None:
        self.ready_task()
        self.full_call(note='', followup=None)
        rows = self.container.writeback.list(self.admin)['data']
        self.assertEqual([row['kind'] for row in rows], ['activity'])

    def test_idempotent_on_repeat_complete(self) -> None:
        self.ready_task()
        call = self.full_call()
        self.container.writeback.drain()
        sent_before = self.container.writeback.list(self.admin)['summary']['sent']
        self.container.calls.complete(self.admin, call['id'], {'result_code': 'deal', 'note': '改了备注'})
        rows = self.container.writeback.list(self.admin)['data']
        self.assertEqual(len(rows), 3)
        self.assertEqual(self.container.writeback.list(self.admin)['summary']['sent'], sent_before)
        self.assertEqual(len(self.container.gateway.created_records()), 3)

    def test_imported_item_without_crm_target_is_skipped(self) -> None:
        content = csv_bytes([['13800000001', '导入客户', '张伟']])
        batch = self.container.batches.import_file(
            self.admin, filename='名单.csv', content=content
        )['batch']
        self.make_task(batch['id'])
        call = self.make_call()
        self.container.calls.hangup(self.admin, call['id'])
        self.container.calls.complete(self.admin, call['id'], {'result_code': 'deal', 'note': '本地客户'})
        rows = self.container.writeback.list(self.admin)['data']
        self.assertTrue(rows)
        self.assertTrue(all(row['status'] == 'skipped' for row in rows))
        self.assertIn('没有关联 CRM', rows[0]['last_error'])
        self.assertEqual(self.container.writeback.drain()['sent'], 0)

    def test_failure_then_manual_retry(self) -> None:
        self.ready_task()
        self.full_call()

        def boom(*_args: object, **_kwargs: object) -> dict:
            raise RuntimeError('CRM 挂了')

        original = self.container.gateway.create_record
        self.container.gateway.create_record = boom  # type: ignore[method-assign]
        try:
            stats = self.container.writeback.drain()
            self.assertEqual(stats['sent'], 0)
            self.assertEqual(stats['failed'], 3)
            rows = self.container.writeback.list(self.admin, status='failed')['data']
            self.assertEqual(len(rows), 3)
            self.assertIn('CRM 挂了', rows[0]['last_error'])
        finally:
            self.container.gateway.create_record = original  # type: ignore[method-assign]

        requeued = self.container.writeback.retry(self.admin)
        self.assertEqual(requeued['requeued'], 3)
        self.assertEqual(self.container.writeback.drain()['sent'], 3)

    def test_retry_unknown_id(self) -> None:
        with self.assertRaises(NotFound):
            self.container.writeback.retry(self.admin, 'wb-nope')

    def test_filters(self) -> None:
        self.ready_task()
        self.full_call()
        self.container.writeback.drain()
        self.assertEqual(len(self.container.writeback.list(self.admin, kind='note')['data']), 1)
        self.assertEqual(len(self.container.writeback.list(self.admin, status='sent')['data']), 3)
        self.assertEqual(len(self.container.writeback.list(self.admin, status='pending')['data']), 0)


if __name__ == '__main__':
    unittest.main()