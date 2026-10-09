'''存储适配器：sqlite（默认）与 postgres 共用同一套表定义与读写辅助。

这一层只做「表 → 字典」的搬运与条件拼装，业务规则一律留在 services 里。
'''

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.adapters.tables import metadata
from app.core.clock import now_iso


def build_engine(settings: Any) -> Engine:
    url = settings.sqlalchemy_url
    kwargs: dict[str, Any] = {'future': True}
    if url.startswith('sqlite'):
        kwargs['connect_args'] = {'check_same_thread': False}
        if ':memory:' in url:
            kwargs['poolclass'] = sa.pool.StaticPool
        else:
            path = Path(settings.sqlite_path)
            if path.parent and str(path.parent) not in ('', '.'):
                path.parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(url, **kwargs)
    if url.startswith('sqlite'):
        _install_sqlite_pragmas(engine)
    return engine


def _install_sqlite_pragmas(engine: Engine) -> None:
    '''WAL + busy_timeout：后台节拍任务与请求线程同时写库时不至于互相锁死。'''

    @sa.event.listens_for(engine, 'connect')
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA busy_timeout=5000')
            cursor.execute('PRAGMA synchronous=NORMAL')
        finally:
            cursor.close()


class Store:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ---- 表管理 ----
    def create_all(self) -> None:
        metadata.create_all(self.engine)

    def drop_all(self) -> None:
        metadata.drop_all(self.engine)

    # ---- 写 ----
    def insert(self, table: sa.Table, values: dict) -> dict:
        row = dict(values)
        stamp = now_iso()
        if 'created_at' in table.c and not row.get('created_at'):
            row['created_at'] = stamp
        if 'updated_at' in table.c and not row.get('updated_at'):
            row['updated_at'] = stamp
        with self.engine.begin() as conn:
            conn.execute(sa.insert(table).values(**row))
        return row

    def insert_many(self, table: sa.Table, rows: Sequence[dict], chunk_size: int = 400) -> int:
        if not rows:
            return 0
        stamp = now_iso()
        prepared: list[dict] = []
        for raw in rows:
            row = dict(raw)
            if 'created_at' in table.c and not row.get('created_at'):
                row['created_at'] = stamp
            if 'updated_at' in table.c and not row.get('updated_at'):
                row['updated_at'] = stamp
            prepared.append(row)
        total = 0
        with self.engine.begin() as conn:
            for start in range(0, len(prepared), chunk_size):
                chunk = prepared[start : start + chunk_size]
                conn.execute(sa.insert(table), chunk)
                total += len(chunk)
        return total

    def update(self, table: sa.Table, pk: str, values: dict) -> dict | None:
        row = dict(values)
        if 'updated_at' in table.c:
            row['updated_at'] = now_iso()
        row.pop('id', None)
        with self.engine.begin() as conn:
            conn.execute(sa.update(table).where(table.c.id == pk).values(**row))
        return self.get(table, pk)

    def update_where(self, table: sa.Table, conditions: Iterable[Any], values: dict) -> int:
        row = dict(values)
        if 'updated_at' in table.c:
            row['updated_at'] = now_iso()
        with self.engine.begin() as conn:
            result = conn.execute(sa.update(table).where(*list(conditions)).values(**row))
        return int(result.rowcount or 0)

    def delete(self, table: sa.Table, pk: str) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(sa.delete(table).where(table.c.id == pk))
        return int(result.rowcount or 0)

    def delete_where(self, table: sa.Table, conditions: Iterable[Any]) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(sa.delete(table).where(*list(conditions)))
        return int(result.rowcount or 0)

    # ---- 读 ----
    def get(self, table: sa.Table, pk: str) -> dict | None:
        return self.find_one(table, **{'id': pk})

    def find_one(
        self, table: sa.Table, *conditions: Any, filters: dict | None = None, **kwargs: Any
    ) -> dict | None:
        stmt = (
            sa.select(table)
            .where(*list(conditions), *_conditions(table, _merge(filters, kwargs)))
            .limit(1)
        )
        rows = self.raw(stmt)
        return rows[0] if rows else None

    def count(
        self, table: sa.Table, *conditions: Any, filters: dict | None = None, **kwargs: Any
    ) -> int:
        stmt = sa.select(sa.func.count()).select_from(table).where(
            *list(conditions), *_conditions(table, _merge(filters, kwargs))
        )
        with self.engine.connect() as conn:
            return int(conn.execute(stmt).scalar() or 0)

    def select(
        self,
        table: sa.Table,
        *conditions: Any,
        filters: dict | None = None,
        order_by: str | None = None,
        desc: bool = True,
        limit: int | None = None,
        offset: int = 0,
        search: str | None = None,
        search_fields: Sequence[str] = (),
    ) -> list[dict]:
        stmt = sa.select(table).where(*list(conditions), *_conditions(table, filters or {}))
        if search and search_fields:
            pattern = '%' + str(search).strip() + '%'
            stmt = stmt.where(sa.or_(*[table.c[name].like(pattern) for name in search_fields]))
        if order_by and order_by in table.c:
            column = table.c[order_by]
            stmt = stmt.order_by(sa.desc(column) if desc else sa.asc(column))
        if limit is not None:
            stmt = stmt.limit(int(limit)).offset(int(offset or 0))
        return self.raw(stmt)

    def raw(self, stmt: Any) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(row._mapping) for row in conn.execute(stmt).all()]

    def one(self, stmt: Any) -> dict | None:
        rows = self.raw(stmt)
        return rows[0] if rows else None

    def scalar(self, stmt: Any) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar()

    def transaction(self) -> Any:
        return self.engine.begin()


def _merge(filters: dict | None, kwargs: dict) -> dict:
    merged = dict(filters or {})
    merged.update(kwargs or {})
    return merged


def _conditions(table: sa.Table, filters: dict) -> list[Any]:
    out: list[Any] = []
    for key, value in filters.items():
        if key not in table.c:
            raise KeyError('表 ' + table.name + ' 没有字段 ' + str(key))
        column = table.c[key]
        if value is None:
            out.append(column.is_(None))
        elif isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)
            out.append(column.in_(items) if items else sa.false())
        else:
            out.append(column == value)
    return out