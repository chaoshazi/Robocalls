# 接口说明

统一前缀 `/api/v1`（认证在 `/api/auth`）。除 `/health`、`/api/auth/login` 外都需要
`Authorization: Bearer <token>`。

错误体固定为：

```json
{ "detail": "给用户看的中文原因", "code": "机器可读的短码" }
```

常用 `code`：`unauthorized`(401)、`forbidden`(403)、`not_found`(404)、`conflict`(409)、
`compliance_blocked`(409，拦截原因见 `detail`)、`validation_failed`(422)、`upstream_error`(502)。

## 认证与元数据

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | `{email, password}` → `{token, user}` |
| GET | `/api/auth/me` | 当前身份 |
| POST | `/api/auth/password` | `{old_password, new_password}` |
| GET | `/health` | 版本、存储、线路、CRM 模式、节拍器开关、SSE 订阅数（免鉴权） |
| GET | `/api/v1/meta` | 角色、通话状态、结果码、意向、任务与名单状态等全部枚举（中文标签） |

## 名单与 CRM

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/batches` | 批次列表（`search` / `page` / `page_size`） |
| POST | `/api/v1/batches/from-crm` | `{name?, crm_object, limit?, search?, filters?}` 从 CRM 拉名单 |
| POST | `/api/v1/batches/import` | multipart：`file`(.csv/.xlsx) + `name` + `note` |
| GET | `/api/v1/batches/{id}` | 批次详情 |
| GET | `/api/v1/batches/{id}/items` | 名单条目（`status` / `search` / 分页） |
| DELETE | `/api/v1/batches/{id}` | 删除批次（被任务引用时 409） |
| GET | `/api/v1/crm/health` | CRM 连通性与当前模式 |
| POST | `/api/v1/crm/sync` | `{objects?[], limit?}` 把 CRM 记录同步成本地快照 |
| GET | `/api/v1/writeback` | 回写队列（`status` / `kind` / `call_id`），含各状态计数 |
| POST | `/api/v1/writeback/retry` | `{id?}` 把 failed 打回 pending；不带 id 则全量重推 |

导入报告字段：`total_rows` / `imported` / `duplicates` / `failed`，外加 `duplicate_rows`、`failed_rows`（各取前 50 行）。

## 任务与工作台

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/tasks` | 任务列表（`status` / `mode` / `mine` / `search` / 分页），带 `progress` 计数 |
| POST | `/api/v1/tasks` | `{name, batch_id, mode?, status?, priority?, assignee_id?, max_attempts?, dial_window_start?, dial_window_end?, note?}` |
| GET / PATCH / DELETE | `/api/v1/tasks/{id}` | 任务详情 / 更新（含状态流转）/ 删除 |
| POST | `/api/v1/tasks/{id}/claim` \| `/release` | 领取 / 退回 |
| POST | `/api/v1/tasks/{id}/assign` | `{assignee_id, limit?}` 批量指派未分配的任务项 |
| POST | `/api/v1/tasks/{id}/generate` | `{limit?}` 从批次补充任务项 |
| GET | `/api/v1/tasks/{id}/items` | 任务项（含客户资料，号码脱敏） |
| POST | `/api/v1/task-items/{id}/skip` | 跳过一条 |
| GET | `/api/v1/workbench/next` | 取下一个：`{item, due, active_call, compliance}`；`task_id` 可选 |
| GET | `/api/v1/workbench/summary` | 我的待呼数、今日拨打数、合规设置、当日概览 |

## 通话

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/calls/dial` | `{task_item_id}` 或 `{phone}`；也可带 `crm_object` / `crm_record_id` |
| POST | `/api/v1/calls/{id}/hangup` | 挂断（振铃中挂断记为 `canceled`） |
| POST | `/api/v1/calls/{id}/complete` | `{result_code, intent_level?, note?, followup_subject?, followup_due_at?, followup_priority?}` |
| GET | `/api/v1/calls` | 列表（`state` / `result_code` / `category` / `intent_level` / `agent_id` / `task_id` / `day` / `search`），带 `summary` |
| GET | `/api/v1/calls/{id}` | 详情；管理员在此看到全号（写审计） |
| GET | `/api/v1/calls/{id}/events` | 状态事件流，按 `seq` 排序 |
| GET | `/api/v1/calls/{id}/recording` | 录音占位 WAV（模拟线路下是等长静音） |
| GET | `/api/v1/providers` | 线路清单与当前生效项 |
| POST | `/api/v1/providers/{name}/callback` | 线路回调占位（模拟线路不使用） |

`result_code` 取值见 `/api/v1/meta` 的 `call_results`；每个结果码自带 `category`（answered / unanswered）
与 `outcome`（positive / neutral / negative / none），结算口径以它为准。

## 治理与报表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/api/v1/blacklist` | 黑名单（`scope=phone\|customer`），新增需要主管及以上 |
| DELETE | `/api/v1/blacklist/{id}` | 停用一条 |
| GET / PUT | `/api/v1/settings/compliance` | 免打扰时段、每日上限、每号码上限、是否脱敏 |
| GET | `/api/v1/audit` | 审计日志（管理员看全部，其他人只看自己） |
| GET / POST / PATCH | `/api/v1/users`、`/api/v1/teams` | 组织管理 |
| GET | `/api/v1/reports/overview` \| `/agents` \| `/daily` \| `/results` \| `/tasks` \| `/compliance` | 报表 |
| GET | `/api/v1/stream` | SSE：`data: {"type":"call", ...}`，按身份过滤，15 秒心跳 |

## 机器人（二期）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/api/v1/scripts` | 话术脚本列表 / 新建（`{name, content{opening,nodes[],closing}, status?}`） |
| PATCH | `/api/v1/scripts/{id}` | 更新（改内容会自动 +1 版本） |
| GET / POST | `/api/v1/robot-tasks` | 机器人任务（`{name, script_id, batch_id, concurrency?, autostart?}`） |
| POST | `/api/v1/robot-tasks/{id}/start` \| `/pause` | 启停 |
| GET | `/api/v1/robot-tasks/{id}/sessions` | 会话列表 |
| GET | `/api/v1/robot-sessions/{id}` | 会话详情（含 transcript） |
| POST | `/api/v1/robot-sessions/{id}/turn` | `{text}` 客户说一句，机器人回一句（模拟语音） |
| POST | `/api/v1/robot-sessions/{id}/transfer` | `{assignee_id?}` 转人工，任务项打回坐席队列 |
| GET | `/api/v1/robot/summary` | 会话数、平均轮次、意向与结果分布 |