'''号码归一化、校验与脱敏（按中国大陆规则）。'''

from __future__ import annotations

import re

_NON_DIGITS = re.compile(r'[^0-9]')
_MOBILE = re.compile(r'^1[3-9]\d{9}$')
LANDLINE = re.compile(r'^0\d{2,3}\d{7,8}$')


def normalize_phone(raw: str) -> str:
    '''去掉分隔符与国码前缀，返回纯数字号码；无法识别时返回空串。'''
    text = str(raw or '').strip()
    if not text:
        return ''
    digits = _NON_DIGITS.sub('', text)
    if not digits:
        return ''
    for prefix in ('0086', '86'):
        if digits.startswith(prefix) and len(digits) - len(prefix) == 11:
            digits = digits[len(prefix) :]
            break
    if digits.startswith('0086'):
        digits = digits[4:]
    return digits


def validate_phone(raw: str) -> tuple[bool, str, str]:
    '''返回 (是否有效, 归一化号码, 失败原因)。'''
    normalized = normalize_phone(raw)
    if not normalized:
        return False, '', '号码为空'
    if len(normalized) == 11 and normalized.startswith('1'):
        if _MOBILE.match(normalized):
            return True, normalized, ''
        return False, normalized, '手机号段不合法'
    if LANDLINE.match(normalized):
        return True, normalized, ''
    if len(normalized) < 7:
        return False, normalized, '位数不足'
    if len(normalized) > 13:
        return False, normalized, '位数过长'
    return False, normalized, '既不是手机号也不是座机号'


def mask_phone(phone: str) -> str:
    '''保留前 3 位与后 4 位，中间打星；短号整体打星。'''
    digits = str(phone or '')
    if len(digits) >= 8:
        return digits[:3] + '*' * (len(digits) - 7) + digits[-4:]
    if len(digits) > 1:
        return digits[0] + '*' * (len(digits) - 1)
    return digits


def is_masked(value: str) -> bool:
    return '*' in str(value or '')