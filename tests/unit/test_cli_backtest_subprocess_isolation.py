"""#2001: ``ante backtest run`` CLI 가 D-004 subprocess 격리 경로를 사용한다.

회귀 검증 축:
- (a) CLI run 이 ``service.run_subprocess`` 를 호출하고 ``service.run`` 을
  직접 호출하지 않는다 (in-process 회귀 차단).
- (b) ``run_subprocess`` envelope 의 ``result_path`` 가 ``_save_backtest_run`` →
  ``BacktestRunStore.save`` → ``backtest_runs.result_path`` 로 전파된다 (#1998).
- (c) subprocess 실패(returncode≠0)는 ``BACKTEST_ERROR`` exit 1.
- (d) sentinel 라인 부재도 ``BACKTEST_ERROR`` exit 1.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_runner() -> CliRunner:
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


def _envelope(*, result_path: str = "") -> dict:
    """run_subprocess 가 emit 하는 envelope(to_dict superset + 런타임 3키)."""
    return {
        "strategy": "momentum_v1.0.0",
        "period": "2026-01-01 ~ 2026-01-31",
        "initial_balance": 10_000_000.0,
        "final_balance": 11_000_000.0,
        "total_return_pct": 10.0,
        "total_trades": 3,
        "metrics": {"sharpe_ratio": 1.5, "max_drawdown": -3.0, "win_rate": 0.6},
        "equity_curve": [],
        "trades": [],
        "config": {},
        "datasets": [],
        "result_path": result_path,
        "strategy_name": "momentum",
        "strategy_version": "1.0.0",
    }


def _run_args(strategy_path, *extra):
    return [
        "backtest",
        "run",
        str(strategy_path),
        "--start",
        "2026-01-01",
        "--end",
        "2026-01-31",
        *extra,
    ]


# ── (a) CLI run → run_subprocess 호출, run 직접호출 안 함 ──────────────────


class TestCliUsesSubprocessIsolation:
    """CLI run 이 D-004 격리 경로(run_subprocess)를 사용한다."""

    def test_run_invokes_run_subprocess_not_run(self, tmp_path):
        """run 이 service.run_subprocess 를 호출하고 service.run 은 호출 안 함."""
        strategy = tmp_path / "strat.py"
        strategy.write_text("# dummy")
        db_path = tmp_path / "ante.db"
        runner = _make_runner()

        run_subprocess_mock = AsyncMock(return_value=_envelope())
        run_mock = AsyncMock()

        with (
            patch(
                "ante.backtest.service.BacktestService.run_subprocess",
                new=run_subprocess_mock,
            ),
            patch("ante.backtest.service.BacktestService.run", new=run_mock),
            patch(
                "ante.cli.commands.backtest._save_backtest_run",
                new=AsyncMock(return_value="run-iso-1"),
            ),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", *_run_args(strategy, "--db-path", str(db_path))],
            )

        assert result.exit_code == 0, result.output
        # 격리 경로 호출 + in-process 경로 미호출.
        run_subprocess_mock.assert_awaited_once()
        run_mock.assert_not_called()
        payload = json.loads(result.stdout)
        assert payload["run_id"] == "run-iso-1"
        assert payload["strategy"] == "momentum_v1.0.0"


# ── (b) envelope result_path → _save_backtest_run → store.save 전파 ───────


class TestResultPathPropagation:
    """#1998: envelope result_path 가 backtest_runs.result_path 로 전파."""

    def test_result_path_flows_to_run_store_save(self, tmp_path):
        """run_subprocess result_path → store.save(result_path=...) 전파."""
        strategy = tmp_path / "strat.py"
        strategy.write_text("# dummy")
        db_path = tmp_path / "ante.db"
        runner = _make_runner()

        artifact = str(tmp_path / ".backtest" / "results" / "momentum_v1.0.0_x.json")
        save_mock = AsyncMock(return_value="run-1998")

        with (
            patch(
                "ante.backtest.service.BacktestService.run_subprocess",
                new=AsyncMock(return_value=_envelope(result_path=artifact)),
            ),
            patch(
                "ante.backtest.run_store.BacktestRunStore.initialize",
                new=AsyncMock(),
            ),
            patch("ante.backtest.run_store.BacktestRunStore.save", new=save_mock),
            patch("ante.core.database.Database.connect", new=AsyncMock()),
            patch("ante.core.database.Database.close", new=AsyncMock()),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", *_run_args(strategy, "--db-path", str(db_path))],
            )

        assert result.exit_code == 0, result.output
        save_mock.assert_awaited_once()
        kwargs = save_mock.await_args.kwargs
        assert kwargs["result_path"] == artifact
        # envelope 개별 키가 그대로 전파 (combined strategy split 아님).
        assert kwargs["strategy_name"] == "momentum"
        assert kwargs["strategy_version"] == "1.0.0"
        assert kwargs["total_return_pct"] == 10.0
        assert kwargs["total_trades"] == 3


# ── (c)/(d) subprocess 실패 → BACKTEST_ERROR ──────────────────────────────


class TestSubprocessFailureSurfacesError:
    """run_subprocess 가 BacktestError 를 raise 하면 BACKTEST_ERROR exit 1."""

    def test_nonzero_returncode_surfaces_backtest_error(self, tmp_path):
        """(c) returncode≠0 → run_subprocess BacktestError → BACKTEST_ERROR."""
        from ante.backtest.exceptions import BacktestError

        strategy = tmp_path / "strat.py"
        strategy.write_text("# dummy")
        db_path = tmp_path / "ante.db"
        runner = _make_runner()

        with patch(
            "ante.backtest.service.BacktestService.run_subprocess",
            new=AsyncMock(
                side_effect=BacktestError("Backtest subprocess failed: boom")
            ),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", *_run_args(strategy, "--db-path", str(db_path))],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "BACKTEST_ERROR"

    def test_missing_sentinel_surfaces_backtest_error(self, tmp_path):
        """(d) sentinel 부재 → run_subprocess BacktestError → BACKTEST_ERROR.

        실제 ``create_subprocess_exec`` 를 mock 해 returncode=0 이지만 sentinel
        라인이 없는 stdout 을 주면 run_subprocess 가 "did not emit a result
        line" BacktestError 를 raise → CLI 가 BACKTEST_ERROR 로 변환한다.
        """
        strategy = tmp_path / "strat.py"
        strategy.write_text("# dummy")
        db_path = tmp_path / "ante.db"
        runner = _make_runner()

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        async def _fake_communicate(input=None):  # noqa: A002, ARG001
            return (b"noise only\n{}\n", b"")

        mock_proc.communicate = _fake_communicate

        async def _fake_spawn(*args, **kwargs):  # noqa: ARG001
            return mock_proc

        with patch(
            "ante.backtest.service.asyncio.create_subprocess_exec",
            side_effect=_fake_spawn,
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", *_run_args(strategy, "--db-path", str(db_path))],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "BACKTEST_ERROR"
