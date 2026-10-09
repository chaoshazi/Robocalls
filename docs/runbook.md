# 全栈运行手册

覆盖外呼系统本体、它依赖的自研 CRM，以及常见故障的排查顺序。

## 1. 服务与端口

| 服务 | 端口 | 仓库 | 本机状态 |
| --- | --- | --- | --- |
| 外呼系统 API（兼托管前端构建产物） | 9300 | `D:\waihu_system` | 已验证（sqlite） |
| 外呼系统前端 dev | 5176 | `D:\waihu_system\web` | 已验证（tsc + vite build） |
| 自研 CRM API | 9100 | `D:\crm` | 已验证（sqlite，本站已接通） |
| 自研 CRM 前端 dev | 5174 | `D:\crm\web` | 兄弟仓库 |
| 自研 ERP API | 9200 | `D:\erp` | 本系统暂未使用 |
| AI 能力层 API | 8000 | `D:\codex` | 兄弟仓库 |
| Postgres（可选） | 5434 | `D:\waihu_system` | 未验证 |

端口刻意错开：AI 层 8000 / 5173，CRM 9100 / 5174，ERP 9200 / 5175，外呼 9300 / 5176。

## 2. 一次性准备

```powershell
python -V          # 需要 3.11+
node -v            # 需要 18+

cd D:\waihu_system
pip install -r requirements.txt
copy .env.example .env
cd web
npm install
```

## 3. 启动顺序

### 3.1 只用内置假数据（最快）

```powershell
cd D:\waihu_system
python -X utf8 scripts/seed_demo.py                        # 可选：灌演示数据
python -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 9300
```

`.env` 保持 `WAHU_CRM_MODE=fake` 即可，不需要 CRM 在跑。

### 3.2 接真实自研 CRM

```powershell
# 先起 CRM
cd D:\crm
python -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 9100

# 只读探测契约（不会写任何东西）
cd D:\waihu_system
python -X utf8 scripts/crm_probe.py
```

`.env` 改成 `WAHU_CRM_MODE=rest`，并确认 `WAHU_CRM_API_TOKEN` 与 CRM 的 `CRM_SERVICE_TOKEN` 一致，然后重启外呼系统进程。

### 3.3 前端

```powershell
cd D:\waihu_system\web
npm run dev        # http://localhost:5176
```

生产形态是 `npm run build` 出 `web/dist`，由 FastAPI 在 9300 一起托管（`WAHU_SERVE_WEB=true`）。

## 4. 常见故障排查顺序

1. **401 未授权**：令牌过期（默认 12 小时）或 `.env` 里 `WAHU_SECRET_KEY` 改过导致旧令牌失效 → 重新登录。
2. **起不来，报「生产环境配置未通过校验」**：`WAHU_ENV` 落到了生产取值。把 `.env` 调回 `dev`，或按报错逐项补齐（生产不允许默认密钥、模拟线路、模拟语音、stub 大模型、fake CRM）。
3. **拨号报「当前处于免打扰时段」**：`WAHU_COMPLIANCE_DND_START/END`（默认 21:00–09:00 禁呼）。本地演示可临时改成 `00:00`/`00:00`（表示不限制）。
4. **拨号报「该号码今日已被拨打 N 次」**：`WAHU_COMPLIANCE_PER_NUMBER_DAILY_LIMIT`（默认 3）。演示时改大或清掉当天通话记录。
5. **拨号报「你还有一通未结束的电话」**：同一坐席同时只允许一通。把上一通挂断并提交结果。
6. **回写一直是 failed**：`WAHU_CRM_MODE=rest` 但 CRM 没起、或令牌不对。先用 `scripts/crm_probe.py` 确认连通，再在审计/回写页点「重推」。
7. **回写是 skipped**：这条名单来自 CSV 导入，没有 CRM 归属记录，没有可挂靠的对象，属于预期行为。
8. **状态一直停在「拨号中」**：节拍器没跑（`WAHU_TICKER_ENABLED=false`）或进程卡住。检查 `/health` 里的 `ticker` 字段。
9. **接口返回但界面空白**：前端 dev 代理没起来，或构建产物过期（`npm run build`）。
10. **中文乱码**：跑 Python 忘了加 `-X utf8`。

## 5. 管理员与初始数据

- 首次启动自动建表并创建管理员，取值见 `WAHU_BOOTSTRAP_ADMIN_*`（默认 `admin@example.com` / `admin12345`）。
- `scripts/seed_demo.py --reset` 会**清空所有表**再灌演示数据，只在本地用。
- 演示数据里 `leads` 两条与 `D:\crm` 的演示数据同 ID，方便 fake / rest 两种模式对比。