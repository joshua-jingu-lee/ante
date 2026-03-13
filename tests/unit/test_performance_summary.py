"""일별/월별 성과 집계 단위 테스트."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from ante.trade.models import DailySummary, MonthlySummary
from ante.trade.performance import PerformanceTracker

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
            mock_run.return_value = [
                {
                    "date": "2026-03-10",
                    "realized_pnl": 15000.0,
                    "trade_count": 3,
                    "win_rate": 0.67,
                }
            ]
            result = runner.invoke(cli, ["report", "performance", "--period", "daily"])
            assert result.exit_code == 0
            assert "2026-03-10" in result.output

    def test_monthly_performance_json(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "year": 2026,
                    "month": 3,
                    "realized_pnl": 50000.0,
                    "trade_count": 10,
                    "win_rate": 0.7,
                }
            ]
            result = runner.invoke(
                cli,
                ["--format", "json", "report", "performance", "--period", "monthly"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["period"] == "monthly"
            assert len(data["summaries"]) == 1
            assert data["summaries"][0]["year"] == 2026

    def test_performance_empty(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.return_value = []
            result = runner.invoke(cli, ["report", "performance"])
            assert result.exit_code == 0
            assert "없습니다" in result.output

    def test_daily_with_bot_filter(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "date": "2026-03-10",
                    "realized_pnl": 5000.0,
                    "trade_count": 1,
                    "win_rate": 1.0,
                }
            ]
            result = runner.invoke(
                cli,
                ["report", "performance", "--bot-id", "bot-1"],
            )
            assert result.exit_code == 0

    def test_monthly_with_year_filter(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "year": 2025,
                    "month": 12,
                    "realized_pnl": 100000.0,
                    "trade_count": 20,
                    "win_rate": 0.6,
                }
            ]
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
