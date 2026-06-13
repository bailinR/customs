"""GACC API smoke tests."""

from __future__ import annotations

from gacc_models import GaccQueryParams, GaccRecord
from gacc_storage import GaccStorage


def test_gacc_meta_options(client) -> None:
    res = client.get("/api/gacc/meta/options")
    assert res.status_code == 200
    body = res.json()
    assert "flow_types" in body
    assert "currencies" in body
    assert body["source"] == "stats.customs.gov.cn"
    assert "download_dir" in body
    assert body.get("captcha_mode") in ("auto", "manual")


def test_gacc_trade_list(client, tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "gacc_api.db"
    monkeypatch.setattr("config.DB_PATH", str(db_path))
    storage = GaccStorage(db_path)
    job_id = storage.create_job(
        GaccQueryParams(year=2024, month_start=12, month_end=12)
    )
    storage.insert_records(
        [
            GaccRecord(
                job_id=job_id,
                flow_type="import",
                currency="USD",
                year=2024,
                month=12,
                month_start=12,
                month_end=12,
                hs_code="01012900",
                hs_name="其他马",
                partner_code="110",
                partner_name="中国香港",
                trade_mode_code="39",
                trade_mode_name="其他",
                reg_place_code="44",
                reg_place_name="广东省",
                qty1=100.0,
                unit1="千克",
                qty2=None,
                unit2=None,
                value=50000.0,
                fetched_at="2024-12-01T00:00:00+00:00",
            )
        ]
    )

    import api.main as main

    monkeypatch.setattr(main, "_gacc_storage", storage)

    res = client.get(f"/api/gacc/trade?job_id={job_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["hs_name"] == "其他马"
    assert body["items"][0]["period_label"] == "2024年12月"


def test_gacc_trade_filter_by_period(client, tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "gacc_filter.db"
    monkeypatch.setattr("config.DB_PATH", str(db_path))
    storage = GaccStorage(db_path)
    job_id = storage.create_job(
        GaccQueryParams(year=2024, month_start=1, month_end=3, split_by_month=True)
    )
    storage.insert_records(
        [
            GaccRecord(
                job_id=job_id,
                flow_type="import",
                currency="USD",
                year=2024,
                month=2,
                month_start=1,
                month_end=3,
                hs_code="01012900",
                hs_name="其他马",
                partner_code="110",
                partner_name="中国香港",
                trade_mode_code="39",
                trade_mode_name="其他",
                reg_place_code="44",
                reg_place_name="广东省",
                qty1=100.0,
                unit1="千克",
                qty2=None,
                unit2=None,
                value=50000.0,
                fetched_at="2024-12-01T00:00:00+00:00",
            ),
            GaccRecord(
                job_id=job_id,
                flow_type="export",
                currency="CNY",
                year=2025,
                month=0,
                month_start=1,
                month_end=6,
                hs_code="02011000",
                hs_name="其他",
                partner_code=None,
                partner_name=None,
                trade_mode_code=None,
                trade_mode_name=None,
                reg_place_code=None,
                reg_place_name=None,
                qty1=1.0,
                unit1="千克",
                qty2=None,
                unit2=None,
                value=100.0,
                fetched_at="2025-01-01T00:00:00+00:00",
            ),
        ]
    )

    import api.main as main

    monkeypatch.setattr(main, "_gacc_storage", storage)

    res = client.get("/api/gacc/trade?flow_type=import&year=2024&month=2")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["hs_name"] == "其他马"

    res = client.get("/api/gacc/trade?year=2025&month=4")
    assert res.status_code == 200
    assert res.json()["total"] == 1
