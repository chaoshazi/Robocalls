'''线路适配器接口。

上层（CallService）只认这个接口：拨号拿到一份「状态推进计划」，之后由节拍器按时间轴把
计划兑现成状态迁移与事件。真实线路接入时换一个实现即可，上层不动。
'''

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PlanStep:
    '''在拨号后第 at_ms 毫秒，状态应当变成 state。'''

    state: str
    at_ms: int


@dataclass(frozen=True)
class CallPlan:
    steps: tuple[PlanStep, ...]
    provider_call_id: str
    # 计划的预期落点：answered 表示会接通并等待坐席挂断；unanswered 表示按失败终态收尾
    expects_answer: bool
    # 无人为干预时直接写入的默认结果码（接通则留给坐席填写）
    default_result: str
    # true = 状态由线路回调驱动（真实线路），节拍器不会自己推进，只负责超时兜底
    webhook_driven: bool = False


@dataclass(frozen=True)
class HangupResult:
    ok: bool
    detail: str = ''


@runtime_checkable
class TelephonyProvider(Protocol):
    name: str

    def dial(self, *, call_id: str, phone: str) -> CallPlan: ...

    def hangup(self, *, call_id: str, provider_call_id: str) -> HangupResult: ...