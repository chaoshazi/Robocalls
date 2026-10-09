# AGENTS.md

## Repository state

`D:\waihu_system` 是外呼系统本体：名单、外呼任务、坐席工作台、模拟外呼、通话记录与录音、
CRM 回写、合规与报表，外加 AI 机器人外呼。它与 `D:\crm`（自研 CRM，9100）、`D:\erp`（9200）、
`D:\codex`（AI 能力层，8000）是**互相独立的仓库**，只通过 REST 契约交互。

- `app/` 后端：`core/`（配置、日志、时钟、安全、号码）、`adapters/`（存储与表元数据）、
  `api/`（路由与依赖）、`services/`（业务）、`telephony/`（线路）、`integrations/crm/`（CRM 网关）、
  `robot/`（二期：脚本引擎、大模型、模拟语音）
- `app/contract.py` 是枚举与中文标签的唯一来源（角色、通话状态、结果码、意向、任务与名单状态）
- `app/adapters/tables.py` 是表结构的唯一来源，`sql/001_init.sql` 由它生成
- `web/` 控制台（Vite + React + TS + Tailwind），构建产物 `web/dist` 由 FastAPI 托管
- `tests/` 用标准库 unittest；`scripts/` 放演示数据与只读探测

## Commands

```powershell
cd D:\waihu_system
pip install -r requirements.txt

# 全量测试（全离线：sqlite 内存库 + 内置假 CRM + 模拟线路 + stub 大模型）
python -X utf8 -m unittest discover -s tests -t .
python -X utf8 -m compileall -q app tests scripts      # 语法检查

# 起后端（默认端口 9300，同时托管 web/dist）
python -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 9300

# 灌演示数据 / 只读探测自研 CRM 契约
python -X utf8 scripts/seed_demo.py
python -X utf8 scripts/crm_probe.py

cd web
npm install
npx tsc --noEmit
npm run build
npm run dev                                            # 5176，代理到 9300
```

没有配置 lint / formatter，不要引入新的。测试用标准库 unittest，**不用 pytest**。

## 硬性约定

- 跑 Python 一律加 `-X utf8`，否则中文日志与输出在 GBK 控制台会乱码。
- 源码与文档用单引号，不写双引号（JSON 与 HTTP body 除外）；注释中文、标识符英文；UTF-8 无 BOM + LF。
- 真实密钥只写 `.env`（已 gitignore）；`.env.example` 是模板，填进去不生效。
- 号码一律脱敏展示；看全号只有「通话详情」一条路（管理员，且写审计）。列表接口永远返回掩码号。
- 列表一律脱敏：`batches.list_items`、`tasks.list_items`、`workbench` 返回的都是 `138****0001`。
- 回写只走 `WritebackService`，只追加 activities / notes / tasks；不要绕过它直接调 CRM，也不要去改 CRM 业务字段。
- 通话状态只由 `CallService` 的状态机推进：模拟线路走 `plan` + 节拍器 tick，真实线路走网关回调
  （`apply_provider_event`）。不要在别处直接改 `calls.state`。
- **真实线路（`rest`）下绝不允许伪造任何东西**：不本地生成假录音（录音一律 307 跳转到厂商地址）、
  不自己猜通话状态（只认回调）。迟到或重复的回调不改状态，但必须吸收线路给的权威 `talk_sec` 与 `recording_url`。
- 枚举、状态码、中文标签一律从 `app/contract.py` 取，别在业务代码里硬编码字符串。
- `.env` 与后端代码只在进程启动时读一次，改完必须重启。
- `WAHU_ENV` 只认 `dev` / `local` / `test` / `stage` / `staging` / `prod` / `production`。
  落到生产那四个取值时启动会先校验：默认密钥、默认管理员口令、模拟线路、模拟语音、stub 大模型、
  fake CRM、脱敏关闭、CORS 通配，任一项不满足直接起不来（`Settings._guard_production`，
  用例见 `tests/test_config_guard.py`）。唯一逃生开关是 `WAHU_ALLOW_SIMULATED_IN_PROD=true`。

## 已改过的地方（改前先读）

- 加表 / 改表：改 `app/adapters/tables.py`，再重新生成 `sql/001_init.sql`，并确认 sqlite 自动建表仍然通过。
- 加通话结果码：改 `app/contract.py` 的 `CALL_RESULT_ROWS`（同时决定 category / outcome / 默认意向）。
- 加线路或语音：实现 `app/telephony/base.py` 的 `TelephonyProvider` 或 `app/robot/llm.py` 的 `SimulatedVoice` 同款方法，
  上层服务不要因此改动。
- 机器人话术脚本结构改了 `app/robot/engine.py` 的话，`web/src/components/Robot.tsx` 的示例脚本要一起改。