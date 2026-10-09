'''自研 CRM 的 REST 客户端：Bearer 服务令牌 + X-Actor-Id 归因，带限流与重试。

契约与 D:\codex 的 CRM 客户端保持同一套习惯：
- 列表返回 {data, next_cursor, total}；
- 写入带 Idempotency-Key，重放不会写重；
- 参数命名沿用 PAGE_SIZE / RATE_LIMIT_PER_SEC / MAX_RETRIES / TIMEOUT_SECONDS。
'''

from __future__ import annotations

import time
from typing import Any

import httpx

from app.errors import UpstreamError


class RestCrm:
    name = 'rest'

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        actor_id: str = '',
        page_size: int = 100,
        rate_limit_per_sec: int = 5,
        max_retries: int = 4,
        timeout_seconds: int = 15,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = str(base_url or '').rstrip('/')
        self.api_token = str(api_token or '')
        self.actor_id = str(actor_id or '')
        self.page_size = max(1, int(page_size))
        self.max_retries = max(1, int(max_retries))
        self.timeout_seconds = int(timeout_seconds)
        self._min_interval = 1.0 / max(1, int(rate_limit_per_sec))
        self._last_call = 0.0
        self._client = client or httpx.Client(timeout=self.timeout_seconds)

    # ---- 读 ----
    def list_records(
        self,
        crm_object: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        filters: dict | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {'limit': int(limit or self.page_size)}
        if cursor:
            params['cursor'] = cursor
        if search:
            params['q'] = search
        for key, value in (filters or {}).items():
            if value not in (None, ''):
                params[key] = value
        body = self._request('GET', '/' + str(crm_object), params=params)
        if not isinstance(body, dict):
            return {'data': [], 'next_cursor': None, 'total': 0}
        return {
            'data': list(body.get('data') or []),
            'next_cursor': body.get('next_cursor'),
            'total': body.get('total'),
        }

    def get_record(self, crm_object: str, record_id: str) -> dict[str, Any] | None:
        body = self._request('GET', '/' + str(crm_object) + '/' + str(record_id))
        if isinstance(body, dict):
            data = body.get('data')
            return dict(data) if isinstance(data, dict) else None
        return None

    # ---- 写 ----
    def create_record(
        self, crm_object: str, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if idempotency_key:
            headers['Idempotency-Key'] = str(idempotency_key)
        body = self._request('POST', '/' + str(crm_object), json=dict(payload), headers=headers)
        if isinstance(body, dict) and isinstance(body.get('data'), dict):
            return dict(body['data'])
        return dict(body) if isinstance(body, dict) else {}

    # ---- 观测 ----
    def health(self) -> dict[str, Any]:
        try:
            body = self._request('GET', '/meta')
        except UpstreamError as error:
            return {'mode': 'rest', 'ok': False, 'detail': error.detail, 'base_url': self.base_url}
        names: list[str] = []
        if isinstance(body, dict):
            names = list(body.get('object_names') or [])
        return {
            'mode': 'rest',
            'ok': True,
            'detail': '已连通自研 CRM',
            'base_url': self.base_url,
            'objects': names,
        }

    # ---- 内部 ----
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
    ) -> Any:
        url = self.base_url + path
        merged: dict[str, str] = {
            'Authorization': 'Bearer ' + self.api_token,
            'Accept': 'application/json',
        }
        if self.actor_id:
            merged['X-Actor-Id'] = self.actor_id
        merged.update(headers or {})
        last_error = ''
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                response = self._client.request(
                    method, url, params=params, json=json, headers=merged
                )
            except httpx.HTTPError as error:
                last_error = '网络错误：' + str(error)
            else:
                if response.status_code < 400:
                    try:
                        return response.json()
                    except ValueError:
                        return {}
                last_error = 'HTTP ' + str(response.status_code) + '：' + response.text[:200]
                if response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < self.max_retries:
                time.sleep(min(2.0, 0.2 * (2 ** (attempt - 1))))
        raise UpstreamError(
            '调用自研 CRM 失败：' + last_error,
            code='crm_unreachable',
            extra={'base_url': self.base_url, 'path': path},
        )

    def _throttle(self) -> None:
        moment = time.monotonic()
        wait = self._min_interval - (moment - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()