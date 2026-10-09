'''HTTP 层：端到端走一遍坐席链路，外加 SSE、上传、机器人等接口。'''

from __future__ import annotations

import unittest

from tests.support import HttpCase, csv_bytes


class AgentJourneyTest(HttpCase):
    def test_full_journey(self) -> None:
        batch = self.seed_batch(self.admin)
        task = self.seed_task(self.admin, batch['batch']['id'])

        workbench = self.get('/api/v1/workbench/next', self.admin)
        self.assertIsNotNone(workbench['item'])
        self.assertEqual(workbench['due'], 2)
        item_id = workbench['item']['id']
        self.assertEqual(workbench['item']['phone'], '138****0001')  # 管理员也只在详情里看全号

        call = self.post('/api/v1/calls/dial', self.admin, {'task_item_id': item_id})
        self.assertEqual(call['state'], 'dialing')
        self.container.tick_once()

        detail = self.get('/api/v1/calls/' + call['id'], self.admin)
        self.assertEqual(detail['state'], 'answered')
        self.assertEqual(detail['phone'], '13800000001')

        hung = self.post('/api/v1/calls/' + call['id'] + '/hangup', self.admin)
        self.assertEqual(hung['state'], 'ended')

        done = self.post(
            '/api/v1/calls/' + call['id'] + '/complete',
            self.admin,
            {'result_code': 'interested', 'note': '下周再聊', 'followup_subject': '下周回访'},
        )
        self.assertEqual(done['intent_level'], 'B')

        self.container.tick_once()
        listing = self.get('/api/v1/calls', self.admin, day=None)
        self.assertEqual(listing['summary']['total'], 1)
        self.assertEqual(listing['summary']['answered'], 1)

        writeback = self.get('/api/v1/writeback', self.admin)
        self.assertEqual(writeback['summary']['sent'], 3)

        events = self.get('/api/v1/calls/' + call['id'] + '/events', self.admin)['data']
        self.assertEqual([row['state'] for row in events], ['dialing', 'ringing', 'answered', 'ended'])

        progress = self.get('/api/v1/tasks/' + task['id'], self.admin)
        self.assertEqual(progress['progress']['done'], 1)

    def test_task_item_skip(self) -> None:
        batch = self.seed_batch(self.admin)
        task = self.seed_task(self.admin, batch['batch']['id'])
        items = self.get('/api/v1/tasks/' + task['id'] + '/items', self.admin)['data']
        skipped = self.post('/api/v1/task-items/' + items[0]['id'] + '/skip', self.admin)
        self.assertEqual(skipped['status'], 'skipped')

    def test_workbench_summary(self) -> None:
        data = self.get('/api/v1/workbench/summary', self.admin)
        self.assertIn('compliance', data)
        self.assertEqual(data['today_calls'], 0)

    def test_providers(self) -> None:
        data = self.get('/api/v1/providers', self.admin)
        self.assertEqual(data['active'], 'simulated')
        self.assertTrue(any(row['name'] == 'rest' for row in data['items']))

    def test_compliance_blocked_returns_409(self) -> None:
        self.post(
            '/api/v1/blacklist',
            self.admin,
            {'scope': 'phone', 'phone': '13800000001', 'reason': '投诉'},
        )
        batch = self.seed_batch(self.admin)
        self.seed_task(self.admin, batch['batch']['id'])
        item = self.get('/api/v1/workbench/next', self.admin)['item']
        response = self.client.post(
            '/api/v1/calls/dial', headers=self.admin, json={'task_item_id': item['id']}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'blacklisted')

    def test_settings_roundtrip(self) -> None:
        current = self.get('/api/v1/settings/compliance', self.admin)
        self.assertEqual(current['source'], 'env')
        updated = self.client.put(
            '/api/v1/settings/compliance', headers=self.admin, json={'daily_limit': 11}
        ).json()
        self.assertEqual(updated['daily_limit'], 11)
        self.assertEqual(updated['source'], 'runtime')
        bad = self.client.put(
            '/api/v1/settings/compliance', headers=self.admin, json={'dnd_start': 'xx'}
        )
        self.assertEqual(bad.status_code, 422)

    def test_audit_endpoint(self) -> None:
        data = self.get('/api/v1/audit', self.admin, limit=50)
        self.assertTrue(any(row['action'] == 'login' for row in data['data']))

    def test_teams_and_users(self) -> None:
        teams = self.get('/api/v1/teams', self.admin)['data']
        self.assertGreaterEqual(len(teams), 1)
        user = self.post(
            '/api/v1/users',
            self.admin,
            {'name': '新坐席', 'email': 'new@example.com', 'password': 'password123', 'role': 'agent'},
        )
        self.assertEqual(user['role'], 'agent')
        users = self.get('/api/v1/users', self.admin)['data']
        self.assertEqual(len(users), 2)

    def test_unknown_route(self) -> None:
        self.assertEqual(self.client.get('/api/v1/nope', headers=self.admin).status_code, 404)


