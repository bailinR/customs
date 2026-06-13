"""UN Comtrade API client."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from config import ANNUAL_DATA_URL, MONTHLY_DATA_URL
from storage import TradeRecord


def recent_years(n: int = 3) -> list[str]:
    current = datetime.now().year
    return [str(current - i) for i in range(n, 0, -1)]


def _fetch_by_partners(
    client: httpx.Client,
    *,
    data_url: str,
    reporter_code: str,
    period: str,
    flow_code: str,
    api_key: str,
) -> list[dict]:
    params = {
        "reporterCode": reporter_code,
        "period": period,
        "flowCode": flow_code,
        "cmdCode": "TOTAL",
        "breakdownMode": "classic",
        "format": "JSON",
        "partner2Code": "0",
        "customsCode": "C00",
        "motCode": "0",
        "maxRecords": "250000",
        "includeDesc": "true",
        "subscription-key": api_key,
    }

    for attempt in range(3):
        try:
            resp = client.get(data_url, params=params, timeout=120.0)
            resp.raise_for_status()
            return resp.json().get("data") or []
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except httpx.HTTPError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    return []


def fetch_annual_by_partners(
    client: httpx.Client,
    *,
    reporter_code: str,
    year: str,
    flow_code: str,
    api_key: str,
) -> list[dict]:
    return _fetch_by_partners(
        client,
        data_url=ANNUAL_DATA_URL,
        reporter_code=reporter_code,
        period=year,
        flow_code=flow_code,
        api_key=api_key,
    )


def fetch_monthly_by_partners(
    client: httpx.Client,
    *,
    reporter_code: str,
    year: int,
    month: int,
    flow_code: str,
    api_key: str,
) -> list[dict]:
    period = f"{year}{month:02d}"
    return _fetch_by_partners(
        client,
        data_url=MONTHLY_DATA_URL,
        reporter_code=reporter_code,
        period=period,
        flow_code=flow_code,
        api_key=api_key,
    )


def _parse_year_month(row: dict, *, freq_code: str) -> tuple[int, int]:
    period = str(row.get("period") or "")
    if freq_code == "M":
        if len(period) >= 6 and period[:6].isdigit():
            return int(period[:4]), int(period[4:6])
        year = int(row.get("refYear") or 0)
        month = int(row.get("refMonth") or row.get("refPeriodId") or 0)
        return year, month
    year = int(row.get("refYear") or (period[:4] if len(period) >= 4 else 0))
    return year, 0


def api_rows_to_records(rows: list[dict], *, freq_code: str = "A") -> list[TradeRecord]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    records: list[TradeRecord] = []
    for row in rows:
        partner_code = row.get("partnerCode")
        if partner_code is None:
            continue
        year, month = _parse_year_month(row, freq_code=freq_code)
        records.append(
            TradeRecord(
                reporter_code=int(row.get("reporterCode", 0)),
                partner_code=int(partner_code),
                partner_name=row.get("partnerDesc") or row.get("partnerISO"),
                freq_code=freq_code,
                year=year,
                month=month if freq_code == "M" else 0,
                flow_code=str(row.get("flowCode", "")),
                cmd_code=str(row.get("cmdCode", "TOTAL")),
                trade_value_usd=row.get("primaryValue"),
                fob_value_usd=row.get("fobvalue"),
                cif_value_usd=row.get("cifvalue"),
                fetched_at=fetched_at,
            )
        )
    return records
