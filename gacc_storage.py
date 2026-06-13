"""SQLite persistence for GACC query jobs and records."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DB_PATH
from gacc_models import GaccJobStatus, GaccQueryParams, GaccRecord, format_gacc_period

GACC_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS gacc_query_jobs (
    id              TEXT PRIMARY KEY,
    params_json     TEXT NOT NULL,
    status          TEXT NOT NULL,
    message         TEXT,
    record_count    INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS gacc_trade_records (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL,
    flow_type        TEXT NOT NULL,
    currency         TEXT NOT NULL,
    year             INTEGER NOT NULL,
    month            INTEGER NOT NULL DEFAULT 0,
    month_start      INTEGER NOT NULL DEFAULT 0,
    month_end        INTEGER NOT NULL DEFAULT 0,
    hs_code          TEXT,
    hs_name          TEXT,
    partner_code     TEXT,
    partner_name     TEXT,
    trade_mode_code  TEXT,
    trade_mode_name  TEXT,
    reg_place_code   TEXT,
    reg_place_name   TEXT,
    qty1             REAL,
    unit1            TEXT,
    qty2             REAL,
    unit2            TEXT,
    value            REAL NOT NULL,
    fetched_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gacc_records_job ON gacc_trade_records(job_id);
CREATE INDEX IF NOT EXISTS idx_gacc_records_period ON gacc_trade_records(
    year, month, flow_type, currency
);
"""


class GaccStorage:
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
            conn.executescript(GACC_SCHEMA_SQL)
            self._migrate_gacc_records(conn)

    @staticmethod
    def _migrate_gacc_records(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(gacc_trade_records)")}
        if "month_start" not in cols:
            conn.execute(
                "ALTER TABLE gacc_trade_records ADD COLUMN month_start INTEGER NOT NULL DEFAULT 0"
            )
        if "month_end" not in cols:
            conn.execute(
                "ALTER TABLE gacc_trade_records ADD COLUMN month_end INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            """
            UPDATE gacc_trade_records
            SET month_start = month, month_end = month
            WHERE month > 0 AND (month_start = 0 OR month_start IS NULL)
            """
        )

    def create_job(self, params: GaccQueryParams, job_id: str | None = None) -> str:
        job_id = job_id or uuid.uuid4().hex[:12]
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gacc_query_jobs (
                    id, params_json, status, message, created_at
                ) VALUES (?, ?, 'pending', '任务已创建', ?)
                """,
                (job_id, json.dumps(params.to_dict(), ensure_ascii=False), created_at),
            )
        return job_id

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        message: str | None = None,
        record_count: int | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if message is not None:
            fields.append("message = ?")
            params.append(message)
        if record_count is not None:
            fields.append("record_count = ?")
            params.append(record_count)
        if error_message is not None:
            fields.append("error_message = ?")
            params.append(error_message)
        if finished:
            fields.append("finished_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
        if not fields:
            return
        params.append(job_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE gacc_query_jobs SET {', '.join(fields)} WHERE id = ?",
                params,
            )

    def get_job(self, job_id: str) -> GaccJobStatus | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gacc_query_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def list_jobs(self, *, limit: int = 20) -> list[GaccJobStatus]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gacc_query_jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def insert_records(self, records: list[GaccRecord]) -> int:
        if not records:
            return 0
        sql = """
            INSERT INTO gacc_trade_records (
                job_id, flow_type, currency, year, month, month_start, month_end,
                hs_code, hs_name, partner_code, partner_name,
                trade_mode_code, trade_mode_name,
                reg_place_code, reg_place_name,
                qty1, unit1, qty2, unit2, value, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM gacc_trade_records WHERE job_id = ?", (records[0].job_id,))
            conn.executemany(sql, [r.as_tuple() for r in records])
            return conn.total_changes

    def count_records(self, job_id: str | None = None) -> int:
        with self._connect() as conn:
            if job_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM gacc_trade_records WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM gacc_trade_records").fetchone()
            return int(row["c"])

    def fetch_records(
        self,
        *,
        job_id: str | None = None,
        flow_type: str | None = None,
        currency: str | None = None,
        year: int | None = None,
        month: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[sqlite3.Row], int]:
        conditions: list[str] = []
        params: list[Any] = []
        if job_id:
            conditions.append("job_id = ?")
            params.append(job_id)
        if flow_type:
            conditions.append("flow_type = ?")
            params.append(flow_type)
        if currency:
            conditions.append("currency = ?")
            params.append(currency)
        if year is not None:
            conditions.append("year = ?")
            params.append(year)
        if month is not None:
            conditions.append(
                "(month = ? OR (month = 0 AND month_start <= ? AND month_end >= ?))"
            )
            params.extend([month, month, month])
        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size
        with self._connect() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) AS c FROM gacc_trade_records {where_sql}",
                    params,
                ).fetchone()["c"]
            )
            rows = conn.execute(
                f"""
                SELECT * FROM gacc_trade_records
                {where_sql}
                ORDER BY value DESC, id
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        return rows, total

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> GaccJobStatus:
        params = json.loads(row["params_json"])
        return GaccJobStatus(
            id=row["id"],
            status=row["status"],
            message=row["message"] or "",
            record_count=int(row["record_count"] or 0),
            error_message=row["error_message"],
            params=params,
            created_at=row["created_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def params_from_job(job: GaccJobStatus) -> GaccQueryParams:
        return GaccQueryParams.from_dict(job.params)

    def row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        from gacc_models import CURRENCY_LABELS, FLOW_LABELS

        d = dict(row)
        d["flow_label"] = FLOW_LABELS.get(d.get("flow_type"), d.get("flow_type"))
        d["currency_label"] = CURRENCY_LABELS.get(d.get("currency"), d.get("currency"))
        d["period_label"] = format_gacc_period(
            year=int(d.get("year") or 0),
            month=int(d.get("month") or 0),
            month_start=int(d.get("month_start") or 0),
            month_end=int(d.get("month_end") or 0),
        )
        d["value_label"] = d["currency_label"]
        return d
