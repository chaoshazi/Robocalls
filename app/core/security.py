'''口令哈希与登录令牌：只用标准库，不引入额外依赖。'''

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

PBKDF2_ROUNDS = 120_000
ALGO = 'pbkdf2_sha256'


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256', str(password).encode('utf-8'), salt.encode('utf-8'), PBKDF2_ROUNDS
    )
    return '$'.join((ALGO, str(PBKDF2_ROUNDS), salt, digest.hex()))


def verify_password(password: str, stored: str) -> bool:
    parts = str(stored or '').split('$')
    if len(parts) != 4 or parts[0] != ALGO:
        return False
    try:
        rounds = int(parts[1])
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        'sha256', str(password).encode('utf-8'), parts[2].encode('utf-8'), rounds
    )
    return hmac.compare_digest(digest.hex(), parts[3])


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _unb64(text: str) -> bytes:
    pad = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_token(payload: dict, secret_key: str, ttl_hours: int) -> str:
    '''签发无状态令牌：payload.signature，签名用 HMAC-SHA256。'''
    now = int(time.time())
    body = dict(payload)
    body['iat'] = now
    body['exp'] = now + max(1, int(ttl_hours)) * 3600
    raw = json.dumps(body, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')
    signature = hmac.new(str(secret_key).encode('utf-8'), raw, hashlib.sha256).digest()
    return _b64(raw) + '.' + _b64(signature)


def read_token(token: str, secret_key: str) -> dict | None:
    '''校验令牌；签名不对、格式不对或已过期都返回 None。'''
    parts = str(token or '').split('.')
    if len(parts) != 2:
        return None
    try:
        raw = _unb64(parts[0])
        signature = _unb64(parts[1])
    except Exception:
        return None
    expected = hmac.new(str(secret_key).encode('utf-8'), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(raw.decode('utf-8'))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get('exp') or 0) < int(time.time()):
        return None
    return payload