'''测试脚手架：内存库 + 模拟线路 + fake CRM + stub 大模型，全离线可跑。

约定（与 D:\crm / D:\codex 一致）：标准库 unittest，不用 pytest；
跑法：python -X utf8 -m unittest discover -s tests -t .
'''

from __future__ import annotations

import io
import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.container import Container
from app.core.clock import now, to_iso
from app.core.config import Settings
from app.domain import Actor
from app.main import create_app

ADMIN_EMAIL = 'admin@example.com'
ADMIN_PASSWORD = 'admin12345'


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        'storage': 'sqlite',
        'sqlite_path': ':memory:',
        'ticker_enabled': False,
        'telephony_provider': 'simulated',
        # 接通率 1 / 振铃 0：状态机在第一次 tick 就直接走到「通话中」，断言完全确定
        'telephony_answer_rate': 1.0,
        'telephony_ring_seconds': 0.0,
        'telephony_no_answer_seconds': 0.0,
        'crm_mode': 'fake',
        'llm_mode': 'stub',
        'voice_provider': 'simulated',
        'recording_enabled': True,
        'recording_dir': 'var/test-recordings',
        'serve_web': False,
        # 测试里别被 httpx / uvicorn 的 INFO 日志淹没
        'log_level': 'WARNING',
        'secret_key': 'test-secret-key-please-change',
        'bootstrap_admin_email': ADMIN_EMAIL,
        'bootstrap_admin_password': ADMIN_PASSWORD,
        'bootstrap_admin_name': '测试管理员',
        'compliance_dnd_start': '21:00',
        'compliance_dnd_end': '09:00',
    }
    base.update(overrides)
    return Settings(**base)


def make_container(**overrides: Any) -> Container:
    container = Container(make_settings(**overrides))
    container.startup()
    return container


def admin_actor(container: Container) -> Actor:
    result = container.identity.login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return container.identity.actor_for_token(result['token'])


def make_agent(
    container: Container,
    *,
    name: str,
    email: str,
    role: str = 'agent',
    team_id: str | None = None,
    password: str = 'agent12345',
) -> Actor:
    admin = admin_actor(container)
    container.identity.create_user(
        admin,
        {
            'name': name,
            'email': email,
            'password': password,
            'role': role,
            'team_id': team_id or admin.team_id,
        },
    )
    token = container.identity.login(email, password)['token']
    return container.identity.actor_for_token(token)


def make_app(**overrides: Any) -> tuple[FastAPI, Container]:
    application = create_app(make_settings(**overrides))
    return application, application.state.container


class ServiceCase(unittest.TestCase):
    '''服务层用例基类：一个内存容器 + 管理员身份 + 常用造数。'''

    overrides: dict[str, Any] = {}

    def setUp(self) -> None:
        self.container = make_container(**self.overrides)
        self.admin = admin_actor(self.container)

    def rebuild(self, **overrides: Any) -> Container:
        '''换一套配置重来（例如改免打扰时段、改接通率）。'''
        self.container = make_container(**overrides)
        self.admin = admin_actor(self.container)
        return self.container

    def ready_task(self, **extra: Any) -> dict:
        '''一步造出「批次 + 进行中的任务」，返回任务。'''
        batch = self.make_batch()
        return self.make_task(batch['id'], **extra)

    # ---- 造数 ----
    def make_batch(self, *, crm_object: str = 'leads', limit: int = 10) -> dict:
        return self.container.batches.create_from_crm(
            self.admin, {'crm_object': crm_object, 'limit': limit}
        )['batch']

    def make_task(self, batch_id: str, **extra: Any) -> dict:
        payload: dict[str, Any] = {'name': '测试任务', 'batch_id': batch_id, 'status': 'active'}
        payload.update(extra)
        return self.container.tasks.create_task(self.admin, payload)

    def make_call(self, actor: Actor | None = None, **kwargs: Any) -> dict:
        actor = actor or self.admin
        item = self.container.tasks.next_item(actor)
        assert item is not None
        call = self.container.calls.dial(actor, task_item_id=item['id'], **kwargs)
        self.container.tick_once()
        return self.container.calls.get(actor, call['id'])

    def backdate_call(
        self, call_id: str, *, started_ago: int = 0, answered_ago: int = 0, ended_ago: int = 0
    ) -> None:
        '''把通话里「已经发生」的时刻挪到过去，省得用例真的等秒数。'''
        from datetime import timedelta

        from app.adapters.tables import calls

        values: dict[str, Any] = {}
        if started_ago:
            values['started_at'] = to_iso(now() - timedelta(seconds=started_ago))
        if answered_ago:
            values['answered_at'] = to_iso(now() - timedelta(seconds=answered_ago))
        if ended_ago:
            values['ended_at'] = to_iso(now() - timedelta(seconds=ended_ago))
        if values:
            self.container.store.update(calls, call_id, values)


class HttpCase(unittest.TestCase):
    '''HTTP 用例基类：TestClient 跑完整 lifespan。'''

    overrides: dict[str, Any] = {}

    def setUp(self) -> None:
        self.app, self.container = make_app(**self.overrides)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(lambda: self.client.__exit__(None, None, None))
        self.admin = self.login()

    def login(self, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD) -> dict[str, str]:
        response = self.client.post('/api/auth/login', json={'email': email, 'password': password})
        assert response.status_code == 200, response.text
        return {'Authorization': 'Bearer ' + response.json()['token']}

    def get(self, path: str, headers: dict[str, str], **params: Any) -> Any:
        response = self.client.get(path, headers=headers, params=params or None)
        assert response.status_code < 400, (path, response.status_code, response.text)
        return response.json()

    def post(self, path: str, headers: dict[str, str], payload: Any = None) -> Any:
        response = self.client.post(path, headers=headers, json=payload or {})
        assert response.status_code < 400, (path, response.status_code, response.text)
        return response.json()

    def patch(self, path: str, headers: dict[str, str], payload: Any = None) -> Any:
        response = self.client.patch(path, headers=headers, json=payload or {})
        assert response.status_code < 400, (path, response.status_code, response.text)
        return response.json()

    def expect_error(self, method: str, path: str, headers: dict[str, str], payload: Any = None) -> int:
        response = self.client.request(method, path, headers=headers, json=payload)
        assert response.status_code >= 400, (path, response.status_code, response.text)
        return response.status_code

    def seed_batch(self, headers: dict[str, str], *, crm_object: str = 'leads', limit: int = 10) -> dict:
        return self.post(
            '/api/v1/batches/from-crm', headers, {'crm_object': crm_object, 'limit': limit}
        )

    def seed_task(self, headers: dict[str, str], batch_id: str, **extra: Any) -> dict:
        payload = {'name': '测试任务', 'batch_id': batch_id, 'status': 'active'}
        payload.update(extra)
        return self.post('/api/v1/tasks', headers, payload)


def csv_bytes(rows: list[list[str]], header: list[str] | None = None) -> bytes:
    lines = [','.join(header or ['手机号', '客户名称', '联系人'])]
    lines += [','.join(row) for row in rows]
    return ('\n'.join(lines) + '\n').encode('utf-8')


def xlsx_bytes(rows: list[list[str]], header: list[str] | None = None) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(header or ['手机号', '客户名称', '联系人'])
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()