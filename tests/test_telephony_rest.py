'''真实线路（rest）适配器：拨号出站、回调驱动状态机、超时兜底与合规不回归。

全程离线：用一个桩网关替掉真实线路，验证的是「本系统与线路网关的契约」是否成立。
'''

from __future__ import annotations

import json
import unittest

from app.errors import AppError, NotFound, UpstreamError, ValidationFailed
from app.services.calls import CallService
from app.telephony.rest import RestProvider
from tests.support import HttpCase, ServiceCase, admin_actor, make_container, make_agent

GW_URL = 'http://gw.local'
GW_TOKEN = 'tok-123'
AGENT_PHONE = '13900000000'


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}
        self.text = json.dumps(self._payload, ensure_ascii=False)

    def json(self) -> dict:
        return self._payload


class StubGateway:
    '''替真实线路网关：记录收到的请求，按配置返回结果。'''

    def __init__(self, *, provider_call_id: str = 'gw-1', dial_status: int = 200) -> None:
        self.provider_call_id = provider_call_id
        self.dial_status = dial_status
        self.requests: list[tuple[str, str, dict, dict]] = []

    def request(self, method: str, url: str, json: dict | None = None, headers: dict | None = None) -> FakeResponse:
        self.requests.append((method, url, json or {}, headers or {}))
        if method == 'POST' and url.endswith('/calls'):
            if self.dial_status >= 400:
                return FakeResponse(self.dial_status, {'message': '线路忙'})
            return FakeResponse(200, {'provider_call_id': self.provider_call_id})
        if '/hangup' in url:
            return FakeResponse(200, {'ok': True})
        return FakeResponse(404, {'message': 'nope'})

    def dial_request(self) -> dict:
        for method, url, body, _headers in self.requests:
            if method == 'POST' and url.endswith('/calls'):
                return body
        return {}


def make_rest_container(**overrides: object):
    settings: dict = {
        'telephony_provider': 'rest',
        'telephony_base_url': GW_URL,
        'telephony_token': GW_TOKEN,
        'telephony_agent_phone': AGENT_PHONE,
        'telephony_timeout_seconds': 5,
    }
    settings.update(overrides)
    container = make_container(**settings)
    gateway = StubGateway()
    provider = RestProvider(
        base_url=GW_URL,
        token=GW_TOKEN,
        agent_phone=str(settings['telephony_agent_phone']),
        timeout_seconds=int(settings['telephony_timeout_seconds']),
        state_map=dict(settings.get('telephony_state_map') or {}),
        client=gateway,
    )
    container.provider = provider
    container.calls.provider = provider
    return container, gateway, provider


