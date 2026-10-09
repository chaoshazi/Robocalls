'''只读探测自研 CRM 的对外契约，不做任何写入。

用法：
    python -X utf8 scripts/crm_probe.py
    python -X utf8 scripts/crm_probe.py --base-url http://127.0.0.1:9100/api/v1 --token dev-service-token

它做三件事：
1. 拉 /meta，确认对象与字段有没有变（改了就该同步 app/integrations/crm/field_map.py）；
2. 按 lead / contact 各拉一页，确认号码字段真有值、能解析成合法号码；
3. 报出「有号码但号码不合法」的记录，这类会在建名单时被拒。
'''

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.phone import validate_phone  # noqa: E402
from app.integrations.crm import field_map  # noqa: E402
from app.integrations.crm.client import RestCrm  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description='只读探测自研 CRM 契约')
    parser.add_argument('--base-url', default=settings.crm_base_url)
    parser.add_argument('--token', default=settings.crm_api_token)
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()

    client = RestCrm(
        base_url=args.base_url,
        api_token=args.token,
        actor_id=settings.crm_actor_id,
        page_size=args.limit,
        rate_limit_per_sec=settings.crm_rate_limit_per_sec,
        max_retries=1,
        timeout_seconds=settings.crm_timeout_seconds,
    )

    health = client.health()
    print('连通性：' + str(health))
    if not health.get('ok'):
        print('CRM 不可达，先把它起起来（cd D:\\crm 后 python -X utf8 -m uvicorn app.main:app --port 9100）')
        return 2

    problems = 0
    for crm_object in field_map.LIST_OBJECT_FIELDS:
        try:
            page = client.list_records(crm_object, limit=args.limit)
        except Exception as error:
            print('对象 ' + crm_object + ' 拉取失败：' + str(error))
            problems += 1
            continue
        rows = page.get('data') or []
        bad = []
        for record in rows:
            mapped = field_map.map_record(crm_object, record)
            ok, normalized, reason = validate_phone(mapped['phone'])
            if not ok:
                bad.append({'id': record.get('id'), 'phone': mapped['phone'], 'reason': reason})
        print(
            '对象 '
            + crm_object
            + '：返回 '
            + str(len(rows))
            + ' 条，可解析 '
            + str(len(rows) - len(bad))
            + ' 条'
        )
        for row in bad:
            print('  号码不可用：' + str(row))
        problems += len(bad)
    print('探测完成，问题数：' + str(problems))
    return 0 if problems == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())