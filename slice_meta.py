"""Helpers for data slice freshness display."""

from __future__ import annotations

from typing import Any

from comtrade_meta import reporter_label
from config import FLOW_LABELS, FREQ_LABELS, MONTH_LABELS
from storage import EMPTY_SLICE_TTL_DAYS, TradeStorage

STATUS_LABELS: dict[str, str] = {
    "ok": "有数据",
    "empty": "官网暂无",
    "error": "同步失败",
}


def month_label(month: int) -> str:
    if month <= 0:
        return ""
    return MONTH_LABELS.get(month, str(month))


def period_label(freq_code: str, year: int, month: int) -> str:
    if freq_code == "M" and month:
        return f"{month_label(month)} {year}"
    return str(year)


def slice_freshness(status: str, fetched_at: str | None) -> dict[str, Any]:
    if status == "ok":
        return {
            "freshness": "fresh",
            "freshness_label": "本地有效",
            "retryable": False,
            "ttl_days": None,
        }

    ttl_days = EMPTY_SLICE_TTL_DAYS if status == "empty" else 1
    expired = (
        TradeStorage._is_slice_expired(fetched_at, ttl_days)
        if fetched_at
        else True
    )
    if status == "empty":
        label = "可重试" if expired else f"负缓存 {EMPTY_SLICE_TTL_DAYS} 天"
    else:
        label = "可重试" if expired else "失败缓存 1 天"
    return {
        "freshness": "retryable" if expired else "cached",
        "freshness_label": label,
        "retryable": expired,
        "ttl_days": ttl_days,
    }


def slice_cache_note(status: str, fetched_at: str | None) -> str:
    freshness = slice_freshness(status, fetched_at)
    if status == "ok":
        return "不会重复请求"
    if status == "empty":
        return (
            "可重试"
            if freshness["retryable"]
            else f"{EMPTY_SLICE_TTL_DAYS} 天内不重复请求"
        )
    return "可重试" if freshness["retryable"] else "1 天内不重复请求"


def slice_row_to_dict(row: Any) -> dict[str, Any]:
    freq_code = str(row["freq_code"] or "A")
    year = int(row["year"])
    month = int(row["month"] or 0)
    status = str(row["status"])
    fetched_at = row["fetched_at"]
    freshness = slice_freshness(status, fetched_at)
    return {
        "reporter_code": int(row["reporter_code"]),
        "reporter_label": reporter_label(int(row["reporter_code"])),
        "year": year,
        "month": month,
        "month_label": month_label(month),
        "period_label": period_label(freq_code, year, month),
        "freq_code": freq_code,
        "freq_label": FREQ_LABELS.get(freq_code, freq_code),
        "flow_code": row["flow_code"],
        "flow_label": FLOW_LABELS.get(row["flow_code"], row["flow_code"]),
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "record_count": int(row["record_count"] or 0),
        "fetched_at": fetched_at,
        "error_message": row["error_message"],
        "cache_note": slice_cache_note(status, fetched_at),
        **freshness,
    }
