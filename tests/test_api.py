"""FastAPI endpoint smoke tests."""

from __future__ import annotations

from storage import TradeRecord, TradeStorage


def test_health_returns_record_count(client, tmp_path) -> None:
    db_path = tmp_path / "api.db"
    storage = TradeStorage(db_path)
    storage.upsert_records(
        [
            TradeRecord(
                reporter_code=842,
                partner_code=156,
                partner_name="China",
                freq_code="A",
                year=2024,
                month=0,
                flow_code="X",
                cmd_code="TOTAL",
                trade_value_usd=1_000_000.0,
                fob_value_usd=None,
                cif_value_usd=None,
            )
        ]
    )

    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["records"] == 1


def test_meta_filters_monthly_scope(client, tmp_path) -> None:
    db_path = tmp_path / "api.db"
    storage = TradeStorage(db_path)
    storage.upsert_records(
        [
            TradeRecord(
                reporter_code=842,
                partner_code=156,
                partner_name="China",
                freq_code="A",
                year=2024,
                month=0,
                flow_code="X",
                cmd_code="TOTAL",
                trade_value_usd=100.0,
                fob_value_usd=None,
                cif_value_usd=None,
            ),
            TradeRecord(
                reporter_code=842,
                partner_code=156,
                partner_name="China",
                freq_code="M",
                year=2024,
                month=12,
                flow_code="X",
                cmd_code="TOTAL",
                trade_value_usd=200.0,
                fob_value_usd=None,
                cif_value_usd=None,
            ),
        ]
    )

    resp = client.get("/api/meta/filters", params={"freq_code": "M"})
    assert resp.status_code == 200
    body = resp.json()
    assert [m["value"] for m in body["months"]] == [12]
    assert 2024 in body["years"]


def test_sync_slice_returns_cached_without_api(client, monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "api.db"
    storage = TradeStorage(db_path)
    storage.upsert_slice(
        reporter_code=842,
        year=2024,
        flow_code="X",
        status="ok",
        record_count=88,
    )
    monkeypatch.setenv("COMTRADE_API_KEY", "test-key-for-unit-test")

    import api.main as main
    from sync_service import sync_slices

    def sync_with_test_storage(**kwargs):
        return sync_slices(storage=storage, **kwargs)

    monkeypatch.setattr(main, "sync_slices", sync_with_test_storage)

    resp = client.post(
        "/api/sync/slice",
        json={
            "reporter_code": 842,
            "year": 2024,
            "flow_code": "X",
            "freq_code": "A",
            "month": 0,
            "force_refresh": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cached"] is True
    assert body["status"] == "ok"
    assert body["slices"][0]["record_count"] == 88
