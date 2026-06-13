"""Reformat existing Comtrade xlsx without re-fetching API."""

from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from fetch_comtrade import REPORTERS, USD_COLUMNS, USD_FORMAT, export_xlsx

CODE_TO_NAMES = {int(code): (zh, en) for zh, (code, en) in REPORTERS.items()}

src = Path("output/comtrade_trade_data.xlsx")
dst = Path("output/comtrade_trade_data_v2.xlsx")

df = pd.read_excel(src, sheet_name="原始数据")

# 补 reporter_name
if "reporter_name" not in df.columns:
    df["reporter_code"] = df["reporter_code"].astype(int)
    df.insert(
        2,
        "reporter_name",
        df["reporter_code"].map(lambda c: CODE_TO_NAMES.get(c, ("", ""))[1]),
    )

# 重命名 classification
if "classification" in df.columns:
    df = df.rename(columns={"classification": "分类体系"})
if "HS版本" not in df.columns:
    df["HS版本"] = "H6"

export_xlsx(df, dst)
print(f"已导出: {dst}")
