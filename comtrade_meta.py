"""UN Comtrade reference metadata (reporters, years)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import comtradeapicall

from config import DB_PATH

REPORTERS_CACHE_PATH = Path(DB_PATH).parent / "comtrade_reporters.json"
CACHE_TTL_DAYS = 30
COMTRADE_MIN_YEAR = 1962


def comtrade_years() -> list[int]:
    current = datetime.now().year
    return list(range(current, COMTRADE_MIN_YEAR - 1, -1))


def _cache_is_fresh(payload: dict[str, Any]) -> bool:
    fetched_at = payload.get("fetched_at")
    if not fetched_at:
        return False
    try:
        fetched = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - fetched
    return age.days < CACHE_TTL_DAYS


def _load_cache() -> dict[str, Any] | None:
    if not REPORTERS_CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(REPORTERS_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not _cache_is_fresh(payload):
        return None
    return payload


def _save_cache(reporters: list[dict[str, Any]]) -> None:
    REPORTERS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "reporters": reporters,
    }
    REPORTERS_CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _fetch_reporters_from_api() -> list[dict[str, Any]]:
    df = comtradeapicall.getReference("reporter")
    rows = df[df["isGroup"] == False]  # noqa: E712
    rows = rows.sort_values("reporterDesc", kind="mergesort")
    reporters: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        code = int(row["reporterCode"])
        name = str(row["reporterDesc"]).strip()
        reporters.append(
            {
                "code": code,
                "label": name,
                "name_en": name,
                "iso_alpha2": row.get("reporterCodeIsoAlpha2") or None,
                "iso_alpha3": row.get("reporterCodeIsoAlpha3") or None,
            }
        )
    return reporters


def get_reporters(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    if not force_refresh:
        cached = _load_cache()
        if cached and cached.get("reporters"):
            return list(cached["reporters"])
    reporters = _fetch_reporters_from_api()
    _save_cache(reporters)
    return reporters


def get_reporter_codes(*, force_refresh: bool = False) -> set[int]:
    return {int(r["code"]) for r in get_reporters(force_refresh=force_refresh)}


def is_valid_reporter(code: int) -> bool:
    return code in get_reporter_codes()


def is_valid_year(year: int) -> bool:
    current = datetime.now().year
    return COMTRADE_MIN_YEAR <= year <= current


@lru_cache(maxsize=1)
def get_reporter_name_map() -> dict[int, str]:
    cached = _load_cache()
    if cached and cached.get("reporters"):
        return {int(r["code"]): r["label"] for r in cached["reporters"]}
    return {int(r["code"]): r["label"] for r in get_reporters()}


def reporter_label(code: int | None) -> str:
    if code is None:
        return ""
    return get_reporter_name_map().get(int(code), str(code))
