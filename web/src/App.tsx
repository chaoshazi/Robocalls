// 控制台外壳：登录门禁、侧栏导航、SSE 实时连接、设置抽屉。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError, apiBase, clearIdentity, loadIdentity, openStream, request, saveIdentity, type StoredIdentity } from './lib/api';
import type { Meta, StreamEvent } from './lib/types';
import Admin from './components/Admin';
import Audit from './components/Audit';
import Batches from './components/Batches';
import Calls from './components/Calls';
import CompliancePanel from './components/Compliance';
import Dashboard from './components/Dashboard';
import Login from './components/Login';
import Reports from './components/Reports';
import Robot from './components/Robot';
import SettingsDrawer from './components/SettingsDrawer';
import Tasks from './components/Tasks';
import WorkbenchPanel from './components/Workbench';
import Writeback from './components/Writeback';

type PanelKey =
  | 'dashboard'
  | 'workbench'
  | 'tasks'
  | 'batches'
  | 'calls'
  | 'reports'
  | 'robot'
  | 'compliance'
  | 'writeback'
  | 'admin'
  | 'audit';

interface NavItem {
  key: PanelKey;
  label: string;
  icon: string;
  roles?: string[];
}

const NAV: NavItem[] = [
  { key: 'dashboard', label: '仪表盘', icon: '▦' },
  { key: 'workbench', label: '坐席工作台', icon: '☎' },
  { key: 'tasks', label: '外呼任务', icon: '⚑' },
  { key: 'batches', label: '名单批次', icon: '☰', roles: ['admin', 'manager'] },
  { key: 'calls', label: '通话记录', icon: '≡' },
  { key: 'reports', label: '统计报表', icon: '◔', roles: ['admin', 'manager'] },
  { key: 'robot', label: 'AI 机器人', icon: '◎', roles: ['admin', 'manager'] },
  { key: 'compliance', label: '合规与黑名单', icon: '⛨' },
  { key: 'writeback', label: 'CRM 回写', icon: '⇄', roles: ['admin', 'manager'] },
  { key: 'admin', label: '用户与团队', icon: '☺', roles: ['admin'] },
  { key: 'audit', label: '审计日志', icon: '⌛', roles: ['admin', 'manager'] },
];

