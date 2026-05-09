"""리포트 API 테스트."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.report.models import ReportStatus, StrategyReport  # noqa: E402
from ante.web.app import create_app  # noqa: E402


@pytest.fixture
async def db(tmp_path):
    from ante.core import Database

    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def report_store(db):
    from ante.report.store import ReportStore

    store = ReportStore(db)
    await store.initialize()
    return store


@pytest.fixture
def app(report_store):
    return create_app(report_store=report_store)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
async def sample_report(report_store):
    """테스트용 리포트 생성."""
    report = StrategyReport(
        report_id="rpt-test-001",
        strategy_name="momentum_breakout_v2",
        strategy_version="v2.0",
        strategy_path="/strategies/momentum_breakout_v2.py",
        status=ReportStatus.SUBMITTED,
        submitted_at=datetime(2026, 3, 13, 9, 20, tzinfo=UTC),
        submitted_by="strategy-dev-01",
        backtest_period="2024-01 ~ 2026-03",
        total_return_pct=42.3,
        total_trades=127,
        sharpe_ratio=1.72,
        max_drawdown_pct=-6.8,
        win_rate=62.2,
        summary="모멘텀 돌파 전략 요약",
        rationale="거래량 필터 추가",
        risks="변동성 구간 MDD 증가",
        recommendations="모의투자 1개월 검증 후 실전 전환",
        detail_json=json.dumps(
            {
                "equity_curve": [
                    {"date": "2024-01-02", "value": 10000000},
                    {"date": "2024-06-30", "value": 12500000},
                ],
                "metrics": {
                    "sharpe_ratio": 1.72,
                    "max_drawdown": -6.8,
                    "win_rate": 62.2,
                    "profit_factor": 1.85,
                },
                "initial_balance": 10000000,
                "final_balance": 14230000,
                "config": {
                    "strategy_path": "/strategies/momentum_breakout_v2.py",
                    "symbols": ["005930", "000660"],
                    "initial_balance": 10000000,
                    "buy_commission_rate": 0.00015,
                    "sell_commission_rate": 0.00195,
                    "slippage_rate": 0.001,
                },
                "datasets": [
                    {
                        "symbol": "005930",
                        "timeframe": "1d",
                        "row_count": 543,
                    },
                    {
                        "symbol": "000660",
                        "timeframe": "1d",
                        "row_count": 543,
                    },
                ],
                "symbols": [
                    {
                        "symbol": "005930",
                        "name": "삼성전자",
                        "timeframe": "1일",
                        "period": "2024-01-02 ~ 2026-03-12",
                        "rows": 543,
                    },
                    {
                        "symbol": "000660",
                        "name": "SK하이닉스",
                        "timeframe": "1일",
                        "period": "2024-01-02 ~ 2026-03-12",
                        "rows": 543,
                    },
                ],
            }
        ),
    )
    await report_store.submit(report)
    return report


class TestGetReport:
    """GET /api/reports/{report_id} 테스트."""

    def test_get_existing(self, client, sample_report):
        res = client.get(f"/api/reports/{sample_report.report_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["report_id"] == sample_report.report_id
        assert data["strategy_name"] == "momentum_breakout_v2"
        assert data["strategy_version"] == "v2.0"
        assert data["total_return_pct"] == 42.3
        assert data["total_trades"] == 127
        assert data["sharpe_ratio"] == 1.72
        assert data["summary"] == "모멘텀 돌파 전략 요약"

    def test_get_equity_curve(self, client, sample_report):
        res = client.get(f"/api/reports/{sample_report.report_id}")
        data = res.json()
        assert len(data["equity_curve"]) == 2
        assert data["equity_curve"][0]["date"] == "2024-01-02"
        assert data["equity_curve"][0]["value"] == 10000000

    def test_get_metrics(self, client, sample_report):
        res = client.get(f"/api/reports/{sample_report.report_id}")
        data = res.json()
        assert data["metrics"]["profit_factor"] == 1.85
        assert data["initial_balance"] == 10000000
        assert data["final_balance"] == 14230000

    def test_get_symbols(self, client, sample_report):
        res = client.get(f"/api/reports/{sample_report.report_id}")
        data = res.json()
        assert len(data["symbols"]) == 2
        assert data["symbols"][0]["symbol"] == "005930"

    def test_get_config(self, client, sample_report):
        """detail_json의 config 필드가 응답에 포함되는지 확인."""
        res = client.get(f"/api/reports/{sample_report.report_id}")
        data = res.json()
        assert data["config"] is not None
        assert data["config"]["strategy_path"] == "/strategies/momentum_breakout_v2.py"
        assert data["config"]["symbols"] == ["005930", "000660"]
        assert data["config"]["initial_balance"] == 10000000
        assert data["config"]["buy_commission_rate"] == 0.00015
        assert data["config"]["sell_commission_rate"] == 0.00195
        assert data["config"]["slippage_rate"] == 0.001

    def test_get_datasets(self, client, sample_report):
        """detail_json의 datasets 필드가 응답에 포함되는지 확인."""
        res = client.get(f"/api/reports/{sample_report.report_id}")
        data = res.json()
        assert len(data["datasets"]) == 2
        assert data["datasets"][0]["symbol"] == "005930"
        assert data["datasets"][0]["timeframe"] == "1d"
        assert data["datasets"][0]["row_count"] == 543
        assert data["datasets"][1]["symbol"] == "000660"

    def test_get_nonexistent(self, client):
        res = client.get("/api/reports/nonexistent-id")
        assert res.status_code == 404

    def test_get_agent_commentary(self, client, sample_report):
        res = client.get(f"/api/reports/{sample_report.report_id}")
        data = res.json()
        assert data["risks"] == "변동성 구간 MDD 증가"
        assert data["recommendations"] == "모의투자 1개월 검증 후 실전 전환"