class ImportUploadTest(HttpCase):
    def test_csv_upload(self) -> None:
        content = csv_bytes([['13800000001', '远山科技', '张伟'], ['13800000002', '北岭资本', '李娜']])
        response = self.client.post(
            '/api/v1/batches/import',
            headers=self.admin,
            files={'file': ('名单.csv', content, 'text/csv')},
            data={'name': '上传名单'},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload['report']['imported'], 2)
        self.assertEqual(payload['batch']['name'], '上传名单')

    def test_pdf_upload_rejected(self) -> None:
        response = self.client.post(
            '/api/v1/batches/import',
            headers=self.admin,
            files={'file': ('名单.pdf', b'%PDF-1.4', 'application/pdf')},
        )
        self.assertEqual(response.status_code, 422)

    def test_agent_cannot_pull_from_crm(self) -> None:
        from tests.support import make_agent

        make_agent(self.container, name='坐席', email='pull@example.com')
        headers = self.login('pull@example.com', 'agent12345')
        response = self.client.post(
            '/api/v1/batches/from-crm', headers=headers, json={'crm_object': 'leads'}
        )
        self.assertEqual(response.status_code, 403)


class RobotApiTest(HttpCase):
    def _script(self) -> dict:
        return self.post(
            '/api/v1/scripts',
            self.admin,
            {
                'name': '首访话术',
                'status': 'active',
                'content': {
                    'opening': '您好，请问是{name}吗？',
                    'nodes': [
                        {'id': 'n1', 'say': '有采购计划吗？', 'keywords': {'有': 'n2'}, 'default': 'n2'},
                        {'id': 'n2', 'say': '好的，再见。', 'keywords': {}, 'default': None},
                    ],
                    'closing': '打扰了。',
                },
            },
        )

    def test_robot_flow_over_http(self) -> None:
        script = self._script()
        self.assertEqual(script['node_count'], 2)
        scripts = self.get('/api/v1/scripts', self.admin)['data']
        self.assertEqual(len(scripts), 1)

        batch = self.seed_batch(self.admin, crm_object='contacts')
        robot = self.post(
            '/api/v1/robot-tasks',
            self.admin,
            {
                'name': '机器人首轮',
                'script_id': script['id'],
                'batch_id': batch['batch']['id'],
                'concurrency': 1,
                'autostart': True,
            },
        )
        self.assertEqual(robot['status'], 'running')

        self.container.tick_once()
        self.container.tick_once()
        sessions = self.get('/api/v1/robot-tasks/' + robot['id'] + '/sessions', self.admin)['data']
        self.assertEqual(len(sessions), 1)

        first = self.post(
            '/api/v1/robot-sessions/' + sessions[0]['id'] + '/turn', self.admin, {'text': '有'}
        )
        self.assertEqual(first['outcome'], 'in_progress')
        second = self.post(
            '/api/v1/robot-sessions/' + sessions[0]['id'] + '/turn', self.admin, {'text': '好的'}
        )
        self.assertEqual(second['outcome'], 'completed')
        summary = self.get('/api/v1/robot/summary', self.admin)
        self.assertEqual(summary['sessions'], 1)


class StreamTest(HttpCase):
    '''SSE 端点只在这里验鉴权；事件分发与可见性由 test_events 覆盖。

    真流式读取会一直挂在 TestClient 的 portal 上（连接不结束），所以不放进单测；
    需要端到端验证 SSE 时用 scripts/check_stack.py 起真实服务再连。
    '''

    def test_stream_requires_token(self) -> None:
        self.assertEqual(self.client.get('/api/v1/stream').status_code, 401)

    def test_stream_rejects_bad_token(self) -> None:
        response = self.client.get('/api/v1/stream', headers={'Authorization': 'Bearer nope.nope'})
        self.assertEqual(response.status_code, 401)

    def test_stream_route_registered(self) -> None:
        paths = {getattr(route, 'path', '') for route in self.app.routes}
        self.assertIn('/api/v1/stream', paths)


if __name__ == '__main__':
    unittest.main()