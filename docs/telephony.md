# 接真实电话线路

**先说实话：代码只是三件事里的一件。** 想真的把电话打出去，必须同时具备：

| 要素 | 谁提供 | 说明 |
| --- | --- | --- |
| 1. 线路与号码 | 你去办 | 云通信账号（阿里云语音 / 容联云 / 天润融通…）或 SIP 中继 + 一台跑 FreeSWITCH 的服务器 |
| 2. 主叫号码与资质 | 你去办 | 呼出必须用已报备的主叫号码；商业营销外呼还要有被叫同意，运营商侧有明确合规要求 |
| 3. 适配器代码 | 本仓库 | 已实现：把呼叫交给线路网关，状态由网关回调驱动 |

没有第 1、2 项，任何代码都打不出电话；只有第 1、2 项而没有第 3 项，本系统也调不动线路。
第 3 项已经做完了。

## 两种接法

### 接法 A：云通信 / 线路网关（推荐，本机就能跑通）

本系统实现的是一个**线路网关契约**：网关负责跟厂商打交道，本系统只跟它对三个接口。

```
本系统 ──POST /calls──────────────▶ 线路网关 ──▶ 厂商 API / SIP
本系统 ◀─POST /providers/rest/callback── 线路网关 ◀── 状态回调
本系统 ──POST /calls/{id}/hangup─▶ 线路网关
```

- 如果厂商的接口正好符合这个契约，那么**只改配置就能用**（见下面）。
- 如果厂商接口不一样（字段名、签名、状态码不同），有两条路：
  1. 用 `WAHU_TELEPHONY_STATE_MAP` 把厂商状态码映射过来（最常见的情形，不用改代码）；
  2. 写一个 20 行的转译网关（`scripts/fake_telephony_gateway.py` 就是现成的参考实现）。

### 接法 B：SIP 中继 + FreeSWITCH

有 SIP 中继（或 SIM 卡网关）时，在服务器上跑 FreeSWITCH，再写一个符合上面契约的网关
（`originate` 拨号、`CHANNEL_ANSWER`/`CHANNEL_HANGUP_COMPLETE` 事件转回调）。
本机是 Windows，FreeSWITCH 在 Windows 上不好跑，建议放 VPS。

## 配置（本系统这边）

```ini
WAHU_TELEPHONY_PROVIDER=rest
WAHU_TELEPHONY_BASE_URL=http://127.0.0.1:9400      # 网关地址
WAHU_TELEPHONY_TOKEN=dev-line-token                # 出站鉴权 + 回调校验，两边必须一致
WAHU_TELEPHONY_AGENT_PHONE=13800000000             # 双呼：先呼坐席这个号
WAHU_TELEPHONY_TIMEOUT_SECONDS=20                  # 回调超时判失败
WAHU_TELEPHONY_STATE_MAP={"2":"answered","3":"hangup"}   # 厂商状态码映射，可选
```

改完**必须重启进程**（`.env` 只在启动时读一次）。启动时会做校验：`PROVIDER=rest` 却没填
`BASE_URL` 会直接起不来，避免“以为接上了其实没接”。

## 网关要实现什么

### 1) 呼叫

```http
POST {BASE_URL}/calls
Authorization: Bearer {TOKEN}

{"call_id":"call-xxxx","phone":"13800000001","agent_phone":"13900000000","record":true}
```

必须返回 `provider_call_id`（也可叫 `id` / `call_id` / `CallId`）——系统靠它关联后续回调：

```json
{"provider_call_id": "abc123"}
```

### 2) 挂断

```http
POST {BASE_URL}/calls/{provider_call_id}/hangup
```

### 3) 回调（网关 → 本系统）

```http
POST {本系统}/api/v1/providers/rest/callback
X-Wahu-Token: {TOKEN}
```

```json
{"provider_call_id":"abc123","state":"answered"}
{"provider_call_id":"abc123","state":"hangup","talk_sec":57,"recording_url":"https://cdn/r.wav"}
{"provider_call_id":"abc123","state":"no_answer"}
```

- `state` 可取：`ringing` / `answered` / `hangup` / `failed` / `no_answer` / `busy` / `power_off` /
  `invalid_number` / `canceled`（也叫 `event`、`status`、`CallStatus`）
- `talk_sec`、`recording_url` 可以放在**挂断那次回调**里，系统会采信线路给的权威时长与录音地址
- 回调是**幂等**的：坐席先挂断、线路随后才回调时，状态不变，但真实时长与录音会被补上

## 双呼模式（真实外呼的常态）

真实外呼很少让坐席用浏览器说话，主流是**双呼**：平台先呼坐席手机，坐席接起后再呼客户，两边桥接。
所以 `WAHU_TELEPHONY_AGENT_PHONE` 填坐席的手机号，坐席侧的“通话”发生在自己手机上，
浏览器里的工作台只负责选客户、看状态、填结果。

