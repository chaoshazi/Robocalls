'''统计报表口径。'''

from __future__ import annotations

import unittest

from tests.support import ServiceCase


class ReportTest(ServiceCase):
    def setUp(self) -> None:
        super().setUp()
        self.ready_task()
        call = self.make_call()
        self.backdate_call(call['id'], answered_ago=30)
        self.container.calls.hangup(self.admin, call['id'])
        self.container.calls.complete(
            self.admin, call['id'], {'result_code': 'deal', 'note': '成交', 'followup_subject': '签约跟进'}
        )
        self.container.tick_once()

    def test_overview(self) -> None:
        data = self.container.reports.overview(self.admin)
        self.assertEqual(data['total_calls'], 1)
        self.assertEqual(data['answered'], 1)
        self.assertEqual(data['answer_rate'], 1.0)
        self.assertEqual(data['positive'], 1)
        self.assertEqual(data['positive_rate'], 1.0)
        self.assertGreaterEqual(data['talk_seconds'], 29)
        self.assertEqual(data['today']['total_calls'], 1)
        self.assertEqual(data['tasks']['active'], 1)
        # 通话活动 + 备注 + 跟进任务，三条都回写成功
        self.assertEqual(data['writeback']['sent'], 3)
        self.assertEqual(data['blocked'], 0)

    def test_agents_ranking(self) -> None:
        data = self.container.reports.agents(self.admin)['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['agent_id'], self.admin.user_id)
        self.assertEqual(data[0]['answered'], 1)
        self.assertEqual(data[0]['agent_name'], self.admin.display)

    def test_daily_series_has_today(self) -> None:
        series = self.container.reports.daily(self.admin, days=3)['data']
        self.assertEqual(len(series), 3)
        self.assertEqual(series[-1]['total'], 1)
        self.assertEqual(series[0]['total'], 0)

    def test_results_and_intents(self) -> None:
        data = self.container.reports.results(self.admin)
        codes = {row['code']: row['count'] for row in data['results']}
        self.assertEqual(codes.get('deal'), 1)
        intents = {row['code']: row['count'] for row in data['intents']}
        self.assertEqual(intents.get('A'), 1)

    def test_tasks_progress(self) -> None:
        data = self.container.reports.tasks_progress(self.admin)['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['total'], 2)
        self.assertEqual(data[0]['done'], 1)
        self.assertEqual(data[0]['completion_rate'], 0.5)

    def test_compliance_report(self) -> None:
        data = self.container.reports.compliance(self.admin)
        self.assertEqual(data['blocked'], 0)
        self.assertEqual(data['blacklist_active'], 0)
        self.assertEqual(data['writeback']['sent'], 3)

    def test_agent_scope_isolated(self) -> None:
        from tests.support import make_agent

        other = make_agent(self.container, name='别人', email='other@example.com')
        self.assertEqual(self.container.reports.overview(other)['total_calls'], 0)
        self.assertEqual(self.container.reports.agents(other)['data'], [])


if __name__ == '__main__':
    unittest.main()