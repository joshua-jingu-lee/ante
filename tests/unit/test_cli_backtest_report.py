"""CLI backtest history / report submit --run 커맨드 테스트."""

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


class TestBacktestHistory:
    def test_history_empty(self, runner):
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = []
            result = runner.invoke(cli, ["backtest", "history", "test_stg"])
            assert result.exit_code == 0
            assert "이력이 없습니다" in result.output

    def test_history_with_results(self, runner):
        rows = [
            {
                "run_id": "run-1",
                "strategy_name": "momentum",
                "strategy_version": "1.0.0",
                "params_json": "{}",
                "total_return_pct": 15.0,
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": -8.5,
                "total_trades": 42,
                "win_rate": 0.58,
                "result_path": "",
                "created_at": "2026-03-19T00:00:00",
            },
        ]
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = rows
            result = runner.invoke(cli, ["backtest", "history", "momentum"])
            assert result.exit_code == 0
            assert "run-1" in result.output

    def test_history_json_format(self, runner):
        rows = [
            {
                "run_id": "run-1",
                "strategy_name": "momentum",
                "strategy_version": "1.0.0",
                "params_json": "{}",
                "total_return_pct": 15.0,
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": -8.5,
                "total_trades": 42,
                "win_rate": 0.58,
                "result_path": "",
                "created_at": "2026-03-19T00:00:00",
            },
        ]
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = rows
            result = runner.invoke(
                cli, ["--format", "json", "backtest", "history", "momentum"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["strategy_name"] == "momentum"
            assert len(data["runs"]) == 1


class TestReportSubmitWithRun:
    def test_submit_with_run_option(self, runner, tmp_path):
        report_file = tmp_path / "report.json"
        report_file.write_text(
            json.dumps(
                {
                    "strategy_name": "momentum",
                    "strategy_version": "1.0.0",
                    "strategy_path": "strategies/momentum.py",
                    "backtest_period": "2025-01 ~ 2025-12",
                    "total_return_pct": 15.0,
                    "total_trades": 42,
                    "summary": "테스트 리포트",
                    "rationale": "테스트",
                }
            )
        )

        with patch("asyncio.run") as mock_run:
            mock_run.return_value = {
                "report_id": "rpt-123",
                "strategy": "momentum",
                "status": "submitted",
                "backtest_run_id": "run-1",
            }
            result = runner.invoke(
                cli,
                ["report", "submit", str(report_file), "--run", "run-1"],
            )
            assert result.exit_code == 0
            assert "rpt-123" in result.output
