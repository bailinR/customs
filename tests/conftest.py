"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from storage import TradeStorage


@pytest.fixture
def storage(tmp_path) -> TradeStorage:
    return TradeStorage(tmp_path / "test.db")


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    monkeypatch.setattr("config.DB_PATH", str(db_path))
    TradeStorage(db_path)

    import api.main as main

    monkeypatch.setattr(main, "DB_PATH", str(db_path))

    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)
