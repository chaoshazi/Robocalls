-- 外呼系统 Postgres DDL（Postgres 版；sqlite 由启动时按同一份元数据自动建表）
-- 由 app/adapters/tables.py 的元数据生成，改表先改那里，再重新生成本文件。
-- 用法：psql -U wahu -d wahu -f sql/001_init.sql

CREATE TABLE app_settings (
	key VARCHAR(64) NOT NULL, 
	value JSON, 
	updated_at VARCHAR(40) NOT NULL, 
	updated_by VARCHAR(64), 
	PRIMARY KEY (key)
);

CREATE TABLE audit_logs (
	id VARCHAR(64) NOT NULL, 
	at VARCHAR(40) NOT NULL, 
	actor_id VARCHAR(64), 
	actor_name VARCHAR(128), 
	actor_role VARCHAR(32), 
	action VARCHAR(64) NOT NULL, 
	object_type VARCHAR(64), 
	object_id VARCHAR(64), 
	detail JSON, 
	ip VARCHAR(64), 
	PRIMARY KEY (id)
);

CREATE TABLE blacklist (
	id VARCHAR(64) NOT NULL, 
	scope VARCHAR(16) NOT NULL, 
	phone VARCHAR(32), 
	crm_record_id VARCHAR(64), 
	value VARCHAR(128), 
	reason VARCHAR(255), 
	created_by VARCHAR(64), 
	is_active BOOLEAN NOT NULL, 
	expires_at VARCHAR(40), 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE call_events (
	id VARCHAR(64) NOT NULL, 
	call_id VARCHAR(64) NOT NULL, 
	seq INTEGER NOT NULL, 
	at VARCHAR(40) NOT NULL, 
	event VARCHAR(64) NOT NULL, 
	state VARCHAR(32), 
	detail JSON, 
	PRIMARY KEY (id)
);

CREATE TABLE calls (
	id VARCHAR(64) NOT NULL, 
	task_item_id VARCHAR(64), 
	task_id VARCHAR(64), 
	list_item_id VARCHAR(64), 
	agent_id VARCHAR(64), 
	agent_team_id VARCHAR(64), 
	robot_task_id VARCHAR(64), 
	phone VARCHAR(32) NOT NULL, 
	phone_masked VARCHAR(32) NOT NULL, 
	direction VARCHAR(16) NOT NULL, 
	provider VARCHAR(32) NOT NULL, 
	provider_call_id VARCHAR(64), 
	state VARCHAR(32) NOT NULL, 
	result_code VARCHAR(32), 
	category VARCHAR(32), 
	outcome VARCHAR(32), 
	intent_level VARCHAR(16), 
	note TEXT, 
	followup_subject VARCHAR(255), 
	followup_due_at VARCHAR(40), 
	followup_priority VARCHAR(32), 
	started_at VARCHAR(40) NOT NULL, 
	answered_at VARCHAR(40), 
	ended_at VARCHAR(40), 
	duration_sec INTEGER NOT NULL, 
	ring_sec INTEGER NOT NULL, 
	talk_sec INTEGER NOT NULL, 
	recording_url VARCHAR(255), 
	recording_status VARCHAR(32) NOT NULL, 
	recording_seconds INTEGER NOT NULL, 
	plan JSON, 
	step_index INTEGER NOT NULL, 
	next_at VARCHAR(40), 
	ended_reason VARCHAR(32), 
	completed_at VARCHAR(40), 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE crm_records (
	object_type VARCHAR(32) NOT NULL, 
	record_id VARCHAR(64) NOT NULL, 
	title VARCHAR(255), 
	phone VARCHAR(32), 
	name VARCHAR(128), 
	company VARCHAR(128), 
	owner_id VARCHAR(64), 
	team_id VARCHAR(64), 
	stage VARCHAR(32), 
	extra JSON, 
	synced_at VARCHAR(40) NOT NULL, 
	deleted BOOLEAN NOT NULL, 
	PRIMARY KEY (object_type, record_id)
);

CREATE TABLE list_batches (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	crm_object VARCHAR(32), 
	filter_json JSON, 
	note TEXT, 
	total INTEGER NOT NULL, 
	imported_total INTEGER NOT NULL, 
	duplicate_total INTEGER NOT NULL, 
	failed_total INTEGER NOT NULL, 
	created_by VARCHAR(64), 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE list_items (
	id VARCHAR(64) NOT NULL, 
	batch_id VARCHAR(64) NOT NULL, 
	phone VARCHAR(32) NOT NULL, 
	name VARCHAR(128), 
	company VARCHAR(128), 
	contact_name VARCHAR(128), 
	crm_object VARCHAR(32), 
	crm_record_id VARCHAR(64), 
	status VARCHAR(32) NOT NULL, 
	attempts INTEGER NOT NULL, 
	last_call_id VARCHAR(64), 
	last_result VARCHAR(32), 
	extra JSON, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE robot_sessions (
	id VARCHAR(64) NOT NULL, 
	robot_task_id VARCHAR(64) NOT NULL, 
	call_id VARCHAR(64), 
	list_item_id VARCHAR(64), 
	phone_masked VARCHAR(32), 
	node_id VARCHAR(64), 
	turn_count INTEGER NOT NULL, 
	intent_level VARCHAR(16), 
	outcome VARCHAR(32) NOT NULL, 
	transcript JSON, 
	summary TEXT, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE robot_tasks (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	script_id VARCHAR(64), 
	batch_id VARCHAR(64), 
	backing_task_id VARCHAR(64), 
	team_id VARCHAR(64), 
	status VARCHAR(32) NOT NULL, 
	concurrency INTEGER NOT NULL, 
	dial_window_start VARCHAR(8), 
	dial_window_end VARCHAR(8), 
	total INTEGER NOT NULL, 
	done INTEGER NOT NULL, 
	transferred INTEGER NOT NULL, 
	note TEXT, 
	created_by VARCHAR(64), 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	started_at VARCHAR(40), 
	finished_at VARCHAR(40), 
	PRIMARY KEY (id)
);

CREATE TABLE scripts (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	content JSON, 
	status VARCHAR(32) NOT NULL, 
	version INTEGER NOT NULL, 
	note TEXT, 
	created_by VARCHAR(64), 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE task_items (
	id VARCHAR(64) NOT NULL, 
	task_id VARCHAR(64) NOT NULL, 
	list_item_id VARCHAR(64) NOT NULL, 
	assignee_id VARCHAR(64), 
	status VARCHAR(32) NOT NULL, 
	priority VARCHAR(32) NOT NULL, 
	attempts INTEGER NOT NULL, 
	last_call_id VARCHAR(64), 
	result_code VARCHAR(32), 
	intent_level VARCHAR(16), 
	claimed_at VARCHAR(40), 
	finished_at VARCHAR(40), 
	next_attempt_at VARCHAR(40), 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE tasks (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	batch_id VARCHAR(64), 
	mode VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	priority VARCHAR(32) NOT NULL, 
	assignee_id VARCHAR(64), 
	team_id VARCHAR(64), 
	max_attempts INTEGER NOT NULL, 
	dial_window_start VARCHAR(8), 
	dial_window_end VARCHAR(8), 
	note TEXT, 
	created_by VARCHAR(64), 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE teams (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	note TEXT, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE users (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	team_id VARCHAR(64), 
	is_active BOOLEAN NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
);

CREATE TABLE writeback_queue (
	id VARCHAR(64) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	crm_object VARCHAR(32), 
	crm_record_id VARCHAR(64), 
	call_id VARCHAR(64), 
	list_item_id VARCHAR(64), 
	payload JSON, 
	status VARCHAR(32) NOT NULL, 
	attempts INTEGER NOT NULL, 
	last_error TEXT, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	sent_at VARCHAR(40), 
	PRIMARY KEY (id), 
	UNIQUE (idempotency_key)
);

-- 常用查询路径的索引
CREATE INDEX IF NOT EXISTS idx_calls_started_at ON calls (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_agent_started ON calls (agent_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_team_started ON calls (agent_team_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_state ON calls (state);
CREATE INDEX IF NOT EXISTS idx_calls_phone_started ON calls (phone, started_at);
CREATE INDEX IF NOT EXISTS idx_calls_robot_task ON calls (robot_task_id);
CREATE INDEX IF NOT EXISTS idx_call_events_call ON call_events (call_id, seq);
CREATE INDEX IF NOT EXISTS idx_list_items_batch ON list_items (batch_id, status);
CREATE INDEX IF NOT EXISTS idx_list_items_phone ON list_items (phone);
CREATE INDEX IF NOT EXISTS idx_task_items_task ON task_items (task_id, status);
CREATE INDEX IF NOT EXISTS idx_task_items_assignee ON task_items (assignee_id, status);
CREATE INDEX IF NOT EXISTS idx_writeback_status ON writeback_queue (status, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_logs (at DESC);
CREATE INDEX IF NOT EXISTS idx_blacklist_value ON blacklist (scope, value);
CREATE INDEX IF NOT EXISTS idx_robot_sessions_task ON robot_sessions (robot_task_id, created_at DESC);
