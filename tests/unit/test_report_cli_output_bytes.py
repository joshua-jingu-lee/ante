"""report 5개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. 다섯 명령은 IPC를
부르지 않는다(사례마다 IPC 호출 0회를 단언한다). ``report schema`` 는 실제
``ReportStore.get_schema`` 의 값을 낸다.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.member.models import Member
from ante.report.models import ReportStatus
from ante.report.store import ReportStore
from ante.trade.models import DailySummary, MonthlySummary

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_REPORT_ID = "00000000-0000-4000-8000-0000000000aa"

_REPORT_FILE: dict[str, Any] = {
    "strategy_name": "momentum",
    "strategy_version": "1.0.0",
    "strategy_path": "strategies/momentum.py",
    "backtest_period": "2025-01-01~2025-12-31",
    "total_return_pct": 12.5,
    "total_trades": 40,
    "summary": "요약",
    "rationale": "근거",
    "detail_json": {"note": "상세"},
    "submitted_by": "agent-1",
}

_LIST_RECORDS = [
    SimpleNamespace(
        report_id="r-1",
        strategy_name="momentum",
        status=ReportStatus.SUBMITTED,
        submitted_at=datetime(2026, 1, 2, 9, 0, tzinfo=UTC),
    ),
    SimpleNamespace(
        report_id="r-2",
        strategy_name="mean_rev",
        status=ReportStatus.ADOPTED,
        submitted_at=datetime(2026, 1, 3, 9, 0, tzinfo=UTC),
    ),
]

_VIEW_RECORD = SimpleNamespace(
    report_id="r-1",
    strategy_name="momentum",
    strategy_version="1.0.0",
    status=ReportStatus.SUBMITTED,
    submitted_at=datetime(2026, 1, 2, 9, 0, tzinfo=UTC),
    submitted_by="agent-1",
    backtest_period="2025-01-01~2025-12-31",
    backtest_run_id=None,
    total_return_pct=12.5,
    total_trades=40,
    sharpe_ratio=1.25,
    max_drawdown_pct=-8.0,
    win_rate=55.0,
    summary="요약",
    rationale="근거",
    risks="",
    recommendations="추천",
)

_DAILY = [
    DailySummary(date="2026-01-02", realized_pnl=1500.0, trade_count=3, win_rate=66.7),
    DailySummary(date="2026-01-03", realized_pnl=-200.5, trade_count=1, win_rate=0.0),
]

_MONTHLY = [
    MonthlySummary(
        year=2025, month=12, realized_pnl=9000.0, trade_count=20, win_rate=55.0
    ),
]

_DB = ["--db-path", "unused.db"]

_CASES: dict[str, list[str]] = {
    "schema": ["report", "schema"],
    "submit": ["report", "submit", "{report_json}", *_DB],
    "submit_run": ["report", "submit", "{report_json}", *_DB, "--run", "run-1"],
    "list_empty": ["report", "list", *_DB],
    "list_rows": ["report", "list", *_DB],
    "list_status": ["report", "list", "--status", "submitted", *_DB],
    "performance_empty": ["report", "performance"],
    "performance_daily": [
        "report",
        "performance",
        "--bot-id",
        "bot-1",
        "--start",
        "2026-01-01",
        "--end",
        "2026-01-31",
    ],
    "performance_monthly": ["report", "performance", "--period", "monthly"],
    "view": ["report", "view", "r-1", *_DB],
}


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


def _invoke_case(
    branch: str, mode: str, *, mix_stderr: bool = True
) -> tuple[Result, AsyncMock]:
    import tempfile

    from ante.cli.main import cli

    records = [] if branch == "list_empty" else list(_LIST_RECORDS)

    class _FakeStore:
        get_schema = staticmethod(ReportStore.get_schema)

        def __init__(self, db: Any = None) -> None:
            self.db = db

        async def initialize(self) -> None:
            return None

        async def submit(self, report: Any) -> str:
            return str(report.report_id)

        async def list_reports(self, status: Any = None) -> list[Any]:
            return records

        async def get(self, report_id: str) -> Any:
            return _VIEW_RECORD

    class _FakeDatabase:
        def __init__(self, path: str) -> None:
            self.path = path

        async def connect(self) -> None:
            return None

        async def close(self) -> None:
            return None

    class _FakeRunStore:
        def __init__(self, db: Any) -> None:
            self.db = db

        async def initialize(self) -> None:
            return None

        async def get(self, run_id: str) -> Any:
            return {"run_id": run_id}

    class _FakeTracker:
        def __init__(self, db: Any) -> None:
            self.db = db

        async def get_daily_summary(self, **_: Any) -> list[DailySummary]:
            return [] if branch == "performance_empty" else list(_DAILY)

        async def get_monthly_summary(self, **_: Any) -> list[MonthlySummary]:
            return list(_MONTHLY)

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    ipc_send = AsyncMock(side_effect=AssertionError("IPC를 부르면 안 된다"))
    with tempfile.TemporaryDirectory() as tmp:
        report_json = Path(tmp) / "report.json"
        report_json.write_text(json.dumps(_REPORT_FILE), encoding="utf-8")
        args = [a.replace("{report_json}", str(report_json)) for a in _CASES[branch]]
        full_args = ["--format", "json", *args] if mode == "json" else args
        with ExitStack() as stack:
            for target, value in (
                ("ante.report.ReportStore", _FakeStore),
                ("ante.core.database.Database", _FakeDatabase),
                ("ante.backtest.run_store.BacktestRunStore", _FakeRunStore),
                ("ante.trade.performance.PerformanceTracker", _FakeTracker),
                ("ante.cli.commands.report.open_cli_db", _open_cli_db),
                ("uuid.uuid4", lambda: uuid.UUID(_REPORT_ID)),
                ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
            ):
                stack.enter_context(patch(target, new=value))
            result = CliRunner(mix_stderr=mix_stderr).invoke(
                cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
            )
    return result, ipc_send


_REPORT_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("schema", "text"): (
        "  required_fields:\n"
        "    - strategy_name\n"
        "    - strategy_version\n"
        "    - strategy_path\n"
        "    - backtest_period\n"
        "    - total_return_pct\n"
        "    - total_trades\n"
        "    - summary\n"
        "    - rationale\n"
        "  optional_fields:\n"
        "    - sharpe_ratio\n"
        "    - max_drawdown_pct\n"
        "    - win_rate\n"
        "    - risks\n"
        "    - recommendations\n"
        "    - detail_json\n"
        "    - backtest_run_id\n"
        "  format         : JSON\n"
        "  example        :\n"
        "    strategy_name = momentum_breakout\n"
        "    strategy_version = 1.0.0\n"
        "    strategy_path = strategies/momentum_breakout.py\n"
        "    backtest_period = 2024-01 ~ 2026-03\n"
        "    total_return_pct = 15.3\n"
        "    total_trades = 42\n"
        "    sharpe_ratio = 1.2\n"
        "    max_drawdown_pct = -8.5\n"
        "    win_rate = 58.0\n"
        "    summary = 20일 이동평균 돌파 매매 전략\n"
        "    rationale = 모멘텀 효과를 활용한 추세 추종\n"
        "    risks = 횡보장에서 잦은 손절 발생 가능\n"
    ),
    ("schema", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "required_fields": [\n'
        '      "strategy_name",\n'
        '      "strategy_version",\n'
        '      "strategy_path",\n'
        '      "backtest_period",\n'
        '      "total_return_pct",\n'
        '      "total_trades",\n'
        '      "summary",\n'
        '      "rationale"\n'
        "    ],\n"
        '    "optional_fields": [\n'
        '      "sharpe_ratio",\n'
        '      "max_drawdown_pct",\n'
        '      "win_rate",\n'
        '      "risks",\n'
        '      "recommendations",\n'
        '      "detail_json",\n'
        '      "backtest_run_id"\n'
        "    ],\n"
        '    "format": "JSON",\n'
        '    "example": {\n'
        '      "strategy_name": "momentum_breakout",\n'
        '      "strategy_version": "1.0.0",\n'
        '      "strategy_path": "strategies/momentum_breakout.py",\n'
        '      "backtest_period": "2024-01 ~ 2026-03",\n'
        '      "total_return_pct": 15.3,\n'
        '      "total_trades": 42,\n'
        '      "sharpe_ratio": 1.2,\n'
        '      "max_drawdown_pct": -8.5,\n'
        '      "win_rate": 58.0,\n'
        '      "summary": "20일 이동평균 돌파 매매 전략",\n'
        '      "rationale": "모멘텀 효과를 활용한 추세 추종",\n'
        '      "risks": "횡보장에서 잦은 손절 발생 가능"\n'
        "    }\n"
        "  }\n"
        "}\n"
    ),
    ("submit", "text"): ("Report submitted: 00000000-0000-4000-8000-0000000000aa\n"),
    ("submit", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "Report submitted: 00000000-0000-4000-8000-0000000000aa",\n'
        '  "data": {\n'
        '    "report_id": "00000000-0000-4000-8000-0000000000aa",\n'
        '    "strategy": "momentum",\n'
        '    "status": "submitted",\n'
        '    "backtest_run_id": ""\n'
        "  }\n"
        "}\n"
    ),
    ("submit_run", "text"): (
        "Report submitted: 00000000-0000-4000-8000-0000000000aa\n"
    ),
    ("submit_run", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "Report submitted: 00000000-0000-4000-8000-0000000000aa",\n'
        '  "data": {\n'
        '    "report_id": "00000000-0000-4000-8000-0000000000aa",\n'
        '    "strategy": "momentum",\n'
        '    "status": "submitted",\n'
        '    "backtest_run_id": "run-1"\n'
        "  }\n"
        "}\n"
    ),
    ("list_empty", "text"): ("(no data)\n"),
    ("list_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "reports": []\n'
        "  }\n"
        "}\n"
    ),
    ("list_rows", "text"): (
        "   report_id |     strategy |       status | submitted_at\n"
        "---------------------------------------------------------\n"
        "         r-1 |     momentum |    submitted | 2026-01-02 09:00:00+00:00\n"
        "         r-2 |     mean_rev |      adopted | 2026-01-03 09:00:00+00:00\n"
    ),
    ("list_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "reports": [\n'
        "      {\n"
        '        "report_id": "r-1",\n'
        '        "strategy": "momentum",\n'
        '        "status": "submitted",\n'
        '        "submitted_at": "2026-01-02 09:00:00+00:00"\n'
        "      },\n"
        "      {\n"
        '        "report_id": "r-2",\n'
        '        "strategy": "mean_rev",\n'
        '        "status": "adopted",\n'
        '        "submitted_at": "2026-01-03 09:00:00+00:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("list_status", "text"): (
        "   report_id |     strategy |       status | submitted_at\n"
        "---------------------------------------------------------\n"
        "         r-1 |     momentum |    submitted | 2026-01-02 09:00:00+00:00\n"
        "         r-2 |     mean_rev |      adopted | 2026-01-03 09:00:00+00:00\n"
    ),
    ("list_status", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "reports": [\n'
        "      {\n"
        '        "report_id": "r-1",\n'
        '        "strategy": "momentum",\n'
        '        "status": "submitted",\n'
        '        "submitted_at": "2026-01-02 09:00:00+00:00"\n'
        "      },\n"
        "      {\n"
        '        "report_id": "r-2",\n'
        '        "strategy": "mean_rev",\n'
        '        "status": "adopted",\n'
        '        "submitted_at": "2026-01-03 09:00:00+00:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("performance_empty", "text"): ("집계 데이터가 없습니다.\n"),
    ("performance_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "message": "집계 데이터가 없습니다.",\n'
        '    "summaries": []\n'
        "  }\n"
        "}\n"
    ),
    ("performance_daily", "text"): (
        "        date | realized_pnl |  trade_count |     win_rate\n"
        "---------------------------------------------------------\n"
        "  2026-01-02 |       1500.0 |            3 |         66.7\n"
        "  2026-01-03 |       -200.5 |            1 |          0.0\n"
    ),
    ("performance_daily", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "period": "daily",\n'
        '    "summaries": [\n'
        "      {\n"
        '        "date": "2026-01-02",\n'
        '        "realized_pnl": 1500.0,\n'
        '        "trade_count": 3,\n'
        '        "win_rate": 66.7\n'
        "      },\n"
        "      {\n"
        '        "date": "2026-01-03",\n'
        '        "realized_pnl": -200.5,\n'
        '        "trade_count": 1,\n'
        '        "win_rate": 0.0\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("performance_monthly", "text"): (
        "        year |        month | realized_pnl |  trade_count |     win_rate\n"
        "------------------------------------------------------------------------\n"
        "        2025 |           12 |       9000.0 |           20 |         55.0\n"
    ),
    ("performance_monthly", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "period": "monthly",\n'
        '    "summaries": [\n'
        "      {\n"
        '        "year": 2025,\n'
        '        "month": 12,\n'
        '        "realized_pnl": 9000.0,\n'
        '        "trade_count": 20,\n'
        '        "win_rate": 55.0\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("view", "text"): (
        "  report_id           : r-1\n"
        "  strategy            : momentum v1.0.0\n"
        "  status              : submitted\n"
        "  submitted_at        : 2026-01-02 09:00:00+00:00\n"
        "  submitted_by        : agent-1\n"
        "  backtest_period     : 2025-01-01~2025-12-31\n"
        "  total_return_pct    : 12.5\n"
        "  total_trades        : 40\n"
        "  sharpe_ratio        : 1.25\n"
        "  max_drawdown_pct    : -8.0\n"
        "  win_rate            : 55.0\n"
        "  summary             : 요약\n"
        "  rationale           : 근거\n"
        "  recommendations     : 추천\n"
    ),
    ("view", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "report_id": "r-1",\n'
        '    "strategy": "momentum v1.0.0",\n'
        '    "status": "submitted",\n'
        '    "submitted_at": "2026-01-02 09:00:00+00:00",\n'
        '    "submitted_by": "agent-1",\n'
        '    "backtest_period": "2025-01-01~2025-12-31",\n'
        '    "backtest_run_id": null,\n'
        '    "total_return_pct": 12.5,\n'
        '    "total_trades": 40,\n'
        '    "sharpe_ratio": 1.25,\n'
        '    "max_drawdown_pct": -8.0,\n'
        '    "win_rate": 55.0,\n'
        '    "summary": "요약",\n'
        '    "rationale": "근거",\n'
        '    "risks": "",\n'
        '    "recommendations": "추천"\n'
        "  }\n"
        "}\n"
    ),
}


class TestReportOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_REPORT_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _REPORT_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == 0

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_success_output_goes_to_stdout_only(self, branch: str, mode: str) -> None:
        result, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout == _REPORT_OUTPUT_BYTES[(branch, mode)]
        assert result.stderr == ""
