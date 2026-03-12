"""Report Store 모듈 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.database import Database
from ante.report.feedback import PerformanceFeedback
from ante.report.models import ReportStatus, StrategyReport
from ante.report.store import ReportStore
from ante.trade.models import (
    PerformanceMetrics,
    PositionSnapshot,
)

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    return db


@pytest.fixture
async def store(db):
    s = ReportStore(db)
    await s.initialize()
    return s


def _make_report(
    *,
    report_id: str = "rpt-001",
    strategy_name: str = "momentum_breakout",
    strategy_version: str = "1.0.0",
    status: ReportStatus = ReportStatus.SUBMITTED,
) -> StrategyReport:
    return StrategyReport(
        report_id=report_id,
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        strategy_path="strategies/momentum_breakout.py",
        status=status,
        submitted_at=datetime.now(UTC),
        submitted_by="agent",
        backtest_period="2024-01 ~ 2026-03",
        total_return_pct=15.3,
        total_trades=42,
        sharpe_ratio=1.2,
        max_drawdown_pct=-8.5,
        win_rate=0.58,
        summary="20일 이동평균 돌파 매매 전략",
        rationale="모멘텀 효과를 활용한 추세 추종",
        risks="횡보장에서 잦은 손절 발생 가능",
        recommendations="변동성 높은 종목에 적용 권장",
        detail_json='{"equity_curve": [100, 105, 110]}',
    )


# ── ReportStore ──────────────────────────────────────


class TestReportStore:
    async def test_submit_and_get(self, store):
        """리포트 제출 및 조회."""
        report = _make_report()
        rid = await store.submit(report)
        assert rid == "rpt-001"

        fetched = await store.get("rpt-001")
        assert fetched is not None
        assert fetched.strategy_name == "momentum_breakout"
        assert fetched.total_return_pct == pytest.approx(15.3)
        assert fetched.sharpe_ratio == pytest.approx(1.2)
        assert fetched.win_rate == pytest.approx(0.58)

    async def test_get_nonexistent(self, store):
        """존재하지 않는 리포트 조회 시 None."""
        assert await store.get("nonexistent") is None

    async def test_list_reports(self, store):
        """리포트 목록 조회."""
        await store.submit(_make_report(report_id="rpt-001"))
        await store.submit(_make_report(report_id="rpt-002"))
        await store.submit(
            _make_report(
                report_id="rpt-003",
                strategy_name="mean_reversion",
            )
        )

        all_reports = await store.list_reports()
        assert len(all_reports) == 3

    async def test_list_reports_filter_strategy(self, store):
        """전략명으로 필터."""
        await store.submit(_make_report(report_id="rpt-001"))
        await store.submit(
            _make_report(
                report_id="rpt-002",
                strategy_name="mean_reversion",
            )
        )

        filtered = await store.list_reports(strategy_name="momentum_breakout")
        assert len(filtered) == 1
        assert filtered[0].report_id == "rpt-001"

    async def test_list_reports_filter_status(self, store):
        """상태로 필터."""
        await store.submit(_make_report(report_id="rpt-001"))
        await store.submit(
            _make_report(
                report_id="rpt-002",
                status=ReportStatus.ADOPTED,
            )
        )

        submitted = await store.list_reports(status=ReportStatus.SUBMITTED)
        assert len(submitted) == 1

    async def test_list_reports_pagination(self, store):
        """페이지네이션."""
        for i in range(5):
            await store.submit(_make_report(report_id=f"rpt-{i:03d}"))

        page1 = await store.list_reports(limit=2, offset=0)
        page2 = await store.list_reports(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2

    async def test_update_status(self, store):
        """리포트 상태 변경."""
        await store.submit(_make_report())

        await store.update_status(
            "rpt-001",
            ReportStatus.ADOPTED,
            user_notes="실전 적용 결정",
        )

        report = await store.get("rpt-001")
        assert report is not None
        assert report.status == ReportStatus.ADOPTED
        assert report.user_notes == "실전 적용 결정"
        assert report.reviewed_at is not None

    async def test_update_status_archived_no_reviewed_at(self, store):
        """보관 상태로 변경 시 reviewed_at 미설정."""
        await store.submit(_make_report())

        await store.update_status("rpt-001", ReportStatus.ARCHIVED)

        report = await store.get("rpt-001")
        assert report is not None
        assert report.status == ReportStatus.ARCHIVED
        assert report.reviewed_at is None

    async def test_delete(self, store):
        """리포트 삭제."""
        await store.submit(_make_report())
        await store.delete("rpt-001")

        assert await store.get("rpt-001") is None

    async def test_get_schema(self):
        """리포트 스키마 조회."""
        schema = ReportStore.get_schema()
        assert "required_fields" in schema
        assert "optional_fields" in schema
        assert "example" in schema
        assert "strategy_name" in schema["required_fields"]

    async def test_nullable_fields(self, store):
        """선택 필드 None 저장."""
        report = StrategyReport(
            report_id="rpt-null",
            strategy_name="test",
            strategy_version="0.1",
            strategy_path="strategies/test.py",
            status=ReportStatus.SUBMITTED,
            submitted_at=datetime.now(UTC),
            sharpe_ratio=None,
            max_drawdown_pct=None,
            win_rate=None,
        )
        await store.submit(report)

        fetched = await store.get("rpt-null")
        assert fetched is not None
        assert fetched.sharpe_ratio is None
        assert fetched.max_drawdown_pct is None
        assert fetched.win_rate is None


# ── Models ───────────────────────────────────────────


class TestModels:
    def test_report_status_values(self):
        """ReportStatus 값."""
        assert ReportStatus.SUBMITTED == "submitted"
        assert ReportStatus.REVIEWED == "reviewed"
        assert ReportStatus.ADOPTED == "adopted"
        assert ReportStatus.REJECTED == "rejected"
        assert ReportStatus.ARCHIVED == "archived"

    def test_strategy_report_defaults(self):
        """StrategyReport 기본값."""
        report = StrategyReport(
            report_id="rpt-001",
            strategy_name="test",
            strategy_version="1.0",
            strategy_path="strategies/test.py",
            status=ReportStatus.SUBMITTED,
            submitted_at=datetime.now(UTC),
        )
        assert report.submitted_by == "agent"
        assert report.detail_json == "{}"
        assert report.user_notes == ""


# ── PerformanceFeedback ──────────────────────────────


class TestPerformanceFeedback:
    @pytest.fixture
    def mock_trade_service(self):
        ts = AsyncMock()
        ts.get_performance = AsyncMock(
            return_value=PerformanceMetrics(
                total_trades=10,
                winning_trades=6,
                losing_trades=4,
                win_rate=0.6,
                total_pnl=50000.0,
                total_commission=1000.0,
                net_pnl=49000.0,
                avg_profit=12000.0,
                avg_loss=3000.0,
                profit_factor=2.0,
                max_drawdown=0.05,
                max_drawdown_amount=10000.0,
                sharpe_ratio=1.5,
            )
        )
        ts.get_positions = AsyncMock(
            return_value=[
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=100,
                    avg_entry_price=50000.0,
                    realized_pnl=10000.0,
                )
            ]
        )
        ts.get_trades = AsyncMock(return_value=[])
        return ts

    @pytest.fixture
    def mock_bot_manager(self):
        bm = MagicMock()
        bm.list_bots.return_value = [
            {"bot_id": "bot1", "strategy_id": "s1"},
            {"bot_id": "bot2", "strategy_id": "s2"},
        ]
        return bm

    async def test_get_bot_performance(self, mock_trade_service, mock_bot_manager):
        """봇 성과 조회."""
        fb = PerformanceFeedback(mock_trade_service, mock_bot_manager)
        result = await fb.get_bot_performance("bot1")

        assert result["bot_id"] == "bot1"
        assert result["metrics"]["total_trades"] == 10
        assert result["metrics"]["win_rate"] == 0.6
        assert result["metrics"]["net_pnl"] == 49000.0
        assert len(result["current_positions"]) == 1
        assert result["current_positions"][0]["symbol"] == "005930"

    async def test_get_strategy_performance(self, mock_trade_service, mock_bot_manager):
        """전략 성과 집계."""
        fb = PerformanceFeedback(mock_trade_service, mock_bot_manager)
        result = await fb.get_strategy_performance("s1")

        assert result["strategy_id"] == "s1"
        assert result["bot_count"] == 1  # bot1만 s1 전략

    async def test_get_trade_history(self, mock_trade_service, mock_bot_manager):
        """거래 이력 조회."""
        fb = PerformanceFeedback(mock_trade_service, mock_bot_manager)
        result = await fb.get_trade_history("bot1", limit=50)

        assert isinstance(result, list)
        mock_trade_service.get_trades.assert_called_once_with(bot_id="bot1", limit=50)
