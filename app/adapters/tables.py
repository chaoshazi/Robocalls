'''所有表的元数据：sqlite 与 postgres 共用一份，建表与 DDL 都由它推导。

命名约定：
- 主键一律字符串，带业务前缀（call-xxxx / batch-xxxx），便于日志与联调肉眼识别；
- 时间一律存带时区的 ISO 字符串（app/core/clock.now_iso）；
- 结构化字段用 JSON，sqlite 落文本、postgres 落 jsonb 之外的 JSON 类型。
'''

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()


def _pk() -> sa.Column:
    return sa.Column('id', sa.String(64), primary_key=True)


users = sa.Table(
    'users',
    metadata,
    _pk(),
    sa.Column('name', sa.String(128), nullable=False),
    sa.Column('email', sa.String(255), nullable=False, unique=True),
    sa.Column('password_hash', sa.String(255), nullable=False),
    sa.Column('role', sa.String(32), nullable=False),
    sa.Column('team_id', sa.String(64)),
    sa.Column('is_active', sa.Boolean, nullable=False, default=True),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

teams = sa.Table(
    'teams',
    metadata,
    _pk(),
    sa.Column('name', sa.String(128), nullable=False),
    sa.Column('note', sa.Text),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

audit_logs = sa.Table(
    'audit_logs',
    metadata,
    _pk(),
    sa.Column('at', sa.String(40), nullable=False),
    sa.Column('actor_id', sa.String(64)),
    sa.Column('actor_name', sa.String(128)),
    sa.Column('actor_role', sa.String(32)),
    sa.Column('action', sa.String(64), nullable=False),
    sa.Column('object_type', sa.String(64)),
    sa.Column('object_id', sa.String(64)),
    sa.Column('detail', sa.JSON),
    sa.Column('ip', sa.String(64)),
)

list_batches = sa.Table(
    'list_batches',
    metadata,
    _pk(),
    sa.Column('name', sa.String(128), nullable=False),
    sa.Column('source', sa.String(32), nullable=False),
    sa.Column('crm_object', sa.String(32)),
    sa.Column('filter_json', sa.JSON),
    sa.Column('note', sa.Text),
    sa.Column('total', sa.Integer, nullable=False, default=0),
    sa.Column('imported_total', sa.Integer, nullable=False, default=0),
    sa.Column('duplicate_total', sa.Integer, nullable=False, default=0),
    sa.Column('failed_total', sa.Integer, nullable=False, default=0),
    sa.Column('created_by', sa.String(64)),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

list_items = sa.Table(
    'list_items',
    metadata,
    _pk(),
    sa.Column('batch_id', sa.String(64), nullable=False),
    sa.Column('phone', sa.String(32), nullable=False),
    sa.Column('name', sa.String(128)),
    sa.Column('company', sa.String(128)),
    sa.Column('contact_name', sa.String(128)),
    sa.Column('crm_object', sa.String(32)),
    sa.Column('crm_record_id', sa.String(64)),
    sa.Column('status', sa.String(32), nullable=False, default='available'),
    sa.Column('attempts', sa.Integer, nullable=False, default=0),
    sa.Column('last_call_id', sa.String(64)),
    sa.Column('last_result', sa.String(32)),
    sa.Column('extra', sa.JSON),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

tasks = sa.Table(
    'tasks',
    metadata,
    _pk(),
    sa.Column('name', sa.String(128), nullable=False),
    sa.Column('batch_id', sa.String(64)),
    sa.Column('mode', sa.String(32), nullable=False, default='preview'),
    sa.Column('status', sa.String(32), nullable=False, default='draft'),
    sa.Column('priority', sa.String(32), nullable=False, default='normal'),
    sa.Column('assignee_id', sa.String(64)),
    sa.Column('team_id', sa.String(64)),
    sa.Column('max_attempts', sa.Integer, nullable=False, default=3),
    sa.Column('dial_window_start', sa.String(8)),
    sa.Column('dial_window_end', sa.String(8)),
    sa.Column('note', sa.Text),
    sa.Column('created_by', sa.String(64)),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

task_items = sa.Table(
    'task_items',
    metadata,
    _pk(),
    sa.Column('task_id', sa.String(64), nullable=False),
    sa.Column('list_item_id', sa.String(64), nullable=False),
    sa.Column('assignee_id', sa.String(64)),
    sa.Column('status', sa.String(32), nullable=False, default='pending'),
    sa.Column('priority', sa.String(32), nullable=False, default='normal'),
    sa.Column('attempts', sa.Integer, nullable=False, default=0),
    sa.Column('last_call_id', sa.String(64)),
    sa.Column('result_code', sa.String(32)),
    sa.Column('intent_level', sa.String(16)),
    sa.Column('claimed_at', sa.String(40)),
    sa.Column('finished_at', sa.String(40)),
    sa.Column('next_attempt_at', sa.String(40)),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

calls = sa.Table(
    'calls',
    metadata,
    _pk(),
    sa.Column('task_item_id', sa.String(64)),
    sa.Column('task_id', sa.String(64)),
    sa.Column('list_item_id', sa.String(64)),
    sa.Column('agent_id', sa.String(64)),
    sa.Column('agent_team_id', sa.String(64)),
    sa.Column('robot_task_id', sa.String(64)),
    sa.Column('phone', sa.String(32), nullable=False),
    sa.Column('phone_masked', sa.String(32), nullable=False),
    sa.Column('direction', sa.String(16), nullable=False, default='outbound'),
    sa.Column('provider', sa.String(32), nullable=False),
    sa.Column('provider_call_id', sa.String(64)),
    sa.Column('state', sa.String(32), nullable=False, default='dialing'),
    sa.Column('result_code', sa.String(32)),
    sa.Column('category', sa.String(32)),
    sa.Column('outcome', sa.String(32)),
    sa.Column('intent_level', sa.String(16)),
    sa.Column('note', sa.Text),
    sa.Column('followup_subject', sa.String(255)),
    sa.Column('followup_due_at', sa.String(40)),
    sa.Column('followup_priority', sa.String(32)),
    sa.Column('started_at', sa.String(40), nullable=False),
    sa.Column('answered_at', sa.String(40)),
    sa.Column('ended_at', sa.String(40)),
    sa.Column('duration_sec', sa.Integer, nullable=False, default=0),
    sa.Column('ring_sec', sa.Integer, nullable=False, default=0),
    sa.Column('talk_sec', sa.Integer, nullable=False, default=0),
    sa.Column('recording_url', sa.String(255)),
    sa.Column('recording_status', sa.String(32), nullable=False, default='none'),
    sa.Column('recording_seconds', sa.Integer, nullable=False, default=0),
    sa.Column('plan', sa.JSON),
    sa.Column('step_index', sa.Integer, nullable=False, default=0),
    sa.Column('next_at', sa.String(40)),
    sa.Column('ended_reason', sa.String(32)),
    sa.Column('completed_at', sa.String(40)),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

call_events = sa.Table(
    'call_events',
    metadata,
    _pk(),
    sa.Column('call_id', sa.String(64), nullable=False),
    sa.Column('seq', sa.Integer, nullable=False, default=0),
    sa.Column('at', sa.String(40), nullable=False),
    sa.Column('event', sa.String(64), nullable=False),
    sa.Column('state', sa.String(32)),
    sa.Column('detail', sa.JSON),
)

blacklist = sa.Table(
    'blacklist',
    metadata,
    _pk(),
    sa.Column('scope', sa.String(16), nullable=False, default='phone'),
    sa.Column('phone', sa.String(32)),
    sa.Column('crm_record_id', sa.String(64)),
    sa.Column('value', sa.String(128)),
    sa.Column('reason', sa.String(255)),
    sa.Column('created_by', sa.String(64)),
    sa.Column('is_active', sa.Boolean, nullable=False, default=True),
    sa.Column('expires_at', sa.String(40)),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

settings_table = sa.Table(
    'app_settings',
    metadata,
    sa.Column('key', sa.String(64), primary_key=True),
    sa.Column('value', sa.JSON),
    sa.Column('updated_at', sa.String(40), nullable=False),
    sa.Column('updated_by', sa.String(64)),
)

writeback_queue = sa.Table(
    'writeback_queue',
    metadata,
    _pk(),
    sa.Column('kind', sa.String(32), nullable=False),
    sa.Column('idempotency_key', sa.String(128), nullable=False, unique=True),
    sa.Column('crm_object', sa.String(32)),
    sa.Column('crm_record_id', sa.String(64)),
    sa.Column('call_id', sa.String(64)),
    sa.Column('list_item_id', sa.String(64)),
    sa.Column('payload', sa.JSON),
    sa.Column('status', sa.String(32), nullable=False, default='pending'),
    sa.Column('attempts', sa.Integer, nullable=False, default=0),
    sa.Column('last_error', sa.Text),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
    sa.Column('sent_at', sa.String(40)),
)

crm_records = sa.Table(
    'crm_records',
    metadata,
    sa.Column('object_type', sa.String(32), primary_key=True),
    sa.Column('record_id', sa.String(64), primary_key=True),
    sa.Column('title', sa.String(255)),
    sa.Column('phone', sa.String(32)),
    sa.Column('name', sa.String(128)),
    sa.Column('company', sa.String(128)),
    sa.Column('owner_id', sa.String(64)),
    sa.Column('team_id', sa.String(64)),
    sa.Column('stage', sa.String(32)),
    sa.Column('extra', sa.JSON),
    sa.Column('synced_at', sa.String(40), nullable=False),
    sa.Column('deleted', sa.Boolean, nullable=False, default=False),
)

scripts = sa.Table(
    'scripts',
    metadata,
    _pk(),
    sa.Column('name', sa.String(128), nullable=False),
    sa.Column('content', sa.JSON),
    sa.Column('status', sa.String(32), nullable=False, default='draft'),
    sa.Column('version', sa.Integer, nullable=False, default=1),
    sa.Column('note', sa.Text),
    sa.Column('created_by', sa.String(64)),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

robot_tasks = sa.Table(
    'robot_tasks',
    metadata,
    _pk(),
    sa.Column('name', sa.String(128), nullable=False),
    sa.Column('script_id', sa.String(64)),
    sa.Column('batch_id', sa.String(64)),
    sa.Column('backing_task_id', sa.String(64)),
    sa.Column('team_id', sa.String(64)),
    sa.Column('status', sa.String(32), nullable=False, default='draft'),
    sa.Column('concurrency', sa.Integer, nullable=False, default=3),
    sa.Column('dial_window_start', sa.String(8)),
    sa.Column('dial_window_end', sa.String(8)),
    sa.Column('total', sa.Integer, nullable=False, default=0),
    sa.Column('done', sa.Integer, nullable=False, default=0),
    sa.Column('transferred', sa.Integer, nullable=False, default=0),
    sa.Column('note', sa.Text),
    sa.Column('created_by', sa.String(64)),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
    sa.Column('started_at', sa.String(40)),
    sa.Column('finished_at', sa.String(40)),
)

robot_sessions = sa.Table(
    'robot_sessions',
    metadata,
    _pk(),
    sa.Column('robot_task_id', sa.String(64), nullable=False),
    sa.Column('call_id', sa.String(64)),
    sa.Column('list_item_id', sa.String(64)),
    sa.Column('phone_masked', sa.String(32)),
    sa.Column('node_id', sa.String(64)),
    sa.Column('turn_count', sa.Integer, nullable=False, default=0),
    sa.Column('intent_level', sa.String(16)),
    sa.Column('outcome', sa.String(32), nullable=False, default='completed'),
    sa.Column('transcript', sa.JSON),
    sa.Column('summary', sa.Text),
    sa.Column('created_at', sa.String(40), nullable=False),
    sa.Column('updated_at', sa.String(40), nullable=False),
)

TABLES: dict[str, sa.Table] = {
    'users': users,
    'teams': teams,
    'audit_logs': audit_logs,
    'list_batches': list_batches,
    'list_items': list_items,
    'tasks': tasks,
    'task_items': task_items,
    'calls': calls,
    'call_events': call_events,
    'blacklist': blacklist,
    'app_settings': settings_table,
    'writeback_queue': writeback_queue,
    'crm_records': crm_records,
    'scripts': scripts,
    'robot_tasks': robot_tasks,
    'robot_sessions': robot_sessions,
}