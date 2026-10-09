// 通用组件：卡片、表格、表单、弹窗、徽标等，避免每个面板重复写样式。
import type { ChangeEvent, ReactNode } from 'react';

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  width?: string;
  align?: 'left' | 'right' | 'center';
}

export function Card(props: { title?: ReactNode; extra?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={'rounded-lg border border-edge bg-panel ' + (props.className ?? '')}>
      {(props.title || props.extra) && (
        <header className='flex items-center justify-between gap-3 border-b border-edge px-4 py-2.5'>
          <h2 className='text-sm font-medium text-slate-200'>{props.title}</h2>
          <div className='flex items-center gap-2 text-xs text-slate-400'>{props.extra}</div>
        </header>
      )}
      <div className='p-4'>{props.children}</div>
    </section>
  );
}

export function Stat(props: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'default' | 'good' | 'warn' }) {
  const tone =
    props.tone === 'good' ? 'text-emerald-400' : props.tone === 'warn' ? 'text-amber-400' : 'text-slate-100';
  return (
    <div className='rounded-lg border border-edge bg-panel px-4 py-3'>
      <div className='text-xs text-slate-400'>{props.label}</div>
      <div className={'mt-1 text-2xl font-semibold ' + tone}>{props.value}</div>
      {props.hint !== undefined && <div className='mt-1 text-xs text-slate-500'>{props.hint}</div>}
    </div>
  );
}

export function Button(props: {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'default' | 'primary' | 'danger' | 'ghost';
  disabled?: boolean;
  size?: 'sm' | 'md';
  title?: string;
}) {
  const base =
    'inline-flex items-center justify-center whitespace-nowrap rounded border transition disabled:cursor-not-allowed disabled:opacity-40';
  const size = props.size === 'sm' ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm';
  const variant =
    props.variant === 'primary'
      ? 'border-sky-500 bg-sky-600 text-white hover:bg-sky-500'
      : props.variant === 'danger'
        ? 'border-rose-500 bg-rose-600 text-white hover:bg-rose-500'
        : props.variant === 'ghost'
          ? 'border-transparent text-slate-300 hover:bg-slate-800'
          : 'border-edge bg-slate-800 text-slate-200 hover:bg-slate-700';
  return (
    <button
      type='button'
      title={props.title}
      disabled={props.disabled}
      onClick={props.onClick}
      className={base + ' ' + size + ' ' + variant}
    >
      {props.children}
    </button>
  );
}

export function Field(props: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className='block'>
      <span className='mb-1 block text-xs text-slate-400'>{props.label}</span>
      {props.children}
      {props.hint !== undefined && <span className='mt-1 block text-xs text-slate-500'>{props.hint}</span>}
    </label>
  );
}

const inputClass =
  'w-full rounded border border-edge bg-slate-900 px-2 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none';

export function TextInput(props: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  disabled?: boolean;
}) {
  return (
    <input
      type={props.type ?? 'text'}
      value={props.value}
      disabled={props.disabled}
      placeholder={props.placeholder}
      onChange={(event: ChangeEvent<HTMLInputElement>) => props.onChange(event.target.value)}
      className={inputClass}
    />
  );
}

export function TextArea(props: { value: string; onChange: (value: string) => void; rows?: number; placeholder?: string }) {
  return (
    <textarea
      value={props.value}
      rows={props.rows ?? 3}
      placeholder={props.placeholder}
      onChange={(event: ChangeEvent<HTMLTextAreaElement>) => props.onChange(event.target.value)}
      className={inputClass + ' resize-y font-mono'}
    />
  );
}

