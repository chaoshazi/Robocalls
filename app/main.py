'''FastAPI 入口：装配容器、注册路由、跑后台节拍器。

节拍器做三件事：推进通话状态机、冲刷 CRM 回写队列、驱动机器人自动外呼。
测试里把 WAHU_TICKER_ENABLED 关掉，改为手动调用 container.tick_once()，结果完全可复现。
'''

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import (
    routes_admin,
    routes_calls,
    routes_core,
    routes_lists,
    routes_reports,
    routes_robot,
    routes_stream,
    routes_tasks,
)
from app.container import Container
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.errors import AppError

LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)
    container = Container(settings)
    ticker: dict[str, Any] = {'task': None}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        container.startup()
        if settings.ticker_enabled:
            ticker['task'] = asyncio.create_task(_ticker(container))
        try:
            yield
        finally:
            task = ticker.get('task')
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    application = FastAPI(
        title='外呼系统 API',
        version=__version__,
        description='名单、任务、坐席工作台、模拟外呼、CRM 回写、合规与报表，以及 AI 机器人外呼',
        lifespan=lifespan,
    )
    application.state.container = container

    @application.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())

    if settings.cors_origin_list:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=['*'],
            allow_headers=['*'],
        )

    application.include_router(routes_core.health_router)
    application.include_router(routes_core.auth_router)
    for module in (
        routes_core,
        routes_lists,
        routes_tasks,
        routes_calls,
        routes_admin,
        routes_reports,
        routes_robot,
        routes_stream,
    ):
        application.include_router(module.api_router)

    dist = settings.web_dist_path
    if settings.serve_web and (dist / 'index.html').exists():
        application.mount('/', StaticFiles(directory=str(dist), html=True), name='web')

    return application


async def _ticker(container: Container) -> None:
    interval = max(0.05, int(container.settings.telephony_tick_ms) / 1000)
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(container.tick_once)
        except Exception:  # 节拍器绝不能因为单次异常停摆
            LOGGER.exception('节拍器执行失败')


app = create_app()