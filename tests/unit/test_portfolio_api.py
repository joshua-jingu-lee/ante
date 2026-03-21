"""포트폴리오 API 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

_SNAPSHOT = {
    "account_id": "acc-001",
    "snapshot_date": "2026-03-20",
    "total_asset": 50_000_000.0,
    "ante_eval_amount": 40_000_000.0,
    "ante_purchase_amount": 38_000_000.0,
    "unallocated": 10_000_000.0,
    "account_balance": 10_000_000.0,
    "total_allocated": 40_000_000.0,
    "bot_count": 3,
    "daily_pnl": 500_000.0,
    "daily_return": 1.01,
    "net_trade_amount": 200_000.0,
    "unrealized_pnl": 2_000_000.0,
    "created_at": "2026-03-20T18:00:00+09:00",
}


@pytest.fixture
def treasury():
    mock = MagicMock()
    mock.get_summary.return_value = {
        "total_evaluation": 50_000_000.0,
        "total_profit_loss": 500_000.0,
        "account_balance": 10_000_000.0,
    }
    mock.get_latest_snapshot = AsyncMock(return_value=_SNAPSHOT)
    mock.get_snapshots = AsyncMock(return_value=[_SNAPSHOT])
    return mock


@pytest.fixture
def app(treasury):
    return create_app(treasury=treasury)


@pytest.fixture
def client(app):
    return TestClient(app)


class TestPortfolioValue:
    def test_returns_total_value(self, client):
        """총 자산 가치 반환."""
        resp = client.get("/api/portfolio/value")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_value"] == 50_000_000.0
        assert data["daily_pnl"] == 500_000.0
        assert "daily_return" in data
        assert "updated_at" in data

    def test_snapshot_fields(self, client):
        """스냅샷 기반 필드 반환."""
        resp = client.get("/api/portfolio/value")
        data = resp.json()
        assert data["daily_return"] == 1.01
        assert data["unrealized_pnl"] == 2_000_000.0
        assert data["snapshot_date"] == "2026-03-20"

    def test_no_snapshot_fallback_to_summary(self, client, treasury):
        """스냅샷이 없으면 get_summary() fallback으로 기본 응답을 반환한다."""
        treasury.get_latest_snapshot = AsyncMock(return_value=None)
        resp = client.get("/api/portfolio/value")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_value"] == 50_000_000.0
        assert data["daily_pnl"] == 0.0
        assert data["daily_return"] == 0.0
        assert data["unrealized_pnl"] == 0.0
        assert "updated_at" in data
        treasury.get_summary.assert_called_once()


class TestPortfolioHistory:
    def test_returns_time_series(self, client):
        """시계열 데이터 반환."""
        resp = client.get(
            "/api/portfolio/history",
            params={"start_date": "2026-03-01", "end_date": "2026-03-20"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["date"] == "2026-03-20"
        assert data["start_date"] == "2026-03-01"
        assert data["end_date"] == "2026-03-20"

    def test_empty_snapshots(self, client, treasury):
        """스냅샷이 없으면 빈 데이터."""
        treasury.get_snapshots = AsyncMock(return_value=[])
        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []
