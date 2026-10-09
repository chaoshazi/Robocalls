'''名单：CSV / XLSX 导入、号码校验去重、CRM 拉取、脱敏。'''

from __future__ import annotations

import unittest

from app.errors import Conflict, Forbidden, ValidationFailed
from tests.support import ServiceCase, csv_bytes, make_agent, xlsx_bytes


class ImportTest(ServiceCase):
    def test_csv_import_reports_rows(self) -> None:
        content = csv_bytes(
            [
                ['13800000001', '远山科技', '张伟'],
                ['138-0000-0001', '远山科技重复行', '张伟'],
                ['13900000002', '北岭资本', '李娜'],
                ['123', '坏号码', 'x'],
                ['', '空号码', 'y'],
            ]
        )
        result = self.container.batches.import_file(
            self.admin, filename='名单.csv', content=content, name='九月名单'
        )
        report = result['report']
        self.assertEqual(report['total_rows'], 5)
        self.assertEqual(report['imported'], 2)
        self.assertEqual(report['duplicates'], 1)
        self.assertEqual(report['failed'], 2)
        reasons = [row['reason'] for row in report['failed_rows']]
        self.assertIn('位数不足', reasons)
        self.assertIn('号码为空', reasons)
        self.assertEqual(result['batch']['source'], 'import')

    def test_xlsx_import(self) -> None:
        content = xlsx_bytes([['13800000009', '新客户', '王强']])
        result = self.container.batches.import_file(
            self.admin, filename='名单.xlsx', content=content
        )
        self.assertEqual(result['report']['imported'], 1)

    def test_unknown_extension_rejected(self) -> None:
        with self.assertRaises(ValidationFailed):
            self.container.batches.import_file(self.admin, filename='名单.pdf', content=b'x')

    def test_missing_phone_column_rejected(self) -> None:
        content = '姓名,公司\n张伟,远山科技\n'.encode('utf-8')
        with self.assertRaises(ValidationFailed):
            self.container.batches.import_file(self.admin, filename='名单.csv', content=content)

    def test_dedupe_against_existing_library(self) -> None:
        first = csv_bytes([['13800000001', 'A', 'a']])
        self.container.batches.import_file(self.admin, filename='a.csv', content=first)
        second = csv_bytes([['13800000001', 'B', 'b'], ['13800000002', 'C', 'c']])
        result = self.container.batches.import_file(self.admin, filename='b.csv', content=second)
        self.assertEqual(result['report']['imported'], 1)
        self.assertEqual(result['report']['duplicates'], 1)

    def test_gbk_encoded_csv(self) -> None:
        text = '手机号,客户名称\n13800000007,老系统客户\n'
        content = text.encode('gbk')
        result = self.container.batches.import_file(self.admin, filename='gbk.csv', content=content)
        self.assertEqual(result['report']['imported'], 1)


class CrmPullTest(ServiceCase):
    def test_pull_leads_uses_company_as_title(self) -> None:
        batch = self.make_batch(crm_object='leads')
        self.assertEqual(batch['source'], 'crm')
        self.assertEqual(batch['imported_total'], 2)
        items = self.container.batches.list_items(self.admin, batch['id'])
        names = {row['name'] for row in items['data']}
        self.assertIn('远山科技', names)
        first = [row for row in items['data'] if row['crm_record_id'] == 'lead-0001'][0]
        self.assertEqual(first['phone'], '138****0001')
        self.assertEqual(first['contact_name'], '张伟')

    def test_pull_contacts(self) -> None:
        batch = self.make_batch(crm_object='contacts')
        self.assertEqual(batch['imported_total'], 3)

    def test_unsupported_object_rejected(self) -> None:
        with self.assertRaises(ValidationFailed):
            self.container.batches.create_from_crm(self.admin, {'crm_object': 'opportunities'})

    def test_agent_cannot_pull(self) -> None:
        agent = make_agent(self.container, name='坐席', email='a1@example.com')
        with self.assertRaises(Forbidden):
            self.container.batches.create_from_crm(agent, {'crm_object': 'leads'})

    def test_sync_crm_snapshots(self) -> None:
        summary = self.container.batches.sync_crm(self.admin)
        self.assertGreaterEqual(summary['total'], 5)
        snapshot = self.container.batches.get_snapshot('leads', 'lead-0001')
        self.assertEqual(snapshot['title'], '远山科技')

    def test_crm_health(self) -> None:
        health = self.container.gateway.health()
        self.assertTrue(health['ok'])
        self.assertEqual(health['mode'], 'fake')


class PhoneMaskingTest(ServiceCase):
    def test_all_roles_see_masked_in_lists(self) -> None:
        '''列表一律脱敏：管理员要看全号得走通话详情，且会写审计。'''
        batch = self.make_batch(crm_object='leads')
        admin_view = self.container.batches.list_items(self.admin, batch['id'])['data'][0]
        self.assertEqual(admin_view['phone'], '138****0001')

        agent = make_agent(self.container, name='坐席', email='a2@example.com')
        agent_view = self.container.batches.list_items(agent, batch['id'])['data'][0]
        self.assertEqual(agent_view['phone'], '138****0001')
        self.assertNotIn('13800000001', agent_view['phone'])


class BatchLifecycleTest(ServiceCase):
    def test_delete_batch(self) -> None:
        batch = self.make_batch()
        result = self.container.batches.delete_batch(self.admin, batch['id'])
        self.assertEqual(result['id'], batch['id'])
        with self.assertRaises(Exception):
            self.container.batches.get_batch(self.admin, batch['id'])

    def test_delete_batch_refused_when_task_references_it(self) -> None:
        batch = self.make_batch()
        self.make_task(batch['id'])
        with self.assertRaises(Conflict):
            self.container.batches.delete_batch(self.admin, batch['id'])

    def test_agent_cannot_delete_batch(self) -> None:
        batch = self.make_batch()
        agent = make_agent(self.container, name='坐席', email='a3@example.com')
        with self.assertRaises(Forbidden):
            self.container.batches.delete_batch(agent, batch['id'])


if __name__ == '__main__':
    unittest.main()