// 坐席工作台：手动拨号 / 取下一个 → 拨号 → 看状态 → 挂断 → 填结果 → 自动流转。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { clock, duration, stamp } from '../lib/format';
import type { Call, Compliance, Meta, Providers, StreamEvent, WorkItem, Workbench } from '../lib/types';
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Field,
  Loading,
  Modal,
  Note,
  Select,
  Stat,
  Table,
  TextArea,
  TextInput,
  type Column,
} from './ui';

const ACTIVE_STATES = ['dialing', 'ringing', 'answered'];

export default function WorkbenchPanel(props: {
  token: string;
  meta: Meta;
  events: StreamEvent[];
  onNavigate?: (panel: string) => void;
}) {
  const [board, setBoard] = useState<Workbench | null>(null);
  const [call, setCall] = useState<Call | null>(null);
  const [completing, setCompleting] = useState<Call | null>(null);
  const [providers, setProviders] = useState<Providers | null>(null);
  const [manualPhone, setManualPhone] = useState('');
  const [manualName, setManualName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [resultCode, setResultCode] = useState('connected');
  const [intent, setIntent] = useState('');
  const [note, setNote] = useState('');
  const [followup, setFollowup] = useState('');
  const [followupPriority, setFollowupPriority] = useState('normal');
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await request<Workbench>('/api/v1/workbench/next', { token: props.token });
      setBoard(data);
      if (data.active_call) setCall(data.active_call);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [props.token]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const fetchProviders = () => {
      request<Providers>('/api/v1/providers', { token: props.token })
        .then(setProviders)
        .catch(() => setProviders(null));
    };
    fetchProviders();
    const timer = window.setInterval(fetchProviders, 30000);
    return () => window.clearInterval(timer);
  }, [props.token]);

  // 通话进行中每秒刷新一次状态，顺便走秒
  useEffect(() => {
    if (!call || !ACTIVE_STATES.includes(call.state)) {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return undefined;
    }
    const tick = async () => {
      try {
        const fresh = await request<Call>('/api/v1/calls/' + call.id, { token: props.token });
        setCall(fresh);
        if (!ACTIVE_STATES.includes(fresh.state)) {
          if (fresh.state === 'ended' && !fresh.result_code) {
            setCompleting(fresh);
          } else {
            setCall(null);
            await load();
          }
        }
      } catch {
        // 轮询失败不打断界面，下一秒再试
      }
    };
    pollRef.current = window.setInterval(() => void tick(), 1000);
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [call, load, props.token]);

  useEffect(() => {
    if (!call) {
      setSeconds(0);
      return undefined;
    }
    const started = new Date(call.answered_at ?? call.started_at).getTime();
    const timer = window.setInterval(() => {
      setSeconds(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [call]);

  const startCall = async (body: { task_item_id?: string; phone?: string }) => {
    setBusy(true);
    setError(null);
    try {
      const created = await request<Call>('/api/v1/calls/dial', {
        method: 'POST',
        token: props.token,
        body,
      });
      setCall(created);
      setSeconds(0);
      setManualPhone('');
      setManualName('');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
      await load();
    } finally {
      setBusy(false);
    }
  };

  const dialTaskItem = async () => {
    if (!board?.item) return;
    await startCall({ task_item_id: board.item.id });
  };

  const dialManual = async () => {
    const phone = manualPhone.trim();
    if (!phone) return;
    await startCall({ phone });
  };

  const hangup = async () => {
    if (!call) return;
    setBusy(true);
    try {
      const fresh = await request<Call>('/api/v1/calls/' + call.id + '/hangup', {
        method: 'POST',
        token: props.token,
      });
      setCall(null);
      if (fresh.result_code) {
        await load();
      } else {
        setCompleting(fresh);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const submitResult = async () => {
    if (!completing) return;
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = { result_code: resultCode };
      if (intent) payload.intent_level = intent;
      if (note) payload.note = note;
      if (manualName.trim() && !completing.list_item_id) {
        payload.note = (note ? note + ' / ' : '') + '手动拨号：' + manualName.trim();
      }
      if (followup) {
        payload.followup_subject = followup;
        payload.followup_priority = followupPriority;
      }
      await request<Call>('/api/v1/calls/' + completing.id + '/complete', {
        method: 'POST',
        token: props.token,
        body: payload,
      });
      setCompleting(null);
      setNote('');
      setFollowup('');
      setIntent('');
      setResultCode('connected');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const skip = async () => {
    if (!board?.item) return;
    setBusy(true);
    try {
      await request('/api/v1/task-items/' + board.item.id + '/skip', {
        method: 'POST',
        token: props.token,
      });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const resultOptions = useMemo(
    () =>
      props.meta.call_results.map((item) => ({
        value: item.code,
        label: item.label + '（' + (item.category === 'answered' ? '已接通' : '未接通') + '）',
      })),
    [props.meta.call_results],
  );

  const eventColumns: Column<StreamEvent>[] = [
    { key: 'at', label: '时间', width: '80px', render: (row) => clock(row.at) },
    { key: 'phone', label: '号码', render: (row) => row.phone_masked ?? '—' },
    { key: 'state', label: '状态', render: (row) => row.state_label ?? '—' },
  ];

  const item: WorkItem | null = board?.item ?? null;
  const compliance: Compliance | null = board?.compliance ?? null;
  const cooling = board?.cooling ?? 0;
  const calling = !!call;

  return (
    <div className='space-y-4'>
      <ErrorNote message={error} />

      <div className='grid grid-cols-1 gap-4 lg:grid-cols-3'>
        <div className='space-y-4 lg:col-span-2'>
          <Card
            title='手动拨号'
            extra={<span>不用名单，直接拨任意号码</span>}
          >
            <div className='space-y-3'>
              <div className='grid grid-cols-1 gap-3 sm:grid-cols-3'>
                <div className='sm:col-span-2'>
                  <Field label='号码' hint='手机 11 位，或带区号的座机（如 01012345678）'>
                    <TextInput
                      value={manualPhone}
                      onChange={setManualPhone}
                      placeholder='13800000001'
                      disabled={calling}
                    />
                  </Field>
                </div>
                <Field label='客户备注（可选）'>
                  <TextInput
                    value={manualName}
                    onChange={setManualName}
                    placeholder='比如：老客户王总'
                    disabled={calling}
                  />
                </Field>
              </div>
              <div className='flex gap-2'>
                <Button variant='primary' disabled={busy || calling || !manualPhone.trim()} onClick={() => void dialManual()}>
                  拨号
                </Button>
                <span className='self-center text-xs text-slate-500'>
                  手动拨号没有名单归属，通话结果不会回写 CRM（避免往 CRM 里塞无主记录）。
                </span>
              </div>
            </div>
          </Card>

          <Card
            title='名单任务队列'
            extra={
              <span>
                可呼 {board?.due ?? 0} 条
                {cooling > 0 ? ' · 冷却中 ' + String(cooling) + ' 条' : ''}
              </span>
            }
          >
            {!board && <Loading />}
            {board && !item && (
              <div className='space-y-3'>
                {cooling > 0 ? (
                  <Note tone='warn'>
                    你有 {cooling} 条待呼还压在<strong>重呼冷却</strong>里（未接通的号码默认 15 分钟后才会再出现）。
                    想马上继续打，可以直接用上面的手动拨号，或者去「外呼任务」里换一条。
                  </Note>
                ) : (
                  <Note tone='info'>
                    名下暂时没有待呼的任务项。外呼有三条路：
                    <ol className='mt-1 list-decimal pl-4'>
                      <li>用上面的「手动拨号」直接打任意号码（最快，不需要名单）；</li>
                      <li>去「名单批次」从 CRM 拉名单或上传 Excel/CSV，再去「外呼任务」建任务，回到这里点「拨号」；</li>
                      <li>去「AI 机器人」建机器人任务，让它自动批量打。</li>
                    </ol>
                  </Note>
                )}
                <div className='flex flex-wrap gap-2'>
                  <Button onClick={() => props.onNavigate?.('batches')}>去建名单</Button>
                  <Button onClick={() => props.onNavigate?.('tasks')}>去看任务</Button>
                  <Button variant='ghost' onClick={() => props.onNavigate?.('calls')}>
                    看通话记录
                  </Button>
                  <Button variant='ghost' disabled={busy} onClick={() => void load()}>
                    刷新队列
                  </Button>
                </div>
              </div>
            )}
            {item && (
              <div className='space-y-3'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='text-lg font-semibold text-slate-100'>{item.phone}</span>
                  <Badge tone={item.priority === 'high' ? 'bad' : 'default'}>{item.priority_label}</Badge>
                  <Badge>{item.status_label}</Badge>
                  {item.crm_record_id && (
                    <Badge tone='info'>
                      {item.crm_object} / {item.crm_record_id}
                    </Badge>
                  )}
                </div>
                <div className='grid grid-cols-2 gap-3 text-sm lg:grid-cols-4'>
                  <div>
                    <div className='text-xs text-slate-500'>客户</div>
                    <div>{item.company ?? item.customer_name ?? '—'}</div>
                  </div>
                  <div>
                    <div className='text-xs text-slate-500'>联系人</div>
                    <div>{item.contact_name ?? '—'}</div>
                  </div>
                  <div>
                    <div className='text-xs text-slate-500'>第几次拨打</div>
                    <div>{item.attempts + 1}</div>
                  </div>
                  <div>
                    <div className='text-xs text-slate-500'>最近结果</div>
                    <div>{item.last_result ?? '—'}</div>
                  </div>
                </div>
                <div className='flex gap-2'>
                  <Button variant='primary' disabled={busy || calling} onClick={() => void dialTaskItem()}>
                    拨号
                  </Button>
                  <Button disabled={busy || calling} onClick={() => void skip()}>
                    跳过这条
                  </Button>
                  <Button variant='ghost' disabled={busy || calling} onClick={() => void load()}>
                    取下一个
                  </Button>
                </div>
              </div>
            )}
          </Card>

          <Card title='通话状态'>
            {!call && <Note>当前没有进行中的通话。点上面的「拨号」就会开始振铃。</Note>}
            {call && (
              <div className='space-y-3'>
                <div className='flex items-center gap-3'>
                  <span className='text-lg font-semibold text-slate-100'>{call.phone}</span>
                  <Badge tone={call.state === 'answered' ? 'good' : 'warn'}>{call.state_label}</Badge>
                  <span className='font-mono text-sm text-slate-400'>{duration(seconds)}</span>
                </div>
                <div className='grid grid-cols-2 gap-3 text-xs text-slate-400 lg:grid-cols-4'>
                  <div>线路：{call.provider}</div>
                  <div>开始：{stamp(call.started_at)}</div>
                  <div>振铃：{duration(call.ring_sec)}</div>
                  <div>通话：{duration(call.talk_sec)}</div>
                </div>
                <Note tone='info'>
                  模拟线路会按配置的接通率自动推进状态：拨号中 → 振铃中 → 接通 / 无人接听 / 占线 / 关机 / 空号。
                </Note>
                <Button variant='danger' disabled={busy} onClick={() => void hangup()}>
                  挂断
                </Button>
              </div>
            )}
          </Card>
        </div>

        <div className='space-y-4'>
          <Card title='线路'>
            {providers ? (
              <div className='space-y-2 text-xs text-slate-400'>
                <div className='flex items-center gap-2'>
                  <Badge tone={providers.active === 'rest' ? 'good' : 'default'}>
                    {providers.active === 'rest' ? '真实线路' : '模拟线路'}
                  </Badge>
                  <span>{providers.items.find((item) => item.name === providers.active)?.label ?? ''}</span>
                </div>
                {providers.active === 'rest' ? (
                  <ul className='space-y-1'>
                    <li>网关地址：{providers.base_url_configured ? '已配置' : '未配置（拨号会失败）'}</li>
                    <li>坐席号码（双呼）：{providers.agent_phone_configured ? '已配置' : '未配置'}</li>
                    <li>回调超时：{providers.timeout_seconds} 秒</li>
                    <li className='break-all'>回调地址：{providers.callback_path}</li>
                  </ul>
                ) : (
                  <p>模拟线路不拨真实电话，状态在本地按计划推进。要打真实电话，看 docs/telephony.md 配成 rest。</p>
                )}
              </div>
            ) : (
              <Loading />
            )}
          </Card>

          <Card title='合规提示'>
            {compliance ? (
              <ul className='space-y-2 text-xs text-slate-400'>
                <li>免打扰时段：{compliance.dnd_start} – {compliance.dnd_end}</li>
                <li>每日拨打上限：{compliance.daily_limit} 通</li>
                <li>单号码每日上限：{compliance.per_number_daily_limit} 次</li>
                <li>号码脱敏：{compliance.mask_phone ? '开启（全号见通话详情）' : '关闭'}</li>
                <li className='text-slate-500'>
                  当前设置来源：{compliance.source === 'runtime' ? '运行时覆盖' : '环境变量'}
                </li>
              </ul>
            ) : (
              <Loading />
            )}
          </Card>

          <Card title='我的实时事件' extra={<span>{props.events.length}</span>}>
            <Table
              columns={eventColumns}
              rows={props.events.slice(0, 8)}
              rowKey={(row, index) => String(row.at ?? index) + String(index)}
              empty='暂无事件'
            />
          </Card>

          <Card title='今日节奏'>
            <div className='grid grid-cols-2 gap-3'>
              <Stat label='当前计时' value={duration(seconds)} />
              <Stat label='可呼' value={board?.due ?? 0} hint={cooling > 0 ? '冷却 ' + String(cooling) + ' 条' : undefined} />
            </div>
          </Card>
        </div>
      </div>

      <Modal
        open={!!completing}
        title='填写通话结果'
        onClose={() => setCompleting(null)}
        footer={
          <>
            <Button onClick={() => setCompleting(null)}>稍后</Button>
            <Button variant='primary' disabled={busy} onClick={() => void submitResult()}>
              提交结果
            </Button>
          </>
        }
      >
        {completing && (
          <Note tone='info'>
            {completing.phone_masked} · {completing.state_label} · 通话 {duration(completing.talk_sec)}
            {!completing.list_item_id && ' · 手动拨号（不回写 CRM）'}
          </Note>
        )}
        <Field label='结果（必填）'>
          <Select value={resultCode} onChange={setResultCode} options={resultOptions} />
        </Field>
        <Field label='意向等级（留空按结果码默认）'>
          <Select
            value={intent}
            onChange={setIntent}
            options={props.meta.intent_levels}
            emptyLabel='按结果码自动判定'
          />
        </Field>
        <Field
          label='跟进备注'
          hint={completing?.list_item_id ? '有 CRM 归属时会作为 notes 回写' : '手动拨号不会回写 CRM，备注只留在这里'}
        >
          <TextArea value={note} onChange={setNote} placeholder='客户关心什么、下一步做什么…' />
        </Field>
        <div className='grid grid-cols-2 gap-3'>
          <Field label='生成跟进任务'>
            <TextInput value={followup} onChange={setFollowup} placeholder='例如：周五前发报价单' />
          </Field>
          <Field label='优先级'>
            <Select value={followupPriority} onChange={setFollowupPriority} options={props.meta.priorities} />
          </Field>
        </div>
      </Modal>
    </div>
  );
}