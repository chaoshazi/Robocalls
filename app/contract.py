'''对外契约与业务枚举。

这里是三件事的唯一来源：
1. 角色、通话状态、通话结果码、意向等级、任务与名单状态；
2. 中文标签，供前端与报表复用；
3. 给前端与联调工具的对象元数据（/api/v1/meta）。

改这里等于改对外契约：前端下拉、报表口径、状态机合法迁移都在看它。
'''

from __future__ import annotations

from typing import Any

# ---- 角色 ----
ROLES: tuple[str, ...] = ('admin', 'manager', 'agent')
ROLE_LABELS: dict[str, str] = {'admin': '管理员', 'manager': '主管', 'agent': '坐席'}

# ---- 通话状态机 ----
# dialing/ringing/answered 是进行中；其余都是终态。
CALL_STATES: tuple[str, ...] = (
    'dialing',
    'ringing',
    'answered',
    'ended',
    'no_answer',
    'busy',
    'power_off',
    'invalid_number',
    'failed',
    'canceled',
)
ACTIVE_CALL_STATES: tuple[str, ...] = ('dialing', 'ringing', 'answered')
# 终态里哪些算「接通」（用于接通率口径）
ANSWERED_STATES: tuple[str, ...] = ('answered', 'ended')
CALL_STATE_LABELS: dict[str, str] = {
    'dialing': '拨号中',
    'ringing': '振铃中',
    'answered': '通话中',
    'ended': '已结束',
    'no_answer': '无人接听',
    'busy': '占线',
    'power_off': '关机/停机',
    'invalid_number': '空号',
    'failed': '呼叫失败',
    'canceled': '已取消',
}

# ---- 通话结果码 ----
# category: answered / unanswered —— 接通率按 answered 计
# outcome: positive / neutral / negative / none —— 意向口径
CALL_RESULT_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    ('connected', '已接通（有效沟通）', 'answered', 'neutral', ''),
    ('deal', '成交/强意向', 'answered', 'positive', 'A'),
    ('call_back', '约定回拨', 'answered', 'positive', 'B'),
    ('interested', '有意向待跟进', 'answered', 'positive', 'B'),
    ('not_interested', '明确无意向', 'answered', 'negative', 'D'),
    ('refused', '拒绝接听/态度差', 'answered', 'negative', 'D'),
    ('wrong_person', '非本人/打错', 'answered', 'negative', ''),
    ('no_answer', '无人接听', 'unanswered', 'none', ''),
    ('busy', '占线', 'unanswered', 'none', ''),
    ('power_off', '关机/停机', 'unanswered', 'none', ''),
    ('invalid_number', '空号', 'unanswered', 'none', ''),
    ('failed', '呼叫失败', 'unanswered', 'none', ''),
    ('canceled', '已取消', 'unanswered', 'none', ''),
)
CALL_RESULTS: tuple[str, ...] = tuple(row[0] for row in CALL_RESULT_ROWS)
CALL_RESULT_LABELS: dict[str, str] = {row[0]: row[1] for row in CALL_RESULT_ROWS}
CALL_RESULT_CATEGORY: dict[str, str] = {row[0]: row[2] for row in CALL_RESULT_ROWS}
CALL_RESULT_OUTCOME: dict[str, str] = {row[0]: row[3] for row in CALL_RESULT_ROWS}
CATEGORY_LABELS: dict[str, str] = {'answered': '已接通', 'unanswered': '未接通'}
OUTCOME_LABELS: dict[str, str] = {
    'positive': '有意向',
    'neutral': '中性',
    'negative': '无意向',
    'none': '未接触',
}

# ---- 意向等级 ----
INTENT_LEVELS: tuple[str, ...] = ('A', 'B', 'C', 'D', 'none')
INTENT_LABELS: dict[str, str] = {
    'A': 'A 强意向',
    'B': 'B 中意向',
    'C': 'C 弱意向',
    'D': 'D 无需求',
    'none': '未评定',
}

# ---- 名单与任务 ----
BATCH_SOURCES: tuple[str, ...] = ('crm', 'import')
BATCH_SOURCE_LABELS: dict[str, str] = {'crm': '来自 CRM', 'import': 'Excel/CSV 导入'}
LIST_ITEM_STATUSES: tuple[str, ...] = ('available', 'assigned', 'called', 'closed')
LIST_ITEM_STATUS_LABELS: dict[str, str] = {
    'available': '待分配',
    'assigned': '已分配',
    'called': '已呼叫',
    'closed': '已关闭',
}
TASK_MODES: tuple[str, ...] = ('preview', 'robot')
TASK_MODE_LABELS: dict[str, str] = {'preview': '人工预览式', 'robot': 'AI 机器人'}
TASK_STATUSES: tuple[str, ...] = ('draft', 'active', 'paused', 'finished', 'canceled')
TASK_STATUS_LABELS: dict[str, str] = {
    'draft': '草稿',
    'active': '进行中',
    'paused': '已暂停',
    'finished': '已完成',
    'canceled': '已取消',
}
ITEM_STATUSES: tuple[str, ...] = ('pending', 'in_progress', 'done', 'skipped')
ITEM_STATUS_LABELS: dict[str, str] = {
    'pending': '待呼叫',
    'in_progress': '呼叫中',
    'done': '已处理',
    'skipped': '已跳过',
}
PRIORITIES: tuple[str, ...] = ('low', 'normal', 'high')
PRIORITY_LABELS: dict[str, str] = {'low': '低', 'normal': '中', 'high': '高'}

