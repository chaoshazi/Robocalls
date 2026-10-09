// 登录页：登录成功后把令牌交给上层保存。
import { useEffect, useState } from 'react';

import { ApiError, request, type StoredIdentity } from '../lib/api';
import { Button, ErrorNote, Field, Note, TextInput } from './ui';

interface HealthPayload {
  version: string;
  storage: string;
  telephony: string;
  crm_mode: string;
  llm_mode: string;
  env: string;
}

export default function Login(props: { onLogin: (identity: StoredIdentity) => void }) {
  const [email, setEmail] = useState('admin@example.com');
  const [password, setPassword] = useState('admin12345');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthPayload | null>(null);

  useEffect(() => {
    request<HealthPayload>('/health')
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await request<StoredIdentity>('/api/auth/login', {
        method: 'POST',
        body: { email, password },
      });
      props.onLogin(result);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className='flex h-full items-center justify-center p-6'>
      <div className='w-full max-w-sm space-y-4 rounded-lg border border-edge bg-panel p-6'>
        <div>
          <h1 className='text-lg font-semibold text-slate-100'>外呼系统</h1>
          <p className='mt-1 text-xs text-slate-500'>名单 · 任务 · 坐席工作台 · 合规 · 回写 · 机器人</p>
        </div>
        {health && (
          <Note>
            运行模式：{health.env} · 存储 {health.storage} · 线路 {health.telephony} · CRM {health.crm_mode} ·
            大模型 {health.llm_mode}
          </Note>
        )}
        <Field label='邮箱'>
          <TextInput value={email} onChange={setEmail} placeholder='admin@example.com' />
        </Field>
        <Field label='密码'>
          <TextInput value={password} onChange={setPassword} type='password' />
        </Field>
        <ErrorNote message={error} />
        <Button variant='primary' disabled={busy || !email || !password} onClick={() => void submit()}>
          {busy ? '登录中…' : '登录'}
        </Button>
        <p className='text-xs text-slate-500'>首次启动会按 .env 里的 WAHU_BOOTSTRAP_ADMIN_* 创建管理员。</p>
      </div>
    </div>
  );
}