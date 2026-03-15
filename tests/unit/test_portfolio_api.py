"""포트폴리오 API 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ante.web.app import create_app


@pytest.fixture
def treasury():
    mock = MagicMock()
    mock.get_summary.return_value = {
        "total_evaluation": 50_000_000.0,
        "total_profit_loss": 500_000.0,
        "account_balance": 10_000_000.0,
    }
    return mock


@pytest.fixture
def trade_service():
    return MagicMock()


@pytest.fixture
def bot_manager():
    mock = MagicMock()
    mock.list_bots.return_value = [
        {"bot_id": "bot-001"},
    ]
    return mock


@pytest.fixture
def report_store():
    return MagicMock()


@pytest.fixture
def app(treasury, trade_service, bot_manager, report_store):
    return create_app(
        treasury=treasury,
        trade_service=trade_service,
        bot_manager=bot_manager,
        report_store=report_store,
    )


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
        assert "daily_pnl_pct" in data
        assert "updated_at" in data

    def test_pnl_percentage(self, client):
        """손익 비율 계산."""
        resp = client.get("/api/portfolio/value")
        data = resp.json()
        expected_pct = round(500_000.0 / 50_000_000.0 * 100, 4)
        assert data["daily_pnl_pct"] == expected_pct

    def test_zero_total_value(self, client, treasury):
        """총 자산이 0일 때 pnl_pct는 0."""
        treasury.get_summary.return_value = {
            "total_evaluation": 0.0,
            "total_profit_loss": 0.0,
        }
        resp = client.get("/api/portfolio/value")
        data = resp.json()
        assert data["daily_pnl_pct"] == 0.0


class TestPortfolioHistory:
    def test_empty_bots(self, client, bot_manager):
        """봇이 없을 때 빈 데이터."""
        bot_manager.list_bots.return_value = []
        resp = client.get("/api/portfolio/history?period=1m")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []
        assert data["period"] == "1m"

    def test_with_equity_data(self, client):
        """equity curve 데이터가 있는 경우."""
        mock_curve = [
            {"date": "2026-03-01", "value": 10_000_000.0},
            {"date": "2026-03-10", "value": 10_500_000.0},
            {"date": "2026-03-14", "value": 10_200_000.0},
        ]
        with patch(
            "ante.report.feedback.PerformanceFeedback", autospec=True
        ) as mock_feedback_cls:
            instance = mock_feedback_cls.return_value
            instance.get_equity_curve = AsyncMock(return_value=mock_curve)

            resp = client.get("/api/portfolio/history?period=1m")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["data"]) == 3
            assert data["data"][0]["date"] == "2026-03-01"

    def test_invalid_period(self, client):
        """잘못된 기간 값은 422."""
        resp = client.get("/api/portfolio/history?period=2y")
        assert resp.status_code == 422

    def test_all_period(self, client):
        """period=all은 필터 없이 전체 반환."""
        mock_curve = [
            {"date": "2025-01-01", "value": 5_000_000.0},
            {"date": "2026-03-14", "value": 10_000_000.0},
        ]
        with patch(
            "ante.report.feedback.PerformanceFeedback", autospec=True
        ) as mock_feedback_cls:
            instance = mock_feedback_cls.return_value
            instance.get_equity_curve = AsyncMock(return_value=mock_curve)

            resp = client.get("/api/portfolio/history?period=all")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["data"]) == 2
