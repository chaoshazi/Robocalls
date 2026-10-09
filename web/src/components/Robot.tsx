// AI 机器人（二期）：话术脚本、机器人任务、会话与转人工。
import { useCallback, useEffect, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { stamp } from '../lib/format';
import type { Batch, Meta, RobotSession, RobotTask, Script } from '../lib/types';
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Field,
  Loading,
  Modal,
  Note,
  Select,
  Stat,
  Table,
  TextArea,
  TextInput,
  type Column,
} from './ui';

const SCRIPT_TEMPLATE = {
  opening: '您好，我是{company}的小王，请问是{name}吗？',
  nodes: [
    {
      id: 'n1',
      say: '想确认一下，贵司近期有采购计划吗？',
      keywords: { 有: 'n2', 没有: null },
      default: 'n2',
      intent: 'B',
    },
    { id: 'n2', say: '方便的话我加您微信，把资料发您看看？', keywords: { 方便: 'n3', 不方便: null }, default: 'n3' },
    { id: 'n3', say: '好的，那我稍后把资料整理好发您。', keywords: {}, default: null },
  ],
  closing: '好的，打扰了，祝您生活愉快。',
};

interface RobotSummary {
  sessions: number;
  running_tasks: number;
  robot_calls: number;
  avg_turns: number;
  by_outcome: Record<string, number>;
  by_intent: Record<string, number>;
}