class RestDialTest(ServiceCase):
    def setUp(self) -> None:
        self.container, self.gateway, self.provider = make_rest_container()
        self.admin = admin_actor(self.container)

    def dial(self, phone: str = '13800000001') -> dict:
        return self.container.calls.dial(self.admin, phone=phone)

    def callback(self, state: str, **extra: object) -> dict:
        payload = {'provider_call_id': self.gateway.provider_call_id, 'state': state}
        payload.update(extra)
        return self.container.calls.apply_provider_event(
            provider_call_id=str(payload['provider_call_id']),
            state=str(payload['state']),
            result_code=payload.get('result_code') or None,  # type: ignore[arg-type]
            talk_sec=payload.get('talk_sec'),  # type: ignore[arg-type]
            recording_url=payload.get('recording_url') or None,  # type: ignore[arg-type]
        )

    def test_dial_calls_gateway_and_waits_for_callback(self) -> None:
        call = self.dial()
        body = self.gateway.dial_request()
        self.assertEqual(body['phone'], '13800000001')
        self.assertEqual(body['agent_phone'], AGENT_PHONE)
        self.assertTrue(body['call_id'].startswith('call-'))
        self.assertEqual(call['state'], 'dialing')
        self.assertEqual(call['provider'], 'rest')
        self.assertEqual(call['provider_call_id'], 'gw-1')
        # 回调驱动：本地不排时间轴，节拍器推不动它
        row = self.container.store.get(__import__('app.adapters.tables', fromlist=['calls']).calls, call['id'])
        self.assertEqual(row['plan'], [])
        self.assertEqual(self.container.tick_once()['calls']['advanced'], 0)
        self.assertEqual(self.container.calls.get(self.admin, call['id'])['state'], 'dialing')

    def test_gateway_auth_header(self) -> None:
        self.dial()
        _method, _url, _body, headers = [
            item for item in self.gateway.requests if item[1].endswith('/calls')
        ][0]
        self.assertEqual(headers['Authorization'], 'Bearer ' + GW_TOKEN)

    def test_dial_failure_surfaces_as_502(self) -> None:
        container, gateway, _provider = make_rest_container()
        gateway.dial_status = 503
        actor = admin_actor(container)
        with self.assertRaises(UpstreamError) as ctx:
            container.calls.dial(actor, phone='13800000001')
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.code, 'telephony_error')
        self.assertEqual(container.store.count(__import__('app.adapters.tables', fromlist=['calls']).calls), 0)

    def test_missing_provider_call_id_is_rejected(self) -> None:
        container, gateway, _provider = make_rest_container()
        gateway.provider_call_id = ''
        actor = admin_actor(container)
        with self.assertRaises(UpstreamError) as ctx:
            container.calls.dial(actor, phone='13800000001')
        self.assertEqual(ctx.exception.code, 'telephony_bad_response')

    def test_unconfigured_provider_fails_loudly(self) -> None:
        provider = RestProvider(base_url='', token='')
        with self.assertRaises(UpstreamError) as ctx:
            provider.dial(call_id='call-1', phone='13800000001')
        self.assertEqual(ctx.exception.code, 'telephony_not_configured')

    def test_ringing_then_answered_then_hangup(self) -> None:
        call = self.dial()
        self.callback('ringing')
        self.assertEqual(self.container.calls.get(self.admin, call['id'])['state'], 'ringing')

        self.callback('answered')
        answered = self.container.calls.get(self.admin, call['id'])
        self.assertEqual(answered['state'], 'answered')
        self.assertIsNotNone(answered['answered_at'])

        ended = self.callback('hangup', talk_sec=42)
        self.assertEqual(ended['state'], 'ended')
        self.assertEqual(ended['talk_sec'], 42)
        # 真实线路不伪造录音：网关没给 URL 就是没有
        self.assertEqual(ended['recording_status'], 'none')
        with self.assertRaises(NotFound):
            self.container.calls.recording_path(self.admin, call['id'])

        events = [row['state'] for row in self.container.calls.events(self.admin, call['id'])]
        self.assertEqual(events, ['dialing', 'ringing', 'answered', 'ended'])

    def test_recording_url_from_gateway_is_kept(self) -> None:
        call = self.dial()
        self.callback('answered')
        ended = self.callback(
            'hangup', talk_sec=18, recording_url='https://cdn.example.com/r/gw-1.wav'
        )
        self.assertEqual(ended['recording_status'], 'ready')
        self.assertEqual(ended['recording_url'], 'https://cdn.example.com/r/gw-1.wav')
        self.assertEqual(ended['recording_seconds'], 18)

    def test_real_line_recording_is_not_faked(self) -> None:
        call = self.dial()
        self.callback('answered')
        self.callback('hangup', talk_sec=30, recording_url='https://cdn.example.com/r/gw-1.wav')
        with self.assertRaises(NotFound):
            self.container.calls.recording_path(self.admin, call['id'])
        target = self.container.calls.recording_target(self.admin, call['id'])
        self.assertEqual(target['kind'], 'redirect')
        self.assertEqual(target['url'], 'https://cdn.example.com/r/gw-1.wav')

    def test_hangup_without_answer_uses_result_code(self) -> None:
        call = self.dial()
        self.callback('ringing')
        done = self.callback('hangup', result_code='no_answer')
        self.assertEqual(done['state'], 'no_answer')
        self.assertEqual(done['category'], 'unanswered')
        self.assertIsNotNone(done['completed_at'])

    def test_hangup_without_result_code_records_canceled(self) -> None:
        call = self.dial()
        done = self.callback('hangup')
        self.assertEqual(done['state'], 'canceled')

    def test_failure_callback_returns_item_to_pool(self) -> None:
        batch = self.make_batch()
        self.make_task(batch['id'])
        item = self.container.tasks.next_item(self.admin)
        call = self.container.calls.dial(self.admin, task_item_id=item['id'])
        self.callback('no_answer')
        fresh = self.container.store.get(
            __import__('app.adapters.tables', fromlist=['task_items']).task_items, item['id']
        )
        self.assertEqual(fresh['status'], 'pending')
        self.assertIsNotNone(fresh['next_attempt_at'])
        self.assertEqual(self.container.writeback.list(self.admin)['summary']['sent'], 0)
        self.assertEqual(self.container.writeback.list(self.admin)['summary']['pending'], 1)
        self.assertEqual(call['provider'], 'rest')

    def test_complete_after_provider_answer(self) -> None:
        batch = self.make_batch()
        self.make_task(batch['id'])
        item = self.container.tasks.next_item(self.admin)
        call = self.container.calls.dial(self.admin, task_item_id=item['id'])
        self.callback('answered')
        self.callback('hangup', talk_sec=9)
        done = self.container.calls.complete(self.admin, call['id'], {'result_code': 'deal', 'note': '线路接通'})
        self.assertEqual(done['intent_level'], 'A')
        self.container.writeback.drain()
        created = self.container.gateway.created_records()
        self.assertTrue(any(row.get('kind') == 'call' for row in created))

    def test_callback_is_idempotent_after_end(self) -> None:
        call = self.dial()
        self.callback('answered')
        self.callback('hangup', talk_sec=12)
        again = self.callback('no_answer')
        self.assertEqual(again['state'], 'ended')
        self.assertEqual(again['talk_sec'], 12)

    def test_late_hangup_callback_still_enriches_recording(self) -> None:
        '''坐席先挂断、线路随后才回调：状态不变，但真实时长与录音必须补上。'''
        call = self.dial()
        self.callback('answered')
        # 坐席先点挂断（本地按自己的时间戳算时长，且真实线路本地不产录音）
        self.container.calls.hangup(self.admin, call['id'])
        local = self.container.calls.get(self.admin, call['id'])
        self.assertEqual(local['state'], 'ended')
        self.assertEqual(local['recording_status'], 'none')

        # 线路随后回调权威数据
        enriched = self.callback(
            'hangup', talk_sec=57, recording_url='https://cdn.example.com/r/gw-1.wav'
        )
        self.assertEqual(enriched['state'], 'ended')
        self.assertEqual(enriched['talk_sec'], 57)
        self.assertEqual(enriched['recording_status'], 'ready')
        self.assertEqual(enriched['recording_url'], 'https://cdn.example.com/r/gw-1.wav')
        actions = {row['action'] for row in self.container.audit.list(self.admin, limit=50)}
        self.assertIn('provider_callback_late', actions)

    def test_unknown_provider_call_id(self) -> None:
        with self.assertRaises(NotFound):
            self.container.calls.apply_provider_event(provider_call_id='gw-nope', state='answered')

    def test_unrecognized_state_rejected(self) -> None:
        self.dial()
        with self.assertRaises(ValidationFailed):
            self.container.calls.apply_provider_event(
                provider_call_id='gw-1', state='whatever'
            )

    def test_timeout_marks_failed_and_frees_item(self) -> None:
        batch = self.make_batch()
        self.make_task(batch['id'])
        item = self.container.tasks.next_item(self.admin)
        call = self.container.calls.dial(self.admin, task_item_id=item['id'])
        from app.adapters.tables import calls as calls_table

        self.backdate_call(call['id'], started_ago=30)
        stats = self.container.tick_once()['calls']
        self.assertEqual(stats['provider_timeout'], 1)
        fresh = self.container.calls.get(self.admin, call['id'])
        self.assertEqual(fresh['state'], 'failed')
        self.assertEqual(fresh['result_code'], 'failed')
        row = self.container.store.get(calls_table, call['id'])
        self.assertEqual(row['ended_reason'], 'provider_timeout')
        item_row = self.container.store.get(
            __import__('app.adapters.tables', fromlist=['task_items']).task_items, item['id']
        )
        self.assertEqual(item_row['status'], 'pending')

    def test_hangup_calls_gateway(self) -> None:
        call = self.dial()
        self.callback('answered')
        self.container.calls.hangup(self.admin, call['id'])
        self.assertTrue(any('/gw-1/hangup' in item[1] for item in self.gateway.requests))

    def test_vendor_state_codes_via_map(self) -> None:
        container, gateway, provider = make_rest_container(telephony_state_map={'2': 'answered', '3': 'hangup'})
        actor = admin_actor(container)
        call = container.calls.dial(actor, phone='13800000001')
        parsed = provider.parse_callback({'CallId': 'gw-1', 'CallStatus': '2', 'duration': '25'})
        self.assertEqual(parsed['state'], 'answered')
        self.assertEqual(parsed['provider_call_id'], 'gw-1')
        self.assertEqual(parsed['talk_sec'], 25)
        updated = container.calls.apply_provider_event(
            provider_call_id=parsed['provider_call_id'], state=parsed['state']
        )
        self.assertEqual(updated['id'], call['id'])
        self.assertEqual(updated['state'], 'answered')

    def test_compliance_still_applies_on_real_line(self) -> None:
        self.container.compliance.create_blacklist(
            self.admin, {'scope': 'phone', 'phone': '13800000001'}
        )
        with self.assertRaises(AppError) as ctx:
            self.dial()
        self.assertEqual(ctx.exception.code, 'blacklisted')
        self.assertEqual(self.gateway.dial_request(), {})


