// 合规：黑名单与拦截规则设置。
import { useCallback, useEffect, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { stamp } from '../lib/format';
import type { Compliance, Meta } from '../lib/types';
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Field,
  Loading,
  Note,
  Select,
  Table,
  TextInput,
  type Column,
} from './ui';

interface BlacklistRow {
  id: string;
  scope: string;
  phone: string | null;
  crm_record_id: string | null;
  value: string;
  reason: string | null;
  created_by: string | null;
  is_active: boolean;
  created_at: string;
}

export default function CompliancePanel(props: { token: string; meta: Meta; canManage: boolean }) {
  const [rows, setRows] = useState<BlacklistRow[]>([]);
  const [settings, setSettings] = useState<Compliance | null>(null);
  const [scope, setScope] = useState('phone');
  const [value, setValue] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Compliance | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, current] = await Promise.all([
        request<{ data: BlacklistRow[] }>('/api/v1/blacklist?limit=200', { token: props.token }),
        request<Compliance>('/api/v1/settings/compliance', { token: props.token }),
      ]);
      setRows(list.data);
      setSettings(current);
      setDraft(current);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [props.token]);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    if (!value.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await request('/api/v1/blacklist', {
        method: 'POST',
        token: props.token,
        body:
          scope === 'phone'
            ? { scope, phone: value.trim(), reason }
            : { scope, crm_record_id: value.trim(), reason },
      });
      setValue('');
      setReason('');
      setNote('已加入黑名单');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row: BlacklistRow) => {
    setBusy(true);
    try {
      await request('/api/v1/blacklist/' + row.id, { method: 'DELETE', token: props.token });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await request<Compliance>('/api/v1/settings/compliance', {
        method: 'PUT',
        token: props.token,
        body: {
          dnd_start: draft.dnd_start,
          dnd_end: draft.dnd_end,
          daily_limit: Number(draft.daily_limit),
          per_number_daily_limit: Number(draft.per_number_daily_limit),
          mask_phone: draft.mask_phone,
        },
      });
      setSettings(saved);
      setDraft(saved);
      setNote('合规设置已保存（立即生效）');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<BlacklistRow>[] = [
    { key: 'scope', label: '维度', width: '80px', render: (row) => (row.scope === 'phone' ? '号码' : '客户') },
    { key: 'value', label: '值', width: '180px' },
    { key: 'reason', label: '原因', render: (row) => row.reason ?? '—' },
    { key: 'created_by', label: '加入人', width: '150px', render: (row) => row.created_by ?? '—' },
    { key: 'created_at', label: '时间', width: '150px', render: (row) => stamp(row.created_at) },
    {
      key: 'ops',
      label: '操作',
      width: '90px',
      render: (row) =>
        props.canManage ? (
          <Button size='sm' variant='danger' disabled={busy} onClick={() => void remove(row)}>
            移出
          </Button>
        ) : (
          <span className='text-xs text-slate-500'>需主管</span>
        ),
    },
  ];

  return (
    <div className='space-y-4'>
      <ErrorNote message={error} />
      {note && <Note tone='good'>{note}</Note>}

      <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
        <Card title='拦截规则'>
          {!draft && <Loading />}
          {draft && (
            <div className='space-y-3'>
              <Note tone='info'>
                免打扰时段是<strong>禁呼区间</strong>：默认 21:00–09:00（跨零点，写成 start &gt; end）。
                想完全不限制就设成两个相同的值。
              </Note>
              <div className='grid grid-cols-2 gap-3'>
                <Field label='免打扰起'>
                  <TextInput value={draft.dnd_start} onChange={(next) => setDraft({ ...draft, dnd_start: next })} placeholder='21:00' />
                </Field>
                <Field label='免打扰止'>
                  <TextInput value={draft.dnd_end} onChange={(next) => setDraft({ ...draft, dnd_end: next })} placeholder='09:00' />
                </Field>
                <Field label='坐席每日上限（通）'>
                  <TextInput
                    value={String(draft.daily_limit)}
                    onChange={(next) => setDraft({ ...draft, daily_limit: Number(next) || 0 })}
                    type='number'
                  />
                </Field>
                <Field label='单号码每日上限（次）'>
                  <TextInput
                    value={String(draft.per_number_daily_limit)}
                    onChange={(next) => setDraft({ ...draft, per_number_daily_limit: Number(next) || 0 })}
                    type='number'
                  />
                </Field>
              </div>
              <label className='flex items-center gap-2 text-sm'>
                <input
                  type='checkbox'
                  checked={draft.mask_phone}
                  onChange={(event) => setDraft({ ...draft, mask_phone: event.target.checked })}
                />
                号码脱敏展示（生产环境必须开启）
              </label>
              <div className='flex items-center gap-3'>
                <Button variant='primary' disabled={busy || !props.canManage} onClick={() => void save()}>
                  保存
                </Button>
                <span className='text-xs text-slate-500'>
                  当前来源：{settings?.source === 'runtime' ? '运行时覆盖（写库）' : '环境变量默认值'}
                </span>
              </div>
            </div>
          )}
        </Card>

        <Card title='加入黑名单'>
          <div className='space-y-3'>
            <Field label='维度'>
              <Select value={scope} onChange={setScope} options={props.meta.blacklist_scopes} />
            </Field>
            <Field label={scope === 'phone' ? '号码' : 'CRM 记录 ID'} hint={scope === 'phone' ? '会自动做号码归一化' : '例如 lead-0001'}>
              <TextInput value={value} onChange={setValue} placeholder={scope === 'phone' ? '13800000000' : 'lead-0001'} />
            </Field>
            <Field label='原因'>
              <TextInput value={reason} onChange={setReason} placeholder='例如：客户明确要求不再联系' />
            </Field>
            <Button variant='primary' disabled={busy || !value.trim() || !props.canManage} onClick={() => void add()}>
              加入
            </Button>
            {!props.canManage && <Note tone='warn'>只有主管及以上可以维护黑名单。</Note>}
          </div>
        </Card>
      </div>

      <Card title='黑名单' extra={<Badge>{rows.length} 条</Badge>}>
        <Table columns={columns} rows={rows} rowKey={(row) => row.id} empty='黑名单为空' />
      </Card>
    </div>
  );
}