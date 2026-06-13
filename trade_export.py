"""Export trade query results to xlsx."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import pandas as pd

from comtrade_meta import reporter_label
from config import FLOW_LABELS, FREQ_LABELS, MONTH_LABELS

USD_FORMAT = "#,##0"
MAX_EXPORT_ROWS = 50_000


def _month_label(month: int) -> str:
    if month <= 0:
        return ""
    return MONTH_LABELS.get(month, str(month))


def rows_to_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        freq_code = str(row.get("freq_code") or "A")
        month = int(row.get("month") or 0)
        record = {
            "报告国": row.get("reporter_label") or reporter_label(row.get("reporter_code")),
            "报告国代码": row.get("reporter_code"),
            "年份": row.get("year"),
            "频率": FREQ_LABELS.get(freq_code, freq_code),
            "月份": _month_label(month) if freq_code == "M" else "",
            "流向": row.get("flow_label")
            or FLOW_LABELS.get(row.get("flow_code"), row.get("flow_code")),
            "伙伴国": row.get("partner_name") or "",
            "伙伴国代码": row.get("partner_code"),
            "贸易额_USD": row.get("trade_value_usd"),
            "FOB_USD": row.get("fob_value_usd"),
            "CIF_USD": row.get("cif_value_usd"),
            "商品编码": row.get("cmd_code"),
            "数据来源": row.get("source"),
            "同步时间": row.get("fetched_at"),
        }
        records.append(record)
    return records


def _apply_usd_format(writer: pd.ExcelWriter, sheet_name: str, df: pd.DataFrame) -> None:
    usd_cols = [c for c in ("贸易额_USD", "FOB_USD", "CIF_USD") if c in df.columns]
    if not usd_cols:
        return
    ws = writer.sheets[sheet_name]
    col_index = {name: idx + 1 for idx, name in enumerate(df.columns)}
    for col_name in usd_cols:
        col_letter = ws.cell(row=1, column=col_index[col_name]).column_letter
        for row in range(2, len(df) + 2):
            cell = ws[f"{col_letter}{row}"]
            if cell.value is not None:
                cell.number_format = USD_FORMAT


def build_export_filename() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"trade_export_{stamp}.xlsx"


def records_to_xlsx_bytes(
    records: list[dict[str, Any]],
    *,
    total_matched: int,
    truncated: bool = False,
) -> bytes:
    df = pd.DataFrame(records)
    meta = pd.DataFrame(
        {
            "项": ["导出时间", "匹配条数", "导出条数", "说明"],
            "值": [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                str(total_matched),
                str(len(records)),
                "金额列为美元，已格式化为千分位整数；数据来自本地 SQLite（UN Comtrade 同步）"
                + ("；结果已截断至导出上限" if truncated else ""),
            ],
        }
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="查询结果", index=False)
        _apply_usd_format(writer, "查询结果", df)
        meta.to_excel(writer, sheet_name="说明", index=False)
    buffer.seek(0)
    return buffer.getvalue()
