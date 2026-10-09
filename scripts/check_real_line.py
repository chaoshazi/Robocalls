'''验证「真实线路」这条链路：对着已经跑起来的外呼系统 + 线路网关，真拨一通电话。

用法：
    python -X utf8 scripts/check_real_line.py
    python -X utf8 scripts/check_real_line.py --phone 13800000000 --keep

它会走完整链路：建名单 → 建任务 → 拨号 → 等线路回调（振铃 / 接通）→ 挂断 → 提交结果 → 查回写，
并把每一步的实测值打出来。接真实厂商线路时，这个脚本同样用来验收（把网关地址换成厂商的）。
默认跑完把这次产生的名单与任务删掉，加 --keep 保留。
'''

from __future__ import annotations

import argparse
import random
import time

import httpx

TERMINAL = ('ended', 'no_answer', 'busy', 'power_off', 'invalid_number', 'failed', 'canceled')


def step(name: str, detail: str) -> None:
    print('  [ok] ' + name + '：' + detail)


def main() -> int:
    parser = argparse.ArgumentParser(description='真实线路链路自检')
    parser.add_argument('--base-url', default='http://127.0.0.1:9300')
    parser.add_argument('--email', default='admin@example.com')
    parser.add_argument('--password', default='admin12345')
    parser.add_argument('--phone', default='', help='指定要拨的号码，默认随机生成一个演示号码')
    parser.add_argument('--wait', type=float, default=25.0, help='等待接通或终态的最长秒数')
    parser.add_argument('--keep', action='store_true', help='保留这次产生的名单与任务')
    args = parser.parse_args()

    base = args.base_url.rstrip('/')
    client = httpx.Client(timeout=30.0)

    health = client.get(base + '/health').json()
    if health.get('telephony') != 'rest':
        print('当前线路是 ' + str(health.get('telephony')) + '，不是 rest。'
              '请把 WAHU_TELEPHONY_PROVIDER 改成 rest 并重启进程。')
        return 2
    step('健康检查', '线路 rest，节拍器 ' + str(health.get('ticker')))

    login = client.post(base + '/api/auth/login', json={'email': args.email, 'password': args.password})
    if login.status_code != 200:
        print('登录失败：' + login.text)
        return 2
    headers = {'Authorization': 'Bearer ' + str(login.json()['token'])}

    providers = client.get(base + '/api/v1/providers', headers=headers).json()
    rest = [row for row in providers.get('items', []) if row['name'] == 'rest']
    ready = bool(rest and rest[0]['ready'])
    step(
        '线路状态',
        '当前 ' + str(providers.get('active'))
        + '，网关地址已配置=' + str(providers.get('base_url_configured'))
        + '，rest 就绪=' + str(ready),
    )
    if not providers.get('base_url_configured'):
        print('WAHU_TELEPHONY_BASE_URL 没配，拨号一定失败。先看 docs/telephony.md。')
        return 2

    stamp = time.strftime('%H%M%S')
    phone = args.phone or ('139' + str(random.randint(0, 99999999)).zfill(8))
    csv = '手机号,客户名称,联系人\n' + phone + ',真实线路自检,自检\n'
    uploaded = client.post(
        base + '/api/v1/batches/import',
        headers=headers,
        files={'file': ('真实线路自检.csv', csv.encode('utf-8'), 'text/csv')},
        data={'name': '真实线路自检 ' + stamp},
    ).json()
    report = uploaded['report']
    step('建名单', '批次 ' + uploaded['batch']['id'] + '，入库 ' + str(report['imported']) + ' 条，目标号码 ' + phone)
    if report['imported'] == 0:
        print('名单没入库（多半是号码已被占用），换个号码或加 --phone 指定。')
        return 2

    task = client.post(
        base + '/api/v1/tasks',
        headers=headers,
        json={'name': '真实线路自检 ' + stamp, 'batch_id': uploaded['batch']['id'], 'status': 'active'},
    ).json()
    item = client.get(base + '/api/v1/workbench/next', headers=headers).json()['item']
    if item is None:
        print('工作台没取到任务项，先确认任务里有余量。')
        return 2
    step('建任务', task['id'] + ' → 取到任务项 ' + str(item['phone']))

    call = client.post(base + '/api/v1/calls/dial', headers=headers, json={'task_item_id': item['id']}).json()
    if not call.get('provider_call_id'):
        print('拨号没有拿到 provider_call_id：' + str(call))
        return 2
    step('拨号', call['id'] + ' → 线路侧单号 ' + str(call['provider_call_id']))

    def fetch() -> dict:
        return client.get(base + '/api/v1/calls/' + call['id'], headers=headers).json()

    deadline = time.time() + args.wait
    seen: list[str] = []
    fresh = call
    while time.time() < deadline:
        time.sleep(1)
        fresh = fetch()
        if not seen or seen[-1] != fresh['state_label']:
            seen.append(str(fresh['state_label']))
            print('       ' + str(len(seen)) + '. ' + str(fresh['state_label']))
        if fresh['state'] in TERMINAL or fresh['state'] == 'answered':
            break
    step('状态推进', ' → '.join(seen))

    if fresh['state'] not in TERMINAL and fresh['state'] != 'answered':
        print('等待超时，当前状态 ' + str(fresh['state_label']) + '（检查网关回调地址与令牌）')
        return 1

    if fresh['state'] == 'answered' or fresh.get('answered_at'):
        client.post(base + '/api/v1/calls/' + call['id'] + '/hangup', headers=headers)
        for _ in range(10):
            time.sleep(1)
            fresh = fetch()
            if fresh['state'] in TERMINAL:
                break
        # 等线路把权威时长与录音地址回调过来（坐席点挂断与线路回调之间有时差）
        for _ in range(6):
            time.sleep(1)
            fresh = fetch()
            if fresh.get('recording_status') == 'ready':
                break
        step(
            '挂断',
            str(fresh['state_label']) + '，通话 ' + str(fresh['talk_sec'])
            + ' 秒，录音 ' + str(fresh['recording_status']),
        )
        if fresh.get('recording_url'):
            recording = client.get(
                base + '/api/v1/calls/' + call['id'] + '/recording',
                headers=headers,
                follow_redirects=False,
            )
            if recording.status_code in (301, 302, 307, 308):
                step(
                    '取录音',
                    'HTTP ' + str(recording.status_code) + ' 跳转线路录音地址 '
                    + str(recording.headers.get('location')),
                )
            else:
                step('取录音', 'HTTP ' + str(recording.status_code) + '，' + str(len(recording.content)) + ' 字节')
        done = client.post(
            base + '/api/v1/calls/' + call['id'] + '/complete',
            headers=headers,
            json={'result_code': 'deal', 'note': '真实线路自检', 'followup_subject': '自检回访'},
        ).json()
        step('提交结果', str(done['result_label']) + ' / ' + str(done['intent_label']))
    else:
        step('未接通', '按 ' + str(fresh['result_code']) + ' 收尾，任务项已回池')

    time.sleep(2)
    queue = client.get(base + '/api/v1/writeback', headers=headers).json()['summary']
    step('回写队列', str(queue))
    events = client.get(base + '/api/v1/calls/' + call['id'] + '/events', headers=headers).json()['data']
    step('事件流', ' → '.join(str(row['state_label']) for row in events))

    if not args.keep:
        client.delete(base + '/api/v1/tasks/' + task['id'], headers=headers)
        client.delete(base + '/api/v1/batches/' + uploaded['batch']['id'], headers=headers)
        print('（已清理本次自检数据，加 --keep 可保留）')

    print('真实线路链路自检通过。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())