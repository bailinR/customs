"""SQLite persistence for trade records."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DB_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trade_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_code   INTEGER NOT NULL,
    partner_code    INTEGER NOT NULL,
    partner_name    TEXT,
    freq_code       TEXT NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER,
    flow_code       TEXT NOT NULL,
    cmd_code        TEXT NOT NULL DEFAULT 'TOTAL',
    trade_value_usd REAL,
    fob_value_usd   REAL,
    cif_value_usd   REAL,
    source          TEXT NOT NULL DEFAULT 'un_comtrade',
    fetched_at      TEXT NOT NULL,
    UNIQUE (
        reporter_code, partner_code, freq_code, year, month,
        flow_code, cmd_code, source
    )
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name        TEXT NOT NULL,
    reporter_code    INTEGER,
    year             INTEGER,
    flow_code        TEXT,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    records_fetched  INTEGER DEFAULT 0,
    records_upserted INTEGER DEFAULT 0,
    status           TEXT NOT NULL,
    error_message    TEXT
);

CREATE TABLE IF NOT EXISTS data_slices (
    reporter_code  INTEGER NOT NULL,
    year           INTEGER NOT NULL,
    month          INTEGER NOT NULL DEFAULT 0,
    flow_code      TEXT NOT NULL,
    freq_code      TEXT NOT NULL DEFAULT 'A',
    status         TEXT NOT NULL,
    record_count   INTEGER DEFAULT 0,
    fetched_at     TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'un_comtrade',
    error_message  TEXT,
    UNIQUE (reporter_code, year, month, flow_code, freq_code)
);
"""

EMPTY_SLICE_TTL_DAYS = 7


@dataclass
class TradeRecord:
    reporter_code: int
    partner_code: int
    partner_name: str | None
    freq_code: str
    year: int
    month: int  # 年度=0，月度=1-12
    flow_code: str
    cmd_code: str
    trade_value_usd: float | None
    fob_value_usd: float | None
    cif_value_usd: float | None
    source: str = "un_comtrade"
    fetched_at: str | None = None

    def as_tuple(self) -> tuple[Any, ...]:
        fetched_at = self.fetched_at or datetime.now(timezone.utc).isoformat()
        return (
            self.reporter_code,
            self.partner_code,
            self.partner_name,
            self.freq_code,
            self.year,
            self.month,
            self.flow_code,
            self.cmd_code,
            self.trade_value_usd,
            self.fob_value_usd,
            self.cif_value_usd,
            self.source,
            fetched_at,
        )


