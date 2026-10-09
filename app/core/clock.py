'''时间工具：全系统统一用带时区的 ISO 字符串，落库即字符串，跨 sqlite/postgres 都一致。'''

from __future__ import annotations

from datetime import date, datetime, timedelta

ISO_FORMAT = '%Y-%m-%dT%H:%M:%S'


def now() -> datetime:
    return datetime.now().astimezone()


def now_iso() -> str:
    return now().strftime(ISO_FORMAT) + _offset()


def to_iso(moment: datetime) -> str:
    local = moment.astimezone()
    return local.strftime(ISO_FORMAT) + _offset()


def _offset() -> str:
    raw = now().strftime('%z')
    return raw[:3] + ':' + raw[3:] if raw else '+08:00'


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone() if parsed.tzinfo else parsed


def today_str() -> str:
    return now().strftime('%Y-%m-%d')


def date_str(moment: datetime) -> str:
    return moment.strftime('%Y-%m-%d')


def minutes_of_day(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def shift_minutes(moment: datetime, minutes: int) -> datetime:
    return moment + timedelta(minutes=minutes)


def day_range(day: str) -> tuple[str, str]:
    '''给定 YYYY-MM-DD，返回当天的时间字符串闭区间端点，便于按前缀比较。'''
    return day + 'T00:00:00', day + 'T23:59:59'


def days_back(count: int) -> list[str]:
    today = date.today()
    return [(today - timedelta(days=offset)).strftime('%Y-%m-%d') for offset in range(count - 1, -1, -1)]


def in_window(moment_minutes: int, start_minutes: int, end_minutes: int) -> bool:
    '''判断当日分钟数是否落在 [start, end) 内；start > end 表示跨零点窗口。'''
    if start_minutes == end_minutes:
        return True
    if start_minutes < end_minutes:
        return start_minutes <= moment_minutes < end_minutes
    return moment_minutes >= start_minutes or moment_minutes < end_minutes