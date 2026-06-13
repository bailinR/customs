"""Shared configuration."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# 中文名 -> (UN M49 reporter_code, 英文名，仅用于日志)
REPORTERS: dict[str, tuple[str, str]] = {
    "中国": ("156", "China"),
    "美国": ("842", "United States"),
    "德国": ("276", "Germany"),
    "英国": ("826", "United Kingdom"),
    "日本": ("392", "Japan"),
}

FLOW_LABELS: dict[str, str] = {"X": "出口", "M": "进口"}

FREQ_LABELS: dict[str, str] = {"A": "年度", "M": "月度"}

MONTH_LABELS: dict[int, str] = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

ANNUAL_DATA_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
MONTHLY_DATA_URL = "https://comtradeapi.un.org/data/v1/get/C/M/HS"
DATA_URL = ANNUAL_DATA_URL
DB_PATH = "data/customs.db"

# 海关总署在线查询 stats.customs.gov.cn
GACC_BASE_URL = os.environ.get("GACC_BASE_URL", "http://stats.customs.gov.cn/")
# Windows 默认 Edge；可设 chrome / chromium / 留空用 Playwright 自带 Chromium
GACC_BROWSER_CHANNEL = os.environ.get(
    "GACC_BROWSER_CHANNEL",
    "msedge" if sys.platform == "win32" else "",
)
GACC_BROWSER_HEADLESS = os.environ.get("GACC_BROWSER_HEADLESS", "false").lower() in (
    "1",
    "true",
    "yes",
)
GACC_CAPTCHA_TIMEOUT_SEC = int(os.environ.get("GACC_CAPTCHA_TIMEOUT_SEC", "300"))
GACC_CAPTCHA_AUTO = os.environ.get("GACC_CAPTCHA_AUTO", "true").lower() in (
    "1",
    "true",
    "yes",
)
GACC_CAPTCHA_AUTO_MAX_ATTEMPTS = int(
    os.environ.get("GACC_CAPTCHA_AUTO_MAX_ATTEMPTS", "5")
)
GACC_CAPTCHA_FALLBACK_MANUAL = os.environ.get(
    "GACC_CAPTCHA_FALLBACK_MANUAL", "true"
).lower() in ("1", "true", "yes")
GACC_CAPTCHA_OFFSET_PX = float(os.environ.get("GACC_CAPTCHA_OFFSET_PX", "0"))
GACC_LOAD_TIMEOUT_SEC = int(os.environ.get("GACC_LOAD_TIMEOUT_SEC", "600"))
GACC_DOWNLOAD_DIR = os.environ.get("GACC_DOWNLOAD_DIR", "data/gacc_downloads")
# 海关已发布数据的最新年月（2026 年目前到 4 月，可在 .env 调整）
GACC_LATEST_YEAR = int(os.environ.get("GACC_LATEST_YEAR", "2026"))
GACC_LATEST_MONTH = int(os.environ.get("GACC_LATEST_MONTH", "4"))
GACC_DEFAULT_MONTH_START = int(os.environ.get("GACC_DEFAULT_MONTH_START", "1"))
GACC_DEFAULT_MONTH_END = int(os.environ.get("GACC_DEFAULT_MONTH_END", "1"))
