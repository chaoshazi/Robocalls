// 统一的接口调用层：令牌注入、错误归一化、SSE 读取。
import type { StreamEvent } from './types';

const IDENTITY_KEY = 'wahu.identity';
const API_BASE_KEY = 'wahu.apiBase';

export interface StoredIdentity {
  token: string;
  user: { id: string; name: string | null; email: string | null; role: string; team_id: string | null };
}

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function loadIdentity(): StoredIdentity | null {
  const raw = window.localStorage.getItem(IDENTITY_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as StoredIdentity;
    return parsed && parsed.token ? parsed : null;
  } catch {
    return null;
  }
}

export function saveIdentity(value: StoredIdentity): void {
  window.localStorage.setItem(IDENTITY_KEY, JSON.stringify(value));
}

export function clearIdentity(): void {
  window.localStorage.removeItem(IDENTITY_KEY);
}

export function apiBase(): string {
  return window.localStorage.getItem(API_BASE_KEY) ?? '';
}

export function setApiBase(value: string): void {
  const trimmed = value.trim().replace(/\/$/, '');
  if (trimmed) {
    window.localStorage.setItem(API_BASE_KEY, trimmed);
  } else {
    window.localStorage.removeItem(API_BASE_KEY);
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
  form?: FormData;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.token) headers.Authorization = 'Bearer ' + options.token;
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }
  let response: Response;
  try {
    response = await fetch(apiBase() + path, {
      method: options.method ?? 'GET',
      headers,
      body,
    });
  } catch (error) {
    throw new ApiError('无法连接后端（' + String(error) + '）', 0, 'network_error');
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : '请求失败（HTTP ' + String(response.status) + '）';
    const code =
      payload && typeof payload === 'object' && 'code' in payload
        ? String((payload as { code: unknown }).code)
        : 'http_error';
    throw new ApiError(detail, response.status, code);
  }
  return payload as T;
}

export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? '?' + text : '';
}

export interface StreamHandle {
  close: () => void;
}

// 浏览器原生 EventSource 不能带 Authorization 头，这里用 fetch + ReadableStream 自己解帧。
export function openStream(
  token: string,
  onEvent: (event: StreamEvent) => void,
  onStatus: (state: 'open' | 'closed' | 'error') => void,
): StreamHandle {
  const controller = new AbortController();
  let closed = false;

  const run = async () => {
    try {
      const response = await fetch(apiBase() + '/api/v1/stream', {
        headers: { Authorization: 'Bearer ' + token, Accept: 'text/event-stream' },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        throw new ApiError('SSE 连接失败', response.status, 'stream_failed');
      }
      onStatus('open');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';
        frames.forEach((frame) => {
          const line = frame.split('\n').find((item) => item.startsWith('data:'));
          if (!line) return;
          try {
            onEvent(JSON.parse(line.slice(5).trim()) as StreamEvent);
          } catch {
            // 坏帧直接忽略，不要打断整条流
          }
        });
      }
      if (!closed) onStatus('closed');
    } catch (error) {
      if (!closed) onStatus('error');
      void error;
    }
  };

  void run();
  return {
    close: () => {
      closed = true;
      controller.abort();
    },
  };
}