class TradeStorage:
    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def upsert_records(self, records: list[TradeRecord]) -> int:
        if not records:
            return 0
        sql = """
            INSERT INTO trade_records (
                reporter_code, partner_code, partner_name, freq_code, year, month,
                flow_code, cmd_code, trade_value_usd, fob_value_usd, cif_value_usd,
                source, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reporter_code, partner_code, freq_code, year, month,
                        flow_code, cmd_code, source)
            DO UPDATE SET
                partner_name    = excluded.partner_name,
                trade_value_usd = excluded.trade_value_usd,
                fob_value_usd   = excluded.fob_value_usd,
                cif_value_usd   = excluded.cif_value_usd,
                fetched_at      = excluded.fetched_at
        """
        with self._connect() as conn:
            conn.executemany(sql, [r.as_tuple() for r in records])
            return conn.total_changes

    def start_sync_log(
        self,
        task_name: str,
        reporter_code: int | None = None,
        year: int | None = None,
        flow_code: str | None = None,
    ) -> int:
        started_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO sync_logs (
                    task_name, reporter_code, year, flow_code,
                    started_at, status
                ) VALUES (?, ?, ?, ?, ?, 'running')
                """,
                (task_name, reporter_code, year, flow_code, started_at),
            )
            return int(cur.lastrowid)

    def finish_sync_log(
        self,
        log_id: int,
        *,
        records_fetched: int,
        records_upserted: int,
        status: str = "success",
        error_message: str | None = None,
    ) -> None:
        finished_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sync_logs SET
                    finished_at = ?, records_fetched = ?, records_upserted = ?,
                    status = ?, error_message = ?
                WHERE id = ?
                """,
                (
                    finished_at,
                    records_fetched,
                    records_upserted,
                    status,
                    error_message,
                    log_id,
                ),
            )

    def count_records(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM trade_records").fetchone()
            return int(row["c"])

    def get_slice(
        self,
        reporter_code: int,
        year: int,
        flow_code: str,
        *,
        freq_code: str = "A",
        month: int = 0,
    ) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM data_slices
                WHERE reporter_code = ? AND year = ? AND month = ?
                  AND flow_code = ? AND freq_code = ?
                """,
                (reporter_code, year, month, flow_code, freq_code),
            ).fetchone()

    def upsert_slice(
        self,
        *,
        reporter_code: int,
        year: int,
        flow_code: str,
        status: str,
        record_count: int = 0,
        fetched_at: str | None = None,
        freq_code: str = "A",
        month: int = 0,
        source: str = "un_comtrade",
        error_message: str | None = None,
    ) -> None:
        fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO data_slices (
                    reporter_code, year, month, flow_code, freq_code,
                    status, record_count, fetched_at, source, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reporter_code, year, month, flow_code, freq_code)
                DO UPDATE SET
                    status = excluded.status,
                    record_count = excluded.record_count,
                    fetched_at = excluded.fetched_at,
                    source = excluded.source,
                    error_message = excluded.error_message
                """,
                (
                    reporter_code,
                    year,
                    month,
                    flow_code,
                    freq_code,
                    status,
                    record_count,
                    fetched_at,
                    source,
                    error_message,
                ),
            )

    def slice_needs_fetch(
        self,
        reporter_code: int,
        year: int,
        flow_code: str,
        *,
        freq_code: str = "A",
        month: int = 0,
        force_refresh: bool = False,
        empty_ttl_days: int = EMPTY_SLICE_TTL_DAYS,
    ) -> bool:
        if force_refresh:
            return True
        row = self.get_slice(
            reporter_code, year, flow_code, freq_code=freq_code, month=month
        )
        if row is None:
            return True
        status = row["status"]
        if status == "ok":
            return False
        if status == "empty":
            return self._is_slice_expired(row["fetched_at"], empty_ttl_days)
        if status == "error":
            return self._is_slice_expired(row["fetched_at"], 1)
        return True

    def list_slice_statuses(
        self,
        reporter_code: int | None = None,
        year: int | None = None,
        freq_code: str | None = None,
        status: str | None = None,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[sqlite3.Row]:
        conditions, params = self._slice_filter_params(
            reporter_code=reporter_code,
            year=year,
            freq_code=freq_code,
            status=status,
        )
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT reporter_code, year, month, flow_code, freq_code,
                   status, record_count, fetched_at, error_message
            FROM data_slices
            {where_sql}
            ORDER BY fetched_at DESC, year DESC, month DESC, reporter_code, flow_code
        """
        query_params = list(params)
        if limit is not None:
            sql += " LIMIT ?"
            query_params.append(limit)
        if offset is not None:
            sql += " OFFSET ?"
            query_params.append(offset)
        with self._connect() as conn:
            return conn.execute(sql, query_params).fetchall()

    def count_slices(
        self,
        reporter_code: int | None = None,
        year: int | None = None,
        freq_code: str | None = None,
        status: str | None = None,
    ) -> int:
        conditions, params = self._slice_filter_params(
            reporter_code=reporter_code,
            year=year,
            freq_code=freq_code,
            status=status,
        )
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            return int(
                conn.execute(
                    f"SELECT COUNT(*) AS c FROM data_slices {where_sql}",
                    params,
                ).fetchone()["c"]
            )

    def summarize_slices(
        self,
        reporter_code: int | None = None,
        year: int | None = None,
        freq_code: str | None = None,
        status: str | None = None,
    ) -> dict[str, int]:
        conditions, params = self._slice_filter_params(
            reporter_code=reporter_code,
            year=year,
            freq_code=freq_code,
            status=status,
        )
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT status, COUNT(*) AS c
                FROM data_slices
                {where_sql}
                GROUP BY status
                """,
                params,
            ).fetchall()
        summary = {"total": 0, "ok": 0, "empty": 0, "error": 0}
        for row in rows:
            count = int(row["c"])
            summary["total"] += count
            key = str(row["status"])
            if key in summary:
                summary[key] = count
        return summary

    @staticmethod
    def _slice_filter_params(
        *,
        reporter_code: int | None,
        year: int | None,
        freq_code: str | None,
        status: str | None,
    ) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if reporter_code is not None:
            conditions.append("reporter_code = ?")
            params.append(reporter_code)
        if year is not None:
            conditions.append("year = ?")
            params.append(year)
        if freq_code is not None:
            conditions.append("freq_code = ?")
            params.append(freq_code)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        return conditions, params

    @staticmethod
    def _is_slice_expired(fetched_at: str, ttl_days: int) -> bool:
        try:
            fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - fetched
        return age.days >= ttl_days