## 本机怎么先跑通（不需要任何账号）

```powershell
# 1) 起一个线路网关（它假装自己是厂商，行为和真网关完全一致）
cd D:\waihu_system
python -X utf8 scripts/fake_telephony_gateway.py --port 9400 --answer-rate 1.0

# 2) 另开一个窗口，把系统切到真实线路模式
$env:WAHU_TELEPHONY_PROVIDER='rest'
$env:WAHU_TELEPHONY_BASE_URL='http://127.0.0.1:9400'
$env:WAHU_TELEPHONY_TOKEN='dev-line-token'
$env:WAHU_TELEPHONY_AGENT_PHONE='13800000000'
python -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 9300

# 3) 验证整条链路（建名单 → 拨号 → 等回调 → 挂断 → 提交结果 → 回写）
python -X utf8 scripts/check_real_line.py
```

跑通输出的样子：

```
[ok] 拨号：call-xxxx → 线路侧单号 gw-0003
     1. 拨号中
     2. 振铃中
     3. 通话中
[ok] 挂断：已结束，通话 1 秒，录音 ready
[ok] 取录音：HTTP 200，8044 字节
[ok] 回写队列：{'pending': 0, 'sent': 3, ...}
```

这套流程和真实厂商线路**走的是同一段代码**，所以换个 `BASE_URL` + 令牌就是真实线路。

## 换到真实厂商时要确认的字段

| 厂商 | 呼叫接口 | 状态字段 | 常见处理 |
| --- | --- | --- | --- |
| 阿里云语音服务 | `SingleCallByTone` / `SmartCall`（RPC 风格，需 HMAC 签名） | 回调里的状态码 | 用一个转译网关包一层签名与字段 |
| 容联云 | REST + 签名头 | `state` / `status` 数字码 | `WAHU_TELEPHONY_STATE_MAP` 映射数字码 |
| 天润融通 / 华为云 / 腾讯云 | REST | 数字或字符串状态 | 同上 |
| Twilio | `POST /2010-04-01/Accounts/{sid}/Calls.json`（Basic 认证） | `CallStatus`，回调 `StatusCallback` | 状态名基本可直接映射 |

如果厂商需要**请求签名**（阿里云 RPC、容联云等），建议做法是写一个小网关负责签名与字段转译，
本系统保持只认上面那三个接口——这样换厂商不动本系统一行代码。

## 阿里云：先选对产品线（最容易买错的一步）

阿里云有好几个都能"打电话"的产品，能力差得很远，买错了功能就对不上：

| 你想要的效果 | 该买的产品 | 接口（Action） | 对应本系统 |
| --- | --- | --- | --- |
| 机器人批量外呼、语音通知、首访触达 | **语音服务 → 语音通知 / 语音外呼** | `SingleCallByTone`（TTS）/ `SingleCallByVoice`（语音文件） | AI 机器人模块 |
| 智能外呼机器人（能听懂客户说话并应答） | **智能联络中心 / 智能外呼** | `SmartCall` 等 | AI 机器人模块 |
| **人工坐席双呼、真实通话 + 录音** | **云呼叫中心 CCC** | `ccc` 那套接口（双呼/坐席状态） | 坐席工作台 |

**关键区别**：`SingleCallByTone` 这类是**单向**的——平台给客户播一段语音就结束，
客户没法跟你的坐席对话，也没有坐席侧的通话记录。所以：

- 只做机器人外呼 → 语音通知类就够，便宜且好接；
- 要**人工坐席真的和客户通话** → 必须用云呼叫中心（CCC），语音通知那套做不到。

我们这套系统两边都支持，但**用的是哪个产品线，决定了你配哪些 `--param`。**

## 阿里云接入步骤

1. **开通产品 + 申请主叫号码**：语音服务控制台里申请号码（或申请显号），拿到 `CalledShowNumber`。
2. **建模板**：语音通知要建 TTS 模板，审核通过后拿到 `TtsCode`（如 `TTS_10086`）。
3. **拿 AccessKey**：RAM 里建一个子账号，只给语音服务的权限，拿到 ID/Secret。
4. **配回调地址**：控制台里把状态回调配成 `http://<阿里云能访问到的地址>:9400/aliyun/callback`
   （本机调试可以用内网穿透；生产建议放公网服务器）。
5. **起网关**（AccessKey 只走环境变量，不写文件）：

```powershell
$env:ALIYUN_ACCESS_KEY_ID='LTAI...'
$env:ALIYUN_ACCESS_KEY_SECRET='...'
python -X utf8 scripts/aliyun_voice_gateway.py --live --port 9400 ``
  --param CalledShowNumber=0571xxxxxxxx ``
  --param TtsCode=TTS_xxxxxxxx ``
  --param CalledNumber={phone} ``
  --param OutId={call_id}
```

