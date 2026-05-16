"""`ante report performance` period별 옵션 배타 검증 단위 테스트 (#1593).

`--start`/`--end`는 `--period daily` 전용, `--year`는 `--period monthly`
전용이다. period와 맞지 않는 옵션 조합은 DB 접근 이전에
``CLI_OPTION_CONFLICT`` + exit 1로 거부되어야 한다.

회귀: period에 맞는 유효 조합은 그대로 통과해야 한다.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

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


def _assert_conflict_json(result) -> None:
    """JSON 포맷 충돌 응답 공통 검증."""
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["code"] == "CLI_OPTION_CONFLICT"


class TestPeriodOptionConflictRejected:
    """period와 맞지 않는 옵션 조합은 exit 1 + CLI_OPTION_CONFLICT."""

    def test_monthly_with_start_and_end(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "monthly",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-31",
                ],
            )
        _assert_conflict_json(result)
        assert "--start/--end" in result.output
        mock_run.assert_not_called()

    def test_monthly_with_start_only(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "monthly",
                    "--start",
                    "2026-01-01",
                ],
            )
        _assert_conflict_json(result)
        mock_run.assert_not_called()

    def test_monthly_with_end_only(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "monthly",
                    "--end",
                    "2026-01-31",
                ],
            )
        _assert_conflict_json(result)
        mock_run.assert_not_called()

    def test_daily_with_year(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--year",
                    "2026",
                ],
            )
        _assert_conflict_json(result)
        assert "--year" in result.output
        mock_run.assert_not_called()

    def test_year_without_period_defaults_daily(self, runner):
        """`--period` 생략 시 기본값 daily이므로 `--year`는 충돌로 거부."""
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--year",
                    "2026",
                ],
            )
        _assert_conflict_json(result)
        mock_run.assert_not_called()

    def test_conflict_does_not_touch_db(self, runner):
        """진입 검증이 _run_performance(Database/asyncio.run) 이전임을 고정."""
        with (
            patch("ante.cli.commands.report.asyncio.run") as mock_run,
            patch("ante.core.database.Database") as mock_db,
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "monthly",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-31",
                ],
            )
        assert result.exit_code == 1
        mock_run.assert_not_called()
        mock_db.assert_not_called()

    def test_conflict_text_format(self, runner):
        """text 포맷에서도 exit 1로 거부된다 (formatter.error text 경로)."""
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "report",
                    "performance",
                    "--period",
                    "monthly",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-31",
                ],
            )
        assert result.exit_code == 1
        assert "--start/--end" in result.output
        mock_run.assert_not_called()

    def test_daily_year_conflict_text_format(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--year",
                    "2026",
                ],
            )
        assert result.exit_code == 1
        assert "--year" in result.output
        mock_run.assert_not_called()


class TestValidPeriodOptionCombosRegression:
    """period에 맞는 유효 조합은 회귀 없이 통과한다."""

    def test_daily_with_start_and_end(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "date": "2026-01-15",
                    "realized_pnl": 12000.0,
                    "trade_count": 2,
                    "win_rate": 0.5,
                }
            ]
            result = runner.invoke(
                cli,
                [
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-31",
                ],
            )
        assert result.exit_code == 0
        assert "2026-01-15" in result.output
        mock_run.assert_called_once()

    def test_monthly_with_year(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "year": 2026,
                    "month": 1,
                    "realized_pnl": 50000.0,
                    "trade_count": 10,
                    "win_rate": 0.7,
                }
            ]
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "monthly",
                    "--year",
                    "2026",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["period"] == "monthly"
        assert data["summaries"][0]["year"] == 2026
        mock_run.assert_called_once()

    def test_daily_with_bot_id_and_dates(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "date": "2026-01-10",
                    "realized_pnl": 3000.0,
                    "trade_count": 1,
                    "win_rate": 1.0,
                }
            ]
            result = runner.invoke(
                cli,
                [
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--bot-id",
                    "b1",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-31",
                ],
            )
        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_daily_default_no_options(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.return_value = []
            result = runner.invoke(cli, ["report", "performance"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_monthly_default_no_options(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            mock_run.return_value = []
            result = runner.invoke(
                cli,
                ["report", "performance", "--period", "monthly"],
            )
        assert result.exit_code == 0
        mock_run.assert_called_once()
