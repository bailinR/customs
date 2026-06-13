"""GACC CSV parser tests."""

from __future__ import annotations

from pathlib import Path

from gacc_models import GaccQueryParams
from gacc_parser import parse_gacc_csv

FIXTURE = Path(__file__).parent / "fixtures" / "gacc_sample.csv"


def test_parse_gacc_csv_reads_hs_and_value() -> None:
    params = GaccQueryParams(
        flow_type="import",
        currency="USD",
        year=2024,
        month_start=4,
        month_end=4,
    )
    records = parse_gacc_csv(FIXTURE, job_id="testjob", params=params)
    assert len(records) == 2
    assert records[0].year == 2024
    assert records[0].month == 4
    assert records[0].month_start == 4
    assert records[0].month_end == 4
    assert records[0].hs_code == "01012900"
    assert records[0].partner_name == "中国香港"
    assert records[0].value == 11348655.0
    assert records[0].unit1 == "千克"
