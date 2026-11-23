"""일별/주별/월별 성과 집계 단위 테스트."""

from __future__ import annotations

import json
import re
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core.database import OperationalError
from ante.member.models import Member, MemberRole, MemberType
from ante.trade.models import (
    DailySummary,
    MonthlySummary,
    TradeRecord,
    TradeStatus,
)
from ante.trade.performance import PerformanceTracker
from tests.unit._async_test_utils import asyncio_run_returning

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture
def runner():
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


class TestGetDailySummary:
    @pytest.mark.asyncio
    async def test_daily_summary_basic(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(
            return_value=[
                {
                    "trade_date": "2026-03-10",
                    "realized_pnl": 15000.0,
                    "trade_count": 3,
                    "win_count": 2,
                },
                {
                    "trade_date": "2026-03-11",
                    "realized_pnl": -5000.0,
                    "trade_count": 2,
                    "win_count": 0,
                },
            ]
        )

        tracker = PerformanceTracker(db)
        result = await tracker.get_daily_summary()

        assert len(result) == 2
        assert isinstance(result[0], DailySummary)
        assert result[0].date == "2026-03-10"
        assert result[0].realized_pnl == 15000.0
        assert result[0].trade_count == 3
        assert result[0].win_rate == pytest.approx(2 / 3)
        assert result[1].win_rate == 0.0

    @pytest.mark.asyncio
    async def test_daily_summary_with_bot_filter(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        result = await tracker.get_daily_summary(bot_id="bot-1")

        assert result == []
        call_args = db.fetch_all.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "t.bot_id = ?" in query
        assert "bot-1" in params

    @pytest.mark.asyncio
    async def test_daily_summary_with_date_range(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        await tracker.get_daily_summary(start_date="2026-03-01", end_date="2026-03-31")

        call_args = db.fetch_all.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "date(t.timestamp) >= ?" in query
        assert "date(t.timestamp) <= ?" in query
        assert "2026-03-01" in params
        assert "2026-03-31" in params

    @pytest.mark.asyncio
    async def test_daily_summary_empty(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        result = await tracker.get_daily_summary()

        assert result == []


class TestGetWeeklySummary:
    @pytest.mark.asyncio
    async def test_weekly_summary_basic(self):
        from ante.trade.models import WeeklySummary

        db = AsyncMock()
        db.fetch_all = AsyncMock(
            return_value=[
                {
                    "week_start": "2026-03-09",
                    "week_end": "2026-03-15",
                    "realized_pnl": 30000.0,
                    "trade_count": 5,
                    "win_count": 3,
                },
                {
                    "week_start": "2026-03-16",
                    "week_end": "2026-03-22",
                    "realized_pnl": -10000.0,
                    "trade_count": 4,
                    "win_count": 1,
                },
            ]
        )

        tracker = PerformanceTracker(db)
        result = await tracker.get_weekly_summary()

        assert len(result) == 2
        assert isinstance(result[0], WeeklySummary)
        assert result[0].week_start == "2026-03-09"
        assert result[0].week_end == "2026-03-15"
        assert result[0].realized_pnl == 30000.0
        assert result[0].trade_count == 5
        assert result[0].win_rate == pytest.approx(3 / 5)
        assert result[0].week_label == "03-09 ~ 03-15"
        assert result[1].win_rate == pytest.approx(1 / 4)

    @pytest.mark.asyncio
    async def test_weekly_summary_with_bot_filter(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        result = await tracker.get_weekly_summary(bot_id="bot-1")

        assert result == []
        call_args = db.fetch_all.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "t.bot_id = ?" in query
        assert "bot-1" in params

    @pytest.mark.asyncio
    async def test_weekly_summary_empty(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        result = await tracker.get_weekly_summary()

        assert result == []

    @pytest.mark.asyncio
    async def test_weekly_summary_query_groups_by_week(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        await tracker.get_weekly_summary()

        call_args = db.fetch_all.call_args
        query = call_args[0][0]
        assert "week_start" in query
        assert "GROUP BY week_start" in query


class TestGetMonthlySummary:
    @pytest.mark.asyncio
    async def test_monthly_summary_basic(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(
            return_value=[
                {
                    "yr": 2026,
                    "mo": 1,
                    "realized_pnl": 50000.0,
                    "trade_count": 10,
                    "win_count": 7,
                },
                {
                    "yr": 2026,
                    "mo": 2,
                    "realized_pnl": -20000.0,
                    "trade_count": 8,
                    "win_count": 3,
                },
            ]
        )

        tracker = PerformanceTracker(db)
        result = await tracker.get_monthly_summary()

        assert len(result) == 2
        assert isinstance(result[0], MonthlySummary)
        assert result[0].year == 2026
        assert result[0].month == 1
        assert result[0].realized_pnl == 50000.0
        assert result[0].trade_count == 10
        assert result[0].win_rate == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_monthly_summary_with_year_filter(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        await tracker.get_monthly_summary(year=2026)

        call_args = db.fetch_all.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "strftime('%Y', t.timestamp) = ?" in query
        assert "2026" in params

    @pytest.mark.asyncio
    async def test_monthly_summary_with_bot_filter(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        await tracker.get_monthly_summary(bot_id="bot-1")

        call_args = db.fetch_all.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "t.bot_id = ?" in query
        assert "bot-1" in params

    @pytest.mark.asyncio
    async def test_monthly_summary_empty(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        result = await tracker.get_monthly_summary()

        assert result == []


class TestReportPerformanceCLI:
    def test_daily_performance_text(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.side_effect = asyncio_run_returning(
                [
                    {
                        "date": "2026-03-10",
                        "realized_pnl": 15000.0,
                        "trade_count": 3,
                        "win_rate": 0.67,
                    }
                ]
            )
            result = runner.invoke(cli, ["report", "performance", "--period", "daily"])
            assert result.exit_code == 0
            assert "2026-03-10" in result.output

    def test_monthly_performance_json(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.side_effect = asyncio_run_returning(
                [
                    {
                        "year": 2026,
                        "month": 3,
                        "realized_pnl": 50000.0,
                        "trade_count": 10,
                        "win_rate": 0.7,
                    }
                ]
            )
            result = runner.invoke(
                cli,
                ["--format", "json", "report", "performance", "--period", "monthly"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)["data"]
            assert data["period"] == "monthly"
            assert len(data["summaries"]) == 1
            assert data["summaries"][0]["year"] == 2026

    def test_performance_empty(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.side_effect = asyncio_run_returning([])
            result = runner.invoke(cli, ["report", "performance"])
            assert result.exit_code == 0
            assert "없습니다" in result.output

    def test_daily_with_bot_filter(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.side_effect = asyncio_run_returning(
                [
                    {
                        "date": "2026-03-10",
                        "realized_pnl": 5000.0,
                        "trade_count": 1,
                        "win_rate": 1.0,
                    }
                ]
            )
            result = runner.invoke(
                cli,
                ["report", "performance", "--bot-id", "bot-1"],
            )
            assert result.exit_code == 0

    def test_monthly_with_year_filter(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.side_effect = asyncio_run_returning(
                [
                    {
                        "year": 2025,
                        "month": 12,
                        "realized_pnl": 100000.0,
                        "trade_count": 20,
                        "win_rate": 0.6,
                    }
                ]
            )
            result = runner.invoke(
                cli,
                [
                    "report",
                    "performance",
                    "--period",
                    "monthly",
                    "--year",
                    "2025",
                ],
            )
            assert result.exit_code == 0


class TestSummaryStrategyIdFilter:
    """get_*_summary 의 strategy_id 필터 (#2144).

    ``trades.strategy_id`` (거래 시점 전략 귀속 durable key) 로 전략 전체
    거래를 집계한다. 봇 멤버십/상태와 무관하며, bot_id/account_id 와 함께
    전달되면 AND 로 결합된다.
    """

    @pytest.mark.asyncio
    async def test_daily_summary_with_strategy_filter(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        result = await tracker.get_daily_summary(strategy_id="strat-1")

        assert result == []
        query, params = db.fetch_all.call_args[0]
        assert "t.strategy_id = ?" in query
        assert "strat-1" in params

    @pytest.mark.asyncio
    async def test_weekly_summary_with_strategy_filter(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        result = await tracker.get_weekly_summary(strategy_id="strat-1")

        assert result == []
        query, params = db.fetch_all.call_args[0]
        assert "t.strategy_id = ?" in query
        assert "strat-1" in params

    @pytest.mark.asyncio
    async def test_monthly_summary_with_strategy_filter(self):
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        result = await tracker.get_monthly_summary(strategy_id="strat-1")

        assert result == []
        query, params = db.fetch_all.call_args[0]
        assert "t.strategy_id = ?" in query
        assert "strat-1" in params

    @pytest.mark.asyncio
    async def test_daily_summary_bot_and_strategy_are_anded(self):
        """bot_id + strategy_id 동시 전달 시 둘 다 AND 로 적용."""
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        await tracker.get_daily_summary(bot_id="bot-1", strategy_id="strat-1")

        query, params = db.fetch_all.call_args[0]
        assert "t.bot_id = ?" in query
        assert "t.strategy_id = ?" in query
        assert "bot-1" in params
        assert "strat-1" in params

    @pytest.mark.asyncio
    async def test_monthly_summary_year_and_strategy_are_anded(self):
        """year + strategy_id 동시 전달 시 둘 다 AND 로 적용."""
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        await tracker.get_monthly_summary(year=2026, strategy_id="strat-1")

        query, params = db.fetch_all.call_args[0]
        assert "strftime('%Y', t.timestamp) = ?" in query
        assert "t.strategy_id = ?" in query
        assert "2026" in params
        assert "strat-1" in params

    @pytest.mark.asyncio
    async def test_daily_summary_no_strategy_filter_omits_condition(self):
        """strategy_id 미전달(기존 호출자) 시 strategy_id 조건 미포함 (무회귀)."""
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        await tracker.get_daily_summary(bot_id="bot-1")

        query, params = db.fetch_all.call_args[0]
        assert "t.strategy_id = ?" not in query
        assert "strat-1" not in params


_MISSING_TABLE = "no such table: trades"
_RAISED_MESSAGES = [
    pytest.param("database is locked", id="locked"),
    pytest.param("disk I/O error", id="io"),
    pytest.param("no such column: ph.pnl", id="no-column"),
]


async def _summary_daily(tracker: PerformanceTracker) -> object:
    return await tracker.get_daily_summary()


async def _summary_weekly(tracker: PerformanceTracker) -> object:
    return await tracker.get_weekly_summary()


async def _summary_monthly(tracker: PerformanceTracker) -> object:
    return await tracker.get_monthly_summary()


async def _filled_trades(tracker: PerformanceTracker) -> object:
    return await tracker._get_filled_trades(account_id="acc-test")


_FETCH_ALL_SITES = [
    pytest.param(_summary_daily, id="daily"),
    pytest.param(_summary_weekly, id="weekly"),
    pytest.param(_summary_monthly, id="monthly"),
    pytest.param(_filled_trades, id="filled-trades"),
]


def _sell_trade(commission: float) -> TradeRecord:
    return TradeRecord(
        trade_id=uuid4(),
        bot_id="bot-1",
        strategy_id="strat-1",
        symbol="005930",
        side="sell",
        quantity=10.0,
        price=70000.0,
        status=TradeStatus.FILLED,
        commission=commission,
        timestamp=datetime(2026, 3, 23, 11, 0, 0),
        account_id="acc-test",
    )


class TestOperationalErrorOnlyMissingTableIsEmpty:
    """테이블 없음만 빈 결과로 보고 그 밖의 OperationalError는 올린다 (#2660)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("site", _FETCH_ALL_SITES)
    async def test_missing_table_is_empty(self, site):
        db = AsyncMock()
        db.fetch_all = AsyncMock(side_effect=OperationalError(_MISSING_TABLE))

        assert await site(PerformanceTracker(db)) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("message", _RAISED_MESSAGES)
    @pytest.mark.parametrize("site", _FETCH_ALL_SITES)
    async def test_other_operational_error_is_raised(self, site, message):
        db = AsyncMock()
        db.fetch_all = AsyncMock(side_effect=OperationalError(message))

        with pytest.raises(OperationalError, match=f"^{re.escape(message)}$"):
            await site(PerformanceTracker(db))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("commission", "expected"),
        [
            pytest.param(150.0, -150.0, id="commission"),
            pytest.param(0.0, 0.0, id="zero"),
        ],
    )
    @pytest.mark.parametrize(
        "message",
        [
            pytest.param(_MISSING_TABLE, id="trades"),
            pytest.param("no such table: position_history", id="position-history"),
        ],
    )
    async def test_pnl_missing_table_counts_commission_only(
        self, message, commission, expected
    ):
        db = AsyncMock()
        db.fetch_one = AsyncMock(side_effect=OperationalError(message))

        pnl = await PerformanceTracker(db)._calculate_pnl_per_trade(
            [_sell_trade(commission)], "bot-1"
        )

        assert pnl == [expected]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("message", _RAISED_MESSAGES)
    async def test_pnl_other_operational_error_is_raised(self, message):
        db = AsyncMock()
        db.fetch_one = AsyncMock(side_effect=OperationalError(message))

        with pytest.raises(OperationalError, match=f"^{re.escape(message)}$"):
            await PerformanceTracker(db)._calculate_pnl_per_trade(
                [_sell_trade(150.0)], "bot-1"
            )
