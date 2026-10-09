'''通话：拨号、挂断、提交结果、查询、事件与录音。'''

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.api.deps import current_actor, get_container
from app.domain import Actor
from app.errors import AuthError, Conflict, ValidationFailed

api_router = APIRouter(prefix='/api/v1', tags=['calls'])


@api_router.post('/calls/dial')
def dial(
    request: Request,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    data = payload or {}
    return get_container(request).calls.dial(
        actor,
        task_item_id=str(data['task_item_id']) if data.get('task_item_id') else None,
        phone=str(data['phone']) if data.get('phone') else None,
        crm_object=str(data['crm_object']) if data.get('crm_object') else None,
        crm_record_id=str(data['crm_record_id']) if data.get('crm_record_id') else None,
    )


@api_router.post('/calls/{call_id}/hangup')
def hangup(
    request: Request, call_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return get_container(request).calls.hangup(actor, call_id)


@api_router.post('/calls/{call_id}/complete')
def complete(
    request: Request,
    call_id: str,
    payload: dict[str, Any] = Body(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).calls.complete(actor, call_id, payload or {})


@api_router.get('/calls')
def list_calls(
    request: Request,
    state: str | None = Query(default=None),
    result_code: str | None = Query(default=None),
    category: str | None = Query(default=None),
    intent_level: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    day: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int | None = Query(default=None),
    actor: Actor = Depends(current_actor),
) -> dict[str, Any]:
    return get_container(request).calls.list(
        actor,
        state=state,
        result_code=result_code,
        category=category,
        intent_level=intent_level,
        agent_id=agent_id,
        task_id=task_id,
        day=day,
        search=search,
        page=page,
        page_size=page_size,
    )


@api_router.get('/calls/{call_id}')
def get_call(request: Request, call_id: str, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    return get_container(request).calls.get(actor, call_id)


@api_router.get('/calls/{call_id}/events')
def call_events(
    request: Request, call_id: str, actor: Actor = Depends(current_actor)
) -> dict[str, Any]:
    return {'data': get_container(request).calls.events(actor, call_id)}


@api_router.get('/calls/{call_id}/recording')
def call_recording(
    request: Request, call_id: str, actor: Actor = Depends(current_actor)
) -> Response:
    '''录音：模拟线路返回本机占位文件；真实线路 307 跳转到线路厂商的录音地址。'''
    target = get_container(request).calls.recording_target(actor, call_id)
    if target['kind'] == 'redirect':
        return RedirectResponse(url=str(target['url']), status_code=307)
    return FileResponse(target['path'], media_type='audio/wav', filename=str(target['filename']))


@api_router.get('/providers')
def providers(request: Request, actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    '''线路现状：当前生效的是哪条、真实线路配没配全、回调地址是什么。'''
    container = get_container(request)
    settings = container.settings
    return {
        'active': container.provider.name,
        'callback_path': '/api/v1/providers/' + str(container.provider.name) + '/callback',
        'base_url_configured': bool(settings.telephony_base_url),
        'agent_phone_configured': bool(settings.telephony_agent_phone),
        'timeout_seconds': int(settings.telephony_timeout_seconds),
        'items': [
            {
                'name': 'simulated',
                'label': '模拟线路（离线可用，不产生真实话费）',
                'ready': True,
            },
            {
                'name': 'rest',
                'label': '真实线路（呼叫交线路网关，状态由回调驱动）',
                'ready': bool(settings.telephony_base_url and settings.telephony_token),
            },
        ],
    }


@api_router.post('/providers/{name}/callback')
def provider_callback(
    request: Request,
    name: str,
    payload: dict[str, Any] = Body(default=None),
    x_wahu_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    '''线路侧状态回调：真实线路靠它推进通话状态机（ringing / answered / hangup / 失败）。

    鉴权用 WAHU_TELEPHONY_TOKEN（`X-Wahu-Token` 头或 `?token=`）。回调是幂等的：
    已经结束的通话收到迟到或重复的回调不会再改结果。
    '''
    container = get_container(request)
    provider = container.provider
    if str(name) != provider.name:
        raise Conflict('当前生效的线路是 ' + str(provider.name) + '，不接收 ' + str(name) + ' 的回调')
    if provider.name != 'rest':
        return {
            'accepted': False,
            'provider': provider.name,
            'detail': '模拟线路的状态在本地按计划推进，没有外部回调',
        }
    expected = str(container.settings.telephony_token or '')
    provided = str(x_wahu_token or token or '')
    if not expected or not hmac.compare_digest(provided, expected):
        raise AuthError('线路回调凭证不正确')
    parsed = provider.parse_callback(payload or {})
    if not parsed['provider_call_id']:
        raise ValidationFailed('回调缺少 provider_call_id')
    if not parsed['state']:
        raise ValidationFailed('回调状态无法识别：' + str(parsed['raw_state']))
    call = container.calls.apply_provider_event(
        provider_call_id=parsed['provider_call_id'],
        state=parsed['state'],
        result_code=parsed['result_code'] or None,
        talk_sec=parsed['talk_sec'],
        recording_url=parsed['recording_url'],
        detail=parsed['detail'],
    )
    return {
        'accepted': True,
        'provider': provider.name,
        'state': parsed['state'],
        'result_code': parsed['result_code'] or None,
        'call': container.calls.public_call(call, _callback_actor(container)),
    }


def _callback_actor(container: Any) -> Actor:
    '''回调没有登录用户；用一个非管理员身份出参，保证号码仍然脱敏。'''
    return Actor(
        user_id='provider-callback',
        role='agent',
        team_id=None,
        tenant_id=container.settings.tenant_id,
        display='线路回调',
    )