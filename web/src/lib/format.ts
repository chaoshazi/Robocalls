// 展示格式化：时间、时长、百分比、标签。
const pad = (value: number): string => String(value).padStart(2, '0');

export function clock(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
}

export function stamp(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return (
    date.getFullYear() +
    '-' +
    pad(date.getMonth() + 1) +
    '-' +
    pad(date.getDate()) +
    ' ' +
    clock(value)
  );
}

export function day(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
}

export function duration(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const minute = Math.floor(total / 60);
  const rest = total % 60;
  if (minute === 0) return String(rest) + '秒';
  return String(minute) + '分' + String(rest).padStart(2, '0') + '秒';
}

export function percent(value: number | null | undefined): string {
  return (Math.max(0, Number(value) || 0) * 100).toFixed(1) + '%';
}

export function summarize(content: unknown): string {
  if (content === null || content === undefined) return '';
  if (typeof content === 'string') return content;
  if (typeof content === 'number' || typeof content === 'boolean') return String(content);
  try {
    return JSON.stringify(content);
  } catch {
    return String(content);
  }
}

export function localTimeInput(date = new Date()): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}