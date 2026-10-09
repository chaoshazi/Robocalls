// 仪表盘：概览数字 + 我的待办 + 实时事件流。
import { useEffect, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { clock, duration, percent } from '../lib/format';
import type { Compliance, Meta, Overview, StreamEvent } from '../lib/types';
import { Card, ErrorNote, Loading, Note, Stat, Table, type Column } from './ui';

interface Summary {
  due: number;
  today_calls: number;
  compliance: Compliance;
  reports: Overview;
}

export default function Dashboard(props: { token: string; meta: Meta; events: StreamEvent[] }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [data, mine] = await Promise.all([
          request<Overview>('/api/v1/reports/overview', { token: props.token }),
          request<Summary>('/api/v1/workbench/summary', { token: props.token }),
        ]);
        setOverview(data);
        setSummary(mine);
        setError(null);
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : String(caught));
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(timer);
  }, [props.token]);

  if (error) return <ErrorNote message={error} />;
  if (!overview || !summary) return <Loading />;

  const writes = overview.writeback;
  const eventColumns: Column<StreamEvent>[] = [
    { key: 'at', label: '时间', width: '90px', render: (row) => clock(row.at) },
    { key: 'phone', label: '号码', width: '130px', render: (row) => row.phone_masked ?? '—' },
    { key: 'state', label: '状态', render: (row) => row.state_label ?? row.state ?? '—' },
    { key: 'talk', label: '通话', width: '80px', render: (row) => (row.talk_sec ? duration(row.talk_sec) : '—') },
  ];

  return (
    <div className='space-y-4'>
      <div className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
        <Stat label={'近 ' + String(overview.days) + ' 天拨打'} value={overview.total_calls} hint={'今日 ' + String(overview.today.total_calls)} />
        <Stat
          label='接通率'
          value={percent(overview.answer_rate)}
          tone='good'
          hint={String(overview.answered) + ' / ' + String(overview.total_calls)}
        />
        <Stat label='累计通话时长' value={duration(overview.talk_seconds)} hint={'均 ' + duration(overview.avg_talk_seconds)} />
        <Stat label='有意向' value={overview.positive} tone='good' hint={'占比 ' + percent(overview.positive_rate)} />
      </div>

      <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
        <Card title='我的待办'>
          <div className='grid grid-cols-2 gap-3'>
            <Stat label='待呼任务项' value={summary.due} />
            <Stat label='今日已拨' value={summary.today_calls} hint={'上限 ' + String(summary.compliance.daily_limit)} />
          </div>
          <div className='mt-3 space-y-2 text-xs text-slate-400'>
            <Note>
              免打扰时段 {summary.compliance.dnd_start}–{summary.compliance.dnd_end} · 单号码每日上限{' '}
              {summary.compliance.per_number_daily_limit} 次 · 号码脱敏{' '}
              {summary.compliance.mask_phone ? '开启' : '关闭'}
            </Note>
            <Note tone='info'>
              我的角色：{props.meta.roles.find((role) => role.value === props.meta.me.role)?.label ?? props.meta.me.role}
              {' · '}
              数据范围：
              {props.meta.me.role === 'admin' ? '全部' : props.meta.me.role === 'manager' ? '本团队' : '仅自己'}
            </Note>
          </div>
        </Card>

        <Card title='运行状态' extra={<span>回写 待发 {writes.pending ?? 0} / 失败 {writes.failed ?? 0}</span>}>
          <div className='grid grid-cols-2 gap-3'>
            <Stat label='进行中任务' value={overview.tasks.active} />
            <Stat label='全量待呼' value={overview.items.pending} hint={'其中我的 ' + String(overview.items.mine_pending)} />
            <Stat label='合规拦截' value={overview.blocked} tone={overview.blocked > 0 ? 'warn' : 'default'} />
            <Stat label='回写成功' value={writes.sent ?? 0} tone='good' />
          </div>
        </Card>
      </div>

      <Card title='实时事件' extra={<span>{props.events.length} 条</span>}>
        <Table
          columns={eventColumns}
          rows={props.events.slice(0, 12)}
          rowKey={(row, index) => String(row.call_id ?? index) + String(index)}
          empty='还没有事件。打开坐席工作台拨一通电话试试。'
        />
      </Card>
    </div>
  );
}