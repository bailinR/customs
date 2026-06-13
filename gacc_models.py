"""Pydantic/dataclass models for GACC queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


FlowType = Literal["import", "export", "both"]
Currency = Literal["USD", "CNY"]

FLOW_LABELS: dict[str, str] = {
    "import": "进口",
    "export": "出口",
    "both": "进出口",
}

CURRENCY_LABELS: dict[str, str] = {
    "USD": "美元",
    "CNY": "人民币",
}

# 海关站 radio value（indexEn 与中文站一致）
FLOW_RADIO_VALUES: dict[str, str] = {
    "import": "1",
    "export": "0",
    "both": "2",
}

CURRENCY_RADIO_VALUES: dict[str, tuple[str, ...]] = {
    "USD": ("usd", "USD", "2"),
    "CNY": ("rmb", "cny", "CNY", "1"),
}

# 海关站 outerField1-4 的 option value（与页面 select 一致）
OUTPUT_FIELD_OPTIONS: list[dict[str, str]] = [
    {"value": "CODE_TS", "label": "商品"},
    {"value": "ORIGIN_COUNTRY", "label": "贸易伙伴"},
    {"value": "TRADE_MODE", "label": "贸易方式"},
    {"value": "TRADE_CO_PORT", "label": "收发货人注册地"},
]

DEFAULT_OUTPUT_FIELDS: list[str] = [opt["value"] for opt in OUTPUT_FIELD_OPTIONS]

FIELD_SELECT_IDS = ("outerField1", "outerField2", "outerField3", "outerField4")


@dataclass
class GaccQueryParams:
    flow_type: FlowType = "import"
    currency: Currency = "USD"
    year: int = 2024
    month_start: int = 1
    month_end: int = 12
    split_by_month: bool = False
    output_fields: list[str] = field(default_factory=lambda: list(DEFAULT_OUTPUT_FIELDS))

    def to_dict(self) -> dict[str, Any]:
        return {
            "flow_type": self.flow_type,
            "currency": self.currency,
            "year": self.year,
            "month_start": self.month_start,
            "month_end": self.month_end,
            "split_by_month": self.split_by_month,
            "output_fields": list(self.output_fields),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GaccQueryParams":
        fields = data.get("output_fields") or DEFAULT_OUTPUT_FIELDS
        return cls(
            flow_type=data.get("flow_type", "import"),
            currency=data.get("currency", "USD"),
            year=int(data.get("year", 2024)),
            month_start=int(data.get("month_start", 1)),
            month_end=int(data.get("month_end", 12)),
            split_by_month=bool(data.get("split_by_month", False)),
            output_fields=list(fields),
        )


def format_gacc_period(
    *,
    year: int,
    month: int = 0,
    month_start: int = 0,
    month_end: int = 0,
) -> str:
    if month > 0:
        return f"{year}年{month}月"
    start = month_start or 0
    end = month_end or 0
    if start and end:
        if start == end:
            return f"{year}年{start}月"
        return f"{year}年{start}-{end}月"
    if start:
        return f"{year}年{start}月"
    return f"{year}年"


@dataclass
class GaccRecord:
    job_id: str
    flow_type: str
    currency: str
    year: int
    month: int
    month_start: int
    month_end: int
    hs_code: str | None
    hs_name: str | None
    partner_code: str | None
    partner_name: str | None
    trade_mode_code: str | None
    trade_mode_name: str | None
    reg_place_code: str | None
    reg_place_name: str | None
    qty1: float | None
    unit1: str | None
    qty2: float | None
    unit2: str | None
    value: float
    fetched_at: str

    def period_label(self) -> str:
        return format_gacc_period(
            year=self.year,
            month=self.month,
            month_start=self.month_start,
            month_end=self.month_end,
        )

    def as_tuple(self) -> tuple[Any, ...]:
        return (
            self.job_id,
            self.flow_type,
            self.currency,
            self.year,
            self.month,
            self.month_start,
            self.month_end,
            self.hs_code,
            self.hs_name,
            self.partner_code,
            self.partner_name,
            self.trade_mode_code,
            self.trade_mode_name,
            self.reg_place_code,
            self.reg_place_name,
            self.qty1,
            self.unit1,
            self.qty2,
            self.unit2,
            self.value,
            self.fetched_at,
        )


@dataclass
class GaccJobStatus:
    id: str
    status: str
    message: str = ""
    record_count: int = 0
    error_message: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "record_count": self.record_count,
            "error_message": self.error_message,
            "params": self.params,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }
