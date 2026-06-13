"""Fetch annual trade data from UN Comtrade and export to xlsx."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# UN M49 reporter codes: 中文名 -> (code, 英文名)
REPORTERS: dict[str, tuple[str, str]] = {
    "中国": ("156", "China"),
    "美国": ("842", "United States"),
    "德国": ("276", "Germany"),
    "英国": ("826", "United Kingdom"),
    "日本": ("392", "Japan"),
}

# 金额列：Excel 中用千分位整数显示，避免 3.38E+12 科学计数法
USD_COLUMNS = ("贸易额_USD", "fobvalue_USD", "cifvalue_USD")
USD_FORMAT = "#,##0"

FLOW_LABELS = {"X": "出口", "M": "进口"}
PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
DATA_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"


def recent_years(n: int = 3) -> list[str]:
    current = datetime.now().year
    return [str(current - i) for i in range(n, 0, -1)]


def fetch_record(
    client: httpx.Client,
    *,
    reporter_code: str,
    period: str,
    flow_code: str,
    api_key: str | None,
) -> dict | None:
    params = {
        "reporterCode": reporter_code,
        "partnerCode": "0",
        "period": period,
        "flowCode": flow_code,
        "cmdCode": "TOTAL",
        "breakdownMode": "classic",
        "format": "JSON",
        "partner2Code": "0",
        "customsCode": "C00",
        "motCode": "0",
    }
    url = DATA_URL if api_key else PREVIEW_URL
    if api_key:
        params["subscription-key"] = api_key

    for attempt in range(3):
        try:
            resp = client.get(url, params=params, timeout=60.0)
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("data") or []
            if rows:
                return rows[0]
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
        except (httpx.HTTPError, ValueError):
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    return None


def collect_trade_data(years: list[str], api_key: str | None = None) -> pd.DataFrame:
    records: list[dict] = []
    headers = {"User-Agent": "customsR/1.0 (trade-data-fetcher)"}

    with httpx.Client(headers=headers) as client:
        total = len(REPORTERS) * len(years) * 2
        done = 0
        for country, (reporter_code, reporter_name_en) in REPORTERS.items():
            for year in years:
                for flow_code, flow_label in FLOW_LABELS.items():
                    done += 1
                    print(f"[{done}/{total}] {country} {year} {flow_label}...", flush=True)
                    row = fetch_record(
                        client,
                        reporter_code=reporter_code,
                        period=year,
                        flow_code=flow_code,
                        api_key=api_key,
                    )
                    if row:
                        records.append(
                            {
                                "国家": country,
                                "reporter_code": int(reporter_code),
                                "reporter_name": reporter_name_en,
                                "年份": int(year),
                                "贸易流向": flow_label,
                                "flow_code": flow_code,
                                "伙伴": "World",
                                "partner_code": 0,
                                "商品编码": row.get("cmdCode", "TOTAL"),
                                "贸易额_USD": row.get("primaryValue"),
                                "fobvalue_USD": row.get("fobvalue"),
                                "cifvalue_USD": row.get("cifvalue"),
                                "分类体系": row.get("classificationSearchCode"),
                                "HS版本": row.get("classificationCode"),
                                "period": row.get("period"),
                                "数据源": "UN Comtrade",
                            }
                        )
                    else:
                        records.append(
                            {
                                "国家": country,
                                "reporter_code": int(reporter_code),
                                "reporter_name": reporter_name_en,
                                "年份": int(year),
                                "贸易流向": flow_label,
                                "flow_code": flow_code,
                                "伙伴": "World",
                                "partner_code": 0,
                                "商品编码": "TOTAL",
                                "贸易额_USD": None,
                                "fobvalue_USD": None,
                                "cifvalue_USD": None,
                                "分类体系": None,
                                "HS版本": None,
                                "period": year,
                                "数据源": "UN Comtrade",
                            }
                        )
                    time.sleep(0.6)

    df = pd.DataFrame(records)
    return df


def _apply_usd_number_format(writer: pd.ExcelWriter, sheet_name: str, df: pd.DataFrame) -> None:
    """为金额列设置千分位格式，避免 Excel 显示为科学计数法。"""
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
    summary = (
        df.pivot_table(
            index=["国家", "reporter_name", "年份"],
            columns="贸易流向",
            values="贸易额_USD",
            aggfunc="first",
        )
        .reset_index()
        .sort_values(["国家", "年份"])
    )
    if "出口" in summary.columns and "进口" in summary.columns:
        summary["贸易差额_USD"] = summary["出口"] - summary["进口"]

    column_help = pd.DataFrame(
        {
            "字段": [
                "reporter_code",
                "reporter_name",
                "贸易额_USD",
                "fobvalue_USD",
                "cifvalue_USD",
                "分类体系",
                "HS版本",
            ],
            "含义": [
                "UN M49 国家/地区数字代码",
                "报告国英文名称（与 reporter_code 对应）",
                "主贸易值（美元）。出口多为 FOB，进口多为 CIF",
                "FOB 离岸价（Free On Board，美元）",
                "CIF 到岸价（Cost+Insurance+Freight，美元）",
                "商品分类体系，HS = 协调制度（Harmonized System）",
                "实际采用的 HS 版本，如 H6 表示 HS 6 位编码体系",
            ],
        }
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="原始数据", index=False)
        _apply_usd_number_format(writer, "原始数据", df)

        summary.to_excel(writer, sheet_name="汇总", index=False)
        summary_usd_cols = [c for c in ("出口", "进口", "贸易差额_USD") if c in summary.columns]
        if summary_usd_cols:
            ws = writer.sheets["汇总"]
            col_index = {name: idx + 1 for idx, name in enumerate(summary.columns)}
            for col_name in summary_usd_cols:
                col_letter = ws.cell(row=1, column=col_index[col_name]).column_letter
                for row in range(2, len(summary) + 2):
                    cell = ws[f"{col_letter}{row}"]
                    if cell.value is not None:
                        cell.number_format = USD_FORMAT

        column_help.to_excel(writer, sheet_name="字段说明", index=False)

        meta = pd.DataFrame(
            {
                "项": [
                    "导出时间",
                    "数据来源",
                    "国家",
                    "年份范围",
                    "说明",
                ],
                "值": [
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "UN Comtrade (Annual, HS, TOTAL, Partner=World)",
                    "、".join(REPORTERS.keys()),
                    f"{df['年份'].min()}-{df['年份'].max()}",
                    "部分国家最新年度可能尚未报送至 Comtrade，对应单元格为空；"
                    "金额列已格式化为千分位整数（单位：美元）",
                ],
            }
        )
        meta.to_excel(writer, sheet_name="说明", index=False)


def main() -> None:
    years = recent_years(3)
    api_key = os.environ.get("COMTRADE_API_KEY") or None
    output_path = Path(__file__).resolve().parent / "output" / "comtrade_trade_data.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"查询年份: {', '.join(years)}")
    print(f"API 模式: {'正式 Key' if api_key else 'Preview (免费)'}")
    df = collect_trade_data(years, api_key=api_key)
    export_xlsx(df, output_path)

    available = df["贸易额_USD"].notna().sum()
    print(f"\n完成: 共 {len(df)} 条，有效数据 {available} 条")
    print(f"已导出: {output_path}")


if __name__ == "__main__":
    main()
