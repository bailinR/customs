"""Sync 5 countries' annual trade by partner into SQLite."""

from __future__ import annotations

import os
import sys
import time

import httpx
from dotenv import load_dotenv

from comtrade_client import api_rows_to_records, fetch_annual_by_partners, recent_years
from config import FLOW_LABELS, REPORTERS
from storage import TradeStorage

load_dotenv()


def sync_annual_by_country(years: list[str] | None = None) -> None:
    api_key = os.environ.get("COMTRADE_API_KEY")
    if not api_key:
        print("错误: 请在 .env 中配置 COMTRADE_API_KEY", file=sys.stderr)
        sys.exit(1)

    years = years or recent_years(3)
    storage = TradeStorage()
    headers = {"User-Agent": "customsR/1.0 (sync)"}

    total_calls = len(REPORTERS) * len(years) * len(FLOW_LABELS)
    done = 0
    total_fetched = 0
    total_upserted = 0

    print(f"同步范围: {len(REPORTERS)} 国 × {len(years)} 年 × 进出口")
    print(f"年份: {', '.join(years)}")
    print(f"数据库: {storage.db_path}\n")

    with httpx.Client(headers=headers) as client:
        for country_zh, (reporter_code, _name_en) in REPORTERS.items():
            for year in years:
                for flow_code, flow_label in FLOW_LABELS.items():
                    done += 1
                    log_id = storage.start_sync_log(
                        "annual_by_country",
                        reporter_code=int(reporter_code),
                        year=int(year),
                        flow_code=flow_code,
                    )
                    label = f"[{done}/{total_calls}] {country_zh} {year} {flow_label}"
                    try:
                        print(f"{label} ...", flush=True)
                        rows = fetch_annual_by_partners(
                            client,
                            reporter_code=reporter_code,
                            year=year,
                            flow_code=flow_code,
                            api_key=api_key,
                        )
                        records = api_rows_to_records(rows, freq_code="A")
                        upserted = storage.upsert_records(records)
                        slice_status = "ok" if records else "empty"
                        storage.upsert_slice(
                            reporter_code=int(reporter_code),
                            year=int(year),
                            flow_code=flow_code,
                            status=slice_status,
                            record_count=len(records),
                            fetched_at=records[0].fetched_at if records else None,
                            freq_code="A",
                            month=0,
                        )
                        total_fetched += len(records)
                        total_upserted += upserted
                        storage.finish_sync_log(
                            log_id,
                            records_fetched=len(records),
                            records_upserted=upserted,
                            status="success" if slice_status == "ok" else "empty",
                        )
                        partners = sum(1 for r in records if r.partner_code != 0)
                        world = sum(1 for r in records if r.partner_code == 0)
                        print(
                            f"  → {len(records)} 条"
                            f"（伙伴国 {partners}，World合计 {world}）",
                            flush=True,
                        )
                    except Exception as exc:
                        storage.finish_sync_log(
                            log_id,
                            records_fetched=0,
                            records_upserted=0,
                            status="error",
                            error_message=str(exc),
                        )
                        print(f"  → 失败: {exc}", flush=True)
                    time.sleep(1)

    print(f"\n完成: 拉取 {total_fetched} 条, 写入变更 {total_upserted} 次")
    print(f"库内总记录: {storage.count_records()}")


if __name__ == "__main__":
    sync_annual_by_country()
