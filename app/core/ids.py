'''业务主键：前缀 + 短随机串，日志与联调时一眼能看出是什么对象。'''

from __future__ import annotations

import secrets

PREFIXES: dict[str, str] = {
    'user': 'user',
    'team': 'team',
    'audit': 'audit',
    'batch': 'batch',
    'item': 'item',
    'task': 'task',
    'titem': 'titem',
    'call': 'call',
    'cevent': 'cevent',
    'blacklist': 'bl',
    'writeback': 'wb',
    'script': 'script',
    'robot': 'robot',
    'session': 'rs',
    'setting': 'set',
}


def new_id(kind: str) -> str:
    prefix = PREFIXES.get(kind, kind)
    return prefix + '-' + secrets.token_hex(6)