export default function App() {
  const [identity, setIdentity] = useState<StoredIdentity | null>(() => loadIdentity());
  const [meta, setMeta] = useState<Meta | null>(null);
  const [panel, setPanel] = useState<PanelKey>('dashboard');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [streamState, setStreamState] = useState<'idle' | 'open' | 'closed' | 'error'>('idle');
  const [baseVersion, setBaseVersion] = useState(0);
  const closeRef = useRef<{ close: () => void } | null>(null);

  const token = identity?.token ?? '';
  const logout = useCallback(() => {
    clearIdentity();
    setIdentity(null);
    setMeta(null);
    setEvents([]);
  }, []);

  // 拉元数据
  useEffect(() => {
    if (!token) {
      setMeta(null);
      return;
    }
    request<Meta>('/api/v1/meta', { token })
      .then((data) => {
        setMeta(data);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (caught instanceof ApiError && caught.status === 401) {
          logout();
          return;
        }
        setError(caught instanceof ApiError ? caught.message : String(caught));
      });
  }, [baseVersion, logout, token]);

  // SSE：断线 3 秒后重连
  useEffect(() => {
    if (!token) {
      setStreamState('idle');
      return undefined;
    }
    let retry: number | null = null;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      closeRef.current = openStream(
        token,
        (event) => {
          if (event.type === 'hello') return;
          setEvents((current) => [event, ...current].slice(0, 50));
        },
        (state) => {
          setStreamState(state);
          if (state === 'error' || state === 'closed') {
            retry = window.setTimeout(connect, 3000);
          }
        },
      );
    };

    connect();
    return () => {
      stopped = true;
      if (retry !== null) window.clearTimeout(retry);
      closeRef.current?.close();
      closeRef.current = null;
    };
  }, [baseVersion, token]);

  const visibleNav = useMemo(
    () => NAV.filter((item) => !item.roles || !meta || item.roles.includes(meta.me.role)),
    [meta],
  );

  if (!identity || !meta) {
    return (
      <Login
        onLogin={(value) => {
          saveIdentity(value);
          setIdentity(value);
        }}
      />
    );
  }

  const canManage = meta.me.role === 'admin' || meta.me.role === 'manager';

  return (
    <div className='flex h-full'>
      <aside className='flex w-52 flex-col border-r border-edge bg-panel'>
        <div className='border-b border-edge px-4 py-3'>
          <div className='text-sm font-semibold'>外呼系统</div>
          <div className='mt-1 text-xs text-slate-500'>名单 · 任务 · 坐席 · 合规</div>
        </div>
        <nav className='scroll-thin flex-1 overflow-auto p-2'>
          {visibleNav.map((item) => (
            <button
              key={item.key}
              type='button'
              onClick={() => setPanel(item.key)}
              className={
                'mb-1 flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm transition ' +
                (panel === item.key ? 'bg-sky-600/20 text-sky-200' : 'text-slate-300 hover:bg-slate-800')
              }
            >
              <span className='w-4 text-center text-slate-500'>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className='border-t border-edge px-3 py-2 text-xs text-slate-400'>
          <div className='truncate'>{meta.me.name}</div>
          <div className='mt-0.5 flex items-center gap-2'>
            <span>{meta.roles.find((item) => item.value === meta.me.role)?.label ?? meta.me.role}</span>
            <span className={streamState === 'open' ? 'text-emerald-400' : 'text-slate-500'}>
              {streamState === 'open' ? '· 实时已连' : '· 实时未连'}
            </span>
          </div>
          <button type='button' className='mt-2 text-xs text-slate-400 hover:text-slate-200' onClick={() => setSettingsOpen(true)}>
            设置
          </button>
        </div>
      </aside>

      <main className='scroll-thin flex-1 overflow-auto'>
        <header className='sticky top-0 z-10 flex items-center justify-between border-b border-edge bg-ink/95 px-5 py-3 backdrop-blur'>
          <div>
            <h1 className='text-sm font-medium text-slate-100'>
              {visibleNav.find((item) => item.key === panel)?.label ?? ''}
            </h1>
            <p className='mt-0.5 text-xs text-slate-500'>
              后端 {apiBase() || '同源'} · 租户 {meta.tenant_id} · 事件 {events.length} 条
            </p>
          </div>
          <div className='flex items-center gap-2'>
            <button
              type='button'
              className='rounded border border-edge px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800'
              onClick={() => setSettingsOpen(true)}
            >
              设置
            </button>
          </div>
        </header>

        <div className='p-5'>
          {error && (
            <div className='mb-4'>
              <div className='rounded border border-rose-700 bg-rose-950/40 px-3 py-2 text-xs text-rose-200'>{error}</div>
            </div>
          )}
          {panel === 'dashboard' && <Dashboard token={token} meta={meta} events={events} />}
          {panel === 'workbench' && (
            <WorkbenchPanel
              token={token}
              meta={meta}
              events={events}
              onNavigate={(next) => setPanel(next as PanelKey)}
            />
          )}
          {panel === 'tasks' && <Tasks token={token} meta={meta} me={{ id: meta.me.id, role: meta.me.role }} />}
          {panel === 'batches' && <Batches token={token} meta={meta} />}
          {panel === 'calls' && <Calls token={token} meta={meta} />}
          {panel === 'reports' && <Reports token={token} />}
          {panel === 'robot' && <Robot token={token} meta={meta} canManage={canManage} />}
          {panel === 'compliance' && <CompliancePanel token={token} meta={meta} canManage={canManage} />}
          {panel === 'writeback' && <Writeback token={token} meta={meta} />}
          {panel === 'admin' && <Admin token={token} meta={meta} canManage={meta.me.role === 'admin'} />}
          {panel === 'audit' && <Audit token={token} />}
        </div>
      </main>

      <SettingsDrawer
        open={settingsOpen}
        meta={meta}
        token={token}
        apiBaseValue={apiBase()}
        streamState={streamState}
        onClose={() => setSettingsOpen(false)}
        onApiBase={() => setBaseVersion((value) => value + 1)}
        onLogout={logout}
      />
    </div>
  );
}