class CallbackRouteTest(HttpCase):
    overrides = {
        'telephony_provider': 'rest',
        'telephony_base_url': GW_URL,
        'telephony_token': GW_TOKEN,
        'telephony_agent_phone': AGENT_PHONE,
        'telephony_timeout_seconds': 5,
    }

    def setUp(self) -> None:
        super().setUp()
        self.gateway = StubGateway()
        provider = RestProvider(
            base_url=GW_URL, token=GW_TOKEN, agent_phone=AGENT_PHONE, client=self.gateway
        )
        self.container.provider = provider
        self.container.calls.provider = provider

    def test_happy_path_over_http(self) -> None:
        call = self.post('/api/v1/calls/dial', self.admin, {'phone': '13800000001'})
        self.assertEqual(call['provider_call_id'], 'gw-1')

        res = self.client.post(
            '/api/v1/providers/rest/callback',
            headers={'X-Wahu-Token': GW_TOKEN},
            json={'provider_call_id': 'gw-1', 'state': 'answered'},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()['call']['state'], 'answered')
        # 回调出参也脱敏
        self.assertEqual(res.json()['call']['phone'], '138****0001')

        ended = self.client.post(
            '/api/v1/providers/rest/callback',
            headers={'X-Wahu-Token': GW_TOKEN},
            json={'provider_call_id': 'gw-1', 'state': 'hangup', 'talk_sec': 20},
        ).json()
        self.assertEqual(ended['call']['state'], 'ended')
        self.assertEqual(ended['call']['talk_sec'], 20)

        audit = self.get('/api/v1/audit', self.admin, action='provider_callback')['data']
        self.assertTrue(any(row['action'] == 'provider_callback' for row in audit))

    def test_token_via_query(self) -> None:
        self.post('/api/v1/calls/dial', self.admin, {'phone': '13800000001'})
        res = self.client.post(
            '/api/v1/providers/rest/callback?token=' + GW_TOKEN,
            json={'provider_call_id': 'gw-1', 'state': 'ringing'},
        )
        self.assertEqual(res.status_code, 200)

    def test_missing_or_wrong_token_rejected(self) -> None:
        self.assertEqual(
            self.client.post('/api/v1/providers/rest/callback', json={'provider_call_id': 'gw-1'}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/providers/rest/callback',
                headers={'X-Wahu-Token': 'wrong'},
                json={'provider_call_id': 'gw-1'},
            ).status_code,
            401,
        )

    def test_wrong_provider_name_conflicts(self) -> None:
        res = self.client.post(
            '/api/v1/providers/simulated/callback',
            headers={'X-Wahu-Token': GW_TOKEN},
            json={'provider_call_id': 'gw-1'},
        )
        self.assertEqual(res.status_code, 409)

    def test_bad_payload_rejected(self) -> None:
        res = self.client.post(
            '/api/v1/providers/rest/callback',
            headers={'X-Wahu-Token': GW_TOKEN},
            json={'state': 'answered'},
        )
        self.assertEqual(res.status_code, 422)
        res = self.client.post(
            '/api/v1/providers/rest/callback',
            headers={'X-Wahu-Token': GW_TOKEN},
            json={'provider_call_id': 'gw-1', 'state': '???'},
        )
        self.assertEqual(res.status_code, 422)

    def test_unknown_call_not_found(self) -> None:
        res = self.client.post(
            '/api/v1/providers/rest/callback',
            headers={'X-Wahu-Token': GW_TOKEN},
            json={'provider_call_id': 'gw-nope', 'state': 'answered'},
        )
        self.assertEqual(res.status_code, 404)

    def test_recording_endpoint_redirects_to_vendor(self) -> None:
        call = self.post('/api/v1/calls/dial', self.admin, {'phone': '13800000001'})
        for payload in (
            {'provider_call_id': 'gw-1', 'state': 'answered'},
            {'provider_call_id': 'gw-1', 'state': 'hangup', 'talk_sec': 30, 'recording_url': 'https://cdn.example.com/r/1.wav'},
        ):
            self.client.post(
                '/api/v1/providers/rest/callback', headers={'X-Wahu-Token': GW_TOKEN}, json=payload
            )
        res = self.client.get(
            '/api/v1/calls/' + call['id'] + '/recording', headers=self.admin, follow_redirects=False
        )
        self.assertEqual(res.status_code, 307)
        self.assertEqual(res.headers['location'], 'https://cdn.example.com/r/1.wav')

    def test_providers_endpoint_reports_ready(self) -> None:
        data = self.get('/api/v1/providers', self.admin)
        self.assertEqual(data['active'], 'rest')
        rest = [row for row in data['items'] if row['name'] == 'rest'][0]
        self.assertTrue(rest['ready'])

    def test_simulated_line_has_no_callback(self) -> None:
        from app.telephony.simulated import SimulatedProvider

        self.container.provider = SimulatedProvider()
        self.container.calls.provider = self.container.provider
        res = self.client.post(
            '/api/v1/providers/simulated/callback',
            headers={'X-Wahu-Token': GW_TOKEN},
            json={'provider_call_id': 'x'},
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()['accepted'])


class RealLineSafetyTest(ServiceCase):
    def test_agent_cannot_forge_callback_state(self) -> None:
        '''坐席没有线路回调入口，只能靠真实回调推进——这里确认接口边界。'''
        container, _gateway, _provider = make_rest_container()
        agent = make_agent(container, name='坐席', email='li@example.com')
        with self.assertRaises(AppError) as ctx:
            container.calls.apply_provider_event(provider_call_id='gw-x', state='answered')
        self.assertIsInstance(ctx.exception, NotFound)
        self.assertTrue(agent.user_id)


if __name__ == '__main__':
    unittest.main()