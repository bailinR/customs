"""On-demand slice sync from UN Comtrade into SQLite."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv

from comtrade_client import (
    api_rows_to_records,
    fetch_annual_by_partners,
    fetch_monthly_by_partners,
)
from config import FLOW_LABELS, MONTH_LABELS
from storage import TradeStorage

load_dotenv()


@dataclass
class SliceSyncResult:
    reporter_code: int
    year: int
    flow_code: str
    freq_code: str
    month: int
    status: str
    record_count: int
    records_upserted: int
    cached: bool
    fetched_at: str | None
    message: str
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reporter_code": self.reporter_code,
            "year": self.year,
            "flow_code": self.flow_code,
            "freq_code": self.freq_code,
            "month": self.month,
            "status": self.status,
            "record_count": self.record_count,
            "records_upserted": self.records_upserted,
            "cached": self.cached,
            "fetched_at": self.fetched_at,
            "message": self.message,
            "error_message": self.error_message,
        }


def _get_api_key() -> str:
    api_key = os.environ.get("COMTRADE_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 COMTRADE_API_KEY，请在 .env 中设置")
    return api_key


def _period_label(freq_code: str, year: int, month: int) -> str:
    if freq_code == "M" and month:
        name = MONTH_LABELS.get(month, str(month))
        return f"{name} {year}"
    return str(year)


def _slice_step_label(
    *,
    freq_code: str,
    year: int,
    month: int,
    flow_code: str,
) -> str:
    period = _period_label(freq_code, year, month)
    flow = FLOW_LABELS.get(flow_code, flow_code)
    return f"{period} · {flow}"


def build_sync_plan(
    *,
    flow_code: str | None,
    freq_code: str,
    month: int,
) -> list[tuple[int, str]]:
    flows = [flow_code] if flow_code else list(FLOW_LABELS.keys())
    slice_month = month if freq_code == "M" else 0
    if freq_code == "M" and slice_month == 0:
        months_to_sync = list(range(12, 0, -1))
    elif freq_code == "M":
        months_to_sync = [slice_month]
    else:
        months_to_sync = [0]
    return [(m, fc) for m in months_to_sync for fc in flows]


def _summarize_slice_results(
    slice_results: list[SliceSyncResult],
    *,
    freq_code: str,
    slice_month: int,
) -> dict[str, Any]:
    total_records = sum(r.record_count for r in slice_results)
    total_upserted = sum(r.records_upserted for r in slice_results)
    all_cached = all(r.cached for r in slice_results)
    has_error = any(r.status == "error" for r in slice_results)
    all_empty = all(r.status == "empty" for r in slice_results)
    has_ok = any(r.status == "ok" for r in slice_results)

    if has_error:
        overall_status = "error"
        message = "部分切片同步失败"
    elif has_ok:
        overall_status = "ok"
        message = f"同步完成，共 {total_records} 条记录"
    elif all_empty:
        overall_status = "empty"
        message = "官网暂无该组合数据（已记录，短期内不会重复请求）"
    else:
        overall_status = "ok"
        message = "同步完成"

    return {
        "status": overall_status,
        "message": message,
        "record_count": total_records,
        "records_upserted": total_upserted,
        "cached": all_cached,
        "freq_code": freq_code,
        "month": slice_month,
        "slices": [r.as_dict() for r in slice_results],
    }


def _cached_result(
    storage: TradeStorage,
    reporter_code: int,
    year: int,
    flow_code: str,
    freq_code: str,
    month: int,
) -> SliceSyncResult:
    row = storage.get_slice(
        reporter_code, year, flow_code, freq_code=freq_code, month=month
    )
    if row is None:
        raise RuntimeError("切片缓存不存在")
    status = row["status"]
    label = _period_label(freq_code, year, month)
    if status == "empty":
        message = f"官网暂无该国家 {label} 该流向数据（已缓存，短期内不会重复请求）"
    elif status == "ok":
        message = f"本地已有 {row['record_count']} 条记录"
    else:
        message = row["error_message"] or "上次同步失败"
    return SliceSyncResult(
        reporter_code=reporter_code,
        year=year,
        flow_code=flow_code,
        freq_code=freq_code,
        month=month,
        status=status,
        record_count=int(row["record_count"] or 0),
        records_upserted=0,
        cached=True,
        fetched_at=row["fetched_at"],
        message=message,
        error_message=row["error_message"],
    )


def sync_one_slice(
    storage: TradeStorage,
    client: httpx.Client,
    api_key: str,
    *,
    reporter_code: int,
    year: int,
    flow_code: str,
    freq_code: str = "A",
    month: int = 0,
    force_refresh: bool = False,
) -> SliceSyncResult:
    if not storage.slice_needs_fetch(
        reporter_code,
        year,
        flow_code,
        freq_code=freq_code,
        month=month,
        force_refresh=force_refresh,
    ):
        return _cached_result(
            storage, reporter_code, year, flow_code, freq_code, month
        )

    log_id = storage.start_sync_log(
        "sync_slice",
        reporter_code=reporter_code,
        year=year,
        flow_code=flow_code,
    )
    label = _period_label(freq_code, year, month)
    try:
        if freq_code == "M":
            if month < 1 or month > 12:
                raise ValueError("月度同步需要有效月份 (1-12)")
            rows = fetch_monthly_by_partners(
                client,
                reporter_code=str(reporter_code),
                year=year,
                month=month,
                flow_code=flow_code,
                api_key=api_key,
            )
        else:
            rows = fetch_annual_by_partners(
                client,
                reporter_code=str(reporter_code),
                year=str(year),
                flow_code=flow_code,
                api_key=api_key,
            )
        records = api_rows_to_records(rows, freq_code=freq_code)
        upserted = storage.upsert_records(records)
        status = "ok" if records else "empty"
        fetched_at = records[0].fetched_at if records else None
        storage.upsert_slice(
            reporter_code=reporter_code,
            year=year,
            flow_code=flow_code,
            status=status,
            record_count=len(records),
            fetched_at=fetched_at,
            freq_code=freq_code,
            month=month if freq_code == "M" else 0,
        )
        storage.finish_sync_log(
            log_id,
            records_fetched=len(records),
            records_upserted=upserted,
            status="success" if status == "ok" else "empty",
        )
        if status == "ok":
            message = f"已从 UN Comtrade 同步 {len(records)} 条记录"
        else:
            message = f"官网暂无该国家 {label} 该流向数据（已记录，短期内不会重复请求）"
        return SliceSyncResult(
            reporter_code=reporter_code,
            year=year,
            flow_code=flow_code,
            freq_code=freq_code,
            month=month if freq_code == "M" else 0,
            status=status,
            record_count=len(records),
            records_upserted=upserted,
            cached=False,
            fetched_at=fetched_at
            or storage.get_slice(
                reporter_code, year, flow_code, freq_code=freq_code, month=month
            )["fetched_at"],
            message=message,
        )
    except Exception as exc:
        storage.upsert_slice(
            reporter_code=reporter_code,
            year=year,
            flow_code=flow_code,
            status="error",
            record_count=0,
            error_message=str(exc),
            freq_code=freq_code,
            month=month if freq_code == "M" else 0,
        )
        storage.finish_sync_log(
            log_id,
            records_fetched=0,
            records_upserted=0,
            status="error",
            error_message=str(exc),
        )
        return SliceSyncResult(
            reporter_code=reporter_code,
            year=year,
            flow_code=flow_code,
            freq_code=freq_code,
            month=month if freq_code == "M" else 0,
            status="error",
            record_count=0,
            records_upserted=0,
            cached=False,
            fetched_at=None,
            message="同步失败",
            error_message=str(exc),
        )


def sync_slices(
    *,
    reporter_code: int,
    year: int,
    flow_code: str | None = None,
    freq_code: str = "A",
    month: int = 0,
    force_refresh: bool = False,
    storage: TradeStorage | None = None,
    on_progress: Callable[[int, int, SliceSyncResult, str], None] | None = None,
) -> dict[str, Any]:
    storage = storage or TradeStorage()
    api_key = _get_api_key()
    headers = {"User-Agent": "customsR/1.0 (sync_service)"}
    slice_month = month if freq_code == "M" else 0
    plan = build_sync_plan(flow_code=flow_code, freq_code=freq_code, month=month)
    total_steps = len(plan)

    slice_results: list[SliceSyncResult] = []
    with httpx.Client(headers=headers) as client:
        for step_idx, (m, fc) in enumerate(plan, start=1):
            if step_idx > 1:
                time.sleep(1)
            result = sync_one_slice(
                storage,
                client,
                api_key,
                reporter_code=reporter_code,
                year=year,
                flow_code=fc,
                freq_code=freq_code,
                month=m,
                force_refresh=force_refresh,
            )
            slice_results.append(result)
            if on_progress:
                label = _slice_step_label(
                    freq_code=freq_code,
                    year=year,
                    month=m,
                    flow_code=fc,
                )
                on_progress(step_idx, total_steps, result, label)

    return _summarize_slice_results(
        slice_results,
        freq_code=freq_code,
        slice_month=slice_month,
    )


def iter_sync_events(
    *,
    reporter_code: int,
    year: int,
    flow_code: str | None = None,
    freq_code: str = "A",
    month: int = 0,
    force_refresh: bool = False,
    storage: TradeStorage | None = None,
) -> Iterator[dict[str, Any]]:
    """逐步产出同步事件：start → progress* → done。"""
    storage = storage or TradeStorage()
    api_key = _get_api_key()
    headers = {"User-Agent": "customsR/1.0 (sync_service)"}
    slice_month = month if freq_code == "M" else 0
    plan = build_sync_plan(flow_code=flow_code, freq_code=freq_code, month=month)
    total_steps = len(plan)

    yield {"type": "start", "total": total_steps}

    slice_results: list[SliceSyncResult] = []
    with httpx.Client(headers=headers) as client:
        for step_idx, (m, fc) in enumerate(plan, start=1):
            if step_idx > 1:
                time.sleep(1)
            result = sync_one_slice(
                storage,
                client,
                api_key,
                reporter_code=reporter_code,
                year=year,
                flow_code=fc,
                freq_code=freq_code,
                month=m,
                force_refresh=force_refresh,
            )
            slice_results.append(result)
            label = _slice_step_label(
                freq_code=freq_code,
                year=year,
                month=m,
                flow_code=fc,
            )
            yield {
                "type": "progress",
                "current": step_idx,
                "total": total_steps,
                "percent": round(step_idx / total_steps * 100) if total_steps else 0,
                "label": label,
                "slice": result.as_dict(),
            }

    yield {
        "type": "done",
        "result": _summarize_slice_results(
            slice_results,
            freq_code=freq_code,
            slice_month=slice_month,
        ),
    }
