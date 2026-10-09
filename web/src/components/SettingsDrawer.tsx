// 设置抽屉：接口地址、SSE 开关、当前身份、改密码、退出。
import { useEffect, useState } from 'react';

import { ApiError, request, setApiBase } from '../lib/api';
import type { Meta, Providers } from '../lib/types';
import { Button, ErrorNote, Field, Note, TextInput } from './ui';

export default function SettingsDrawer(props: {
  open: boolean;
  meta: Meta;
  token: string;
  apiBaseValue: string;
  streamState: string;
  onClose: () => void;
  onApiBase: (value: string) => void;
  onLogout: () => void;
}) {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [base, setBase] = useState(props.apiBaseValue);
  const [providers, setProviders] = useState<Providers | null>(null);

  useEffect(() => {
    if (!props.open) return;
    request<Providers>('/api/v1/providers', { token: props.token })
      .then(setProviders)
      .catch(() => setProviders(null));
  }, [props.open, props.token]);

  if (!props.open) return null;

  const changePassword = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await request('/api/auth/password', {
        method: 'POST',
        token: props.token,
        body: { old_password: oldPassword, new_password: newPassword },
      });
      setMessage('密码已更新');
      setOldPassword('');
      setNewPassword('');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const roleLabel = props.meta.roles.find((item) => item.value === props.meta.me.role)?.label ?? props.meta.me.role;

  return (
    <div className='fixed inset-0 z-50 flex justify-end bg-black/50'>
      <aside className='scroll-thin h-full w-full max-w-sm overflow-auto border-l border-edge bg-panel p-4'>
        <header className='mb-4 flex items-center justify-between'>
          <h2 className='text-sm font-medium'>设置</h2>
          <Button size='sm' variant='ghost' onClick={props.onClose}>
            关闭
          </Button>
        </header>

        <div className='space-y-4 text-sm'>
          <div className='rounded border border-edge p-3 text-xs text-slate-400'>
            <div>
              当前身份：{props.meta.me.name}（{roleLabel}）
            </div>
            <div className='mt-1 font-mono'>{props.meta.me.id}</div>
            <div className='mt-1'>团队：{props.meta.me.team_id ?? '—'}</div>
            <div className='mt-1'>
              实时连接：
              {props.streamState === 'open' ? '已连接' : props.streamState === 'error' ? '连接失败（自动重试）' : '未连接'}
            </div>
          </div>

          <div className='rounded border border-edge p-3 text-xs text-slate-400'>
            <div className='mb-2 text-slate-300'>电话线路</div>
            {providers ? (
              <div className='space-y-1'>
                <div>
                  当前：{providers.active === 'rest' ? '真实线路（rest）' : '模拟线路（simulated）'}
                </div>
                {providers.active === 'rest' && (
                  <>
                    <div>网关地址：{providers.base_url_configured ? '已配置' : '未配置'}</div>
                    <div>坐席号码：{providers.agent_phone_configured ? '已配置' : '未配置'}</div>
                    <div className='break-all'>回调：{providers.callback_path}</div>
                  </>
                )}
                <div className='pt-1 text-slate-500'>
                  线路在 <span className='font-mono'>.env</span> 里配（WAHU_TELEPHONY_*），改完要重启后端进程。
                  详细接法与网关契约见 <span className='font-mono'>docs/telephony.md</span>。
                </div>
              </div>
            ) : (
              <div>读取中…</div>
            )}
          </div>

          <Field label='后端地址' hint='留空表示用同源（前端 dev 由 vite 代理到 9300）'>
            <TextInput value={base} onChange={setBase} placeholder='http://127.0.0.1:9300' />
          </Field>
          <div className='flex gap-2'>
            <Button
              onClick={() => {
                setApiBase(base);
                props.onApiBase(base);
              }}
            >
              保存地址
            </Button>
            <Button variant='ghost' onClick={props.onClose}>
              返回
            </Button>
          </div>

          <div className='rounded border border-edge p-3'>
            <div className='mb-2 text-xs text-slate-400'>修改密码</div>
            <div className='space-y-2'>
              <TextInput value={oldPassword} onChange={setOldPassword} type='password' placeholder='原密码' />
              <TextInput value={newPassword} onChange={setNewPassword} type='password' placeholder='新密码（至少 8 位）' />
              <Button variant='primary' disabled={busy || newPassword.length < 8} onClick={() => void changePassword()}>
                提交
              </Button>
            </div>
            {message && (
              <div className='mt-2'>
                <Note tone='good'>{message}</Note>
              </div>
            )}
            <ErrorNote message={error} />
          </div>

          <Note>
            身份令牌存在浏览器本地，默认 12 小时有效。接口地址同样保存在本地，切换环境不用改代码。
          </Note>

          <Button variant='danger' onClick={props.onLogout}>
            退出登录
          </Button>
        </div>
      </aside>
    </div>
  );
}