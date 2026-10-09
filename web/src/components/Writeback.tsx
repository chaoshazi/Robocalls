// CRM 回写队列：看每条回写去哪了、成功没有，失败可重推。
import { useCallback, useEffect, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { stamp, summarize } from '../lib/format';
import type { Meta, Paged, WritebackRow } from '../lib/types';
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Modal,
  Note,
  Pagination,
  Select,
  Stat,
  Table,
  type Column,
} from './ui';

const STATUS_TONE: Record<string, 'good' | 'warn' | 'bad' | 'default'> = {
  sent: 'good',
  pending: 'warn',
  failed: 'bad',
  skipped: 'default',
};

export default function Writeback(props: { token: string; meta: Meta }) {
  const [rows, setRows] = useState<WritebackRow[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const [kind, setKind] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<WritebackRow | null>(null);
  const pageSize = 20;

  const load = useCallback(async () => {
    try {
      const data = await request<Paged<WritebackRow> & { summary: Record<string, number> }>(
        '/api/v1/writeback?page=' +
          String(page) +
          '&page_size=' +
          String(pageSize) +
          (status ? '&status=' + status : '') +
          (kind ? '&kind=' + kind : ''),
        { token: props.token },
      );
      setRows(data.data);
      setTotal(data.total);
      setSummary(data.summary);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [kind, page, props.token, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const retry = async (id?: string) => {
    setBusy(true);
    try {
      const result = await request<{ requeued: number }>('/api/v1/writeback/retry', {
        method: 'POST',
        token: props.token,
        body: id ? { id } : {},
      });
      setNote('已重新排队 ' + String(result.requeued) + ' 条，等待下一次节拍推送');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<WritebackRow>[] = [
    { key: 'created_at', label: '时间', width: '150px', render: (row) => stamp(row.created_at) },
    { key: 'kind_label', label: '类型', width: '100px' },
    { key: 'status', label: '状态', width: '100px', render: (row) => <Badge tone={STATUS_TONE[row.status] ?? 'default'}>{row.status}</Badge> },
    {
      key: 'target',
      label: '挂靠对象',
      width: '180px',
      render: (row) => (row.crm_record_id ? row.crm_object + ' / ' + row.crm_record_id : <span className='text-slate-500'>无归属（导入名单）</span>),
    },
    { key: 'call_id', label: '通话', width: '160px', render: (row) => <span className='font-mono text-xs'>{row.call_id ?? '—'}</span> },
    { key: 'attempts', label: '尝试', width: '70px', align: 'right' },
    { key: 'last_error', label: '最近错误', render: (row) => row.last_error ?? '—' },
    {
      key: 'ops',
      label: '操作',
      width: '150px',
      render: (row) => (
        <div className='flex gap-1'>
          <Button size='sm' onClick={() => setDetail(row)}>
            查看
          </Button>
          {row.status === 'failed' && (
            <Button size='sm' variant='primary' disabled={busy} onClick={() => void retry(row.id)}>
              重推
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className='space-y-4'>
      <ErrorNote message={error} />
      {note && <Note tone='good'>{note}</Note>}

      <div className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
        <Stat label='待发送' value={summary.pending ?? 0} tone={(summary.pending ?? 0) > 0 ? 'warn' : 'default'} />
        <Stat label='已回写' value={summary.sent ?? 0} tone='good' />
        <Stat label='失败' value={summary.failed ?? 0} tone={(summary.failed ?? 0) > 0 ? 'warn' : 'default'} />
        <Stat label='无需回写' value={summary.skipped ?? 0} hint='本地导入名单没有 CRM 归属' />
      </div>

      <Card
        title='CRM 回写队列'
        extra={
          <>
            <Select value={status} onChange={(value) => { setStatus(value); setPage(1); }} options={props.meta.writeback_statuses} emptyLabel='全部状态' />
            <Select value={kind} onChange={(value) => { setKind(value); setPage(1); }} options={props.meta.writeback_kinds} emptyLabel='全部类型' />
            <Button size='sm' disabled={busy} onClick={() => void retry()}>
              全部重推
            </Button>
          </>
        }
      >
        <Note tone='info'>
          回写只做追加：activities（通话活动）+ notes（跟进备注）+ tasks（跟进任务），一律带 Idempotency-Key，
          重复提交不会写重；<strong>不会修改 CRM 的任何业务字段</strong>。
        </Note>
        <div className='mt-3'>
          <Table columns={columns} rows={rows} rowKey={(row) => row.id} empty='还没有回写记录' />
        </div>
        <Pagination page={page} pageSize={pageSize} total={total} onChange={setPage} />
      </Card>

      <Modal open={!!detail} title='回写详情' onClose={() => setDetail(null)}>
        {detail && (
          <div className='space-y-2 text-sm'>
            <div className='text-xs text-slate-400'>
              {detail.kind_label} · {detail.status} · 尝试 {detail.attempts} 次
            </div>
            {detail.last_error && <Note tone={detail.status === 'failed' ? 'bad' : 'warn'}>{detail.last_error}</Note>}
            <pre className='scroll-thin max-h-72 overflow-auto rounded border border-edge bg-slate-900 p-3 text-xs text-slate-300'>
              {JSON.stringify(detail.payload, null, 2)}
            </pre>
            <div className='text-xs text-slate-500'>创建 {stamp(detail.created_at)} · 回写 {stamp(detail.sent_at)}</div>
            <div className='text-xs text-slate-500'>摘要：{summarize(detail.payload)}</div>
          </div>
        )}
      </Modal>
    </div>
  );
}