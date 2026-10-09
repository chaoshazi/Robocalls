'''真实线路 REST 适配器：把外呼交给线路网关，状态由网关回调驱动。

它不猜状态，也不假装接通：拨号只是发一个请求，之后 ringing / answered / hangup / 失败
全部由网关回调（POST /api/v1/providers/rest/callback）告诉本系统。节拍器只做超时兜底——
拨号后一直没回调就判失败，避免通话永远挂在「拨号中」。

约定（网关要实现的三个接口）：

1) 呼叫
   POST {WAHU_TELEPHONY_BASE_URL}/calls
   Header: Authorization: Bearer {WAHU_TELEPHONY_TOKEN}
   Body:   {"call_id":"call-xxx","phone":"13800000001","agent_phone":"13900000000","record":true}
   返回:   {"provider_call_id":"..."}         ← 必须回，否则无法关联回调

2) 挂断
   POST {WAHU_TELEPHONY_BASE_URL}/calls/{provider_call_id}/hangup

3) 回调（网关 → 本系统）
   POST {本系统}/api/v1/providers/rest/callback
   Header: X-Wahu-Token: {WAHU_TELEPHONY_TOKEN}
   Body:   {"provider_call_id":"...","state":"ringing|answered|hangup","result_code":"no_answer|busy|power_off|invalid_number|failed","talk_sec":32,"recording_url":"https://..."}

若网关用的是厂商自己的状态码（阿里云 / 容联云等），用 WAHU_TELEPHONY_STATE_MAP 做映射即可，
不必改代码：WAHU_TELEPHONY_STATE_MAP='{"2":"answered","3":"hangup"}'。
'''

from __future__ import annotations

import time
from typing import Any

from app.errors import UpstreamError
from app.telephony.base import CallPlan, HangupResult, PlanStep

# 回调里状态字段/呼叫 ID 字段的常见写法，尽量少让网关做转译
CALL_ID_KEYS = ('provider_call_id', 'call_id', 'CallId', 'callId', 'uuid', 'sid')
STATE_KEYS = ('state', 'event', 'status', 'CallStatus', 'state_code', 'status_code')
RESULT_KEYS = ('result_code', 'result', 'fail_reason', 'reason')
TALK_KEYS = ('talk_sec', 'duration', 'duration_sec', 'billsec', 'talk_time')
RECORDING_KEYS = ('recording_url', 'record_url', 'recording', 'file_url')

# 网关直接给规范状态名时的同义词
STATE_ALIASES: dict[str, str] = {
    'ring': 'ringing',
    'ringing': 'ringing',
    'calling': 'ringing',
    'answered': 'answered',
    'answer': 'answered',
    'talk': 'answered',
    'talking': 'answered',
    'hangup': 'hangup',
    'hangup_by_callee': 'hangup',
    'hangup_by_caller': 'hangup',
    'ended': 'hangup',
    'end': 'hangup',
    'complete': 'hangup',
    'completed': 'hangup',
    'failed': 'failed',
    'fail': 'failed',
    'no_answer': 'no_answer',
    'noanswer': 'no_answer',
    'busy': 'busy',
    'power_off': 'power_off',
    'invalid_number': 'invalid_number',
    'canceled': 'canceled',
    'cancelled': 'canceled',
}

CANONICAL_STATES = (
    'ringing',
    'answered',
    'hangup',
    'failed',
    'no_answer',
    'busy',
    'power_off',
    'invalid_number',
    'canceled',
)


