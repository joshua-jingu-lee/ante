"""backtest 2개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. ``run``은 격리 실행
(``BacktestService.run_subprocess``)의 결과 객체와 이력 저장을 대역으로 바꾸고,
``history``는 이력 조회를 대역으로 바꾼다. 두 명령은 IPC를 부르지 않는다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.backtest.run_store import BacktestRun
from ante.member.models import Member

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_FULL_METRICS: dict[str, Any] = {
    "total_return": 12.5,
    "annual_return": 11.98765,
    "sharpe_ratio": 1.23456789,
    "max_drawdown": 5.4321,
    "max_drawdown_duration": 17,
    "total_trades": 8,
    "winning_trades": 5,
    "losing_trades": None,
    "win_rate": 62.5,
    "profit_factor": float("inf"),
    "avg_profit": 123456.789,
    "avg_loss": -54321.0,
}


def _envelope(**overrides: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "strategy": "momentum_v1.0.0",
        "period": "2025-01-01 ~ 2025-12-31",
        "initial_balance": 10_000_000.0,
        "final_balance": 11_250_000.4,
        "total_return_pct": 12.5,
        "total_trades": 8,
        "metrics": dict(_FULL_METRICS),
        "equity_curve": [
            {"timestamp": "2025-01-02", "equity": 10_000_000.0, "balance": 1.0},
        ],
        "trades": [],
        "config": {"exchange": "KRX", "timeframe": "1d"},
        "datasets": [{"symbol": "005930", "timeframe": "1d", "row_count": 245}],
        "result_path": "results/momentum.json",
        "strategy_name": "momentum",
        "strategy_version": "1.0.0",
    }
    envelope.update(overrides)
    return envelope


_RUNS = [
    BacktestRun(
        run_id="run-002",
        strategy_name="momentum",
        strategy_version="1.1.0",
        params_json='{"start_date": "2025-01-01"}',
        total_return_pct=12.5,
        sharpe_ratio=1.5,
        max_drawdown_pct=5.0,
        total_trades=8,
        win_rate=62.5,
        result_path="results/run-002.json",
        created_at="2026-01-15 10:00:00",
    ),
    BacktestRun(
        run_id="run-001",
        strategy_name="momentum",
        strategy_version="1.0.0",
        created_at="2026-01-14 09:00:00",
    ),
]

_RUN = ["backtest", "run", "strat.py", "--start", "2025-01-01", "--end", "2025-12-31"]
_RUN_OPTIONS = [
    "--symbols",
    "005930,000660",
    "--balance",
    "5000000",
    "--timeframe",
    "1d",
    "--exchange",
    "KRX",
    "--data-path",
    "data",
    "--db-path",
    "ante.db",
]

_CASES: dict[str, list[str]] = {
    "run_metrics": [*_RUN, "--db-path", "ante.db"],
    "run_no_metrics": [*_RUN, "--db-path", "ante.db"],
    "run_options": [*_RUN, *_RUN_OPTIONS],
    "history_empty": ["backtest", "history", "momentum"],
    "history_no_table": ["backtest", "history", "momentum"],
    "history_rows": ["backtest", "history", "momentum", "--limit", "5"],
}


def _prepare_files(root: Path) -> None:
    (root / "strat.py").write_text("# stub\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


@pytest.fixture(autouse=True)
def _workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _prepare_files(tmp_path)


def _run_result(branch: str) -> dict[str, Any]:
    if branch == "run_no_metrics":
        return _envelope(metrics={}, total_trades=0, final_balance=10_000_000.0)
    return _envelope()


def _runs(branch: str) -> Any:
    if branch == "history_no_table":
        return AsyncMock(side_effect=sqlite3.OperationalError("no such table: x"))
    return AsyncMock(return_value=[] if branch == "history_empty" else list(_RUNS))


def _invoke_case(
    branch: str,
    mode: str,
    *,
    mix_stderr: bool = True,
    run_result: dict[str, Any] | None = None,
    runs: list[BacktestRun] | None = None,
) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    result_dict = run_result if run_result is not None else _run_result(branch)
    listed = AsyncMock(return_value=runs) if runs is not None else _runs(branch)
    ipc_send = AsyncMock(side_effect=AssertionError("IPC를 부르면 안 된다"))
    args = list(_CASES[branch])
    full_args = ["--format", "json", *args] if mode == "json" else args
    with ExitStack() as stack:
        for target, value in (
            (
                "ante.backtest.service.BacktestService.run_subprocess",
                AsyncMock(return_value=result_dict),
            ),
            ("ante.backtest.run_store.BacktestRunStore.initialize", AsyncMock()),
            (
                "ante.backtest.run_store.BacktestRunStore.save",
                AsyncMock(return_value="run-003"),
            ),
            ("ante.backtest.run_store.BacktestRunStore.list_by_strategy", listed),
            ("ante.core.database.Database.connect", AsyncMock()),
            ("ante.core.database.Database.close", AsyncMock()),
            ("ante.cli.commands.backtest.open_cli_db", _open_cli_db),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send


_BACKTEST_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("run_metrics", "text"): (
        "Run ID: run-003\n"
        "Strategy: momentum_v1.0.0\n"
        "Period: 2025-01-01 ~ 2025-12-31\n"
        "Return: 12.5%\n"
        "Trades: 8\n"
        "Final Balance: 11,250,000\n"
        "          지표 |            값\n"
        "---------------------------\n"
        "       총 수익률 |       12.50%\n"
        "     연환산 수익률 |       11.99%\n"
        "Sharpe Ratio |       1.2346\n"
        " 최대 낙폭 (MDD) |        5.43%\n"
        "   MDD 지속 기간 |          17일\n"
        "     총 거래 횟수 |            8\n"
        "       승리 거래 |            5\n"
        "       패배 거래 |          N/A\n"
        "          승률 |       62.50%\n"
        "Profit Factor |            ∞\n"
        "       평균 수익 |  123,456.79원\n"
        "       평균 손실 |  -54,321.00원\n"
        "       총 수수료 |          N/A\n"
    ),
    ("run_metrics", "json"): (
        "{\n"
        '  "strategy": "momentum_v1.0.0",\n'
        '  "period": "2025-01-01 ~ 2025-12-31",\n'
        '  "initial_balance": 10000000.0,\n'
        '  "final_balance": 11250000.4,\n'
        '  "total_return_pct": 12.5,\n'
        '  "total_trades": 8,\n'
        '  "metrics": {\n'
        '    "total_return": 12.5,\n'
        '    "annual_return": 11.98765,\n'
        '    "sharpe_ratio": 1.23456789,\n'
        '    "max_drawdown": 5.4321,\n'
        '    "max_drawdown_duration": 17,\n'
        '    "total_trades": 8,\n'
        '    "winning_trades": 5,\n'
        '    "losing_trades": null,\n'
        '    "win_rate": 62.5,\n'
        '    "profit_factor": null,\n'
        '    "avg_profit": 123456.789,\n'
        '    "avg_loss": -54321.0\n'
        "  },\n"
        '  "equity_curve": [\n'
        "    {\n"
        '      "timestamp": "2025-01-02",\n'
        '      "equity": 10000000.0,\n'
        '      "balance": 1.0\n'
        "    }\n"
        "  ],\n"
        '  "trades": [],\n'
        '  "config": {\n'
        '    "exchange": "KRX",\n'
        '    "timeframe": "1d"\n'
        "  },\n"
        '  "datasets": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "timeframe": "1d",\n'
        '      "row_count": 245\n'
        "    }\n"
        "  ],\n"
        '  "result_path": "results/momentum.json",\n'
        '  "strategy_name": "momentum",\n'
        '  "strategy_version": "1.0.0",\n'
        '  "run_id": "run-003"\n'
        "}\n"
    ),
    ("run_no_metrics", "text"): (
        "Run ID: run-003\n"
        "Strategy: momentum_v1.0.0\n"
        "Period: 2025-01-01 ~ 2025-12-31\n"
        "Return: 12.5%\n"
        "Trades: 0\n"
        "Final Balance: 10,000,000\n"
    ),
    ("run_no_metrics", "json"): (
        "{\n"
        '  "strategy": "momentum_v1.0.0",\n'
        '  "period": "2025-01-01 ~ 2025-12-31",\n'
        '  "initial_balance": 10000000.0,\n'
        '  "final_balance": 10000000.0,\n'
        '  "total_return_pct": 12.5,\n'
        '  "total_trades": 0,\n'
        '  "metrics": {},\n'
        '  "equity_curve": [\n'
        "    {\n"
        '      "timestamp": "2025-01-02",\n'
        '      "equity": 10000000.0,\n'
        '      "balance": 1.0\n'
        "    }\n"
        "  ],\n"
        '  "trades": [],\n'
        '  "config": {\n'
        '    "exchange": "KRX",\n'
        '    "timeframe": "1d"\n'
        "  },\n"
        '  "datasets": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "timeframe": "1d",\n'
        '      "row_count": 245\n'
        "    }\n"
        "  ],\n"
        '  "result_path": "results/momentum.json",\n'
        '  "strategy_name": "momentum",\n'
        '  "strategy_version": "1.0.0",\n'
        '  "run_id": "run-003"\n'
        "}\n"
    ),
    ("run_options", "text"): (
        "Run ID: run-003\n"
        "Strategy: momentum_v1.0.0\n"
        "Period: 2025-01-01 ~ 2025-12-31\n"
        "Return: 12.5%\n"
        "Trades: 8\n"
        "Final Balance: 11,250,000\n"
        "          지표 |            값\n"
        "---------------------------\n"
        "       총 수익률 |       12.50%\n"
        "     연환산 수익률 |       11.99%\n"
        "Sharpe Ratio |       1.2346\n"
        " 최대 낙폭 (MDD) |        5.43%\n"
        "   MDD 지속 기간 |          17일\n"
        "     총 거래 횟수 |            8\n"
        "       승리 거래 |            5\n"
        "       패배 거래 |          N/A\n"
        "          승률 |       62.50%\n"
        "Profit Factor |            ∞\n"
        "       평균 수익 |  123,456.79원\n"
        "       평균 손실 |  -54,321.00원\n"
        "       총 수수료 |          N/A\n"
    ),
    ("run_options", "json"): (
        "{\n"
        '  "strategy": "momentum_v1.0.0",\n'
        '  "period": "2025-01-01 ~ 2025-12-31",\n'
        '  "initial_balance": 10000000.0,\n'
        '  "final_balance": 11250000.4,\n'
        '  "total_return_pct": 12.5,\n'
        '  "total_trades": 8,\n'
        '  "metrics": {\n'
        '    "total_return": 12.5,\n'
        '    "annual_return": 11.98765,\n'
        '    "sharpe_ratio": 1.23456789,\n'
        '    "max_drawdown": 5.4321,\n'
        '    "max_drawdown_duration": 17,\n'
        '    "total_trades": 8,\n'
        '    "winning_trades": 5,\n'
        '    "losing_trades": null,\n'
        '    "win_rate": 62.5,\n'
        '    "profit_factor": null,\n'
        '    "avg_profit": 123456.789,\n'
        '    "avg_loss": -54321.0\n'
        "  },\n"
        '  "equity_curve": [\n'
        "    {\n"
        '      "timestamp": "2025-01-02",\n'
        '      "equity": 10000000.0,\n'
        '      "balance": 1.0\n'
        "    }\n"
        "  ],\n"
        '  "trades": [],\n'
        '  "config": {\n'
        '    "exchange": "KRX",\n'
        '    "timeframe": "1d"\n'
        "  },\n"
        '  "datasets": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "timeframe": "1d",\n'
        '      "row_count": 245\n'
        "    }\n"
        "  ],\n"
        '  "result_path": "results/momentum.json",\n'
        '  "strategy_name": "momentum",\n'
        '  "strategy_version": "1.0.0",\n'
        '  "run_id": "run-003"\n'
        "}\n"
    ),
    ("history_empty", "text"): ("'momentum' 백테스트 이력이 없습니다.\n"),
    ("history_empty", "json"): (
        '{\n  "message": "\'momentum\' 백테스트 이력이 없습니다.",\n  "runs": []\n}\n'
    ),
    ("history_no_table", "text"): ("'momentum' 백테스트 이력이 없습니다.\n"),
    ("history_no_table", "json"): (
        '{\n  "message": "\'momentum\' 백테스트 이력이 없습니다.",\n  "runs": []\n}\n'
    ),
    ("history_rows", "text"): (
        "      run_id | strategy_version | total_return_pct | sharpe_ratio | total_trad"
        "es |     win_rate |   created_at\n"
        "------------------------------------------------------------------------------"
        "--------------------------------\n"
        "     run-002 |        1.1.0 |         12.5 |          1.5 |            8 |    "
        "     62.5 | 2026-01-15 10:00:00\n"
        "     run-001 |        1.0.0 |         None |         None |         None |    "
        "     None | 2026-01-14 09:00:00\n"
    ),
    ("history_rows", "json"): (
        "{\n"
        '  "strategy_name": "momentum",\n'
        '  "runs": [\n'
        "    {\n"
        '      "run_id": "run-002",\n'
        '      "strategy_name": "momentum",\n'
        '      "strategy_version": "1.1.0",\n'
        '      "params_json": "{\\"start_date\\": \\"2025-01-01\\"}",\n'
        '      "total_return_pct": 12.5,\n'
        '      "sharpe_ratio": 1.5,\n'
        '      "max_drawdown_pct": 5.0,\n'
        '      "total_trades": 8,\n'
        '      "win_rate": 62.5,\n'
        '      "result_path": "results/run-002.json",\n'
        '      "created_at": "2026-01-15 10:00:00"\n'
        "    },\n"
        "    {\n"
        '      "run_id": "run-001",\n'
        '      "strategy_name": "momentum",\n'
        '      "strategy_version": "1.0.0",\n'
        '      "params_json": "{}",\n'
        '      "total_return_pct": null,\n'
        '      "sharpe_ratio": null,\n'
        '      "max_drawdown_pct": null,\n'
        '      "total_trades": null,\n'
        '      "win_rate": null,\n'
        '      "result_path": "",\n'
        '      "created_at": "2026-01-14 09:00:00"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
}


class TestBacktestOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_BACKTEST_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }
        assert len(_BACKTEST_OUTPUT_BYTES) == 2 * len(_CASES)

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _BACKTEST_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == 0

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_success_output_goes_to_stdout_only(self, branch: str, mode: str) -> None:
        result, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout == _BACKTEST_OUTPUT_BYTES[(branch, mode)]
        assert result.stderr == ""


_MARKER = "user-name-marker"


@pytest.mark.parametrize("mode", ["text", "json"])
def test_run_paths_appear_only_in_json_stdout(mode: str) -> None:
    """``run``의 결과 객체에 든 경로(사용자 이름이 들 수 있다)는 JSON의 stdout에
    결과 객체에 든 횟수만큼 나가고 text와 stderr에는 나가지 않는다."""
    run_result = _envelope(
        result_path=f"/home/{_MARKER}/results/momentum.json",
        config={"data_path": f"/home/{_MARKER}/data"},
    )
    result, _ = _invoke_case(
        "run_metrics", mode, mix_stderr=False, run_result=run_result
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.count(_MARKER) == (2 if mode == "json" else 0)
    assert _MARKER not in result.stderr


@pytest.mark.parametrize("mode", ["text", "json"])
def test_history_paths_appear_only_in_json_stdout(mode: str) -> None:
    """``history``의 행에 든 경로는 JSON의 stdout에 행에 든 횟수만큼 나가고
    text의 표와 stderr에는 나가지 않는다."""
    row = BacktestRun(
        run_id="run-009",
        strategy_name="momentum",
        strategy_version="1.0.0",
        params_json=f'{{"data_path": "/home/{_MARKER}/data"}}',
        result_path=f"/home/{_MARKER}/results/run-009.json",
    )
    result, _ = _invoke_case("history_rows", mode, mix_stderr=False, runs=[row])
    assert result.exit_code == 0, result.output
    assert result.stdout.count(_MARKER) == (2 if mode == "json" else 0)
    assert _MARKER not in result.stderr


_PARTIAL_RESULT: dict[str, Any] = {
    "final_balance": None,
    "total_return_pct": 1.5,
    "total_trades": 0,
    "metrics": {"sharpe_ratio": None},
    "result_path": "",
    "strategy_name": "momentum",
    "strategy_version": "1.0.0",
}

_PARTIAL_JSON: str = (
    "{\n"
    '  "final_balance": null,\n'
    '  "total_return_pct": 1.5,\n'
    '  "total_trades": 0,\n'
    '  "metrics": {\n'
    '    "sharpe_ratio": null\n'
    "  },\n"
    '  "result_path": "",\n'
    '  "strategy_name": "momentum",\n'
    '  "strategy_version": "1.0.0",\n'
    '  "run_id": "run-003"\n'
    "}\n"
)
_PARTIAL_TEXT: tuple[str, str, int] = ("", "Error: BACKTEST_ERROR: 'strategy'\n", 1)


def test_run_json_does_not_read_text_only_fields() -> None:
    """text 줄만 읽는 키(``strategy``·``period``)가 없고 ``final_balance``가
    ``None``인 결과 객체도 JSON은 exit 0으로 객체를 그대로 낸다."""
    result, _ = _invoke_case(
        "run_metrics", "json", mix_stderr=False, run_result=dict(_PARTIAL_RESULT)
    )
    assert result.exit_code == 0, result.output
    assert result.stdout == _PARTIAL_JSON
    assert result.stderr == ""


_BRACE_NAME = "mo{men}tum"
_BRACE_JSON: str = (
    '{\n  "message": "\'mo{men}tum\' 백테스트 이력이 없습니다.",\n  "runs": []\n}\n'
)
_BRACE_TEXT: tuple[str, str, int] = ("", "Error: BACKTEST_ERROR: 'men'\n", 1)


def _invoke_history_brace(mode: str) -> Result:
    from ante.cli.main import cli

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    args = ["backtest", "history", _BRACE_NAME]
    with (
        patch(
            "ante.backtest.run_store.BacktestRunStore.list_by_strategy",
            new=AsyncMock(return_value=[]),
        ),
        patch("ante.cli.commands.backtest.open_cli_db", new=_open_cli_db),
    ):
        return CliRunner(mix_stderr=False).invoke(
            cli,
            ["--format", "json", *args] if mode == "json" else args,
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )


def test_history_empty_json_keeps_brace_name() -> None:
    """중괄호가 든 전략 이름의 빈 이력도 JSON은 exit 0으로 이름을 그대로 낸다."""
    result = _invoke_history_brace("json")
    assert result.exit_code == 0, result.output
    assert result.stdout == _BRACE_JSON
    assert result.stderr == ""


def test_history_empty_text_formats_message_again() -> None:
    """같은 이름의 text는 지금처럼 안내 문장을 한 번 더 ``str.format``에 넣어
    BACKTEST_ERROR로 실패한다(지금의 동작)."""
    result = _invoke_history_brace("text")
    assert (result.stdout, result.stderr, result.exit_code) == _BRACE_TEXT


def test_run_text_fails_on_text_only_fields() -> None:
    """같은 결과 객체의 text 출력은 지금처럼 BACKTEST_ERROR로 실패한다."""
    result, _ = _invoke_case(
        "run_metrics", "text", mix_stderr=False, run_result=dict(_PARTIAL_RESULT)
    )
    assert (result.stdout, result.stderr, result.exit_code) == _PARTIAL_TEXT
