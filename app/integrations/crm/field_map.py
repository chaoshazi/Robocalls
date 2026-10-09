'''CRM 字段映射：把 CRM 记录拍平成本地名单条目，回写时再拼回 CRM 需要的形状。

字段名必须与 D:\crm 的 app/contract.py 一致，改这里等于改对接契约。
'''

from __future__ import annotations

from typing import Any

# phone 是号码来源；name 用于列表主标题；company / contact 用于详情展示
LIST_OBJECT_FIELDS: dict[str, dict[str, str]] = {
    'leads': {
        'label': '线索',
        'phone': 'phone',
        'name': 'company',
        'company': 'company',
        'contact': 'contact',
        'stage': 'stage',
    },
    'contacts': {
        'label': '联系人',
        'phone': 'phone',
        'name': 'name',
        'company': '',
        'contact': 'name',
        'stage': '',
    },
}

# 回写目标对象的必需字段，供写回队列拼 payload 时校验
WRITEBACK_REQUIRED: dict[str, tuple[str, ...]] = {
    'activities': ('kind', 'subject'),
    'notes': ('target_id', 'content'),
    'tasks': ('subject',),
}


def supports(crm_object: str) -> bool:
    return str(crm_object or '') in LIST_OBJECT_FIELDS


def map_record(crm_object: str, record: dict[str, Any]) -> dict[str, Any]:
    '''把一条 CRM 记录拍平成名单条目需要的字段。'''
    spec = LIST_OBJECT_FIELDS.get(str(crm_object or ''))
    if spec is None:
        raise KeyError('不支持从 CRM 拉取的对象类型：' + str(crm_object))

    def pick(key: str) -> Any:
        field = spec.get(key) or ''
        return record.get(field) if field else None

    name = pick('name') or pick('contact') or record.get('id')
    extra = {
        'stage': pick('stage'),
        'owner_id': record.get('owner_id'),
        'team_id': record.get('team_id'),
        'email': record.get('email'),
        'source': record.get('source'),
        'industry': record.get('industry'),
        'region': record.get('region'),
    }
    return {
        'phone': str(pick('phone') or '').strip(),
        'name': str(name or '').strip(),
        'company': str(pick('company') or '').strip(),
        'contact_name': str(pick('contact') or '').strip(),
        'crm_object': str(crm_object),
        'crm_record_id': str(record.get('id') or ''),
        'extra': {key: value for key, value in extra.items() if value not in (None, '')},
    }


def title_of(crm_object: str, record: dict[str, Any]) -> str:
    spec = LIST_OBJECT_FIELDS.get(str(crm_object or ''), {})
    for key in ('name', 'contact'):
        field = spec.get(key) or ''
        if field and record.get(field):
            return str(record[field])
    return str(record.get('id') or '')

