"""Shared trade list query builders."""

from __future__ import annotations

import sqlite3
from typing import Any

TRADE_SELECT = """
    SELECT
        id, reporter_code, partner_code, partner_name,
        freq_code, year, month, flow_code, cmd_code,
        trade_value_usd, fob_value_usd, cif_value_usd,
        source, fetched_at
    FROM trade_records
"""


def build_trade_conditions(
    *,
    reporter_code: int | None = None,
    year: int | None = None,
    month: int | None = None,
    freq_code: str = "A",
    flow_code: str | None = None,
    partner_name: str | None = None,
    partner_scope: str = "countries",
) -> tuple[list[str], list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if freq_code == "M":
        conditions.append("freq_code = 'M'")
        conditions.append("month > 0")
        if month is not None:
            conditions.append("month = ?")
            params.append(month)
    else:
        conditions.append("freq_code = 'A'")
        conditions.append("month = 0")

    if reporter_code is not None:
        conditions.append("reporter_code = ?")
        params.append(reporter_code)
    if year is not None:
        conditions.append("year = ?")
        params.append(year)
    if flow_code is not None:
        conditions.append("flow_code = ?")
        params.append(flow_code)
    if partner_scope == "total":
        conditions.append("partner_code = 0")
    else:
        conditions.append("partner_code != 0")
    if partner_name and partner_scope != "total":
        conditions.append("partner_name LIKE ?")
        params.append(f"%{partner_name}%")

    return conditions, params


def trade_order_sql(*, partner_scope: str = "countries") -> str:
    if partner_scope == "total":
        return "year DESC, month DESC, reporter_code, flow_code"
    return (
        "(trade_value_usd IS NULL), trade_value_usd DESC, "
        "year DESC, month DESC, reporter_code"
    )


def count_trade_rows(
    conn: sqlite3.Connection,
    conditions: list[str],
    params: list[Any],
) -> int:
    where_sql = " AND ".join(conditions)
    return int(
        conn.execute(
            f"SELECT COUNT(*) AS c FROM trade_records WHERE {where_sql}",
            params,
        ).fetchone()["c"]
    )


def fetch_trade_rows(
    conn: sqlite3.Connection,
    conditions: list[str],
    params: list[Any],
    *,
    partner_scope: str = "countries",
    limit: int | None = None,
    offset: int | None = None,
) -> list[sqlite3.Row]:
    where_sql = " AND ".join(conditions)
    order_sql = trade_order_sql(partner_scope=partner_scope)
    sql = f"{TRADE_SELECT} WHERE {where_sql} ORDER BY {order_sql}"
    query_params = list(params)
    if limit is not None:
        sql += " LIMIT ?"
        query_params.append(limit)
    if offset is not None:
        sql += " OFFSET ?"
        query_params.append(offset)
    return conn.execute(sql, query_params).fetchall()
