'''依赖装配：配置、存储、线路、CRM 网关与各服务在这里组装一次。

单进程部署，容器里所有服务共享一个 Store 与一个事件总线；换多进程时把事件总线与节拍器
挪到独立 worker 即可，服务层接口不用改。
'''

from __future__ import annotations

import logging
from typing import Any

from app.adapters.sql import Store, build_engine
from app.core.config import Settings
from app.integrations.crm.gateway import build_gateway
from app.services.audit import AuditService
from app.services.batches import BatchService
from app.services.calls import CallService
from app.services.compliance import ComplianceService
from app.services.events import EventBus
from app.services.identity import IdentityService
from app.services.reports import ReportService
from app.services.robot import RobotService
from app.services.campaigns import TaskService
from app.services.writeback import WritebackService
from app.telephony.simulated import build_provider

LOGGER = logging.getLogger(__name__)


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = build_engine(settings)
        self.store = Store(self.engine)
        self.events = EventBus()
        self.audit = AuditService(self.store)
        self.identity = IdentityService(self.store, settings, self.audit)
        self.gateway = build_gateway(settings)
        self.batches = BatchService(self.store, settings, self.audit, self.gateway)
        self.compliance = ComplianceService(self.store, settings, self.audit)
        self.writeback = WritebackService(self.store, settings, self.audit, self.gateway)
        self.tasks = TaskService(self.store, settings, self.audit)
        self.provider = build_provider(settings)
        self.calls = CallService(
            self.store,
            settings,
            self.audit,
            self.provider,
            self.events,
            self.compliance,
            self.writeback,
            self.tasks,
        )
        self.reports = ReportService(self.store, settings, self.tasks)
        self.robot = RobotService(
            self.store, settings, self.audit, self.batches, self.tasks, self.calls
        )

    # ---- 生命周期 ----
    def startup(self) -> dict[str, Any]:
        if self.settings.auto_migrate:
            self.store.create_all()
        boot = self.identity.bootstrap()
        LOGGER.info(
            '外呼系统已就绪：存储=%s 线路=%s CRM=%s 管理员初始化=%s',
            self.settings.storage,
            self.provider.name,
            self.gateway.name,
            boot.get('created'),
        )
        return boot

    def tick_once(self) -> dict[str, Any]:
        '''一次节拍：推进通话状态机 + 冲刷回写队列。'''
        calls_stats = self.calls.tick()
        writeback_stats = self.writeback.drain(limit=20)
        robot_stats = self.robot.run_once()
        return {'calls': calls_stats, 'writeback': writeback_stats, 'robot': robot_stats}

    def health(self) -> dict[str, Any]:
        return {
            'storage': self.settings.storage,
            'telephony': self.provider.name,
            'crm_mode': self.gateway.name,
            'llm_mode': self.settings.llm_mode,
            'voice': self.settings.voice_provider,
            'env': self.settings.env,
            'ticker': self.settings.ticker_enabled,
            'sse_subscribers': self.events.subscriber_count,
        }