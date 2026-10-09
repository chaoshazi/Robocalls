'''本机线路网关（开发/验收用）：实现外呼系统要求的那三个接口，让「真实线路」这条链路
在没有真实账号的情况下也能端到端跑通。

它做的事情和一个真实的线路网关完全一样：
1. POST /calls                    收下呼叫请求，返回 provider_call_id；
2. 过一会儿回调 /api/v1/providers/rest/callback 告诉系统「振铃了」；
3. 再过一会儿回调「接通了」或「无人接听」；
4. POST /calls/{id}/hangup        系统要求挂断时，回调「通话结束 + 时长 + 录音地址」；
5. GET  /recordings/{id}.wav      提供一个能播放的静音 WAV 当录音。

接真实线路时，把这三个接口换成厂商的（或用它做参考写一层转译），本系统代码一行都不用改。

用法：
    python -X utf8 scripts/fake_telephony_gateway.py
    python -X utf8 scripts/fake_telephony_gateway.py --port 9400 --answer-rate 0.7 --token dev-line-token

然后把外呼系统的 .env 配成：
    WAHU_TELEPHONY_PROVIDER=rest
    WAHU_TELEPHONY_BASE_URL=http://127.0.0.1:9400
    WAHU_TELEPHONY_TOKEN=dev-line-token
    WAHU_TELEPHONY_AGENT_PHONE=13800000000
'''

from __future__ import annotations

import argparse
import json
import random
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any

CALLS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()
CONFIG: dict[str, Any] = {}


def log(message: str) -> None:
    print(time.strftime('%H:%M:%S') + ' ' + message, flush=True)


def silent_wav(seconds: int) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(8000)
        handle.writeframes(b'\x80' * int(8000 * max(1, seconds)))
    return buffer.getvalue()


def callback(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        CONFIG['callback_url'],
        data=body,
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'X-Wahu-Token': CONFIG['token'],
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            log('回调 ' + str(payload.get('state')) + ' → HTTP ' + str(response.status))
    except urllib.error.HTTPError as error:
        log('回调失败 HTTP ' + str(error.code) + '：' + error.read().decode('utf-8', 'replace')[:200])
    except Exception as error:  # 网关侧失败不影响呼叫本身
        log('回调失败：' + str(error))


def lifecycle(call_id: str) -> None:
    '''模拟一通真实外呼：振铃 → 接通 / 无人接听 → 等系统挂断。'''
    time.sleep(float(CONFIG['ring_delay']))
    callback({'provider_call_id': call_id, 'state': 'ringing'})

    time.sleep(float(CONFIG['answer_delay']))
    with LOCK:
        record = CALLS.get(call_id)
    if record is None or record.get('ended'):
        return
    if random.random() < float(CONFIG['answer_rate']):
        with LOCK:
            CALLS[call_id]['answered_at'] = time.time()
            CALLS[call_id]['state'] = 'answered'
        callback({'provider_call_id': call_id, 'state': 'answered'})
    else:
        with LOCK:
            CALLS[call_id]['ended'] = True
            CALLS[call_id]['state'] = 'no_answer'
        callback({'provider_call_id': call_id, 'state': 'no_answer'})


def end_call(call_id: str, result_code: str | None = None) -> None:
    with LOCK:
        record = CALLS.get(call_id)
        if record is None or record.get('ended'):
            return
        record['ended'] = True
        answered_at = record.get('answered_at')
    if answered_at:
        talk = max(1, int(time.time() - answered_at))
        payload: dict[str, Any] = {
            'provider_call_id': call_id,
            'state': 'hangup',
            'talk_sec': talk,
            'recording_url': CONFIG['public_url'] + '/recordings/' + call_id + '.wav',
        }
    else:
        payload = {'provider_call_id': call_id, 'state': 'hangup', 'result_code': result_code or 'canceled'}
    callback(payload)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get('Authorization') or ''
        return header == 'Bearer ' + str(CONFIG['token'])

    def do_POST(self) -> None:  # noqa: N802 - http.server 的命名约定
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(raw.decode('utf-8') or '{}')
        except ValueError:
            payload = {}

        if self.path == '/calls':
            if not self._authorized():
                self._json(401, {'message': '令牌不对'})
                return
            call_id = 'gw-' + str(len(CALLS) + 1).zfill(4)
            with LOCK:
                CALLS[call_id] = {'phone': payload.get('phone'), 'state': 'dialing', 'created_at': time.time()}
            log(
                '收到呼叫 ' + call_id
                + ' 客户 ' + str(payload.get('phone'))
                + ' 坐席 ' + str(payload.get('agent_phone') or '-')
            )
            threading.Thread(target=lifecycle, args=(call_id,), daemon=True).start()
            self._json(200, {'provider_call_id': call_id})
            return

        if self.path.startswith('/calls/') and self.path.endswith('/hangup'):
            call_id = self.path.split('/')[2]
            log('收到挂断 ' + call_id)
            threading.Thread(target=end_call, args=(call_id,), daemon=True).start()
            self._json(200, {'ok': True})
            return

        self._json(404, {'message': '没有这个接口：' + self.path})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == '/health':
            self._json(200, {'ok': True, 'calls': len(CALLS), 'mode': 'fake-gateway'})
            return
        if self.path.startswith('/recordings/'):
            name = Path(self.path).name
            call_id = name.replace('.wav', '')
            with LOCK:
                record = CALLS.get(call_id) or {}
            answered_at = record.get('answered_at')
            seconds = max(1, int(time.time() - answered_at)) if answered_at else 3
            body = silent_wav(min(seconds, 120))
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {'message': '没有这个接口：' + self.path})

    def handle_one_request(self) -> None:
        # 对端断开（我们的客户端换连接时会这样）不该刷一堆堆栈出来
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def log_message(self, *args: Any) -> None:
        return  # 自己打的日志更清楚，屏蔽默认访问日志


def main() -> int:
    parser = argparse.ArgumentParser(description='本机线路网关（开发/验收用）')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9400)
    parser.add_argument('--token', default='dev-line-token')
    parser.add_argument('--answer-rate', type=float, default=0.7)
    parser.add_argument('--ring-delay', type=float, default=1.0)
    parser.add_argument('--answer-delay', type=float, default=3.0)
    parser.add_argument(
        '--callback-url',
        default='http://127.0.0.1:9300/api/v1/providers/rest/callback',
    )
    parser.add_argument('--public-url', default='', help='录音地址对外前缀，默认用 host:port')
    args = parser.parse_args()

    if not 0.0 <= args.answer_rate <= 1.0:
        print('--answer-rate 必须落在 0~1')
        return 2

    CONFIG.update(
        {
            'token': args.token,
            'answer_rate': args.answer_rate,
            'ring_delay': args.ring_delay,
            'answer_delay': args.answer_delay,
            'callback_url': args.callback_url,
            'public_url': args.public_url or ('http://' + args.host + ':' + str(args.port)),
        }
    )
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print('线路网关已启动：http://' + args.host + ':' + str(args.port))
    print('  令牌        ：' + args.token)
    print('  接通率      ：' + str(args.answer_rate))
    print('  回调地址    ：' + args.callback_url)
    print('配到外呼系统里：')
    print('  WAHU_TELEPHONY_PROVIDER=rest')
    print('  WAHU_TELEPHONY_BASE_URL=http://' + args.host + ':' + str(args.port))
    print('  WAHU_TELEPHONY_TOKEN=' + args.token)
    print('  WAHU_TELEPHONY_AGENT_PHONE=13800000000')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())