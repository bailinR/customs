"""Parse CSV exports from stats.customs.gov.cn."""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from gacc_models import GaccQueryParams, GaccRecord

VALUE_COLUMNS = {
    "USD": ("美元", "trade value (us$)", "value_usd"),
    "CNY": ("人民币", "人民币(元)", "value_cny", "cny"),
}

COLUMN_ALIASES: dict[str, str] = {
    "商品编码": "hs_code",
    "商品名称": "hs_name",
    "贸易伙伴编码": "partner_code",
    "贸易伙伴名称": "partner_name",
    "贸易方式编码": "trade_mode_code",
    "贸易方式名称": "trade_mode_name",
    "注册地编码": "reg_place_code",
    "注册地名称": "reg_place_name",
    "第一数量": "qty1",
    "第一计量单位": "unit1",
    "第二数量": "qty2",
    "第二计量单位": "unit2",
}


def _normalize_header(name: str) -> str:
    return re.sub(r"\s+", "", name.strip().lower())


def _parse_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("，", "")
    if not text or text in {"—", "-", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    reader = csv.reader(text.splitlines())
    rows = list(reader)
    if not rows:
        return [], []

    headers = [h.strip() for h in rows[0]]
    data_rows: list[dict[str, str]] = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * (len(headers) - len(row))
        data_rows.append(dict(zip(headers, padded[: len(headers)])))
    return headers, data_rows


def _map_row(headers: list[str], row: dict[str, str], currency: str) -> dict[str, str | None]:
    mapped: dict[str, str | None] = {}
    norm_to_orig = {_normalize_header(h): h for h in headers}
    for cn, key in COLUMN_ALIASES.items():
        orig = norm_to_orig.get(_normalize_header(cn))
        mapped[key] = row.get(orig, "").strip() if orig else None

    value_key = None
    for candidate in VALUE_COLUMNS.get(currency, VALUE_COLUMNS["USD"]):
        orig = norm_to_orig.get(_normalize_header(candidate))
        if orig and row.get(orig, "").strip():
            value_key = orig
            break
    if value_key is None:
        for h in headers:
            if "美元" in h or "人民币" in h:
                value_key = h
                break
    mapped["value_raw"] = row.get(value_key or "", "").strip() if value_key else ""
    return mapped


def parse_gacc_csv(
    path: Path | str,
    *,
    job_id: str,
    params: GaccQueryParams,
) -> list[GaccRecord]:
    csv_path = Path(path)
    headers, rows = _read_csv_rows(csv_path)
    if not rows:
        return []

    fetched_at = datetime.now(timezone.utc).isoformat()
    month_start = params.month_start
    month_end = params.month_end
    month = month_start if month_start == month_end else 0
    records: list[GaccRecord] = []

    for row in rows:
        mapped = _map_row(headers, row, params.currency)
        value = _parse_number(mapped.get("value_raw"))
        if value is None:
            continue
        row_month = month
        if params.split_by_month:
            month_col = next(
                (h for h in headers if "月" in h or _normalize_header(h) == "month"),
                None,
            )
            if month_col:
                parsed = _parse_number(row.get(month_col))
                if parsed is not None:
                    row_month = int(parsed)
        records.append(
            GaccRecord(
                job_id=job_id,
                flow_type=params.flow_type,
                currency=params.currency,
                year=params.year,
                month=row_month,
                month_start=month_start,
                month_end=month_end,
                hs_code=mapped.get("hs_code"),
                hs_name=mapped.get("hs_name"),
                partner_code=mapped.get("partner_code"),
                partner_name=mapped.get("partner_name"),
                trade_mode_code=mapped.get("trade_mode_code"),
                trade_mode_name=mapped.get("trade_mode_name"),
                reg_place_code=mapped.get("reg_place_code"),
                reg_place_name=mapped.get("reg_place_name"),
                qty1=_parse_number(mapped.get("qty1")),
                unit1=mapped.get("unit1"),
                qty2=_parse_number(mapped.get("qty2")),
                unit2=mapped.get("unit2"),
                value=value,
                fetched_at=fetched_at,
            )
        )
    return records