`{phone}` / `{call_id}` 是占位符，每个呼叫会被替换成实际值，所以不用改代码。

6. **先干跑自检**（不发真请求，只把将要发出的报文打出来）：

```powershell
python -X utf8 scripts/aliyun_voice_gateway.py --print-request ``
  --param CalledShowNumber=0571xxxxxxxx --param TtsCode=TTS_xxxxxxxx --param CalledNumber={phone}
```

输出就是阿里云 RPC 的真实报文形状（AccessKeyId 与 Signature 已打码）：

```
POST https://dyvmsapi.aliyuncs.com/
{ "Format": "JSON", "Version": "2017-05-25", "Action": "SingleCallByTone",
  "SignatureMethod": "HMAC-SHA1", "SignatureVersion": "1.0",
  "CalledShowNumber": "057188888888", "TtsCode": "TTS_10086", "CalledNumber": "13800000001", ... }
```

7. **把系统切过去**（`.env` 改完重启）：

```ini
WAHU_TELEPHONY_PROVIDER=rest
WAHU_TELEPHONY_BASE_URL=http://127.0.0.1:9400
WAHU_TELEPHONY_TOKEN=dev-line-token
WAHU_TELEPHONY_AGENT_PHONE=13800000000
```

8. **验收**：`python -X utf8 scripts/check_real_line.py`

签名那层（`app/integrations/aliyun/signature.py`）严格按阿里云 RPC 规范实现并单测锁定；
换 Action、换参数都只用命令行传，不用改代码。

### 阿里云回调

网关的 `/aliyun/callback` 同时接受 **form-encoded** 与 **JSON** 两种回调，字段名认这些：

- 呼叫 ID：`call_id` / `CallId` / `callId`
- 状态：`state` / `status` / `CallStatus` / `call_status`
- 时长：`duration` / `talk_sec` / `call_duration` / `billsec`
- 录音：`recording_url` / `record_url` / `file_url`

各家产品线的回调字段不完全一样，**你第一次收到真实回调后，把原始报文发我，我按它把映射核准**
（或者你自己用 `--state-map` 调，例如 `--state-map '{"success":"answered","fail":"failed"}'`）。

### 阿里云常见错误

| 返回 | 含义 | 怎么办 |
| --- | --- | --- |
| `SignatureDoesNotMatch` | 签名不对 | 检查 AccessKeySecret 是否有多余空格；这是本仓库单测覆盖的部分，一般不是算法问题 |
| `InvalidAccessKeyId.NotFound` | AccessKey 不存在 | 检查环境变量拼写 |
| `isv.AMOUNT_NOT_ENOUGH` | 账户余额/套餐不足 | 充值或买套餐 |
| `isv.TTS_TEMPLATE_ILLEGAL` | 模板不可用 | 模板是否审核通过、`TtsCode` 是否写对 |
| `isv.BUSINESS_LIMIT_CONTROL` | 触发流控 | 降低并发 |
| `isv.DAY_LIMIT_CONTROL` | 超过日限 | 你的号码在阿里云侧的日限，与系统内的每日上限是两回事 |
| `isv.MOBILE_NUMBER_ILLEGAL` | 被叫号码不合法 | 号码必须是真实的国内号码 |

（完整错误码看阿里云控制台的接口文档；网关会把阿里云的原始返回打日志，方便对号。）

## 常见问题

| 现象 | 原因 |
| --- | --- |
| 拨号返回 502 `telephony_not_configured` | 没填 `WAHU_TELEPHONY_BASE_URL` |
| 拨号返回 502 `telephony_unreachable` | 网关没起或地址不对 |
| 拨号返回 502 `telephony_bad_response` | 网关没回 `provider_call_id`，回调无法关联 |
| 状态一直停在「拨号中」 | 网关没回调，或回调地址/令牌不对；`WAHU_TELEPHONY_TIMEOUT_SECONDS` 后会判失败 |
| 回调返回 401 | `X-Wahu-Token` 与 `WAHU_TELEPHONY_TOKEN` 不一致 |
| 回调返回 409 | 回调打到了非当前生效的线路名（`/providers/{name}/callback`） |
| 回调返回 422 | 缺少 `provider_call_id`，或状态值认不出来（用 `STATE_MAP` 补映射） |
| 通话时长是 0 或偏短 | 网关没在挂断回调里带 `talk_sec`，系统只能用本地时间戳估算 |
| 录音打不开 | 真实线路的录音接口是 **307 跳转**到厂商地址；厂商地址若需要鉴权或已过期，请在网关侧转存 |