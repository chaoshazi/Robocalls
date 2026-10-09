// 通话记录：筛选、概览、详情（状态事件流 + 录音）。
import { useCallback, useEffect, useState } from 'react';

import { apiBase, ApiError, request } from '../lib/api';
import { clock, duration, percent, stamp, summarize } from '../lib/format';
import type { Call, CallSummary, Meta, Paged } from '../lib/types';
import {
  Badge,
  Card,
  ErrorNote,
  Field,
  Loading,
  Modal,
  Note,
  Pagination,
  Select,
  Stat,
  Table,
  TextInput,
  type Column,
} from './ui';

interface CallEvent {
  id: string;
  seq: number;
  at: string;
  event: string;
  state: string | null;
  state_label: string;
  detail: Record<string, unknown> | null;
}

const STATE_TONE: Record<string, 'good' | 'warn' | 'bad' | 'default'> = {
  answered: 'good',
  ended: 'good',
  dialing: 'warn',
  ringing: 'warn',
  no_answer: 'bad',
  busy: 'bad',
  power_off: 'bad',
  invalid_number: 'bad',
  failed: 'bad',
  canceled: 'default',
};

export default function Calls(props: { token: string; meta: Meta }) {
  const [rows, setRows] = useState<Call[]>([]);
  const [summary, setSummary] = useState<CallSummary | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [state, setState] = useState('');
  const [category, setCategory] = useState('');
  const [intent, setIntent] = useState('');
  const [dayFilter, setDayFilter] = useState('');
  const [search, setSearch] = useState('');
  const [detail, setDetail] = useState<Call | null>(null);
  const [events, setEvents] = useState<CallEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 20;

  const load = useCallback(async () => {
    try {
      const query =
        '/api/v1/calls?page=' +
        String(page) +
        '&page_size=' +
        String(pageSize) +
        (state ? '&state=' + state : '') +
        (category ? '&category=' + category : '') +
        (intent ? '&intent_level=' + intent : '') +
        (dayFilter ? '&day=' + dayFilter : '') +
        (search ? '&search=' + encodeURIComponent(search) : '');
      const data = await request<Paged<Call> & { summary: CallSummary }>(query, { token: props.token });
      setRows(data.data);
      setTotal(data.total);
      setSummary(data.summary);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [category, dayFilter, intent, page, props.token, search, state]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (row: Call) => {
    try {
      const [fresh, history] = await Promise.all([
        request<Call>('/api/v1/calls/' + row.id, { token: props.token }),
        request<{ data: CallEvent[] }>('/api/v1/calls/' + row.id + '/events', { token: props.token }),
      ]);
      setDetail(fresh);
      setEvents(history.data);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  };

  const columns: Column<Call>[] = [
    { key: 'started_at', label: '开始', width: '150px', render: (row) => stamp(row.started_at) },
    { key: 'phone', label: '号码', width: '140px' },
    { key: 'state', label: '状态', width: '100px', render: (row) => <Badge tone={STATE_TONE[row.state] ?? 'default'}>{row.state_label}</Badge> },
    { key: 'result_label', label: '结果', width: '150px', render: (row) => row.result_label || '未填写' },
    { key: 'intent_label', label: '意向', width: '100px', render: (row) => row.intent_label || '—' },
    { key: 'talk_sec', label: '通话时长', width: '100px', align: 'right', render: (row) => duration(row.talk_sec) },
    { key: 'ring_sec', label: '振铃', width: '80px', align: 'right', render: (row) => duration(row.ring_sec) },
    { key: 'agent_id', label: '坐席', width: '140px', render: (row) => row.agent_name ?? row.agent_id ?? '—' },
    {
      key: 'recording',
      label: '录音',
      width: '80px',
      render: (row) => (row.recording_status === 'ready' ? <Badge tone='info'>可播放</Badge> : <span className='text-slate-500'>—</span>),
    },
  ];

  const eventColumns: Column<CallEvent>[] = [
    { key: 'seq', label: '#', width: '40px', align: 'right' },
    { key: 'at', label: '时间', width: '90px', render: (row) => clock(row.at) },
    { key: 'state', label: '状态', width: '100px', render: (row) => row.state_label },
    { key: 'detail', label: '细节', render: (row) => summarize(row.detail) },
  ];

  return (
    <div className='space-y-4'>
      <ErrorNote message={error} />

      {summary && (
        <div className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
          <Stat label='筛选结果' value={summary.total} />
          <Stat label='接通' value={summary.answered} tone='good' hint={'接通率 ' + percent(summary.answer_rate)} />
          <Stat label='累计通话' value={duration(summary.talk_seconds)} hint={'均 ' + duration(summary.avg_talk_seconds)} />
          <Stat label='有意向' value={summary.positive} />
        </div>
      )}

      <Card
        title='通话记录'
        extra={
          <>
            <Select value={state} onChange={(value) => { setState(value); setPage(1); }} options={props.meta.call_states} emptyLabel='全部状态' />
            <Select value={category} onChange={(value) => { setCategory(value); setPage(1); }} options={props.meta.categories} emptyLabel='全部接通情况' />
            <Select value={intent} onChange={(value) => { setIntent(value); setPage(1); }} options={props.meta.intent_levels} emptyLabel='全部意向' />
            <TextInput value={dayFilter} onChange={(value) => { setDayFilter(value); setPage(1); }} placeholder='日期 YYYY-MM-DD' />
            <TextInput value={search} onChange={(value) => { setSearch(value); setPage(1); }} placeholder='号码 / 备注' />
          </>
        }
      >
        <Table columns={columns} rows={rows} rowKey={(row) => row.id} onRowClick={(row) => void openDetail(row)} empty='还没有通话记录' />
        <Pagination page={page} pageSize={pageSize} total={total} onChange={setPage} />
      </Card>

      <Modal open={!!detail} title='通话详情' onClose={() => setDetail(null)}>
        {!detail && <Loading />}
        {detail && (
          <div className='space-y-3'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='text-lg font-semibold'>{detail.phone}</span>
              <Badge tone={STATE_TONE[detail.state] ?? 'default'}>{detail.state_label}</Badge>
              {detail.result_label && <Badge tone='info'>{detail.result_label}</Badge>}
              {detail.intent_label && <Badge>{detail.intent_label}</Badge>}
              {detail.outcome_label && <Badge>{detail.outcome_label}</Badge>}
            </div>
            <div className='grid grid-cols-2 gap-3 text-xs text-slate-400 lg:grid-cols-3'>
              <div>线路：{detail.provider}</div>
              <div>开始：{stamp(detail.started_at)}</div>
              <div>接通：{stamp(detail.answered_at)}</div>
              <div>结束：{stamp(detail.ended_at)}</div>
              <div>振铃：{duration(detail.ring_sec)}</div>
              <div>通话：{duration(detail.talk_sec)}</div>
              <div className='font-mono'>ID：{detail.id}</div>
              <div className='font-mono'>任务项：{detail.task_item_id ?? '—'}</div>
              <div>坐席：{detail.agent_name ?? detail.agent_id ?? '—'}</div>
            </div>
            {detail.note && <Note tone='info'>备注：{detail.note}</Note>}
            {detail.followup_subject && <Note tone='good'>跟进任务：{detail.followup_subject}</Note>}
            {detail.recording_status === 'ready' ? (
              <div>
                <div className='mb-1 text-xs text-slate-400'>
                  录音（模拟线路下是等长静音占位，用于验证链路）
                </div>
                <audio controls src={apiBase() + (detail.recording_url ?? '')} className='w-full' />
              </div>
            ) : (
              <Note>该通话没有录音（未接通或已关闭录音）。</Note>
            )}
            <Field label='状态事件流'>
              <Table columns={eventColumns} rows={events} rowKey={(row) => row.id} empty='无事件' />
            </Field>
          </div>
        )}
      </Modal>
    </div>
  );
}