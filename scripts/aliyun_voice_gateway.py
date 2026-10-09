'''阿里云语音服务网关：把外呼系统的三个接口翻译成阿里云 RPC 调用。

外呼系统只跟网关打交道（POST /calls 呼叫、POST /calls/{id}/hangup 挂断、状态回调），
网关负责阿里云那套东西：RPC 签名、参数命名、主叫显号、模板变量、状态回调解析。

用法：

    # 1) 先干跑：把将要发给阿里云的请求打出来（密钥打码），不发请求
    python -X utf8 scripts/aliyun_voice_gateway.py --dry-run --param CalledShowNumber=0571xxxx --param TtsCode=TTS_xxx

    # 2) 上真账号：AccessKey 只从环境变量读，不写文件
    set ALIYUN_ACCESS_KEY_ID=LTAI...
    set ALIYUN_ACCESS_KEY_SECRET=...
    python -X utf8 scripts/aliyun_voice_gateway.py --live --param CalledShowNumber=0571xxxx --param TtsCode=TTS_xxx

参数里可以用 {phone} 与 {call_id} 占位，每个呼叫会被替换成实际值，例如：
    --param CalledNumber={phone} --param OutId={call_id}

阿里云那个产品线要用哪个 Action、哪些参数，由你自己用 --param 传，不必改代码：
    语音通知/语音外呼   SingleCallByTone（TTS）或 SingleCallByVoice（语音文件）
    智能外呼（机器人）  SmartCall
    云呼叫中心（坐席双呼）  用 ccc 那套接口，同样用 --action/--param 传

状态回调：阿里云控制台里配的回调地址指向本网关的 /aliyun/callback，
网关再翻译成本系统的规范状态转发给外呼系统。字段名各家产品线不一致，
用 --state-map 做映射，例如 --state-map '{"success":"answered","fail":"failed"}'。
'''

from __future__ import annotations

import argparse
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.aliyun.signature import build_request, redact  # noqa: E402

CALLS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()
CONFIG: dict[str, Any] = {}

DEFAULT_STATE_MAP = {
    # 常见叫法先给一份默认映射，实际以你账号回调里的值为准，用 --state-map 覆盖
    'success': 'answered',
    'succeed': 'answered',
    'answered': 'answered',
    'ringing': 'ringing',
    'ring': 'ringing',
    'calling': 'ringing',
    'fail': 'failed',
    'failed': 'failed',
    'no_answer': 'no_answer',
    'unanswer': 'no_answer',
    'busy': 'busy',
    'power_off': 'power_off',
    'hangup': 'hangup',
    'end': 'hangup',
}

CALL_ID_KEYS = ('call_id', 'CallId', 'callId', 'provider_call_id')
STATE_KEYS = ('state', 'status', 'CallStatus', 'call_status', 'callState')
TALK_KEYS = ('duration', 'talk_sec', 'call_duration', 'billsec', 'CallDuration')
RECORDING_KEYS = ('recording_url', 'record_url', 'file_url', 'oss_url')


def log(message: str) -> None:
    print(time.strftime('%H:%M:%S') + ' ' + message, flush=True)


