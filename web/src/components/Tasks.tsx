// 外呼任务：创建、指派、领取 / 退回、暂停 / 完成、查看任务项。
import { useCallback, useEffect, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { stamp } from '../lib/format';
import type { Batch, Meta, Paged, Task, User, WorkItem } from '../lib/types';
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Field,
  Modal,
  Note,
  Pagination,
  Select,
  Table,
  TextArea,
  TextInput,
  type Column,
} from './ui';

const STATUS_TONE: Record<string, 'default' | 'good' | 'warn' | 'info'> = {
  active: 'good',
  draft: 'info',
  paused: 'warn',
  finished: 'default',
  canceled: 'default',
};

export default function Tasks(props: { token: string; meta: Meta; me: { id: string; role: string } }) {
  const [rows, setRows] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const [mine, setMine] = useState(false);
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<Task | null>(null);
  const [items, setItems] = useState<WorkItem[]>([]);
  const [itemPage, setItemPage] = useState(1);
  const [itemTotal, setItemTotal] = useState(0);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [agents, setAgents] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: '',
    batch_id: '',
    priority: 'normal',
    max_attempts: '3',
    dial_window_start: '',
    dial_window_end: '',
    assignee_id: '',
    note: '',
  });
  const pageSize = 20;
  const canManage = props.me.role === 'admin' || props.me.role === 'manager';

  const load = useCallback(async () => {
    try {
      const data = await request<Paged<Task>>(
        '/api/v1/tasks' +
          '?page=' +
          String(page) +
          '&page_size=' +
          String(pageSize) +
          (status ? '&status=' + status : '') +
          (mine ? '&mine=true' : ''),
        { token: props.token },
      );
      setRows(data.data);
      setTotal(data.total);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [mine, page, props.token, status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    request<Paged<Batch>>('/api/v1/batches?page_size=200', { token: props.token })
      .then((data) => setBatches(data.data))
      .catch(() => setBatches([]));
    if (canManage) {
      request<{ data: User[] }>('/api/v1/users', { token: props.token })
        .then((data) => setAgents(data.data))
        .catch(() => setAgents([]));
    }
  }, [canManage, props.token]);

  const loadItems = async (task: Task, targetPage = 1) => {
    try {
      const data = await request<Paged<WorkItem>>(
        '/api/v1/tasks/' + task.id + '/items?page=' + String(targetPage) + '&page_size=20',
        { token: props.token },
      );
      setItems(data.data);
      setItemTotal(data.total);
      setItemPage(targetPage);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  };

  const act = async (path: string, body?: unknown, message?: string) => {
    setBusy(true);
    setError(null);
    try {
      await request(path, { method: 'POST', token: props.token, body: body ?? {} });
      if (message) setNote(message);
      await load();
      if (detail) await loadItems(detail, itemPage);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const update = async (task: Task, body: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await request('/api/v1/tasks/' + task.id, { method: 'PATCH', token: props.token, body });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await request('/api/v1/tasks', {
        method: 'POST',
        token: props.token,
        body: {
          name: form.name,
          batch_id: form.batch_id || undefined,
          priority: form.priority,
          max_attempts: Number(form.max_attempts) || 3,
          dial_window_start: form.dial_window_start || undefined,
          dial_window_end: form.dial_window_end || undefined,
          assignee_id: form.assignee_id || undefined,
          note: form.note || undefined,
          status: 'active',
        },
      });
      setCreating(false);
      setForm({ ...form, name: '', batch_id: '', note: '' });
      setNote('任务已创建');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<Task>[] = [
    { key: 'name', label: '任务', render: (row) => (
        <button type='button' className='text-left text-sky-300 hover:underline' onClick={() => { setDetail(row); void loadItems(row, 1); }}>
          {row.name}
        </button>
      ) },
    { key: 'status', label: '状态', width: '90px', render: (row) => <Badge tone={STATUS_TONE[row.status] ?? 'default'}>{row.status_label}</Badge> },
    { key: 'mode', label: '模式', width: '100px', render: (row) => row.mode_label },
    { key: 'priority', label: '优先级', width: '80px' },
    {
      key: 'progress',
      label: '进度',
      width: '190px',
      render: (row) => {
        const totalCount = Math.max(1, row.progress.total);
        const done = row.progress.done + row.progress.skipped;
        return (
          <div>
            <div className='h-1.5 w-full overflow-hidden rounded bg-slate-800'>
              <div className='h-full bg-sky-500' style={{ width: String((done / totalCount) * 100) + '%' }} />
            </div>
            <div className='mt-1 text-xs text-slate-500'>
              待呼 {row.progress.pending} · 完成 {row.progress.done} · 跳过 {row.progress.skipped} / 共 {row.progress.total}
            </div>
          </div>
        );
      },
    },
    {
      key: 'assignee_id',
      label: '负责人',
      width: '120px',
      render: (row) => agents.find((agent) => agent.id === row.assignee_id)?.name ?? row.assignee_id ?? '未分配',
    },
    { key: 'created_at', label: '创建', width: '150px', render: (row) => stamp(row.created_at) },
    {
      key: 'ops',
      label: '操作',
      width: '230px',
      render: (row) => (
        <div className='flex flex-wrap gap-1'>
          {!row.assignee_id && (
            <Button size='sm' disabled={busy} onClick={() => void act('/api/v1/tasks/' + row.id + '/claim', {}, '已领取')}>
              领取
            </Button>
          )}
          {row.assignee_id === props.me.id && (
            <Button size='sm' variant='ghost' disabled={busy} onClick={() => void act('/api/v1/tasks/' + row.id + '/release', {}, '已退回')}>
              退回
            </Button>
          )}
          {canManage && row.status === 'active' && (
            <Button size='sm' variant='ghost' disabled={busy} onClick={() => void update(row, { status: 'paused' })}>
              暂停
            </Button>
          )}
          {canManage && row.status === 'paused' && (
            <Button size='sm' variant='ghost' disabled={busy} onClick={() => void update(row, { status: 'active' })}>
              继续
            </Button>
          )}
          {canManage && row.status !== 'finished' && (
            <Button size='sm' variant='ghost' disabled={busy} onClick={() => void update(row, { status: 'finished' })}>
              完成
            </Button>
          )}
          {canManage && (
            <Button size='sm' variant='danger' disabled={busy} onClick={() => void update(row, { status: 'canceled' })}>
              取消
            </Button>
          )}
        </div>
      ),
    },
  ];

  const itemColumns: Column<WorkItem>[] = [
    { key: 'phone', label: '号码', width: '140px' },
    { key: 'company', label: '客户', render: (row) => row.company ?? row.customer_name ?? '—' },
    { key: 'contact_name', label: '联系人', width: '110px', render: (row) => row.contact_name ?? '—' },
    { key: 'status', label: '状态', width: '90px', render: (row) => <Badge>{row.status_label}</Badge> },
    { key: 'attempts', label: '拨打次数', width: '90px', align: 'right' },
    { key: 'assignee_id', label: '坐席', width: '130px', render: (row) => agents.find((agent) => agent.id === row.assignee_id)?.name ?? row.assignee_id ?? '未分配' },
  ];

  return (
    <div className='space-y-4'>
      <ErrorNote message={error} />
      {note && <Note tone='good'>{note}</Note>}

      <Card
        title='外呼任务'
        extra={
          <>
            <Select
              value={status}
              onChange={(value) => { setStatus(value); setPage(1); }}
              options={props.meta.task_statuses}
              emptyLabel='全部状态'
            />
            <label className='flex items-center gap-1 text-xs'>
              <input type='checkbox' checked={mine} onChange={(event) => { setMine(event.target.checked); setPage(1); }} />
              只看我的
            </label>
            {canManage && (
              <Button variant='primary' size='sm' onClick={() => setCreating(true)}>
                新建任务
              </Button>
            )}
          </>
        }
      >
        <Table columns={columns} rows={rows} rowKey={(row) => row.id} empty='还没有外呼任务' />
        <Pagination page={page} pageSize={pageSize} total={total} onChange={setPage} />
      </Card>

      <Modal open={creating} title='新建外呼任务' onClose={() => setCreating(false)}>
        <Field label='任务名称'>
          <TextInput value={form.name} onChange={(value) => setForm({ ...form, name: value })} placeholder='例如：九月首轮外呼' />
        </Field>
        <Field label='名单批次' hint='选定批次后会自动把该批次里「待分配」的名单拉成任务项'>
          <Select
            value={form.batch_id}
            onChange={(value) => setForm({ ...form, batch_id: value })}
            options={batches.map((batch) => ({ value: batch.id, label: batch.name + '（' + String(batch.imported_total) + ' 条）' }))}
            emptyLabel='选择批次'
          />
        </Field>
        <div className='grid grid-cols-2 gap-3'>
          <Field label='优先级'>
            <Select value={form.priority} onChange={(value) => setForm({ ...form, priority: value })} options={props.meta.priorities} />
          </Field>
          <Field label='最大重呼次数'>
            <TextInput value={form.max_attempts} onChange={(value) => setForm({ ...form, max_attempts: value })} type='number' />
          </Field>
          <Field label='拨打时段起（可空）' hint='HH:MM，任务级限制'>
            <TextInput value={form.dial_window_start} onChange={(value) => setForm({ ...form, dial_window_start: value })} placeholder='09:00' />
          </Field>
          <Field label='拨打时段止（可空）'>
            <TextInput value={form.dial_window_end} onChange={(value) => setForm({ ...form, dial_window_end: value })} placeholder='18:00' />
          </Field>
        </div>
        <Field label='指派坐席（可空，留空进团队公共池）'>
          <Select
            value={form.assignee_id}
            onChange={(value) => setForm({ ...form, assignee_id: value })}
            options={agents.map((agent) => ({ value: agent.id, label: (agent.name ?? agent.id) + '（' + agent.role + '）' }))}
            emptyLabel='不指派'
          />
        </Field>
        <Field label='备注'>
          <TextArea value={form.note} onChange={(value) => setForm({ ...form, note: value })} rows={2} />
        </Field>
        <Button variant='primary' disabled={busy || !form.name} onClick={() => void create()}>
          创建
        </Button>
      </Modal>

      <Modal
        open={!!detail}
        title={detail ? '任务项 · ' + detail.name : ''}
        onClose={() => setDetail(null)}
        footer={
          canManage && detail ? (
            <>
              <Select
                value=''
                onChange={(value) => {
                  if (value) void act('/api/v1/tasks/' + detail.id + '/assign', { assignee_id: value, limit: 50 }, '已指派 50 条');
                }}
                options={agents.map((agent) => ({ value: agent.id, label: agent.name ?? agent.id }))}
                emptyLabel='批量指派给…'
              />
              <Button onClick={() => void act('/api/v1/tasks/' + detail.id + '/generate', {}, '已补充任务项')}>
                补充任务项
              </Button>
            </>
          ) : undefined
        }
      >
        {detail && (
          <div className='space-y-3'>
            <div className='flex flex-wrap gap-2 text-xs text-slate-400'>
              <Badge tone={STATUS_TONE[detail.status] ?? 'default'}>{detail.status_label}</Badge>
              <span>{detail.mode_label}</span>
              <span>优先级 {detail.priority_label}</span>
              <span>最大重呼 {detail.max_attempts} 次</span>
              <span>
                拨打时段 {detail.dial_window_start ?? '不限'} – {detail.dial_window_end ?? '不限'}
              </span>
            </div>
            <Table columns={itemColumns} rows={items} rowKey={(row) => row.id} empty='该任务没有任务项' />
            <Pagination page={itemPage} pageSize={20} total={itemTotal} onChange={(next) => void loadItems(detail, next)} />
          </div>
        )}
      </Modal>
    </div>
  );
}