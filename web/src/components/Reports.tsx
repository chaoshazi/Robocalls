// 报表：概览、坐席排行、按日趋势、结果与意向分布、任务进度。
import { useCallback, useEffect, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { duration, percent } from '../lib/format';
import type { Overview } from '../lib/types';
import { Button, Card, ErrorNote, Loading, Note, Stat, Table, type Column } from './ui';

interface AgentRow {
  agent_id: string;
  agent_name: string;
  total: number;
  answered: number;
  answer_rate: number;
  positive: number;
  talk_seconds: number;
  avg_talk_seconds: number;
}

interface DailyRow {
  day: string;
  total: number;
  answered: number;
  answer_rate: number;
  talk_seconds: number;
}

interface DistributionRow {
  code: string;
  label?: string;
  count: number;
}

interface TaskProgressRow {
  id: string;
  name: string;
  status_label: string;
  mode: string;
  total: number;
  pending: number;
  done: number;
  completion_rate: number;
}

interface ComplianceReport {
  days: number;
  blocked: number;
  by_action: DistributionRow[];
  blacklist_active: number;
  writeback: Record<string, number>;
}

export default function Reports(props: { token: string }) {
  const [days, setDays] = useState(7);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [daily, setDaily] = useState<DailyRow[]>([]);
  const [results, setResults] = useState<DistributionRow[]>([]);
  const [intents, setIntents] = useState<DistributionRow[]>([]);
  const [tasks, setTasks] = useState<TaskProgressRow[]>([]);
  const [compliance, setCompliance] = useState<ComplianceReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const suffix = '?days=' + String(days);
      const [a, b, c, d, e, f] = await Promise.all([
        request<Overview>('/api/v1/reports/overview' + suffix, { token: props.token }),
        request<{ data: AgentRow[] }>('/api/v1/reports/agents' + suffix, { token: props.token }),
        request<{ data: DailyRow[] }>('/api/v1/reports/daily' + suffix, { token: props.token }),
        request<{ results: DistributionRow[]; intents: DistributionRow[] }>('/api/v1/reports/results' + suffix, {
          token: props.token,
        }),
        request<{ data: TaskProgressRow[] }>('/api/v1/reports/tasks', { token: props.token }),
        request<ComplianceReport>('/api/v1/reports/compliance' + suffix, { token: props.token }),
      ]);
      setOverview(a);
      setAgents(b.data);
      setDaily(c.data);
      setResults(d.results);
      setIntents(d.intents);
      setTasks(e.data);
      setCompliance(f);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [days, props.token]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorNote message={error} />;
  if (!overview) return <Loading />;

  const peak = Math.max(1, ...daily.map((row) => row.total));
  const agentColumns: Column<AgentRow>[] = [
    { key: 'agent_name', label: '坐席', width: '120px' },
    { key: 'total', label: '拨打', width: '80px', align: 'right' },
    { key: 'answered', label: '接通', width: '80px', align: 'right' },
    { key: 'answer_rate', label: '接通率', width: '100px', align: 'right', render: (row) => percent(row.answer_rate) },
    { key: 'positive', label: '有意向', width: '90px', align: 'right' },
    { key: 'talk_seconds', label: '通话时长', width: '120px', align: 'right', render: (row) => duration(row.talk_seconds) },
    { key: 'avg_talk_seconds', label: '均长', width: '100px', align: 'right', render: (row) => duration(row.avg_talk_seconds) },
  ];
  const taskColumns: Column<TaskProgressRow>[] = [
    { key: 'name', label: '任务' },
    { key: 'status_label', label: '状态', width: '100px' },
    { key: 'mode', label: '模式', width: '90px' },
    { key: 'total', label: '总量', width: '80px', align: 'right' },
    { key: 'pending', label: '待呼', width: '80px', align: 'right' },
    { key: 'done', label: '已完成', width: '90px', align: 'right' },
    { key: 'completion_rate', label: '完成率', width: '100px', align: 'right', render: (row) => percent(row.completion_rate) },
  ];

  return (
    <div className='space-y-4'>
      <div className='flex items-center gap-2 text-xs text-slate-400'>
        <span>统计范围</span>
        {[1, 7, 30].map((value) => (
          <Button key={value} size='sm' variant={days === value ? 'primary' : 'default'} onClick={() => setDays(value)}>
            近 {value} 天
          </Button>
        ))}
      </div>

      <div className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
        <Stat label='拨打' value={overview.total_calls} hint={'接通 ' + String(overview.answered)} />
        <Stat label='接通率' value={percent(overview.answer_rate)} tone='good' />
        <Stat label='总通话时长' value={duration(overview.talk_seconds)} hint={'均 ' + duration(overview.avg_talk_seconds)} />
        <Stat label='有意向' value={overview.positive} hint={percent(overview.positive_rate)} />
      </div>

      <Card title='按日趋势'>
        {daily.length === 0 ? (
          <Note>区间内没有通话。</Note>
        ) : (
          <div className='flex h-40 items-end gap-2'>
            {daily.map((row) => (
              <div key={row.day} className='flex flex-1 flex-col items-center gap-1'>
                <div className='text-xs text-slate-500'>{row.total}</div>
                <div className='relative w-full' style={{ height: '110px' }}>
                  <div
                    className='absolute bottom-0 w-full rounded-t bg-slate-700'
                    style={{ height: String((row.total / peak) * 100) + '%' }}
                  />
                  <div
                    className='absolute bottom-0 w-full rounded-t bg-sky-500'
                    style={{ height: String((row.answered / peak) * 100) + '%' }}
                  />
                </div>
                <div className='text-xs text-slate-500'>{row.day.slice(5)}</div>
              </div>
            ))}
          </div>
        )}
        <div className='mt-2 text-xs text-slate-500'>深色为拨打总量，浅蓝为接通量。</div>
      </Card>

      <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
        <Card title='坐席排行'>
          <Table columns={agentColumns} rows={agents} rowKey={(row) => row.agent_id} empty='暂无数据' />
        </Card>
        <Card title='结果与意向分布'>
          <div className='grid grid-cols-2 gap-4'>
            <div>
              <div className='mb-2 text-xs text-slate-400'>通话结果</div>
              <Table
                columns={[
                  { key: 'label', label: '结果', render: (row: DistributionRow) => row.label ?? row.code },
                  { key: 'count', label: '数量', width: '70px', align: 'right' },
                ]}
                rows={results}
                rowKey={(row) => row.code}
                empty='暂无'
              />
            </div>
            <div>
              <div className='mb-2 text-xs text-slate-400'>意向等级</div>
              <Table
                columns={[
                  { key: 'label', label: '意向', render: (row: DistributionRow) => row.label ?? row.code },
                  { key: 'count', label: '数量', width: '70px', align: 'right' },
                ]}
                rows={intents}
                rowKey={(row) => row.code}
                empty='暂无'
              />
            </div>
          </div>
        </Card>
      </div>

      <Card title='任务进度'>
        <Table columns={taskColumns} rows={tasks} rowKey={(row) => row.id} empty='暂无任务' />
      </Card>

      {compliance && (
        <Card title='合规与回写'>
          <div className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
            <Stat label={'近 ' + String(compliance.days) + ' 天拦截'} value={compliance.blocked} tone={compliance.blocked > 0 ? 'warn' : 'default'} />
            <Stat label='黑名单生效中' value={compliance.blacklist_active} />
            <Stat label='回写成功' value={compliance.writeback.sent ?? 0} tone='good' />
            <Stat label='回写待处理' value={compliance.writeback.pending ?? 0} />
          </div>
          {compliance.by_action.length > 0 && (
            <div className='mt-3'>
              <Table
                columns={[
                  { key: 'code', label: '拦截类型', render: (row: DistributionRow) => row.code },
                  { key: 'count', label: '次数', width: '80px', align: 'right' },
                ]}
                rows={compliance.by_action}
                rowKey={(row) => row.code}
              />
            </div>
          )}
        </Card>
      )}
    </div>
  );
}