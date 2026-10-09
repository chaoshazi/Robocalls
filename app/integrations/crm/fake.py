'''内置假 CRM：离线可跑，ID 与 D:\crm 的演示数据对齐。

leads 两条与 D:\crm\app\seed.py 完全一致（同 ID / 同字段），这样 WAHU_CRM_MODE 从 fake
切到 rest 之后，名单与回写结果可以直接对比。contacts 是额外补的演示条目（自研 CRM 的演示
数据里没有联系人），只为让预览式外呼的演示更丰满。
'''

from __future__ import annotations

from typing import Any, Callable

DEMO_RECORDS: dict[str, list[dict[str, Any]]] = {
    'leads': [
        {
            'id': 'lead-0001',
            'company': '远山科技',
            'contact': '张伟',
            'email': 'zhangwei@yuanshan.example',
            'phone': '13800000001',
            'source': '官网表单',
            'stage': 'new',
            'owner_id': 'u-100',
            'team_id': 't-sales',
            'version': '1',
            'updated_at': '2026-09-01T02:00:00+00:00',
        },
        {
            'id': 'lead-0002',
            'company': '北岭资本',
            'contact': '李娜',
            'email': 'lina@beiling.example',
            'phone': '13800000002',
            'source': '展会',
            'stage': 'contacted',
            'owner_id': 'u-200',
            'team_id': 't-finance',
            'version': '1',
            'updated_at': '2026-09-05T06:30:00+00:00',
        },
    ],
    'contacts': [
        {
            'id': 'con-0001',
            'name': '张伟',
            'account_id': 'acc-0001',
            'title': '技术总监',
            'email': 'zhangwei@yuanshan.example',
            'phone': '13800000001',
            'owner_id': 'u-100',
            'team_id': 't-sales',
            'version': '1',
            'updated_at': '2026-09-01T02:00:00+00:00',
        },
        {
            'id': 'con-0002',
            'name': '李娜',
            'account_id': 'acc-0002',
            'title': '投资经理',
            'email': 'lina@beiling.example',
            'phone': '13800000002',
            'owner_id': 'u-200',
            'team_id': 't-finance',
            'version': '1',
            'updated_at': '2026-09-05T06:30:00+00:00',
        },
        {
            'id': 'con-0003',
            'name': '王强',
            'account_id': 'acc-0001',
            'title': '采购主管',
            'email': 'wangqiang@yuanshan.example',
            'phone': '13900000003',
            'owner_id': 'u-100',
            'team_id': 't-sales',
            'version': '1',
            'updated_at': '2026-09-08T01:10:00+00:00',
        },
    ],
}


class FakeCrm:
    name = 'fake'

    def __init__(self, *, id_factory: Callable[[str], str] | None = None) -> None:
        self._records: dict[str, list[dict[str, Any]]] = {
            key: [dict(row) for row in rows] for key, rows in DEMO_RECORDS.items()
        }
        # 回写出去的记录留在内存里，离线演示与测试都能看到「写成功了什么」
        self.created: list[dict[str, Any]] = []
        self._seq = 0
        self._id_factory = id_factory

    # ---- 读 ----
    def list_records(
        self,
        crm_object: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        filters: dict | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        rows = list(self._records.get(str(crm_object), []))
        if search:
            needle = str(search).strip()
            rows = [row for row in rows if any(needle in str(value) for value in row.values())]
        start = int(cursor) if cursor and str(cursor).isdigit() else 0
        size = int(limit or len(rows) or 1)
        page = rows[start : start + size]
        next_cursor = str(start + size) if start + size < len(rows) else None
        return {'data': page, 'next_cursor': next_cursor, 'total': len(rows)}

    def get_record(self, crm_object: str, record_id: str) -> dict[str, Any] | None:
        for row in self._records.get(str(crm_object), []):
            if str(row.get('id')) == str(record_id):
                return dict(row)
        return None

    # ---- 写 ----
    def create_record(
        self, crm_object: str, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        if idempotency_key:
            for row in self.created:
                if row.get('_idempotency_key') == idempotency_key:
                    return dict(row)
        self._seq += 1
        record_id = str(crm_object) + '-w' + str(self._seq).zfill(4)
        record = {'id': record_id, **dict(payload), '_idempotency_key': idempotency_key}
        self.created.append(record)
        self._records.setdefault(str(crm_object), []).append(dict(record))
        return dict(record)

    # ---- 观测 ----
    def health(self) -> dict[str, Any]:
        return {
            'mode': 'fake',
            'ok': True,
            'detail': '内置假数据，离线可用',
            'objects': {key: len(rows) for key, rows in self._records.items()},
        }

    def created_records(self, crm_object: str | None = None) -> list[dict[str, Any]]:
        if crm_object:
            return [row for row in self.created if row.get('id', '').startswith(str(crm_object))]
        return list(self.created)