# ---- 合规 ----
BLACKLIST_SCOPES: tuple[str, ...] = ('phone', 'customer')
BLACKLIST_SCOPE_LABELS: dict[str, str] = {'phone': '号码', 'customer': '客户'}

# ---- CRM 对接 ----
# 可拉名单的 CRM 对象：phone 字段是号码来源，name/company 用于展示
CRM_LIST_OBJECTS: dict[str, dict[str, str]] = {
    'leads': {'label': '线索', 'phone': 'phone', 'name': 'company', 'person': 'contact'},
    'contacts': {'label': '联系人', 'phone': 'phone', 'name': 'name', 'person': 'name'},
}

# ---- 回写 ----
WRITEBACK_KINDS: tuple[str, ...] = ('activity', 'note', 'task')
WRITEBACK_KIND_LABELS: dict[str, str] = {'activity': '通话活动', 'note': '跟进备注', 'task': '跟进任务'}
WRITEBACK_STATUSES: tuple[str, ...] = ('pending', 'sent', 'failed', 'skipped')
WRITEBACK_STATUS_LABELS: dict[str, str] = {
    'pending': '待发送',
    'sent': '已回写',
    'failed': '回写失败',
    'skipped': '无需回写',
}

# ---- 二期：机器人 ----
SCRIPT_STATUSES: tuple[str, ...] = ('draft', 'active', 'archived')
ROBOT_TASK_STATUSES: tuple[str, ...] = ('draft', 'running', 'paused', 'finished', 'canceled')
ROBOT_TASK_STATUS_LABELS: dict[str, str] = {
    'draft': '草稿',
    'running': '运行中',
    'paused': '已暂停',
    'finished': '已完成',
    'canceled': '已取消',
}
ROBOT_OUTCOMES: tuple[str, ...] = ('completed', 'transferred', 'aborted')
ROBOT_OUTCOME_LABELS: dict[str, str] = {
    'completed': '机器人完成',
    'transferred': '已转人工',
    'aborted': '客户挂断',
}


def result_meta(code: str) -> dict[str, str]:
    return {
        'code': code,
        'label': CALL_RESULT_LABELS.get(code, code),
        'category': CALL_RESULT_CATEGORY.get(code, 'unanswered'),
        'outcome': CALL_RESULT_OUTCOME.get(code, 'none'),
    }


def default_intent_for(code: str) -> str:
    for row in CALL_RESULT_ROWS:
        if row[0] == code:
            return row[4] or 'none'
    return 'none'


def meta_payload() -> dict[str, Any]:
    '''给前端与联调工具的枚举元数据。'''
    return {
        'roles': [{'value': item, 'label': ROLE_LABELS.get(item, item)} for item in ROLES],
        'call_states': [
            {'value': item, 'label': CALL_STATE_LABELS.get(item, item)} for item in CALL_STATES
        ],
        'active_call_states': list(ACTIVE_CALL_STATES),
        'call_results': [result_meta(item) for item in CALL_RESULTS],
        'categories': [
            {'value': item, 'label': CATEGORY_LABELS[item]} for item in CATEGORY_LABELS
        ],
        'outcomes': [{'value': item, 'label': OUTCOME_LABELS[item]} for item in OUTCOME_LABELS],
        'intent_levels': [
            {'value': item, 'label': INTENT_LABELS.get(item, item)} for item in INTENT_LEVELS
        ],
        'batch_sources': [
            {'value': item, 'label': BATCH_SOURCE_LABELS.get(item, item)} for item in BATCH_SOURCES
        ],
        'list_item_statuses': [
            {'value': item, 'label': LIST_ITEM_STATUS_LABELS.get(item, item)}
            for item in LIST_ITEM_STATUSES
        ],
        'task_modes': [
            {'value': item, 'label': TASK_MODE_LABELS.get(item, item)} for item in TASK_MODES
        ],
        'task_statuses': [
            {'value': item, 'label': TASK_STATUS_LABELS.get(item, item)} for item in TASK_STATUSES
        ],
        'item_statuses': [
            {'value': item, 'label': ITEM_STATUS_LABELS.get(item, item)} for item in ITEM_STATUSES
        ],
        'priorities': [
            {'value': item, 'label': PRIORITY_LABELS.get(item, item)} for item in PRIORITIES
        ],
        'blacklist_scopes': [
            {'value': item, 'label': BLACKLIST_SCOPE_LABELS.get(item, item)}
            for item in BLACKLIST_SCOPES
        ],
        'crm_list_objects': [
            {'value': key, 'label': value['label']} for key, value in CRM_LIST_OBJECTS.items()
        ],
        'writeback_kinds': [
            {'value': item, 'label': WRITEBACK_KIND_LABELS.get(item, item)}
            for item in WRITEBACK_KINDS
        ],
        'writeback_statuses': [
            {'value': item, 'label': WRITEBACK_STATUS_LABELS.get(item, item)}
            for item in WRITEBACK_STATUSES
        ],
        'robot_outcomes': [
            {'value': item, 'label': ROBOT_OUTCOME_LABELS.get(item, item)} for item in ROBOT_OUTCOMES
        ],
    }