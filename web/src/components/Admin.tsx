// 组织管理：用户与团队。仅管理员可写。
import { useCallback, useEffect, useState } from 'react';

import { ApiError, request } from '../lib/api';
import { stamp } from '../lib/format';
import type { Meta, Team, User } from '../lib/types';
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Field,
  Modal,
  Note,
  Select,
  Table,
  TextInput,
  type Column,
} from './ui';

export default function Admin(props: { token: string; meta: Meta; canManage: boolean }) {
  const [users, setUsers] = useState<User[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [creatingTeam, setCreatingTeam] = useState(false);
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'agent', team_id: '' });
  const [teamForm, setTeamForm] = useState({ name: '', note: '' });

  const load = useCallback(async () => {
    try {
      const list = await request<{ data: User[] }>('/api/v1/users', { token: props.token });
      setUsers(list.data);
      const teamList = await request<{ data: Team[] }>('/api/v1/teams', { token: props.token });
      setTeams(teamList.data);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    }
  }, [props.token]);

  useEffect(() => {
    void load();
  }, [load]);

  const createUser = async () => {
    setBusy(true);
    setError(null);
    try {
      await request('/api/v1/users', {
        method: 'POST',
        token: props.token,
        body: {
          name: form.name,
          email: form.email,
          password: form.password,
          role: form.role,
          team_id: form.team_id || undefined,
        },
      });
      setCreating(false);
      setForm({ name: '', email: '', password: '', role: 'agent', team_id: '' });
      setNote('用户已创建');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const createTeam = async () => {
    setBusy(true);
    try {
      await request('/api/v1/teams', { method: 'POST', token: props.token, body: teamForm });
      setCreatingTeam(false);
      setTeamForm({ name: '', note: '' });
      setNote('团队已创建');
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (user: User) => {
    setBusy(true);
    try {
      await request('/api/v1/users/' + user.id, {
        method: 'PATCH',
        token: props.token,
        body: { is_active: !user.is_active },
      });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const userColumns: Column<User>[] = [
    { key: 'name', label: '姓名', render: (row) => row.name ?? '—' },
    { key: 'email', label: '邮箱' },
    { key: 'role', label: '角色', width: '100px', render: (row) => props.meta.roles.find((item) => item.value === row.role)?.label ?? row.role },
    { key: 'team_id', label: '团队', width: '160px', render: (row) => teams.find((team) => team.id === row.team_id)?.name ?? row.team_id ?? '—' },
    { key: 'is_active', label: '状态', width: '90px', render: (row) => <Badge tone={row.is_active ? 'good' : 'bad'}>{row.is_active ? '启用' : '停用'}</Badge> },
    {
      key: 'ops',
      label: '操作',
      width: '100px',
      render: (row) => (
        <Button size='sm' disabled={busy || !props.canManage} onClick={() => void toggleActive(row)}>
          {row.is_active ? '停用' : '启用'}
        </Button>
      ),
    },
  ];

  const teamColumns: Column<Team & { created_at?: string }>[] = [
    { key: 'name', label: '团队' },
    { key: 'note', label: '备注', render: (row) => row.note ?? '—' },
    {
      key: 'members',
      label: '成员数',
      width: '90px',
      align: 'right',
      render: (row) => String(users.filter((user) => user.team_id === row.id).length),
    },
    { key: 'created_at', label: '创建时间', width: '150px', render: (row) => (row.created_at ? stamp(row.created_at) : '—') },
  ];

  return (
    <div className='space-y-4'>
      <ErrorNote message={error} />
      {note && <Note tone='good'>{note}</Note>}
      {!props.canManage && <Note tone='warn'>只有管理员可以新增用户与团队。</Note>}

      <Card
        title='用户'
        extra={
          <>
            <Badge>{users.length} 人</Badge>
            <Button size='sm' variant='primary' disabled={!props.canManage} onClick={() => setCreating(true)}>
              新增用户
            </Button>
          </>
        }
      >
        <Table columns={userColumns} rows={users} rowKey={(row) => row.id} empty='没有用户' />
      </Card>

      <Card
        title='团队'
        extra={
          <>
            <Badge>{teams.length} 个</Badge>
            <Button size='sm' variant='primary' disabled={!props.canManage} onClick={() => setCreatingTeam(true)}>
              新增团队
            </Button>
          </>
        }
      >
        <Table columns={teamColumns} rows={teams} rowKey={(row) => row.id} empty='没有团队' />
      </Card>

      <Modal open={creating} title='新增用户' onClose={() => setCreating(false)}>
        <Field label='姓名'>
          <TextInput value={form.name} onChange={(value) => setForm({ ...form, name: value })} />
        </Field>
        <Field label='邮箱（登录名）'>
          <TextInput value={form.email} onChange={(value) => setForm({ ...form, email: value })} />
        </Field>
        <Field label='初始密码' hint='至少 8 位'>
          <TextInput value={form.password} onChange={(value) => setForm({ ...form, password: value })} type='password' />
        </Field>
        <div className='grid grid-cols-2 gap-3'>
          <Field label='角色'>
            <Select value={form.role} onChange={(value) => setForm({ ...form, role: value })} options={props.meta.roles} />
          </Field>
          <Field label='团队'>
            <Select
              value={form.team_id}
              onChange={(value) => setForm({ ...form, team_id: value })}
              options={teams.map((team) => ({ value: team.id, label: team.name }))}
              emptyLabel='默认团队'
            />
          </Field>
        </div>
        <Button variant='primary' disabled={busy || !form.email || form.password.length < 8} onClick={() => void createUser()}>
          创建
        </Button>
      </Modal>

      <Modal open={creatingTeam} title='新增团队' onClose={() => setCreatingTeam(false)}>
        <Field label='团队名称'>
          <TextInput value={teamForm.name} onChange={(value) => setTeamForm({ ...teamForm, name: value })} />
        </Field>
        <Field label='备注'>
          <TextInput value={teamForm.note} onChange={(value) => setTeamForm({ ...teamForm, note: value })} />
        </Field>
        <Button variant='primary' disabled={busy || !teamForm.name} onClick={() => void createTeam()}>
          创建
        </Button>
      </Modal>
    </div>
  );
}