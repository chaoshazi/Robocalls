// 前端共用的类型定义，与后端 /api/v1/meta 的枚举保持一致。

export type Role = 'admin' | 'manager' | 'agent';

export interface User {
  id: string;
  name: string | null;
  email: string | null;
  role: Role;
  team_id: string | null;
  is_active: boolean;
}

export interface Meta {
  me: { id: string; name: string; role: Role; team_id: string | null };
  tenant_id: string;
  roles: Option[];
  call_states: Option[];
  active_call_states: string[];
  call_results: ResultOption[];
  categories: Option[];
  outcomes: Option[];
  intent_levels: Option[];
  batch_sources: Option[];
  list_item_statuses: Option[];
  task_modes: Option[];
  task_statuses: Option[];
  item_statuses: Option[];
  priorities: Option[];
  blacklist_scopes: Option[];
  crm_list_objects: Option[];
  writeback_kinds: Option[];
  writeback_statuses: Option[];
  robot_outcomes: Option[];
}

export interface Option {
  value: string;
  label: string;
}

export interface ResultOption extends Option {
  code: string;
  category: string;
  outcome: string;
}

export interface Compliance {
  dnd_start: string;
  dnd_end: string;
  daily_limit: number;
  per_number_daily_limit: number;
  mask_phone: boolean;
  source: string;
}

export interface Batch {
  id: string;
  name: string;
  source: string;
  crm_object: string | null;
  total: number;
  imported_total: number;
  duplicate_total: number;
  failed_total: number;
  note: string | null;
  created_by: string | null;
  created_at: string;
}

export interface ListItem {
  id: string;
  batch_id: string;
  phone: string;
  phone_masked: string;
  name: string | null;
  company: string | null;
  contact_name: string | null;
  crm_object: string | null;
  crm_record_id: string | null;
  status: string;
  attempts: number;
  last_result: string | null;
}

export interface TaskProgress {
  total: number;
  pending: number;
  in_progress: number;
  done: number;
  skipped: number;
}

export interface Task {
  id: string;
  name: string;
  batch_id: string | null;
  mode: string;
  status: string;
  status_label: string;
  mode_label: string;
  priority: string;
  priority_label: string;
  assignee_id: string | null;
  team_id: string | null;
  max_attempts: number;
  dial_window_start: string | null;
  dial_window_end: string | null;
  note: string | null;
  progress: TaskProgress;
  created_at: string;
}

export interface WorkItem {
  id: string;
  task_id: string;
  list_item_id: string;
  assignee_id: string | null;
  status: string;
  status_label: string;
  priority: string;
  priority_label: string;
  attempts: number;
  phone: string;
  phone_masked: string;
  customer_name: string | null;
  company: string | null;
  contact_name: string | null;
  crm_object: string | null;
  crm_record_id: string | null;
  last_result: string | null;
}

export interface Call {
  id: string;
  task_id: string | null;
  task_item_id: string | null;
  list_item_id: string | null;
  agent_id: string | null;
  agent_name?: string;
  agent_team_id: string | null;
  phone: string;
  phone_masked: string;
  provider: string;
  state: string;
  state_label: string;
  result_code: string | null;
  result_label: string;
  category: string | null;
  category_label: string;
  outcome: string | null;
  outcome_label: string;
  intent_level: string | null;
  intent_label: string;
  note: string | null;
  followup_subject: string | null;
  started_at: string;
  answered_at: string | null;
  ended_at: string | null;
  completed_at: string | null;
  duration_sec: number;
  ring_sec: number;
  talk_sec: number;
  recording_status: string;
  recording_seconds: number;
  recording_url: string | null;
}

export interface CallSummary {
  total: number;
  answered: number;
  unanswered: number;
  answer_rate: number;
  talk_seconds: number;
  avg_talk_seconds: number;
  positive: number;
}

export interface Workbench {
  item: WorkItem | null;
  due: number;
  cooling: number;
  active_call: Call | null;
  compliance: Compliance;
}

export interface WritebackRow {
  id: string;
  kind: string;
  kind_label: string;
  crm_object: string | null;
  crm_record_id: string | null;
  call_id: string | null;
  payload: Record<string, unknown> | null;
  status: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface AuditRow {
  id: string;
  at: string;
  actor_id: string | null;
  actor_name: string | null;
  actor_role: string | null;
  action: string;
  object_type: string | null;
  object_id: string | null;
  detail: Record<string, unknown> | null;
}

export interface Overview {
  days: number;
  total_calls: number;
  answered: number;
  unanswered: number;
  answer_rate: number;
  talk_seconds: number;
  avg_talk_seconds: number;
  positive: number;
  positive_rate: number;
  today: { total_calls: number; answered: number; answer_rate: number };
  tasks: { active: number };
  items: { pending: number; mine_pending: number };
  blocked: number;
  writeback: Record<string, number>;
}

export interface Script {
  id: string;
  name: string;
  content: Record<string, unknown>;
  status: string;
  version: number;
  node_count: number;
  created_at: string;
}

export interface RobotTask {
  id: string;
  name: string;
  script_id: string | null;
  batch_id: string | null;
  status: string;
  status_label: string;
  concurrency: number;
  total: number;
  done: number;
  transferred: number;
  created_at: string;
}

export interface RobotSession {
  id: string;
  robot_task_id: string;
  call_id: string | null;
  phone_masked: string | null;
  node_id: string | null;
  turn_count: number;
  intent_level: string | null;
  outcome: string;
  outcome_label: string;
  transcript: { role: string; text: string; at: string; node?: string | null; llm?: boolean }[];
  summary: string | null;
  created_at: string;
}

export interface Providers {
  active: string;
  callback_path: string;
  base_url_configured: boolean;
  agent_phone_configured: boolean;
  timeout_seconds: number;
  items: { name: string; label: string; ready: boolean }[];
}

export interface Team {
  id: string;
  name: string;
  note: string | null;
}

export interface Paged<T> {
  data: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface StreamEvent {
  type: string;
  call_id?: string;
  state?: string;
  state_label?: string;
  result_label?: string;
  agent_id?: string | null;
  team_id?: string | null;
  task_id?: string | null;
  phone_masked?: string;
  talk_sec?: number;
  at?: string;
}