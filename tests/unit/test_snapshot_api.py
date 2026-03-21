"""일별 자산 스냅샷 및 포트폴리오 API 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

# ── 공통 픽스처 ─────────────────────────────────────────


_SNAPSHOT_20260320 = {
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

_SNAPSHOT_20260319 = {
    "account_id": "acc-001",
    "snapshot_date": "2026-03-19",
    "total_asset": 49_500_000.0,
    "ante_eval_amount": 39_500_000.0,
    "ante_purchase_amount": 37_500_000.0,
    "unallocated": 10_000_000.0,
    "account_balance": 10_000_000.0,
    "total_allocated": 39_500_000.0,
    "bot_count": 3,
    "daily_pnl": 300_000.0,
    "daily_return": 0.61,
    "net_trade_amount": 100_000.0,
    "unrealized_pnl": 1_500_000.0,
    "created_at": "2026-03-19T18:00:00+09:00",
}


@pytest.fixture
def treasury():
    mock = MagicMock()
    mock.account_id = "acc-001"
    mock.get_summary.return_value = {
        "total_evaluation": 50_000_000.0,
        "total_profit_loss": 500_000.0,
        "account_balance": 10_000_000.0,
    }
    mock.get_latest_snapshot = AsyncMock(return_value=_SNAPSHOT_20260320)
    mock.get_daily_snapshot = AsyncMock(return_value=_SNAPSHOT_20260320)
    mock.get_snapshots = AsyncMock(
        return_value=[_SNAPSHOT_20260319, _SNAPSHOT_20260320]
    )
    return mock


@pytest.fixture
def app(treasury):
    return create_app(treasury=treasury)


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Treasury 스냅샷 API 테스트 ──────────────────────────


class TestTreasurySnapshotLatest:
    def test_returns_latest_snapshot(self, client, treasury):
        """최신 스냅샷 반환."""
        resp = client.get("/api/treasury/snapshots/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshot"]["snapshot_date"] == "2026-03-20"
        assert data["snapshot"]["total_asset"] == 50_000_000.0
        assert data["snapshot"]["daily_pnl"] == 500_000.0
        treasury.get_latest_snapshot.assert_awaited_once()

    def test_fallback_to_summary_when_no_snapshot(self, client, treasury):
        """스냅샷이 없으면 get_summary() fallback으로 기본 응답을 반환한다."""
        treasury.get_latest_snapshot = AsyncMock(return_value=None)
        resp = client.get("/api/treasury/snapshots/latest")
        assert resp.status_code == 200
        data = resp.json()
        snapshot = data["snapshot"]
        assert snapshot["total_asset"] == 50_000_000.0
        assert snapshot["daily_pnl"] == 0.0
        assert snapshot["daily_return"] == 0.0
        treasury.get_summary.assert_called_once()


class TestTreasurySnapshotList:
    def test_returns_snapshots_with_date_range(self, client, treasury):
        """날짜 범위로 스냅샷 목록 조회."""
        resp = client.get(
            "/api/treasury/snapshots",
            params={"start_date": "2026-03-19", "end_date": "2026-03-20"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["snapshots"]) == 2
        assert data["snapshots"][0]["snapshot_date"] == "2026-03-19"
        assert data["snapshots"][1]["snapshot_date"] == "2026-03-20"
        treasury.get_snapshots.assert_awaited_once_with("2026-03-19", "2026-03-20")

    def test_defaults_when_no_dates(self, client, treasury):
        """날짜 미지정 시 기본값으로 조회."""
        resp = client.get("/api/treasury/snapshots")
        assert resp.status_code == 200
        treasury.get_snapshots.assert_awaited_once()

    def test_returns_empty_list(self, client, treasury):
        """결과가 없으면 빈 목록."""
        treasury.get_snapshots = AsyncMock(return_value=[])
        resp = client.get("/api/treasury/snapshots")
        assert resp.status_code == 200
        assert resp.json()["snapshots"] == []


class TestTreasurySnapshotByDate:
    def test_returns_snapshot_for_date(self, client, treasury):
        """특정일 스냅샷 조회."""
        resp = client.get("/api/treasury/snapshots/2026-03-20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshot"]["snapshot_date"] == "2026-03-20"
        treasury.get_daily_snapshot.assert_awaited_once_with("2026-03-20")

    def test_returns_404_when_not_found(self, client, treasury):
        """해당 날짜 스냅샷이 없으면 404."""
        treasury.get_daily_snapshot = AsyncMock(return_value=None)
        resp = client.get("/api/treasury/snapshots/2026-01-01")
        assert resp.status_code == 404


# ── Portfolio API 테스트 (스냅샷 기반) ────────────────────


class TestPortfolioValue:
    def test_returns_snapshot_based_value(self, client, treasury):
        """스냅샷 기반 총 자산 가치 반환."""
        resp = client.get("/api/portfolio/value")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_value"] == 50_000_000.0
        assert data["daily_pnl"] == 500_000.0
        assert data["daily_return"] == 1.01
        assert data["daily_pnl_pct"] == 1.01
        assert data["unrealized_pnl"] == 2_000_000.0
        assert data["snapshot_date"] == "2026-03-20"
        assert "updated_at" in data
        treasury.get_latest_snapshot.assert_awaited_once()

    def test_fallback_to_summary_when_no_snapshot(self, client, treasury):
        """스냅샷이 없으면 get_summary() fallback으로 기본 응답을 반환한다."""
        treasury.get_latest_snapshot = AsyncMock(return_value=None)
        resp = client.get("/api/portfolio/value")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_value"] == 50_000_000.0
        assert data["daily_pnl"] == 0.0
        assert data["daily_pnl_pct"] == 0.0
        assert data["daily_return"] == 0.0
        treasury.get_summary.assert_called()


class TestPortfolioHistory:
    def test_returns_snapshot_time_series(self, client, treasury):
        """스냅샷 기반 시계열 반환."""
        resp = client.get(
            "/api/portfolio/history",
            params={"start_date": "2026-03-19", "end_date": "2026-03-20"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 2
        assert data["data"][0]["date"] == "2026-03-19"
        assert data["data"][0]["total_asset"] == 49_500_000.0
        assert data["data"][0]["daily_pnl"] == 300_000.0
        assert data["start_date"] == "2026-03-19"
        assert data["end_date"] == "2026-03-20"

    def test_defaults_when_no_dates(self, client, treasury):
        """날짜 미지정 시 기본 30일 범위로 조회."""
        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "start_date" in data
        assert "end_date" in data

    def test_returns_empty_when_no_snapshots(self, client, treasury):
        """스냅샷이 없으면 빈 데이터."""
        treasury.get_snapshots = AsyncMock(return_value=[])
        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 200
        assert resp.json()["data"] == []
