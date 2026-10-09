// 审计：谁在什么时候对什么对象做了什么。
import { useCallback, useEffect, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { stamp, summarize } from '../lib/format';
import type { AuditRow } from '../lib/types';
import { Button, Card, ErrorNote, Pagination, Select, Table, TextInput, type Column } from './ui';

const ACTIONS = [
  'login',
  'dial',
  'hangup',
  'complete_call',
  'call_ended',
  'create_batch_from_crm',
  'import_batch',
  'delete_batch',
  'create_task',
  'update_task',
  'claim_task',
  'assign_items',
  'skip_item',
  'create_blacklist',
  'remove_blacklist',
  'block_blacklist',
  'block_number_limit',
  'view_full_phone',
  'update_compliance',
  'sync_crm',
  'retry_writeback',
  'create_script',
  'update_script',
  'create_robot_task',
  'start_robot_task',
  'pause_robot_task',
  'create_user',
  'update_user',
  'change_password',
];

export default function Audit(props: { token: string }) {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [action, setAction] = useState('');
  const [objectType, setObjectType] = useState('');
  const [limit, setLimit] = useState(100);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await request<{ data: AuditRow[] }>(
        '/api/v1/audit?limit=' + String(limit) + (action ? '&action=' + action : '') + (objectType ? '&object_type=' + objectType : ''),
        { token: props.token },
      );
      setRows(data.data);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [action, limit, objectType, props.token]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: Column<AuditRow>[] = [
    { key: 'at', label: '时间', width: '160px', render: (row) => stamp(row.at) },
    { key: 'actor_name', label: '操作者', width: '140px', render: (row) => row.actor_name ?? row.actor_id ?? '—' },
    { key: 'action', label: '动作', width: '170px' },
    { key: 'object_type', label: '对象', width: '130px', render: (row) => row.object_type ?? '—' },
    { key: 'object_id', label: '对象 ID', width: '170px', render: (row) => <span className='font-mono text-xs'>{row.object_id ?? '—'}</span> },
    { key: 'detail', label: '细节', render: (row) => <span className='text-xs text-slate-400'>{summarize(row.detail)}</span> },
  ];

  return (
    <div className='space-y-4'>
      <ErrorNote message={error} />
      <Card
        title='审计日志'
        extra={
          <>
            <Select
              value={action}
              onChange={setAction}
              options={ACTIONS.map((item) => ({ value: item, label: item }))}
              emptyLabel='全部动作'
            />
            <TextInput value={objectType} onChange={setObjectType} placeholder='对象类型，如 calls' />
            <Button size='sm' onClick={() => setLimit(limit === 100 ? 200 : 100)}>
              {limit === 100 ? '取 200 条' : '取 100 条'}
            </Button>
            <Button size='sm' variant='ghost' onClick={() => void load()}>
              刷新
            </Button>
          </>
        }
      >
        <Table columns={columns} rows={rows} rowKey={(row) => row.id} empty='没有审计记录' />
        <Pagination page={1} pageSize={limit} total={rows.length} onChange={() => undefined} />
      </Card>
    </div>
  );
}