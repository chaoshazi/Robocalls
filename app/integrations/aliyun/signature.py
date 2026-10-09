'''阿里云 RPC 风格接口的请求签名（HMAC-SHA1），纯标准库实现。

阿里云语音服务（dyvmsapi）、云呼叫中心（ccc）这类产品都是 RPC 风格：
公共参数 + 业务参数 → 按参数名排序拼成规范化查询串 → 用 AccessKeySecret 做 HMAC-SHA1 → Base64。

这里严格按阿里云文档的编码规则实现，两个容易踩坑的点：
1. percent-encode 必须是 RFC3986（空格是 %20 不是 +，* 要编码，~ 不编码）；
2. 参与签名的串是「编码后的键=编码后的值」用 & 连接，再整体编码后进 StringToSign。

AccessKey 只从环境变量读，不写进任何文件。
'''

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

SIGNATURE_METHOD = 'HMAC-SHA1'
SIGNATURE_VERSION = '1.0'
TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def percent_encode(value: Any) -> str:
    '''RFC3986 编码：A-Za-z0-9 与 -_.~ 保持不变，其余（含空格、星号、斜杠）都编码。'''
    return quote(str(value), safe='~')


def canonical_query(params: dict[str, Any]) -> str:
    '''按参数名排序后拼成规范化查询串。'''
    pairs = sorted((percent_encode(key), percent_encode(value)) for key, value in params.items())
    return '&'.join(key + '=' + value for key, value in pairs)


def string_to_sign(method: str, path: str, params: dict[str, Any]) -> str:
    '''把请求方法、路径与规范化参数拼成待签串。'''
    return '&'.join(
        (
            str(method).upper(),
            percent_encode(path or '/'),
            percent_encode(canonical_query(params)),
        )
    )


def sign(params: dict[str, Any], access_key_secret: str, *, method: str = 'POST', path: str = '/') -> str:
    '''算出 Signature（Base64 的 HMAC-SHA1）。'''
    secret = (str(access_key_secret) + '&').encode('utf-8')
    payload = string_to_sign(method, path, params).encode('utf-8')
    return base64.b64encode(hmac.new(secret, payload, hashlib.sha1).digest()).decode('ascii')


def timestamp_now(moment: datetime | None = None) -> str:
    current = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return current.strftime(TIMESTAMP_FORMAT)


def common_params(
    *,
    action: str,
    version: str,
    access_key_id: str,
    region_id: str = '',
    nonce: str | None = None,
    timestamp: str | None = None,
    business: dict[str, Any] | None = None,
) -> dict[str, Any]:
    '''公共参数 + 业务参数。nonce / timestamp 可注入，便于测试与复现。'''
    params: dict[str, Any] = {
        'Format': 'JSON',
        'Version': version,
        'AccessKeyId': access_key_id,
        'SignatureMethod': SIGNATURE_METHOD,
        'SignatureVersion': SIGNATURE_VERSION,
        'SignatureNonce': nonce or uuid.uuid4().hex,
        'Timestamp': timestamp or timestamp_now(),
        'Action': action,
    }
    if region_id:
        params['RegionId'] = region_id
    for key, value in (business or {}).items():
        if value not in (None, ''):
            params[key] = value
    return params


def build_request(
    *,
    action: str,
    version: str,
    access_key_id: str,
    access_key_secret: str,
    business: dict[str, Any] | None = None,
    region_id: str = '',
    endpoint: str,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> tuple[str, dict[str, Any]]:
    '''返回 (请求地址, 表单参数)，参数里已含 Signature。'''
    params = common_params(
        action=action,
        version=version,
        access_key_id=access_key_id,
        region_id=region_id,
        nonce=nonce,
        timestamp=timestamp,
        business=business,
    )
    params['Signature'] = sign(params, access_key_secret)
    return str(endpoint).rstrip('/') + '/', params


def redact(params: dict[str, Any]) -> dict[str, Any]:
    '''打印请求时把密钥类字段打码。'''
    hidden = {'Signature', 'AccessKeyId'}
    return {key: ('***' if key in hidden else value) for key, value in params.items()}