def pick(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if data.get(key) not in (None, ''):
            return data[key]
    return None


def as_int(value: Any) -> int | None:
    if value in (None, ''):
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def map_state(raw: Any) -> str:
    if raw in (None, ''):
        return ''
    text = str(raw).strip()
    table = CONFIG['state_map']
    mapped = table.get(text) or table.get(text.lower())
    return str(mapped) if mapped else text


def business_params(phone: str, call_id: str) -> dict[str, Any]:
    '''把 --param 里的占位符替换成这次呼叫的实际值。'''
    params: dict[str, Any] = {}
    for key, value in CONFIG['params'].items():
        params[key] = str(value).replace('{phone}', phone).replace('{call_id}', call_id)
    return params


def send_to_aliyun(phone: str, call_id: str) -> dict[str, Any]:
    business = business_params(phone, call_id)
    url, params = build_request(
        action=CONFIG['action'],
        version=CONFIG['version'],
        access_key_id=CONFIG['access_key_id'],
        access_key_secret=CONFIG['access_key_secret'],
        business=business,
        region_id=CONFIG['region_id'],
        endpoint=CONFIG['endpoint'],
    )
    if CONFIG['dry_run']:
        log('干跑：本应 POST ' + url)
        log('干跑：参数 ' + json.dumps(redact(params), ensure_ascii=False))
        return {'Code': 'DRYRUN', 'CallId': 'dry-' + call_id}

    body = urlencode(params).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=body,
        method='POST',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as error:
        text = error.read().decode('utf-8', 'replace')
        log('阿里云返回 HTTP ' + str(error.code) + '：' + text[:300])
        return {'Code': 'HTTP_' + str(error.code), 'Message': text[:200]}
    except Exception as error:
        log('调用阿里云失败：' + str(error))
        return {'Code': 'NETWORK_ERROR', 'Message': str(error)}
    log('阿里云返回：' + json.dumps(payload, ensure_ascii=False))
    return payload


def forward_callback(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        CONFIG['callback_url'],
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json', 'X-Wahu-Token': CONFIG['token']},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            log('转给外呼系统 ' + str(payload.get('state')) + ' → HTTP ' + str(response.status))
    except urllib.error.HTTPError as error:
        log('转发出错 HTTP ' + str(error.code) + '：' + error.read().decode('utf-8', 'replace')[:200])
    except Exception as error:
        log('转发出错：' + str(error))


def simulate(call_id: str) -> None:
    '''干跑模式下的本地模拟：走一遍振铃 → 接通，让链路能完整验收。'''
    time.sleep(float(CONFIG['ring_delay']))
    forward_callback({'provider_call_id': call_id, 'state': 'ringing'})
    time.sleep(float(CONFIG['answer_delay']))
    with LOCK:
        record = CALLS.get(call_id)
        if record is None or record.get('ended'):
            return
        record['answered_at'] = time.time()
    forward_callback({'provider_call_id': call_id, 'state': 'answered'})


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(length) if length else b''

    def do_POST(self) -> None:  # noqa: N802
        raw = self._read_body()

        # 1) 外呼系统发起呼叫
        if self.path == '/calls':
            token = self.headers.get('Authorization') or ''
            if token != 'Bearer ' + str(CONFIG['token']):
                self._json(401, {'message': '令牌不对'})
                return
            try:
                payload = json.loads(raw.decode('utf-8') or '{}')
            except ValueError:
                payload = {}
            phone = str(payload.get('phone') or '')
            call_id = str(payload.get('call_id') or ('call-' + str(len(CALLS) + 1)))
            log('收到呼叫 ' + call_id + ' 客户 ' + phone)
            result = send_to_aliyun(phone, call_id)
            provider_call_id = str(pick(result, ('CallId', 'call_id', 'Callid')) or '')
            if not provider_call_id:
                self._json(502, {'message': '阿里云没有返回 CallId', 'upstream': result})
                return
            with LOCK:
                CALLS[provider_call_id] = {'phone': phone, 'created_at': time.time(), 'state': 'dialing'}
            if CONFIG['dry_run']:
                threading.Thread(target=simulate, args=(provider_call_id,), daemon=True).start()
            self._json(200, {'provider_call_id': provider_call_id})
            return

        # 2) 外呼系统要求挂断
        if self.path.startswith('/calls/') and self.path.endswith('/hangup'):
            provider_call_id = self.path.split('/')[2]
            log('收到挂断 ' + provider_call_id)
            with LOCK:
                record = CALLS.get(provider_call_id) or {}
                answered_at = record.get('answered_at')
                record['ended'] = True
                CALLS[provider_call_id] = record
            if CONFIG['dry_run']:
                talk = max(1, int(time.time() - answered_at)) if answered_at else 0
                payload: dict[str, Any] = {'provider_call_id': provider_call_id, 'state': 'hangup'}
                if talk:
                    payload['talk_sec'] = talk
                threading.Thread(
                    target=forward_callback, args=(payload,), daemon=True
                ).start()
                self._json(200, {'ok': True})
                return
            # 单向语音通知类外呼没有「挂断」这个动作
            self._json(400, {'ok': False, 'message': '阿里云语音通知类外呼不支持挂断，通话由平台自行结束'})
            return

        # 3) 阿里云回调本网关
        if self.path.startswith('/aliyun/callback'):
            text = raw.decode('utf-8', 'replace')
            data: dict[str, Any] = {}
            if text.strip().startswith('{'):
                try:
                    data = json.loads(text)
                except ValueError:
                    data = {}
            if not data:
                parsed = parse_qs(text)
                data = {key: values[0] for key, values in parsed.items() if values}
            if not data:
                parsed = parse_qs(self.path.partition('?')[2])
                data = {key: values[0] for key, values in parsed.items() if values}
            log('阿里云回调：' + json.dumps(data, ensure_ascii=False))
            provider_call_id = str(pick(data, CALL_ID_KEYS) or '')
            state = map_state(pick(data, STATE_KEYS))
            if provider_call_id and state:
                payload = {'provider_call_id': provider_call_id, 'state': state}
                talk = as_int(pick(data, TALK_KEYS))
                if talk is not None:
                    payload['talk_sec'] = talk
                recording = pick(data, RECORDING_KEYS)
                if recording:
                    payload['recording_url'] = str(recording)
                threading.Thread(target=forward_callback, args=(payload,), daemon=True).start()
            self._json(200, {'ok': True})
            return

        self._json(404, {'message': '没有这个接口：' + self.path})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == '/health':
            self._json(200, {'ok': True, 'mode': 'dry-run' if CONFIG['dry_run'] else 'live',
                             'action': CONFIG['action'], 'calls': len(CALLS)})
            return
        self._json(404, {'message': '没有这个接口：' + self.path})

    def handle_one_request(self) -> None:
        # 对端断开（我们的客户端换连接时会这样）不该刷一堆堆栈出来
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def log_message(self, *args: Any) -> None:
        return


def parse_params(items: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in items:
        key, _, value = item.partition('=')
        if key:
            params[key.strip()] = value
    return params


def main() -> int:
    parser = argparse.ArgumentParser(description='阿里云语音服务网关（转译层）')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9400)
    parser.add_argument('--token', default='dev-line-token', help='与外呼系统 WAHU_TELEPHONY_TOKEN 一致')
    parser.add_argument('--live', action='store_true', help='真的调用阿里云（默认干跑，只打印请求）')
    parser.add_argument('--action', default='SingleCallByTone', help='阿里云 Action，如 SingleCallByTone / SingleCallByVoice / SmartCall')
    parser.add_argument('--version', default='2017-05-25', help='阿里云 API 版本')
    parser.add_argument('--endpoint', default='https://dyvmsapi.aliyuncs.com', help='阿里云接口域名')
    parser.add_argument('--region', default='cn-hangzhou')
    parser.add_argument(
        '--param',
        action='append',
        default=[],
        help='业务参数，可重复；支持 {phone} {call_id} 占位，如 --param CalledShowNumber=0571xxxx',
    )
    parser.add_argument('--state-map', default='', help='阿里云回调状态 → 本系统状态的 JSON 映射')
    parser.add_argument('--callback-url', default='http://127.0.0.1:9300/api/v1/providers/rest/callback')
    parser.add_argument('--ring-delay', type=float, default=1.0)
    parser.add_argument('--answer-delay', type=float, default=3.0)
    parser.add_argument('--print-request', action='store_true', help='只打印一次示例请求然后退出')
    args = parser.parse_args()

    access_key_id = os.environ.get('ALIYUN_ACCESS_KEY_ID', '')
    access_key_secret = os.environ.get('ALIYUN_ACCESS_KEY_SECRET', '')
    dry_run = not args.live

    state_map = dict(DEFAULT_STATE_MAP)
    if args.state_map:
        try:
            state_map.update({str(k): str(v) for k, v in json.loads(args.state_map).items()})
        except ValueError:
            print('--state-map 必须是 JSON，例如 {"success":"answered"}')
            return 2

    CONFIG.update(
        {
            'dry_run': dry_run,
            'token': args.token,
            'action': args.action,
            'version': args.version,
            'endpoint': args.endpoint,
            'region_id': args.region,
            'access_key_id': access_key_id or 'DRY-RUN',
            'access_key_secret': access_key_secret or 'DRY-RUN',
            'params': parse_params(args.param),
            'state_map': state_map,
            'callback_url': args.callback_url,
            'ring_delay': args.ring_delay,
            'answer_delay': args.answer_delay,
        }
    )

    if not CONFIG['params']:
        print('提示：还没传业务参数。至少要传主叫显号与模板号，例如：')
        print('  --param CalledShowNumber=0571xxxxxxxx --param TtsCode=TTS_xxxxxxxx')
        print('  被叫号码一般由 --param CalledNumber={phone} 从呼叫请求里取。')
        print()

    if args.print_request:
        business = business_params('13800000001', 'call-sample')
        url, params = build_request(
            action=CONFIG['action'],
            version=CONFIG['version'],
            access_key_id=CONFIG['access_key_id'],
            access_key_secret=CONFIG['access_key_secret'],
            business=business,
            region_id=CONFIG['region_id'],
            endpoint=CONFIG['endpoint'],
        )
        print('将要发给阿里云的请求：')
        print('  POST ' + url)
        print('  ' + json.dumps(redact(params), ensure_ascii=False, indent=2))
        return 0

    if args.live and not (access_key_id and access_key_secret):
        print('--live 需要环境变量 ALIYUN_ACCESS_KEY_ID 与 ALIYUN_ACCESS_KEY_SECRET')
        return 2

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print('阿里云网关已启动：http://' + args.host + ':' + str(args.port)
          + '（' + ('干跑模式' if dry_run else '真实调用') + '）')
    print('  Action      ：' + args.action + ' / ' + args.version)
    print('  接口域名    ：' + args.endpoint)
    print('  业务参数    ：' + (json.dumps(CONFIG['params'], ensure_ascii=False) or '（空）'))
    print('  阿里云回调  ：把控制台的回调地址配成 http://<本机可达地址>:' + str(args.port) + '/aliyun/callback')
    print('  转发给系统  ：' + args.callback_url)
    print()
    print('配到外呼系统里：')
    print('  WAHU_TELEPHONY_PROVIDER=rest')
    print('  WAHU_TELEPHONY_BASE_URL=http://' + args.host + ':' + str(args.port))
    print('  WAHU_TELEPHONY_TOKEN=' + args.token)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('已停止。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())