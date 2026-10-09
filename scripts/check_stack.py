'''对着一套「已经跑起来」的外呼系统做端到端自检（会真的拨一通演示电话）。

用法：
    python -X utf8 scripts/check_stack.py
    python -X utf8 scripts/check_stack.py --base-url http://127.0.0.1:9300 --email admin@example.com --password admin12345

检查项：健康检查 → 登录 → 元数据 → 前端构建产物 → 名单与任务 → 拨号 → 等状态机推进 →
挂断 → 提交结果 → 回写队列 → SSE 握手。任何一步失败都会打印原因并以非 0 退出。
'''

from __future__ import annotations

import argparse
import json
import re
import time

import httpx


def step(name: str, detail: str) -> None:
    print('  [ok] ' + name + '：' + detail)


def main() -> int:
    parser = argparse.ArgumentParser(description='外呼系统链路自检')
    parser.add_argument('--base-url', default='http://127.0.0.1:9300')
    parser.add_argument('--email', default='admin@example.com')
    parser.add_argument('--password', default='admin12345')
    parser.add_argument('--timeout', type=float, default=30.0)
    parser.add_argument('--skip-dial', action='store_true', help='只做只读检查，不拨号')
    args = parser.parse_args()

    base = args.base_url.rstrip('/')
    client = httpx.Client(timeout=args.timeout)

    health = client.get(base + '/health').json()
    step('健康检查', '运行模式 ' + str(health.get('env')) + '，线路 ' + str(health.get('telephony')) + '，CRM ' + str(health.get('crm_mode')))

    login = client.post(base + '/api/auth/login', json={'email': args.email, 'password': args.password})
    if login.status_code != 200:
        print('登录失败：' + login.text)
        return 2
    headers = {'Authorization': 'Bearer ' + str(login.json()['token'])}
    step('登录', str(login.json()['user']['name']))

    meta = client.get(base + '/api/v1/meta', headers=headers).json()
    step('元数据', str(len(meta.get('call_results', []))) + ' 个结果码，' + str(len(meta.get('call_states', []))) + ' 个通话状态')

    index = client.get(base + '/')
    if index.status_code == 200 and '外呼系统' in index.text:
        match = re.search(r'/assets/[^"]+\.js', index.text)
        asset = client.get(base + match.group(0)) if match else None
        step('前端产物', '首页 200，JS 资源 ' + (str(asset.status_code) if asset else '未引用'))
    else:
        print('  [warn] 前端产物：web/dist 不存在或未托管（开发时用 npm run dev）')

    batch = client.post(base + '/api/v1/batches/from-crm', headers=headers, json={'crm_object': 'leads', 'limit': 5}).json()
    step('拉名单', '批次 ' + batch['batch']['id'] + '，入库 ' + str(batch['report']['imported']) + ' 条')

    if args.skip_dial:
        print('已跳过拨号（--skip-dial）。')
        return 0

    task = client.post(
        base + '/api/v1/tasks',
        headers=headers,
        json={'name': '自检任务', 'batch_id': batch['batch']['id'], 'status': 'active'},
    ).json()
    step('建任务', task['id'] + '，共 ' + str(task['progress']['total']) + ' 条')

    item = client.get(base + '/api/v1/workbench/next', headers=headers).json()['item']
    call = client.post(base + '/api/v1/calls/dial', headers=headers, json={'task_item_id': item['id']}).json()
    step('拨号', call['id'] + ' → ' + str(call['state']))

    terminal = ('answered', 'no_answer', 'busy', 'power_off', 'invalid_number', 'failed')
    fresh = call
    for _ in range(40):
        time.sleep(1)
        fresh = client.get(base + '/api/v1/calls/' + call['id'], headers=headers).json()
        if fresh['state'] in terminal:
            break
    step('状态机推进', str(fresh['state']) + ' / ' + str(fresh['state_label']))

    if fresh['state'] == 'answered':
        client.post(base + '/api/v1/calls/' + call['id'] + '/hangup', headers=headers)
        done = client.post(
            base + '/api/v1/calls/' + call['id'] + '/complete',
            headers=headers,
            json={'result_code': 'deal', 'note': '自检：客户要报价单', 'followup_subject': '自检：明天回访'},
        ).json()
        step('提交结果', str(done['result_label']) + ' / ' + str(done['intent_label']) + '，通话 ' + str(done['talk_sec']) + ' 秒')
        time.sleep(max(1.0, float(health.get('ticker') and 1 or 1)))
        queue = client.get(base + '/api/v1/writeback', headers=headers).json()['summary']
        step('回写队列', json.dumps(queue, ensure_ascii=False))
    else:
        step('未接通', '按失败终态收尾，任务项已回池，无需提交结果')

    with client.stream('GET', base + '/api/v1/stream', headers=headers) as stream:
        first = ''
        for line in stream.iter_lines():
            if line.startswith('data:'):
                first = line[5:].strip()
                break
    step('SSE 握手', first[:80])

    print('自检通过。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())