export default function Robot(props: { token: string; meta: Meta; canManage: boolean }) {
  const [scripts, setScripts] = useState<Script[]>([]);
  const [tasks, setTasks] = useState<RobotTask[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [sessions, setSessions] = useState<RobotSession[]>([]);
  const [summary, setSummary] = useState<RobotSummary | null>(null);
  const [selected, setSelected] = useState<RobotTask | null>(null);
  const [detail, setDetail] = useState<RobotSession | null>(null);
  const [customerText, setCustomerText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [scriptModal, setScriptModal] = useState(false);
  const [taskModal, setTaskModal] = useState(false);
  const [scriptForm, setScriptForm] = useState({ name: '', status: 'active', content: JSON.stringify(SCRIPT_TEMPLATE, null, 2) });
  const [taskForm, setTaskForm] = useState({ name: '', script_id: '', batch_id: '', concurrency: '2', autostart: true });

  const load = useCallback(async () => {
    try {
      const [scriptList, taskList, batchList, robotSummary] = await Promise.all([
        request<{ data: Script[] }>('/api/v1/scripts', { token: props.token }),
        request<{ data: RobotTask[] }>('/api/v1/robot-tasks', { token: props.token }),
        request<{ data: Batch[] }>('/api/v1/batches?page_size=200', { token: props.token }),
        request<RobotSummary>('/api/v1/robot/summary', { token: props.token }),
      ]);
      setScripts(scriptList.data);
      setTasks(taskList.data);
      setBatches(batchList.data);
      setSummary(robotSummary);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [props.token]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 8000);
    return () => window.clearInterval(timer);
  }, [load]);

  const openSessions = async (task: RobotTask) => {
    setSelected(task);
    try {
      const data = await request<{ data: RobotSession[] }>('/api/v1/robot-tasks/' + task.id + '/sessions', {
        token: props.token,
      });
      setSessions(data.data);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  };

  const createScript = async () => {
    setBusy(true);
    setError(null);
    try {
      const content = JSON.parse(scriptForm.content) as Record<string, unknown>;
      await request('/api/v1/scripts', {
        method: 'POST',
        token: props.token,
        body: { name: scriptForm.name, status: scriptForm.status, content },
      });
      setScriptModal(false);
      setScriptForm({ ...scriptForm, name: '' });
      setNote('话术脚本已创建');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const createTask = async () => {
    setBusy(true);
    setError(null);
    try {
      await request('/api/v1/robot-tasks', {
        method: 'POST',
        token: props.token,
        body: {
          name: taskForm.name,
          script_id: taskForm.script_id,
          batch_id: taskForm.batch_id,
          concurrency: Number(taskForm.concurrency) || 2,
          autostart: taskForm.autostart,
        },
      });
      setTaskModal(false);
      setNote('机器人任务已创建');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const switchTask = async (task: RobotTask, running: boolean) => {
    setBusy(true);
    try {
      await request('/api/v1/robot-tasks/' + task.id + (running ? '/start' : '/pause'), {
        method: 'POST',
        token: props.token,
      });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const sendTurn = async () => {
    if (!detail || !customerText.trim()) return;
    setBusy(true);
    try {
      const fresh = await request<RobotSession>('/api/v1/robot-sessions/' + detail.id + '/turn', {
        method: 'POST',
        token: props.token,
        body: { text: customerText },
      });
      setDetail(fresh);
      setCustomerText('');
      if (selected) await openSessions(selected);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const transfer = async () => {
    if (!detail) return;
    setBusy(true);
    try {
      const fresh = await request<RobotSession>('/api/v1/robot-sessions/' + detail.id + '/transfer', {
        method: 'POST',
        token: props.token,
      });
      setDetail(fresh);
      setNote('已转人工，任务项已回到坐席队列');
      if (selected) await openSessions(selected);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const scriptColumns: Column<Script>[] = [
    { key: 'name', label: '脚本' },
    { key: 'status', label: '状态', width: '90px' },
    { key: 'version', label: '版本', width: '70px', align: 'right', render: (row) => 'v' + String(row.version) },
    { key: 'node_count', label: '节点数', width: '80px', align: 'right' },
    { key: 'created_at', label: '创建', width: '150px', render: (row) => stamp(row.created_at) },
  ];

  const taskColumns: Column<RobotTask>[] = [
    {
      key: 'name',
      label: '任务',
      render: (row) => (
        <button type='button' className='text-left text-sky-300 hover:underline' onClick={() => void openSessions(row)}>
          {row.name}
        </button>
      ),
    },
    { key: 'status_label', label: '状态', width: '90px', render: (row) => <Badge tone={row.status === 'running' ? 'good' : 'default'}>{row.status_label}</Badge> },
    { key: 'concurrency', label: '并发', width: '70px', align: 'right' },
    { key: 'total', label: '名单', width: '70px', align: 'right' },
    { key: 'done', label: '已完成', width: '80px', align: 'right' },
    { key: 'transferred', label: '转人工', width: '80px', align: 'right' },
    {
      key: 'ops',
      label: '操作',
      width: '170px',
      render: (row) => (
        <div className='flex gap-1'>
          {row.status !== 'running' ? (
            <Button size='sm' variant='primary' disabled={busy || !props.canManage} onClick={() => void switchTask(row, true)}>
              启动
            </Button>
          ) : (
            <Button size='sm' disabled={busy || !props.canManage} onClick={() => void switchTask(row, false)}>
              暂停
            </Button>
          )}
          <Button size='sm' variant='ghost' onClick={() => void openSessions(row)}>
            会话
          </Button>
        </div>
      ),
    },
  ];

  const sessionColumns: Column<RobotSession>[] = [
    { key: 'created_at', label: '开始', width: '150px', render: (row) => stamp(row.created_at) },
    { key: 'phone_masked', label: '号码', width: '140px', render: (row) => row.phone_masked ?? '—' },
    { key: 'turn_count', label: '轮次', width: '70px', align: 'right' },
    { key: 'intent_level', label: '意向', width: '80px', render: (row) => row.intent_level ?? '—' },
    { key: 'outcome_label', label: '结果', width: '110px' },
    { key: 'summary', label: '摘要', render: (row) => <span className='text-xs text-slate-400'>{row.summary ?? '—'}</span> },
    {
      key: 'ops',
      label: '操作',
      width: '80px',
      render: (row) => (
        <Button size='sm' onClick={() => setDetail(row)}>
          对话
        </Button>
      ),
    },
  ];

  return (
    <div className='space-y-4'>
      <ErrorNote message={error} />
      {note && <Note tone='good'>{note}</Note>}

      <Note tone='warn'>
        机器人外呼同样受合规约束（黑名单 / 免打扰 / 频次）。语音层是<strong>模拟</strong>的：
        由你在会话里「扮演客户」输入文字，验证话术流、意向判定与转人工链路；真实 ASR/TTS 尚未接入。
      </Note>

      {summary && (
        <div className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
          <Stat label='机器人通话' value={summary.robot_calls} />
          <Stat label='会话数' value={summary.sessions} hint={'均 ' + String(summary.avg_turns) + ' 轮'} />
          <Stat label='运行中任务' value={summary.running_tasks} />
          <Stat label='转人工' value={summary.by_outcome.transferred ?? 0} tone='good' />
        </div>
      )}

      <Card
        title='话术脚本'
        extra={
          <Button size='sm' variant='primary' disabled={!props.canManage} onClick={() => setScriptModal(true)}>
            新建脚本
          </Button>
        }
      >
        <Table columns={scriptColumns} rows={scripts} rowKey={(row) => row.id} empty='还没有话术脚本' />
      </Card>

      <Card
        title='机器人任务'
        extra={
          <Button size='sm' variant='primary' disabled={!props.canManage} onClick={() => setTaskModal(true)}>
            新建机器人任务
          </Button>
        }
      >
        <Table columns={taskColumns} rows={tasks} rowKey={(row) => row.id} empty='还没有机器人任务' />
      </Card>

      {selected && (
        <Card title={'会话 · ' + selected.name} extra={<span>{sessions.length} 条</span>}>
          <Table columns={sessionColumns} rows={sessions} rowKey={(row) => row.id} empty='还没有会话' />
        </Card>
      )}

      <Modal open={scriptModal} title='新建话术脚本' onClose={() => setScriptModal(false)}>
        <Note tone='info'>
          节点结构：keywords 命中就跳到对应节点，值为 null 表示结束通话；default 是兜底分支。
          关键词按长度优先匹配，所以「没有」不会被「有」抢先命中。
        </Note>
        <Field label='脚本名称'>
          <TextInput value={scriptForm.name} onChange={(value) => setScriptForm({ ...scriptForm, name: value })} />
        </Field>
        <Field label='状态'>
          <Select
            value={scriptForm.status}
            onChange={(value) => setScriptForm({ ...scriptForm, status: value })}
            options={[
              { value: 'draft', label: '草稿' },
              { value: 'active', label: '启用' },
              { value: 'archived', label: '归档' },
            ]}
          />
        </Field>
        <Field label='内容（JSON）'>
          <TextArea value={scriptForm.content} onChange={(value) => setScriptForm({ ...scriptForm, content: value })} rows={14} />
        </Field>
        <Button
          variant='primary'
          disabled={busy || !scriptForm.name}
          onClick={() => void createScript()}
        >
          创建
        </Button>
      </Modal>

      <Modal open={taskModal} title='新建机器人任务' onClose={() => setTaskModal(false)}>
        <Field label='任务名称'>
          <TextInput value={taskForm.name} onChange={(value) => setTaskForm({ ...taskForm, name: value })} />
        </Field>
        <Field label='话术脚本'>
          <Select
            value={taskForm.script_id}
            onChange={(value) => setTaskForm({ ...taskForm, script_id: value })}
            options={scripts.map((script) => ({ value: script.id, label: script.name + '（v' + String(script.version) + '）' }))}
            emptyLabel='选择脚本'
          />
        </Field>
        <Field label='名单批次'>
          <Select
            value={taskForm.batch_id}
            onChange={(value) => setTaskForm({ ...taskForm, batch_id: value })}
            options={batches.map((batch) => ({ value: batch.id, label: batch.name + '（' + String(batch.imported_total) + ' 条）' }))}
            emptyLabel='选择批次'
          />
        </Field>
        <Field label='并发路数'>
          <TextInput value={taskForm.concurrency} onChange={(value) => setTaskForm({ ...taskForm, concurrency: value })} type='number' />
        </Field>
        <label className='flex items-center gap-2 text-sm'>
          <input
            type='checkbox'
            checked={taskForm.autostart}
            onChange={(event) => setTaskForm({ ...taskForm, autostart: event.target.checked })}
          />
          创建后立刻开始拨打
        </label>
        <Button
          variant='primary'
          disabled={busy || !taskForm.name || !taskForm.script_id || !taskForm.batch_id}
          onClick={() => void createTask()}
        >
          创建
        </Button>
      </Modal>

      <Modal
        open={!!detail}
        title='机器人会话'
        onClose={() => setDetail(null)}
        footer={
          <>
            <Button variant='ghost' disabled={busy} onClick={() => void transfer()}>
              转人工
            </Button>
            <Button variant='primary' disabled={busy || !customerText.trim()} onClick={() => void sendTurn()}>
              发送客户发言
            </Button>
          </>
        }
      >
        {!detail && <Loading />}
        {detail && (
          <div className='space-y-3'>
            <div className='flex flex-wrap items-center gap-2 text-xs text-slate-400'>
              <Badge tone={detail.outcome === 'completed' ? 'good' : detail.outcome === 'transferred' ? 'info' : 'warn'}>
                {detail.outcome_label}
              </Badge>
              <span>轮次 {detail.turn_count}</span>
              <span>意向 {detail.intent_level ?? '未评定'}</span>
              <span>{detail.phone_masked ?? ''}</span>
            </div>
            <div className='scroll-thin max-h-72 space-y-2 overflow-auto rounded border border-edge bg-slate-900 p-3'>
              {detail.transcript.map((turn, index) => (
                <div key={String(index)} className={turn.role === 'customer' ? 'text-right' : 'text-left'}>
                  <div
                    className={
                      'inline-block max-w-[85%] rounded px-2 py-1 text-sm ' +
                      (turn.role === 'customer' ? 'bg-sky-800 text-sky-50' : 'bg-slate-800 text-slate-200')
                    }
                  >
                    {turn.text}
                  </div>
                </div>
              ))}
            </div>
            <Field label='扮演客户说一句' hint='模拟语音：用文字代替客户说话'>
              <TextInput value={customerText} onChange={setCustomerText} placeholder='例如：有采购计划 / 不需要 / 我要转人工' />
            </Field>
          </div>
        )}
      </Modal>
    </div>
  );
}