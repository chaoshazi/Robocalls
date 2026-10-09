'''大模型客户端（二期机器人对话用）。

stub = 离线占位，机器人只走规则话术；live = 调 OpenAI 兼容接口（默认 DeepSeek）。
调用失败一律降级回规则话术，绝不让一通电话因为模型不可用而卡死。
'''

from __future__ import annotations

import logging
from typing import Any

from app.core.config import Settings

LOGGER = logging.getLogger(__name__)


class LlmClient:
    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.settings = settings
        self.mode = settings.llm_mode
        self._client = client

    @property
    def enabled(self) -> bool:
        return self.mode == 'live' and bool(self.settings.llm_api_key)

    def complete(self, *, prompt: str, system: str = '') -> str | None:
        '''返回模型回答；未启用或失败都返回 None，由调用方降级。'''
        if not self.enabled:
            return None
        import httpx

        url = str(self.settings.llm_base_url).rstrip('/') + '/chat/completions'
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
        payload = {
            'model': self.settings.llm_model,
            'messages': messages,
            'temperature': 0.6,
            'max_tokens': 200,
        }
        headers = {
            'Authorization': 'Bearer ' + str(self.settings.llm_api_key),
            'Content-Type': 'application/json',
        }
        try:
            client = self._client or httpx.Client(timeout=int(self.settings.llm_timeout_seconds))
            response = client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                LOGGER.warning('大模型返回 %s：%s', response.status_code, response.text[:200])
                return None
            body = response.json()
        except Exception:
            LOGGER.warning('调用大模型失败，降级为规则话术', exc_info=True)
            return None
        choices = body.get('choices') or []
        if not choices:
            return None
        message = choices[0].get('message') or {}
        text = str(message.get('content') or '').strip()
        return text or None


class SimulatedVoice:
    '''模拟语音：只做文本轮次与事件流，前端可以「扮演客户」输入文字。

    真实 ASR/TTS 接进来时实现同一组方法即可，对话引擎不用改。
    '''

    name = 'simulated'

    def start(self, *, opening: str) -> dict[str, Any]:
        return {'spoken': opening, 'mode': self.name}

    def turn(self, *, say: str) -> dict[str, Any]:
        return {'spoken': say, 'mode': self.name}