export function Select(props: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  emptyLabel?: string;
  disabled?: boolean;
}) {
  return (
    <select
      value={props.value}
      disabled={props.disabled}
      onChange={(event: ChangeEvent<HTMLSelectElement>) => props.onChange(event.target.value)}
      className={inputClass}
    >
      {props.emptyLabel !== undefined && <option value=''>{props.emptyLabel}</option>}
      {props.options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function Badge(props: { children: ReactNode; tone?: 'default' | 'good' | 'warn' | 'bad' | 'info' }) {
  const tone =
    props.tone === 'good'
      ? 'border-emerald-600 bg-emerald-900/40 text-emerald-300'
      : props.tone === 'warn'
        ? 'border-amber-600 bg-amber-900/40 text-amber-300'
        : props.tone === 'bad'
          ? 'border-rose-600 bg-rose-900/40 text-rose-300'
          : props.tone === 'info'
            ? 'border-sky-600 bg-sky-900/40 text-sky-300'
            : 'border-edge bg-slate-800 text-slate-300';
  return (
    <span className={'inline-flex items-center rounded border px-1.5 py-0.5 text-xs ' + tone}>{props.children}</span>
  );
}

export function Table<T>(props: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  empty?: string;
}) {
  if (props.rows.length === 0) {
    return <div className='py-8 text-center text-sm text-slate-500'>{props.empty ?? '暂无数据'}</div>;
  }
  return (
    <div className='scroll-thin overflow-auto'>
      <table className='w-full border-collapse text-sm'>
        <thead>
          <tr className='border-b border-edge text-left text-xs uppercase tracking-wide text-slate-500'>
            {props.columns.map((column) => (
              <th
                key={column.key}
                style={{ width: column.width }}
                className={'whitespace-nowrap px-2 py-2 font-medium ' + (column.align === 'right' ? 'text-right' : '')}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.rows.map((row, index) => (
            <tr
              key={props.rowKey(row, index)}
              onClick={props.onRowClick ? () => props.onRowClick?.(row) : undefined}
              className={
                'border-b border-edge/60 ' + (props.onRowClick ? 'cursor-pointer hover:bg-slate-800/60' : '')
              }
            >
              {props.columns.map((column) => (
                <td
                  key={column.key}
                  className={
                    'px-2 py-2 align-top text-slate-200 ' + (column.align === 'right' ? 'text-right' : '')
                  }
                >
                  {column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Modal(props: { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  if (!props.open) return null;
  return (
    <div className='fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4'>
      <div className='max-h-[86vh] w-full max-w-2xl overflow-auto rounded-lg border border-edge bg-panel shadow-2xl'>
        <header className='flex items-center justify-between border-b border-edge px-4 py-3'>
          <h3 className='text-sm font-medium'>{props.title}</h3>
          <Button variant='ghost' size='sm' onClick={props.onClose}>
            关闭
          </Button>
        </header>
        <div className='space-y-3 p-4'>{props.children}</div>
        {props.footer && <footer className='flex justify-end gap-2 border-t border-edge px-4 py-3'>{props.footer}</footer>}
      </div>
    </div>
  );
}

export function Note(props: { tone?: 'info' | 'warn' | 'bad' | 'good'; children: ReactNode }) {
  const tone =
    props.tone === 'warn'
      ? 'border-amber-700 bg-amber-950/40 text-amber-200'
      : props.tone === 'bad'
        ? 'border-rose-700 bg-rose-950/40 text-rose-200'
        : props.tone === 'good'
          ? 'border-emerald-700 bg-emerald-950/40 text-emerald-200'
          : 'border-sky-800 bg-sky-950/40 text-sky-200';
  return <div className={'rounded border px-3 py-2 text-xs ' + tone}>{props.children}</div>;
}

export function Loading(props: { label?: string }) {
  return <div className='py-8 text-center text-sm text-slate-500'>{props.label ?? '加载中…'}</div>;
}

export function ErrorNote(props: { message: string | null }) {
  if (!props.message) return null;
  return <Note tone='bad'>{props.message}</Note>;
}

export function Pagination(props: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(props.total / Math.max(1, props.pageSize)));
  return (
    <div className='mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400'>
      <span>
        共 {props.total} 条 · 第 {props.page} / {pages} 页
      </span>
      <span className='flex gap-2'>
        <Button size='sm' disabled={props.page <= 1} onClick={() => props.onChange(props.page - 1)}>
          上一页
        </Button>
        <Button size='sm' disabled={props.page >= pages} onClick={() => props.onChange(props.page + 1)}>
          下一页
        </Button>
      </span>
    </div>
  );
}