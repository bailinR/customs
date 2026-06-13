"""Fetch US 2025 import/export by partner country from UN Comtrade."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DATA_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
USD_FORMAT = "#,##0"
USD_COLUMNS = ("贸易额_USD", "fobvalue_USD", "cifvalue_USD")

US_REPORTER_CODE = "842"
YEAR = "2025"
FLOW_LABELS = {"X": "出口", "M": "进口"}


def fetch_us_by_partners(
    client: httpx.Client,
    *,
    flow_code: str,
    api_key: str,
) -> list[dict]:
    params = {
        "reporterCode": US_REPORTER_CODE,
        "period": YEAR,
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
            resp = client.get(DATA_URL, params=params, timeout=120.0)
            resp.raise_for_status()
            rows = resp.json().get("data") or []
            return [r for r in rows if r.get("partnerCode") not in (0, "0")]
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


def rows_to_dataframe(rows: list[dict], flow_label: str, flow_code: str) -> pd.DataFrame:
    records = []
    for row in rows:
        records.append(
            {
                "报告国": "美国",
                "reporter_code": int(row.get("reporterCode", 842)),
                "年份": int(row.get("refYear", YEAR)),
                "贸易流向": flow_label,
                "flow_code": flow_code,
                "partner_code": int(row.get("partnerCode")),
                "partner_name": row.get("partnerDesc") or row.get("partnerISO"),
                "partner_iso": row.get("partnerISO"),
                "商品编码": row.get("cmdCode", "TOTAL"),
                "贸易额_USD": row.get("primaryValue"),
                "fobvalue_USD": row.get("fobvalue"),
                "cifvalue_USD": row.get("cifvalue"),
                "分类体系": row.get("classificationSearchCode"),
                "HS版本": row.get("classificationCode"),
                "数据源": "UN Comtrade",
            }
        )
    return pd.DataFrame(records)


def _apply_usd_format(writer: pd.ExcelWriter, sheet_name: str, df: pd.DataFrame) -> None:
    ws = writer.sheets[sheet_name]
    col_index = {name: idx + 1 for idx, name in enumerate(df.columns)}
    for col_name in USD_COLUMNS:
        if col_name not in col_index:
            continue
        col_letter = ws.cell(row=1, column=col_index[col_name]).column_letter
        for row in range(2, len(df) + 2):
            cell = ws[f"{col_letter}{row}"]
            if cell.value is not None:
                cell.number_format = USD_FORMAT


def export_xlsx(df: pd.DataFrame, output_path: Path) -> None:
    top_export = (
        df[df["贸易流向"] == "出口"]
        .nlargest(20, "贸易额_USD")[["partner_name", "partner_code", "贸易额_USD"]]
        .reset_index(drop=True)
    )
    top_import = (
        df[df["贸易流向"] == "进口"]
        .nlargest(20, "贸易额_USD")[["partner_name", "partner_code", "贸易额_USD"]]
        .reset_index(drop=True)
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.sort_values(["贸易流向", "贸易额_USD"], ascending=[True, False]).to_excel(
            writer, sheet_name="分国别明细", index=False
        )
        _apply_usd_format(writer, "分国别明细", df)
        top_export.to_excel(writer, sheet_name="出口Top20", index=False)
        _apply_usd_format(writer, "出口Top20", top_export)
        top_import.to_excel(writer, sheet_name="进口Top20", index=False)
        _apply_usd_format(writer, "进口Top20", top_import)

        meta = pd.DataFrame(
            {
                "项": ["导出时间", "报告国", "年份", "贸易流向", "伙伴范围", "数据来源", "记录数"],
                "值": [
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "美国 (842)",
                    YEAR,
                    "进口 + 出口",
                    "各贸易伙伴国/地区（不含 World 合计行）",
                    "UN Comtrade Annual / HS / TOTAL",
                    str(len(df)),
                ],
            }
        )
        meta.to_excel(writer, sheet_name="说明", index=False)


def main() -> None:
    api_key = os.environ.get("COMTRADE_API_KEY")
    if not api_key:
        raise SystemExit("请在 .env 中配置 COMTRADE_API_KEY")

    output_path = Path(__file__).resolve().parent / "output" / "us_2025_by_country.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    headers = {"User-Agent": "customsR/1.0 (us-by-country)"}

    with httpx.Client(headers=headers) as client:
        for flow_code, flow_label in FLOW_LABELS.items():
            print(f"拉取美国 {YEAR} {flow_label}（分国别）...", flush=True)
            rows = fetch_us_by_partners(client, flow_code=flow_code, api_key=api_key)
            print(f"  获取 {len(rows)} 个贸易伙伴", flush=True)
            frames.append(rows_to_dataframe(rows, flow_label, flow_code))
            time.sleep(1)

    df = pd.concat(frames, ignore_index=True)
    export_xlsx(df, output_path)
    print(f"\n完成: 共 {len(df)} 条")
    print(f"已导出: {output_path}")


if __name__ == "__main__":
    main()
