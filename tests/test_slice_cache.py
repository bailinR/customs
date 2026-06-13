"""Negative-cache behavior for data_slices."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_slice_ok_is_not_refetched(storage) -> None:
    storage.upsert_slice(
        reporter_code=842,
        year=2024,
        flow_code="X",
        status="ok",
        record_count=120,
        fetched_at=_iso(30),
    )
    assert storage.slice_needs_fetch(842, 2024, "X") is False


def test_empty_slice_respects_ttl(storage) -> None:
    storage.upsert_slice(
        reporter_code=156,
        year=2025,
        flow_code="M",
        status="empty",
        fetched_at=_iso(1),
    )
    assert storage.slice_needs_fetch(156, 2025, "M") is False

    storage.upsert_slice(
        reporter_code=156,
        year=2025,
        flow_code="M",
        status="empty",
        fetched_at=_iso(8),
    )
    assert storage.slice_needs_fetch(156, 2025, "M") is True


def test_force_refresh_bypasses_ok_cache(storage) -> None:
    storage.upsert_slice(
        reporter_code=842,
        year=2024,
        flow_code="X",
        status="ok",
        record_count=50,
    )
    assert storage.slice_needs_fetch(842, 2024, "X", force_refresh=True) is True
