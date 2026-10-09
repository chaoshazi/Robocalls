// 名单批次：从 CRM 拉取、导入 CSV/XLSX、查看条目、删除。
import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { stamp } from '../lib/format';
import type { Batch, ListItem, Meta, Paged } from '../lib/types';
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Field,
  Loading,
  Modal,
  Note,
  Pagination,
  Select,
  Table,
  TextInput,
  type Column,
} from './ui';

interface ImportReport {
  total_rows: number;
  imported: number;
  duplicates: number;
  failed: number;
  failed_rows: { row?: number; phone?: string; reason?: string }[];
  duplicate_rows: { row?: number; phone?: string }[];
}

export default function Batches(props: { token: string; meta: Meta }) {
  const [rows, setRows] = useState<Batch[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Batch | null>(null);
  const [items, setItems] = useState<ListItem[]>([]);
  const [itemTotal, setItemTotal] = useState(0);
  const [itemPage, setItemPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [crmObject, setCrmObject] = useState('leads');
  const [limit, setLimit] = useState('200');
  const [batchName, setBatchName] = useState('');
  const [report, setReport] = useState<ImportReport | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const pageSize = 20;

  const load = useCallback(async () => {
    try {
      const data = await request<Paged<Batch>>(
        '/api/v1/batches' + '?page=' + String(page) + '&page_size=' + String(pageSize) + (search ? '&search=' + encodeURIComponent(search) : ''),
        { token: props.token },
      );
      setRows(data.data);
      setTotal(data.total);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [page, props.token, search]);

  const loadItems = useCallback(
    async (batch: Batch, targetPage = 1) => {
      try {
        const data = await request<Paged<ListItem>>(
          '/api/v1/batches/' + batch.id + '/items?page=' + String(targetPage) + '&page_size=' + String(pageSize),
          { token: props.token },
        );
        setItems(data.data);
        setItemTotal(data.total);
        setItemPage(targetPage);
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : String(caught));
      }
    },
    [props.token],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const pullFromCrm = async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await request<{ batch: Batch; report: ImportReport }>('/api/v1/batches/from-crm', {
        method: 'POST',
        token: props.token,
        body: { crm_object: crmObject, limit: Number(limit) || 200, name: batchName || undefined },
      });
      setReport(data.report);
      setCreating(false);
      setBatchName('');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      if (batchName) form.append('name', batchName);
      const data = await request<{ batch: Batch; report: ImportReport }>('/api/v1/batches/import', {
        method: 'POST',
        token: props.token,
        form,
      });
      setReport(data.report);
      setCreating(false);
      setBatchName('');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (batch: Batch) => {
    setBusy(true);
    setError(null);
    try {
      await request('/api/v1/batches/' + batch.id, { method: 'DELETE', token: props.token });
      setNote('已删除批次 ' + batch.name);
      if (selected?.id === batch.id) setSelected(null);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const batchColumns: Column<Batch>[] = [
    {
      key: 'name',
      label: '批次',
      render: (row) => (
        <button
          type='button'
          className='text-left text-sky-300 hover:underline'
          onClick={() => {
            setSelected(row);
            void loadItems(row, 1);
          }}
        >
          {row.name}
        </button>
      ),
    },
    { key: 'source', label: '来源', width: '110px', render: (row) => (row.source === 'crm' ? 'CRM' : '导入') },
    { key: 'crm_object', label: 'CRM 对象', width: '100px', render: (row) => row.crm_object ?? '—' },
    { key: 'total', label: '总行数', width: '80px', align: 'right' },
    { key: 'imported_total', label: '入库', width: '70px', align: 'right' },
    { key: 'duplicate_total', label: '重复', width: '70px', align: 'right' },
    {
      key: 'failed_total',
      label: '失败',
      width: '70px',
      align: 'right',
      render: (row) => (row.failed_total > 0 ? <span className='text-amber-400'>{row.failed_total}</span> : '0'),
    },
    { key: 'created_at', label: '创建时间', width: '150px', render: (row) => stamp(row.created_at) },
    {
      key: 'ops',
      label: '操作',
      width: '80px',
      render: (row) => (
        <Button size='sm' variant='danger' disabled={busy} onClick={() => void remove(row)}>
          删除
        </Button>
      ),
    },
  ];

  const itemColumns: Column<ListItem>[] = [
    { key: 'phone', label: '号码', width: '140px' },
    { key: 'company', label: '客户', render: (row) => row.company ?? '—' },
    { key: 'contact_name', label: '联系人', width: '110px', render: (row) => row.contact_name ?? '—' },
    {
      key: 'crm_record_id',
      label: 'CRM 归属',
      width: '140px',
      render: (row) => (row.crm_record_id ? row.crm_object + ' / ' + row.crm_record_id : <span className='text-slate-500'>本地导入</span>),
    },
    { key: 'status', label: '状态', width: '90px', render: (row) => <Badge>{row.status}</Badge> },
    { key: 'attempts', label: '拨打次数', width: '90px', align: 'right' },
    { key: 'last_result', label: '最近结果', width: '120px', render: (row) => row.last_result ?? '—' },
  ];

  return (
    <div className='space-y-4'>
      <ErrorNote message={error} />
      {note && <Note tone='good'>{note}</Note>}

      <Card
        title='名单批次'
        extra={
          <>
            <TextInput value={search} onChange={(value) => { setSearch(value); setPage(1); }} placeholder='搜索批次名' />
            <Button variant='primary' size='sm' onClick={() => setCreating(true)}>
              新建批次
            </Button>
          </>
        }
      >
        <Table columns={batchColumns} rows={rows} rowKey={(row) => row.id} empty='还没有名单批次' />
        <Pagination page={page} pageSize={pageSize} total={total} onChange={setPage} />
      </Card>

      {selected && (
        <Card
          title={'条目 · ' + selected.name}
          extra={
            <span>
              {selected.source === 'crm' ? '来自 CRM' : '本地上传'} · 共 {itemTotal} 条
            </span>
          }
        >
          <Table columns={itemColumns} rows={items} rowKey={(row) => row.id} empty='该批次没有条目' />
          <Pagination
            page={itemPage}
            pageSize={pageSize}
            total={itemTotal}
            onChange={(next) => void loadItems(selected, next)}
          />
        </Card>
      )}

      <Modal open={creating} title='新建名单批次' onClose={() => setCreating(false)}>
        <Note tone='info'>
          号码一律按中国大陆规则归一化（去分隔符、去国码前缀），手机号必须是 11 位，座机需带区号；
          批内与库内重复的号码会被跳过，逐行原因会写在导入报告里。
        </Note>
        <Field label='批次名称（可留空）'>
          <TextInput value={batchName} onChange={setBatchName} placeholder='例如：九月首轮线索' />
        </Field>
        <div className='rounded border border-edge p-3'>
          <div className='mb-2 text-xs text-slate-400'>方式一：从自研 CRM 拉取</div>
          <div className='grid grid-cols-2 gap-3'>
            <Field label='CRM 对象'>
              <Select value={crmObject} onChange={setCrmObject} options={props.meta.crm_list_objects} />
            </Field>
            <Field label='最多拉取条数'>
              <TextInput value={limit} onChange={setLimit} type='number' />
            </Field>
          </div>
          <div className='mt-2'>
            <Button variant='primary' size='sm' disabled={busy} onClick={() => void pullFromCrm()}>
              拉取
            </Button>
          </div>
        </div>
        <div className='rounded border border-edge p-3'>
          <div className='mb-2 text-xs text-slate-400'>方式二：上传 CSV / XLSX（表头支持 phone / 手机号 / 电话）</div>
          <input
            ref={fileRef}
            type='file'
            accept='.csv,.xlsx'
            className='text-xs text-slate-300'
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
        </div>
        {busy && <Loading label='处理中…' />}
        {report && (
          <Note tone={report.failed > 0 ? 'warn' : 'good'}>
            共 {report.total_rows} 行 · 入库 {report.imported} · 重复 {report.duplicates} · 失败 {report.failed}
            {report.failed_rows.length > 0 && (
              <ul className='mt-2 list-disc pl-4'>
                {report.failed_rows.slice(0, 8).map((row) => (
                  <li key={String(row.row) + String(row.phone)}>
                    第 {row.row} 行 {row.phone || '(空)'}：{row.reason}
                  </li>
                ))}
              </ul>
            )}
          </Note>
        )}
      </Modal>
    </div>
  );
}