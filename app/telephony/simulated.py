'''模拟线路：按可配的接通率与时长，生成确定性的状态推进计划。

它不是「假装拨号」，而是把一套真实外呼会经历的状态迁移（拨号 → 振铃 → 接通 / 无人接听 /
占线 / 关机 / 空号）完整跑一遍，让坐席工作台、事件流、报表与合规频次统计都能被真实检验。
接通率与时长为 1 / 0 时结果完全确定，测试据此断言各条分支。
'''

from __future__ import annotations

import random

from app.core.config import Settings
from app.telephony.base import CallPlan, HangupResult, PlanStep

# 未接通的失败分布：无人接听为主，其余为占线 / 关机 / 空号
FAILURE_WEIGHTS: tuple[tuple[str, float], ...] = (
    ('no_answer', 0.62),
    ('busy', 0.14),
    ('power_off', 0.14),
    ('invalid_number', 0.10),
)
RING_DELAY_MS = 400


class SimulatedProvider:
    name = 'simulated'

    def __init__(
        self,
        *,
        answer_rate: float = 0.6,
        ring_seconds: float = 4.0,
        no_answer_seconds: float = 20.0,
        rng: random.Random | None = None,
    ) -> None:
        self.answer_rate = max(0.0, min(1.0, float(answer_rate)))
        self.ring_seconds = max(0.0, float(ring_seconds))
        self.no_answer_seconds = max(0.0, float(no_answer_seconds))
        self._rng = rng or random.Random()

    def dial(self, *, call_id: str, phone: str) -> CallPlan:
        provider_call_id = 'sim-' + call_id
        # 振铃时长为 0 表示「不等待」，此时拨号与振铃在同一跳完成，测试据此完全确定
        ring_delay = 0 if self.ring_seconds <= 0 else RING_DELAY_MS
        roll = self._rng.random()
        if roll < self.answer_rate:
            answer_ms = ring_delay + int(self.ring_seconds * 1000)
            return CallPlan(
                steps=(
                    PlanStep('dialing', 0),
                    PlanStep('ringing', ring_delay),
                    PlanStep('answered', answer_ms),
                ),
                provider_call_id=provider_call_id,
                expects_answer=True,
                default_result='connected',
            )
        failure = self._pick_failure()
        end_ms = ring_delay + int(self.no_answer_seconds * 1000)
        return CallPlan(
            steps=(
                PlanStep('dialing', 0),
                PlanStep('ringing', ring_delay),
                PlanStep(failure, end_ms),
            ),
            provider_call_id=provider_call_id,
            expects_answer=False,
            default_result=failure,
        )

    def hangup(self, *, call_id: str, provider_call_id: str) -> HangupResult:
        return HangupResult(ok=True, detail='模拟挂断')

    def _pick_failure(self) -> str:
        total = sum(weight for _, weight in FAILURE_WEIGHTS)
        point = self._rng.random() * total
        cursor = 0.0
        for state, weight in FAILURE_WEIGHTS:
            cursor += weight
            if point <= cursor:
                return state
        return FAILURE_WEIGHTS[0][0]


def build_provider(settings: Settings, *, rng: random.Random | None = None):
    if settings.telephony_provider == 'rest':
        from app.telephony.rest import RestProvider

        return RestProvider(
            base_url=settings.telephony_base_url,
            token=settings.telephony_token,
            agent_phone=settings.telephony_agent_phone,
            timeout_seconds=settings.telephony_timeout_seconds,
            state_map=settings.telephony_state_map,
        )
    return SimulatedProvider(
        answer_rate=settings.telephony_answer_rate,
        ring_seconds=settings.telephony_ring_seconds,
        no_answer_seconds=settings.telephony_no_answer_seconds,
        rng=rng,
    )