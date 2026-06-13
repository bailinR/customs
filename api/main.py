"""FastAPI service for trade data."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from comtrade_meta import (
    comtrade_years,
    get_reporters,
    is_valid_reporter,
    is_valid_year,
    reporter_label,
)
from config import (
    DB_PATH,
    FLOW_LABELS,
    FREQ_LABELS,
    GACC_CAPTCHA_AUTO,
    GACC_CAPTCHA_AUTO_MAX_ATTEMPTS,
    GACC_CAPTCHA_FALLBACK_MANUAL,
    GACC_CAPTCHA_TIMEOUT_SEC,
    GACC_DEFAULT_MONTH_END,
    GACC_DEFAULT_MONTH_START,
    GACC_DOWNLOAD_DIR,
    GACC_LATEST_MONTH,
    GACC_LATEST_YEAR,
    MONTH_LABELS,
)
from gacc_jobs import start_gacc_job
from gacc_models import (
    CURRENCY_LABELS,
    DEFAULT_OUTPUT_FIELDS,
    FLOW_LABELS as GACC_FLOW_LABELS,
    GaccQueryParams,
    OUTPUT_FIELD_OPTIONS,
)
from gacc_storage import GaccStorage
from slice_meta import STATUS_LABELS, slice_row_to_dict
from storage import EMPTY_SLICE_TTL_DAYS, TradeStorage
from sync_service import iter_sync_events, sync_slices
from trade_export import (
    MAX_EXPORT_ROWS,
    build_export_filename,
    records_to_xlsx_bytes,
    rows_to_records,
)
from trade_query import build_trade_conditions, count_trade_rows, fetch_trade_rows

app = FastAPI(title="customsR API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SyncSliceRequest(BaseModel):
    reporter_code: int = Field(..., description="报告国 UN M49 代码")
    year: int = Field(..., ge=1900, le=2100)
    flow_code: str | None = Field(None, pattern="^(X|M)$", description="为空则同步进出口")
    freq_code: str = Field("A", pattern="^(A|M)$")
    month: int = Field(0, ge=0, le=12)
    force_refresh: bool = False

    @model_validator(mode="after")
    def validate_month(self) -> "SyncSliceRequest":
        if self.freq_code == "M" and self.month not in range(0, 13):
            raise ValueError("月度同步需要 month 为 0（全年）或 1-12")
        if self.freq_code == "A":
            self.month = 0
        return self


def get_conn() -> sqlite3.Connection:
    db = Path(DB_PATH)
    if not db.exists():
        raise FileNotFoundError(f"数据库不存在: {db}，请先运行 python sync.py")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def month_label(month: int) -> str:
    if month <= 0:
        return "—"
    return MONTH_LABELS.get(month, str(month))


def period_label(freq_code: str, year: int, month: int) -> str:
    if freq_code == "M" and month:
        return f"{month_label(month)} {year}"
    return str(year)


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["reporter_label"] = reporter_label(d.get("reporter_code"))
    d["flow_label"] = FLOW_LABELS.get(d.get("flow_code"), d.get("flow_code"))
    d["freq_label"] = FREQ_LABELS.get(d.get("freq_code"), d.get("freq_code"))
    d["month_label"] = month_label(int(d.get("month") or 0))
    d["period_label"] = period_label(
        str(d.get("freq_code") or "A"),
        int(d.get("year") or 0),
        int(d.get("month") or 0),
    )
    return d


def _filter_scope(
    *,
    reporter_code: int | None,
    year: int | None,
    freq_code: str | None,
    month: int | None,
    for_dimension: str | None = None,
) -> tuple[str, list[Any]]:
    """构建 WHERE；for_dimension 为 reporter/year/month 时不应用该维度自身筛选。"""
    conditions: list[str] = []
    params: list[Any] = []
    if reporter_code is not None and for_dimension != "reporter":
        conditions.append("reporter_code = ?")
        params.append(reporter_code)
    if year is not None and for_dimension != "year":
        conditions.append("year = ?")
        params.append(year)
    if freq_code == "M":
        conditions.append("freq_code = 'M'")
        conditions.append("month > 0")
        if month is not None and for_dimension != "month":
            conditions.append("month = ?")
            params.append(month)
    elif freq_code == "A":
        conditions.append("freq_code = 'A'")
        conditions.append("month = 0")
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_sql, params


@app.get("/api/health")
def health() -> dict[str, Any]:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM trade_records").fetchone()["c"]
    return {"status": "ok", "records": total}


@app.get("/api/meta/filters")
def meta_filters(
    reporter_code: int | None = None,
    year: int | None = None,
    freq_code: str | None = Query(None, pattern="^(A|M)$"),
    month: int | None = Query(None, ge=1, le=12),
) -> dict[str, Any]:
    """筛选项仅反映数据库中已有贸易数据；报告国/年份/月份联动（各下拉不受自身当前值约束）。"""
    freq = freq_code or "A"
    reporter_where, reporter_params = _filter_scope(
        reporter_code=reporter_code,
        year=year,
        freq_code=freq,
        month=month,
        for_dimension="reporter",
    )
    year_where, year_params = _filter_scope(
        reporter_code=reporter_code,
        year=year,
        freq_code=freq,
        month=month,
        for_dimension="year",
    )
    month_where, month_params = _filter_scope(
        reporter_code=reporter_code,
        year=year,
        freq_code=freq,
        month=month,
        for_dimension="month",
    )
    flow_where, flow_params = _filter_scope(
        reporter_code=reporter_code,
        year=year,
        freq_code=freq,
        month=month,
    )

    with get_conn() as conn:
        reporter_codes = {
            int(r["reporter_code"])
            for r in conn.execute(
                f"SELECT DISTINCT reporter_code FROM trade_records {reporter_where} ORDER BY reporter_code",
                reporter_params,
            ).fetchall()
        }
        years = [
            r["year"]
            for r in conn.execute(
                f"SELECT DISTINCT year FROM trade_records {year_where} ORDER BY year DESC",
                year_params,
            ).fetchall()
        ]
        months = [
            int(r["month"])
            for r in conn.execute(
                f"""
                SELECT DISTINCT month FROM trade_records
                {month_where}
                {'AND' if month_where else 'WHERE'} month > 0
                ORDER BY month DESC
                """,
                month_params,
            ).fetchall()
        ]
        flow_codes = {
            r["flow_code"]
            for r in conn.execute(
                f"SELECT DISTINCT flow_code FROM trade_records {flow_where}",
                flow_params,
            ).fetchall()
        }
        freq_codes = {
            r["freq_code"]
            for r in conn.execute(
                f"SELECT DISTINCT freq_code FROM trade_records {flow_where}",
                flow_params,
            ).fetchall()
        }

    reporters = sorted(
        [
            {
                "code": code,
                "label": reporter_label(code),
                "name_en": reporter_label(code),
            }
            for code in reporter_codes
        ],
        key=lambda r: r["label"],
    )
    flows = [
        {"code": code, "label": label}
        for code, label in FLOW_LABELS.items()
        if code in flow_codes
    ]
    frequencies = [
        {"code": code, "label": label}
        for code, label in FREQ_LABELS.items()
        if code in freq_codes
    ]
    month_options: list[dict[str, Any]] = []
    if year is not None and (freq_code or "A") == "M":
        month_options.append(
            {
                "value": 0,
                "label": "All",
                "period_label": f"All of {year}",
            }
        )
    month_options.extend(
        {
            "value": m,
            "label": f"{month_label(m)}",
            "period_label": f"{month_label(m)} {year}" if year else month_label(m),
        }
        for m in months
    )
    return {
        "reporters": reporters,
        "years": years,
        "months": month_options,
        "flows": flows,
        "frequencies": frequencies,
    }


@app.get("/api/meta/sync-options")
def meta_sync_options() -> dict[str, Any]:
    """同步表单：国家来自 Comtrade 官网参考表（英文），年份从最近到 1962。"""
    storage = TradeStorage()
    try:
        reporters = get_reporters()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"加载 Comtrade 国家列表失败: {exc}") from exc

    slice_rows = storage.list_slice_statuses()
    slice_hints = [
        {
            "reporter_code": int(r["reporter_code"]),
            "year": int(r["year"]),
            "month": int(r["month"] or 0),
            "freq_code": r["freq_code"],
            "flow_code": r["flow_code"],
            "status": r["status"],
            "record_count": int(r["record_count"] or 0),
            "fetched_at": r["fetched_at"],
            "error_message": r["error_message"],
        }
        for r in slice_rows
    ]
    months = [
        {
            "value": m,
            "label": MONTH_LABELS[m],
        }
        for m in range(12, 0, -1)
    ]
    return {
        "reporters": reporters,
        "years": comtrade_years(),
        "months": months,
        "frequencies": [{"code": c, "label": l} for c, l in FREQ_LABELS.items()],
        "slice_hints": slice_hints,
    }


@app.get("/api/slices/meta")
def slices_meta() -> dict[str, Any]:
    """切片页筛选项：仅来自 data_slices 已有记录。"""
    with get_conn() as conn:
        reporter_codes = [
            int(r["reporter_code"])
            for r in conn.execute(
                "SELECT DISTINCT reporter_code FROM data_slices ORDER BY reporter_code"
            ).fetchall()
        ]
        years = [
            int(r["year"])
            for r in conn.execute(
                "SELECT DISTINCT year FROM data_slices ORDER BY year DESC"
            ).fetchall()
        ]
        freq_codes = [
            r["freq_code"]
            for r in conn.execute(
                "SELECT DISTINCT freq_code FROM data_slices ORDER BY freq_code"
            ).fetchall()
        ]
    reporters = sorted(
        [
            {
                "code": code,
                "label": reporter_label(code),
            }
            for code in reporter_codes
        ],
        key=lambda item: item["label"],
    )
    frequencies = [
        {"code": code, "label": FREQ_LABELS.get(code, code)}
        for code in freq_codes
    ]
    statuses = [
        {"code": code, "label": label}
        for code, label in STATUS_LABELS.items()
    ]
    return {
        "reporters": reporters,
        "years": years,
        "frequencies": frequencies,
        "statuses": statuses,
        "empty_ttl_days": EMPTY_SLICE_TTL_DAYS,
    }


@app.get("/api/slices")
def list_slices(
    reporter_code: int | None = None,
    year: int | None = None,
    freq_code: str | None = Query(None, pattern="^(A|M)$"),
    status: str | None = Query(None, pattern="^(ok|empty|error)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    storage = TradeStorage()
    total = storage.count_slices(
        reporter_code=reporter_code,
        year=year,
        freq_code=freq_code,
        status=status,
    )
    summary = storage.summarize_slices(
        reporter_code=reporter_code,
        year=year,
        freq_code=freq_code,
        status=status,
    )
    offset = (page - 1) * page_size
    rows = storage.list_slice_statuses(
        reporter_code=reporter_code,
        year=year,
        freq_code=freq_code,
        status=status,
        limit=page_size,
        offset=offset,
    )
    return {
        "items": [slice_row_to_dict(row) for row in rows],
        "summary": summary,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    }


def _validate_sync_request(req: SyncSliceRequest) -> None:
    if not is_valid_reporter(req.reporter_code):
        raise HTTPException(status_code=400, detail="不支持的报告国")
    if not is_valid_year(req.year):
        raise HTTPException(status_code=400, detail="不支持的年份（范围 1962–当前年）")


def _sync_request_kwargs(req: SyncSliceRequest) -> dict[str, Any]:
    return {
        "reporter_code": req.reporter_code,
        "year": req.year,
        "flow_code": req.flow_code or None,
        "freq_code": req.freq_code,
        "month": req.month,
        "force_refresh": req.force_refresh,
    }


@app.post("/api/sync/slice")
def sync_slice(req: SyncSliceRequest) -> dict[str, Any]:
    _validate_sync_request(req)
    try:
        return sync_slices(**_sync_request_kwargs(req))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/slice/stream")
def sync_slice_stream(req: SyncSliceRequest) -> StreamingResponse:
    """SSE 流式同步，逐步推送切片进度。"""
    _validate_sync_request(req)

    def event_stream() -> Iterator[str]:
        try:
            for event in iter_sync_events(**_sync_request_kwargs(req)):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except (RuntimeError, ValueError) as exc:
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/trade")
def list_trade(
    reporter_code: int | None = None,
    year: int | None = None,
    month: int | None = Query(None, ge=1, le=12),
    freq_code: str = Query("A", pattern="^(A|M)$"),
    flow_code: str | None = Query(None, pattern="^(X|M)$"),
    partner_name: str | None = None,
    partner_scope: str = Query("countries", pattern="^(countries|total)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    conditions, params = build_trade_conditions(
        reporter_code=reporter_code,
        year=year,
        month=month,
        freq_code=freq_code,
        flow_code=flow_code,
        partner_name=partner_name,
        partner_scope=partner_scope,
    )

    with get_conn() as conn:
        total = count_trade_rows(conn, conditions, params)
        offset = (page - 1) * page_size
        rows = fetch_trade_rows(
            conn,
            conditions,
            params,
            partner_scope=partner_scope,
            limit=page_size,
            offset=offset,
        )

    items = [row_to_dict(r) for r in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    }


@app.get("/api/trade/export")
def export_trade(
    reporter_code: int | None = None,
    year: int | None = None,
    month: int | None = Query(None, ge=1, le=12),
    freq_code: str = Query("A", pattern="^(A|M)$"),
    flow_code: str | None = Query(None, pattern="^(X|M)$"),
    partner_name: str | None = None,
    partner_scope: str = Query("countries", pattern="^(countries|total)$"),
) -> Response:
    """按当前筛选条件导出全部匹配记录为 xlsx（上限 5 万条）。"""
    conditions, params = build_trade_conditions(
        reporter_code=reporter_code,
        year=year,
        month=month,
        freq_code=freq_code,
        flow_code=flow_code,
        partner_name=partner_name,
        partner_scope=partner_scope,
    )

    with get_conn() as conn:
        total = count_trade_rows(conn, conditions, params)
        if total == 0:
            raise HTTPException(status_code=404, detail="当前筛选条件下暂无数据可导出")
        truncated = total > MAX_EXPORT_ROWS
        rows = fetch_trade_rows(
            conn,
            conditions,
            params,
            partner_scope=partner_scope,
            limit=MAX_EXPORT_ROWS,
        )

    items = [row_to_dict(r) for r in rows]
    xlsx_bytes = records_to_xlsx_bytes(
        rows_to_records(items),
        total_matched=total,
        truncated=truncated,
    )
    filename = build_export_filename()
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Total": str(total),
            "X-Export-Rows": str(len(items)),
            "X-Export-Truncated": "1" if truncated else "0",
        },
    )


_gacc_storage = GaccStorage()


class GaccQueryRequest(BaseModel):
    flow_type: str = Field("import", pattern="^(import|export|both)$")
    currency: str = Field("USD", pattern="^(USD|CNY)$")
    year: int = Field(..., ge=2015, le=2100)
    month_start: int = Field(..., ge=1, le=12)
    month_end: int = Field(..., ge=1, le=12)
    split_by_month: bool = False
    output_fields: list[str] = Field(
        default_factory=lambda: list(DEFAULT_OUTPUT_FIELDS),
        min_length=1,
        max_length=4,
    )

    @model_validator(mode="after")
    def validate_range(self) -> "GaccQueryRequest":
        if self.month_end < self.month_start:
            raise ValueError("month_end 不能早于 month_start")
        return self


def _gacc_job_dict(job) -> dict[str, Any]:
    data = job.as_dict()
    if job.status == "success":
        data["csv_path"] = str(Path(GACC_DOWNLOAD_DIR) / f"gacc_{job.id}.csv")
    return data


@app.get("/api/gacc/meta/options")
def gacc_meta_options() -> dict[str, Any]:
    years = list(range(GACC_LATEST_YEAR, 2014, -1))
    max_month_by_year = {
        str(y): (GACC_LATEST_MONTH if y == GACC_LATEST_YEAR else 12) for y in years
    }
    return {
        "flow_types": [
            {"value": k, "label": v} for k, v in GACC_FLOW_LABELS.items()
        ],
        "currencies": [
            {"value": k, "label": v} for k, v in CURRENCY_LABELS.items()
        ],
        "years": years,
        "months": list(range(1, 13)),
        "latest_year": GACC_LATEST_YEAR,
        "latest_month": GACC_LATEST_MONTH,
        "default_year": GACC_LATEST_YEAR,
        "default_month_start": GACC_DEFAULT_MONTH_START,
        "default_month_end": GACC_DEFAULT_MONTH_END,
        "max_month_by_year": max_month_by_year,
        "output_field_options": OUTPUT_FIELD_OPTIONS,
        "default_output_fields": DEFAULT_OUTPUT_FIELDS,
        "captcha_timeout_sec": GACC_CAPTCHA_TIMEOUT_SEC,
        "captcha_mode": "auto" if GACC_CAPTCHA_AUTO else "manual",
        "captcha_auto_max_attempts": GACC_CAPTCHA_AUTO_MAX_ATTEMPTS,
        "captcha_fallback_manual": GACC_CAPTCHA_FALLBACK_MANUAL,
        "download_dir": GACC_DOWNLOAD_DIR,
        "source": "stats.customs.gov.cn",
    }


@app.post("/api/gacc/query")
def gacc_start_query(req: GaccQueryRequest) -> dict[str, Any]:
    params = GaccQueryParams(
        flow_type=req.flow_type,  # type: ignore[arg-type]
        currency=req.currency,  # type: ignore[arg-type]
        year=req.year,
        month_start=req.month_start,
        month_end=req.month_end,
        split_by_month=req.split_by_month,
        output_fields=req.output_fields,
    )
    try:
        job_id = start_gacc_job(params, storage=_gacc_storage)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job = _gacc_storage.get_job(job_id)
    return {"job_id": job_id, "job": _gacc_job_dict(job) if job else None}


@app.get("/api/gacc/jobs")
def gacc_list_jobs(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    jobs = _gacc_storage.list_jobs(limit=limit)
    return {"items": [j.as_dict() for j in jobs]}


@app.get("/api/gacc/jobs/{job_id}")
def gacc_get_job(job_id: str) -> dict[str, Any]:
    job = _gacc_storage.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _gacc_job_dict(job)


@app.get("/api/gacc/trade")
def gacc_list_trade(
    job_id: str | None = None,
    flow_type: str | None = Query(None, pattern="^(import|export|both)$"),
    currency: str | None = Query(None, pattern="^(USD|CNY)$"),
    year: int | None = Query(None, ge=2015, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    rows, total = _gacc_storage.fetch_records(
        job_id=job_id,
        flow_type=flow_type,
        currency=currency,
        year=year,
        month=month,
        page=page,
        page_size=page_size,
    )
    pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": [_gacc_storage.row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "job_id": job_id,
    }