class RestProvider:
    name = 'rest'

    def __init__(
        self,
        *,
        base_url: str = '',
        token: str = '',
        agent_phone: str = '',
        timeout_seconds: int = 20,
        state_map: dict[str, str] | None = None,
        client: Any = None,
    ) -> None:
        self.base_url = str(base_url or '').rstrip('/')
        self.token = str(token or '')
        self.agent_phone = str(agent_phone or '')
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.state_map = {str(k): str(v) for k, v in (state_map or {}).items()}
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    # ---- 出站 ----
    def dial(self, *, call_id: str, phone: str) -> CallPlan:
        if not self.configured:
            raise UpstreamError(
                '真实线路未配置：请填 WAHU_TELEPHONY_BASE_URL 与 WAHU_TELEPHONY_TOKEN',
                code='telephony_not_configured',
                extra={'provider': self.name},
            )
        payload: dict[str, Any] = {'call_id': call_id, 'phone': phone, 'record': True}
        if self.agent_phone:
            # 双呼：先呼坐席，坐席接起后再呼客户
            payload['agent_phone'] = self.agent_phone
        body = self._request('POST', '/calls', json=payload)
        provider_call_id = ''
        for key in CALL_ID_KEYS:
            if isinstance(body, dict) and body.get(key):
                provider_call_id = str(body[key])
                break
        if not provider_call_id:
            raise UpstreamError(
                '线路网关没有返回 provider_call_id，无法关联后续回调',
                code='telephony_bad_response',
                extra={'response': body if isinstance(body, dict) else {}},
            )
        # 状态一律等回调，本地不猜；steps 为空即表示「由回调驱动」
        return CallPlan(
            steps=(PlanStep('dialing', 0),),
            provider_call_id=provider_call_id,
            expects_answer=True,
            default_result='connected',
            webhook_driven=True,
        )

    def hangup(self, *, call_id: str, provider_call_id: str) -> HangupResult:
        if not self.configured or not provider_call_id:
            return HangupResult(ok=False, detail='线路未配置或缺少 provider_call_id')
        try:
            self._request('POST', '/calls/' + str(provider_call_id) + '/hangup', json={})
        except UpstreamError as error:
            return HangupResult(ok=False, detail=error.detail)
        return HangupResult(ok=True, detail='已请求线路挂断')

    # ---- 回调解析 ----
    def normalize_state(self, raw: Any) -> str:
        '''厂商状态码/状态名 → 本系统规范状态；认不出来就返回空串。'''
        if raw is None or raw == '':
            return ''
        text = str(raw).strip()
        if text in self.state_map:
            mapped = str(self.state_map[text]).strip()
            return mapped if mapped in CANONICAL_STATES else ''
        lowered = text.lower()
        if lowered in self.state_map:
            mapped = str(self.state_map[lowered]).strip()
            return mapped if mapped in CANONICAL_STATES else ''
        return STATE_ALIASES.get(lowered, '')

    def parse_callback(self, data: dict[str, Any]) -> dict[str, Any]:
        '''把网关回调整理成统一形状；字段名支持常见几种写法。'''
        body = dict(data or {})

        def pick(keys: tuple[str, ...]) -> Any:
            for key in keys:
                if body.get(key) not in (None, ''):
                    return body[key]
            return None

        raw_state = pick(STATE_KEYS)
        result = pick(RESULT_KEYS)
        talk = pick(TALK_KEYS)
        return {
            'provider_call_id': str(pick(CALL_ID_KEYS) or ''),
            'raw_state': raw_state,
            'state': self.normalize_state(raw_state),
            'result_code': self.normalize_state(result) if result is not None else '',
            'talk_sec': _as_int(talk),
            'recording_url': str(pick(RECORDING_KEYS) or '') or None,
            'detail': body,
        }

    # ---- 内部 ----
    def _http(self) -> Any:
        '''复用同一个 HTTP 客户端：省掉每通电话重建连接的开销，也能正常保持连接池。'''
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self.timeout_seconds)
        return self._client

    def _request(self, method: str, path: str, *, json: dict | None = None) -> Any:
        url = self.base_url + path
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        client = self._http()
        try:
            response = client.request(method, url, json=json, headers=headers)
        except Exception as error:
            raise UpstreamError(
                '呼叫线路网关失败：' + str(error),
                code='telephony_unreachable',
                extra={'base_url': self.base_url, 'path': path},
            ) from error
        if response.status_code >= 400:
            raise UpstreamError(
                '线路网关返回 HTTP ' + str(response.status_code) + '：' + response.text[:200],
                code='telephony_error',
                extra={'base_url': self.base_url, 'path': path, 'status': response.status_code},
            )
        try:
            return response.json()
        except ValueError:
            return {}


def _as_int(value: Any) -> int | None:
    if value in (None, ''):
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def build_client() -> Any:  # pragma: no cover - 仅便于外部注入
    import httpx

    return httpx.Client(timeout=20)