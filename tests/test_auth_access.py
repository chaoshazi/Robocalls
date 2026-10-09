'''登录、角色与行级权限。'''

from __future__ import annotations

import unittest

from app.errors import AuthError, Forbidden
from tests.support import ADMIN_EMAIL, HttpCase, ServiceCase, make_agent


class AuthHttpTest(HttpCase):
    def test_health_is_public(self) -> None:
        payload = self.client.get('/health').json()
        self.assertEqual(payload['service'], '外呼系统')
        self.assertEqual(payload['telephony'], 'simulated')

    def test_login_and_meta(self) -> None:
        meta = self.get('/api/v1/meta', self.admin)
        self.assertEqual(meta['me']['role'], 'admin')
        self.assertTrue(any(row['code'] == 'deal' for row in meta['call_results']))

    def test_wrong_password(self) -> None:
        response = self.client.post(
            '/api/auth/login', json={'email': ADMIN_EMAIL, 'password': 'nope'}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'unauthorized')

    def test_requires_token(self) -> None:
        self.assertEqual(self.client.get('/api/v1/calls').status_code, 401)
        self.assertEqual(self.client.get('/api/v1/tasks').status_code, 401)

    def test_bad_token(self) -> None:
        response = self.client.get('/api/v1/calls', headers={'Authorization': 'Bearer nope.nope'})
        self.assertEqual(response.status_code, 401)

    def test_password_change(self) -> None:
        payload = self.post(
            '/api/auth/password',
            self.admin,
            {'old_password': 'admin12345', 'new_password': 'brand-new-pass'},
        )
        self.assertIn('已更新', payload['detail'])
        self.client.post('/api/auth/login', json={'email': ADMIN_EMAIL, 'password': 'brand-new-pass'})

    def test_agent_cannot_manage_users(self) -> None:
        make_agent(self.container, name='坐席小张', email='zhang@example.com')
        agent = self.login('zhang@example.com', 'agent12345')
        self.assertEqual(self.client.get('/api/v1/users', headers=agent).status_code, 403)
        self.assertEqual(
            self.expect_error('POST', '/api/v1/tasks', agent, {'name': 'x'}), 403
        )

    def test_agent_cannot_see_other_agent_calls(self) -> None:
        make_agent(self.container, name='坐席A', email='a@example.com')
        make_agent(self.container, name='坐席B', email='b@example.com')
        headers_a = self.login('a@example.com', 'agent12345')
        headers_b = self.login('b@example.com', 'agent12345')
        batch = self.seed_batch(self.admin)
        self.seed_task(self.admin, batch['batch']['id'], assignee_id=self._agent_id('a@example.com'))

        item = self.get('/api/v1/workbench/next', headers_a)['item']
        call = self.post('/api/v1/calls/dial', headers_a, {'task_item_id': item['id']})
        self.container.tick_once()

        self.assertEqual(self.get('/api/v1/calls', headers_a)['total'], 1)
        self.assertEqual(self.get('/api/v1/calls', headers_b)['total'], 0)
        self.assertEqual(
            self.client.get('/api/v1/calls/' + call['id'], headers=headers_b).status_code, 403
        )

    def test_manager_sees_team_and_admin_sees_all(self) -> None:
        manager = make_agent(self.container, name='主管', email='m@example.com', role='manager')
        make_agent(self.container, name='坐席C', email='c@example.com', team_id=manager.team_id)
        headers_c = self.login('c@example.com', 'agent12345')
        headers_m = self.login('m@example.com', 'agent12345')
        batch = self.seed_batch(self.admin)
        # 任务不指定坐席：主管在本团队内自动领单，同团队坐席不该看到别人的通话
        self.seed_task(self.admin, batch['batch']['id'])
        item = self.get('/api/v1/workbench/next', headers_m)['item']
        self.post('/api/v1/calls/dial', headers_m, {'task_item_id': item['id']})
        self.container.tick_once()
        self.assertEqual(self.get('/api/v1/calls', headers_m)['total'], 1)
        self.assertEqual(self.get('/api/v1/calls', headers_c)['total'], 0)
        self.assertEqual(self.get('/api/v1/calls', self.admin)['total'], 1)

    def _agent_id(self, email: str) -> str:
        from app.adapters.tables import users

        row = self.container.store.find_one(users, email=email)
        assert row is not None
        return str(row['id'])


class AuthServiceTest(ServiceCase):
    def test_bootstrap_is_idempotent(self) -> None:
        again = self.container.identity.bootstrap()
        self.assertFalse(again['created'])

    def test_change_password_requires_old(self) -> None:
        with self.assertRaises(AuthError):
            self.container.identity.change_password(self.admin, 'wrong', 'brand-new-pass')

    def test_create_user_validations(self) -> None:
        with self.assertRaises(Exception):
            self.container.identity.create_user(self.admin, {'email': 'x@example.com', 'password': 'short'})
        self.container.identity.create_user(
            self.admin, {'email': 'x@example.com', 'password': 'longenough1', 'role': 'agent'}
        )
        with self.assertRaises(Exception):
            self.container.identity.create_user(
                self.admin, {'email': 'x@example.com', 'password': 'longenough1'}
            )

    def test_agent_cannot_create_user(self) -> None:
        agent = make_agent(self.container, name='坐席', email='z@example.com')
        with self.assertRaises(Forbidden):
            self.container.identity.create_user(agent, {'email': 'y@example.com', 'password': 'longenough1'})

    def test_token_roundtrip_and_expiry(self) -> None:
        from app.core.security import issue_token, read_token

        token = issue_token({'sub': 'u1'}, 'secret-key-123456', 1)
        self.assertEqual(read_token(token, 'secret-key-123456')['sub'], 'u1')
        self.assertIsNone(read_token(token, 'other-secret-key'))
        expired = issue_token({'sub': 'u1', 'exp': 1}, 'secret-key-123456', 1)
        self.assertIsNotNone(read_token(expired, 'secret-key-123456'))
        self.assertIsNone(read_token('bad', 'secret-key-123456'))


if __name__ == '__main__':
    unittest.main()