"""strategy 7개 명령의 출력 바이트를 고정한다 (#2773).

성공 분기 × {text, json}은 stdout과 stderr를 합친 ``result.output`` 전체를
고정한다. ``set-status``는 서버가 가동 중일 때의 IPC 분기와 정지했을 때의
직접 실행 분기를 각각 고정한다. ``validate``·``submit``의 실패 출력은
stdout과 stderr를 갈라 종료 코드와 함께 고정한다(#2762가 정할 자리).
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.core.database import OperationalError
from ante.member.models import Member
from ante.strategy.base import StrategyMeta
from ante.strategy.exceptions import StrategyError, StrategyLoadError
from ante.strategy.registry import StrategyRecord, StrategyStatus
from ante.strategy.validator import ValidationResult
from ante.trade.models import (
    DailySummary,
    MonthlySummary,
    PerformanceMetrics,
    WeeklySummary,
)

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_FILE = "strat.py"


def _record(
    strategy_id: str = "strat-1",
    *,
    version: str = "1.0.0",
    status: StrategyStatus = StrategyStatus.REGISTERED,
    warnings: list[str] | None = None,
) -> StrategyRecord:
    return StrategyRecord(
        strategy_id=strategy_id,
        name="my_strategy",
        version=version,
        filepath="strategies/my_strategy.py",
        status=status,
        registered_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        description="테스트 전략",
        author_name="agent",
        author_id="agent-1",
        validation_warnings=list(warnings or []),
    )


_META = StrategyMeta(
    name="my_strategy",
    version="1.0.0",
    description="테스트 전략",
    author_name="agent",
    author_id="agent-1",
)


class _FakeStrategy:
    meta: Any = _META

    def __init__(self, ctx: Any) -> None:
        pass

    def get_rationale(self) -> str:
        return "모멘텀"

    def get_risks(self) -> list[str]:
        return ["급락"]


class _BadMetaStrategy(_FakeStrategy):
    meta: Any = {"name": "my_strategy"}


class _OddParamsStrategy(_FakeStrategy):
    def get_params(self) -> Any:
        return ["window", 20]

    def get_param_schema(self) -> Any:
        return None


class _NoneSchemaStrategy(_FakeStrategy):
    def get_params(self) -> Any:
        return {"window": 20}

    def get_param_schema(self) -> Any:
        return None


_PARAMS = {
    "params": {"window": 20, "threshold": 0.5},
    "param_schema": {"window": "이동평균 기간"},
    "rationale": "추세 추종",
    "risks": ["횡보장", "갭 하락"],
}

_METRICS_FULL = PerformanceMetrics(
    total_trades=40,
    winning_trades=24,
    losing_trades=16,
    win_rate=0.6,
    total_pnl=1_250_000.0,
    total_commission=12_500.0,
    net_pnl=1_237_500.0,
    avg_profit=80_000.0,
    avg_loss=-41_875.0,
    profit_factor=2.87,
    max_drawdown=0.083,
    max_drawdown_amount=415_000.0,
    sharpe_ratio=1.42,
    first_trade_at=datetime(2026, 1, 2, 9, 5, tzinfo=UTC),
    last_trade_at=datetime(2026, 3, 31, 15, 10, tzinfo=UTC),
    active_days=58,
)
_METRICS_MIN = PerformanceMetrics(total_trades=3, winning_trades=1, losing_trades=2)
_METRICS_NO_CAPITAL = dataclasses.replace(_METRICS_MIN, max_drawdown=None)

_DAILY = [
    DailySummary(
        date="2026-01-02", realized_pnl=15_000.0, trade_count=3, win_rate=0.67
    ),
    DailySummary(date="2026-01-03", realized_pnl=-5_000.0, trade_count=1, win_rate=0.0),
]
_WEEKLY = [
    WeeklySummary(
        week_start="2026-01-05",
        week_end="2026-01-11",
        realized_pnl=42_000.0,
        trade_count=7,
        win_rate=0.57,
    )
]
_MONTHLY = [
    MonthlySummary(
        year=2026, month=1, realized_pnl=120_000.0, trade_count=21, win_rate=0.62
    )
]

_SET_STATUS = ["strategy", "set-status", "strat-1", "--status", "adopted"]
_PERF = ["strategy", "performance", "my_strategy", "--account-id", "acc-1"]
_SUMMARY = ["strategy", "summary", "strat-1", "--period"]

_CASES: dict[str, list[str]] = {
    "validate_ok": ["strategy", "validate", _FILE],
    "validate_ok_warnings": ["strategy", "validate", _FILE],
    "submit_ok": ["strategy", "submit", _FILE],
    "submit_ok_warnings": ["strategy", "submit", _FILE],
    "submit_rationale_raises": ["strategy", "submit", _FILE],
    "list_empty": ["strategy", "list"],
    "list_no_table": ["strategy", "list"],
    "list_rows": ["strategy", "list"],
    "list_status_filter": ["strategy", "list", "--status", "adopted"],
    "set_status_ipc": list(_SET_STATUS),
    "set_status_direct": list(_SET_STATUS),
    "set_status_direct_no_record": list(_SET_STATUS),
    "info_minimal": ["strategy", "info", "my_strategy"],
    "info_full": ["strategy", "info", "my_strategy"],
    "summary_daily": [*_SUMMARY, "daily"],
    "summary_weekly": [*_SUMMARY, "weekly"],
    "summary_monthly": [*_SUMMARY, "monthly"],
    "summary_empty": [*_SUMMARY, "daily"],
    "performance_full": list(_PERF),
    "performance_minimal": list(_PERF),
    "performance_no_capital": list(_PERF),
}

_FAILURE_CASES: dict[str, list[str]] = {
    "validate_invalid": ["strategy", "validate", _FILE],
    "submit_invalid": ["strategy", "submit", _FILE],
    "submit_load_error": ["strategy", "submit", _FILE],
    "submit_meta_error": ["strategy", "submit", _FILE],
    "submit_register_error": ["strategy", "submit", _FILE],
}

_IPC_RESULT = {"strategy_id": "strat-1", "status": "adopted"}

_EDGE_CASES: dict[tuple[str, str], list[str]] = {
    ("info_odd_params", "json"): ["strategy", "info", "my_strategy"],
    ("info_odd_params", "text"): ["strategy", "info", "my_strategy"],
    ("info_none_schema", "json"): ["strategy", "info", "my_strategy"],
    ("info_none_schema", "text"): ["strategy", "info", "my_strategy"],
    ("submit_ok_warnings", "text"): ["strategy", "submit", _FILE],
}


def _validation(branch: str) -> ValidationResult:
    if branch in ("validate_invalid", "submit_invalid"):
        return ValidationResult(
            valid=False,
            errors=["금지된 import: os", "on_step 누락"],
            warnings=["print 사용"],
        )
    if branch.endswith("_warnings"):
        return ValidationResult(valid=True, errors=[], warnings=["print 사용"])
    return ValidationResult(valid=True, errors=[], warnings=[])


def _loader(branch: str) -> MagicMock:
    if branch == "submit_load_error":
        return MagicMock(side_effect=StrategyLoadError("SyntaxError: line 3"))
    if branch == "submit_meta_error":
        return MagicMock(return_value=_BadMetaStrategy)
    if branch == "submit_rationale_raises":

        class _Raising(_FakeStrategy):
            def get_rationale(self) -> str:
                raise RuntimeError("boom")

        return MagicMock(return_value=_Raising)
    if branch == "info_odd_params":
        return MagicMock(return_value=_OddParamsStrategy)
    if branch == "info_none_schema":
        return MagicMock(return_value=_NoneSchemaStrategy)
    return MagicMock(return_value=_FakeStrategy)


def _registry(branch: str) -> AsyncMock:
    registry = AsyncMock()
    if branch == "submit_register_error":
        registry.register = AsyncMock(side_effect=StrategyError("이미 등록된 전략"))
    else:
        warnings = ["print 사용"] if branch.endswith("_warnings") else []
        registry.register = AsyncMock(return_value=_record(warnings=warnings))
    if branch == "list_no_table":
        registry.list_strategies = AsyncMock(
            side_effect=OperationalError("no such table: strategies")
        )
    elif branch in ("list_rows", "list_status_filter"):
        rows = [
            _record(),
            _record("strat-2", version="1.1.0", status=StrategyStatus.ADOPTED),
        ]
        registry.list_strategies = AsyncMock(return_value=rows)
    else:
        registry.list_strategies = AsyncMock(return_value=[])
    if branch == "info_full":
        older = _record("strat-0", version="0.9.0", status=StrategyStatus.ARCHIVED)
        newest = _record(warnings=["print 사용", "전역 상태"])
        registry.get_by_name = AsyncMock(return_value=[newest, older])
    elif branch in ("info_odd_params", "info_none_schema"):
        odd = dataclasses.replace(_record(), filepath=_FILE)
        registry.get_by_name = AsyncMock(return_value=[odd])
    else:
        registry.get_by_name = AsyncMock(return_value=[_record()])
    no_record = branch == "set_status_direct_no_record"
    registry.get = AsyncMock(return_value=None if no_record else _record())
    return registry


def _tracker(branch: str) -> MagicMock:
    tracker = MagicMock()
    daily = [] if branch == "summary_empty" else _DAILY
    tracker.get_daily_summary = AsyncMock(return_value=daily)
    tracker.get_weekly_summary = AsyncMock(return_value=_WEEKLY)
    tracker.get_monthly_summary = AsyncMock(return_value=_MONTHLY)
    metrics = {
        "performance_minimal": _METRICS_MIN,
        "performance_no_capital": _METRICS_NO_CAPITAL,
    }.get(branch, _METRICS_FULL)
    tracker.calculate = AsyncMock(return_value=metrics)
    return tracker


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)
    (tmp_path / _FILE).write_text("# stub\n", encoding="utf-8")
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


def _invoke(
    branch: str, args: list[str], mode: str, *, mix_stderr: bool
) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    registry = _registry(branch)
    tracker = _tracker(branch)
    db = AsyncMock()
    db.fetch_one = AsyncMock(return_value={"1": 1})
    db.fetch_all = AsyncMock(return_value=[])

    @asynccontextmanager
    async def _create_registry(ctx: Any = None) -> AsyncIterator[tuple[Any, Any]]:
        yield registry, db

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield db

    if branch == "set_status_ipc":
        ipc_send = AsyncMock(return_value=dict(_IPC_RESULT))
    else:
        ipc_send = AsyncMock(side_effect=AssertionError("IPC를 부르면 안 된다"))
    params = _PARAMS if branch == "info_full" else None
    from ante.cli.commands.strategy import _load_strategy_params as real_params

    full_args = ["--format", "json", *args] if mode == "json" else list(args)
    with ExitStack() as stack:
        for target, value in (
            ("ante.cli.commands.strategy._create_registry", _create_registry),
            ("ante.cli.commands.strategy.open_cli_db", _open_cli_db),
            (
                "ante.strategy.registry.StrategyRegistry",
                MagicMock(return_value=registry),
            ),
            (
                "ante.trade.performance.PerformanceTracker",
                MagicMock(return_value=tracker),
            ),
            (
                "ante.strategy.validator.StrategyValidator.validate",
                MagicMock(return_value=_validation(branch)),
            ),
            ("ante.strategy.loader.StrategyLoader.load", _loader(branch)),
            (
                "ante.cli.commands.strategy._load_strategy_params",
                real_params
                if branch in ("info_odd_params", "info_none_schema")
                else MagicMock(return_value=params),
            ),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
            (
                "ante.cli.cold_path.is_active_runtime",
                MagicMock(return_value=branch == "set_status_ipc"),
            ),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send


def _invoke_case(branch: str, mode: str) -> tuple[Result, AsyncMock]:
    return _invoke(branch, _CASES[branch], mode, mix_stderr=True)


def _invoke_failure(branch: str, mode: str) -> tuple[Result, AsyncMock]:
    return _invoke(branch, _FAILURE_CASES[branch], mode, mix_stderr=False)


def _invoke_edge(branch: str, mode: str) -> tuple[Result, AsyncMock]:
    return _invoke(branch, _EDGE_CASES[(branch, mode)], mode, mix_stderr=False)


_STRATEGY_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("validate_ok", "text"): ("Strategy validation passed: strat.py\n"),
    ("validate_ok", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "Strategy validation passed: strat.py",\n'
        '  "data": {\n'
        '    "valid": true,\n'
        '    "errors": [],\n'
        '    "warnings": []\n'
        "  }\n"
        "}\n"
    ),
    ("validate_ok_warnings", "text"): ("Strategy validation passed: strat.py\n"),
    ("validate_ok_warnings", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "Strategy validation passed: strat.py",\n'
        '  "data": {\n'
        '    "valid": true,\n'
        '    "errors": [],\n'
        '    "warnings": [\n'
        '      "print 사용"\n'
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("submit_ok", "text"): ("전략 등록 완료: strat-1\n"),
    ("submit_ok", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "submitted": true,\n'
        '    "strategy_id": "strat-1",\n'
        '    "name": "my_strategy",\n'
        '    "version": "1.0.0",\n'
        '    "description": "테스트 전략",\n'
        '    "author_name": "agent",\n'
        '    "author_id": "agent-1",\n'
        '    "filepath": "strategies/my_strategy.py",\n'
        '    "registered_at": "2026-01-01T09:00:00+00:00",\n'
        '    "validation_warnings": []\n'
        "  }\n"
        "}\n"
    ),
    ("submit_ok_warnings", "text"): ("  [warn] print 사용\n전략 등록 완료: strat-1\n"),
    ("submit_ok_warnings", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "submitted": true,\n'
        '    "strategy_id": "strat-1",\n'
        '    "name": "my_strategy",\n'
        '    "version": "1.0.0",\n'
        '    "description": "테스트 전략",\n'
        '    "author_name": "agent",\n'
        '    "author_id": "agent-1",\n'
        '    "filepath": "strategies/my_strategy.py",\n'
        '    "registered_at": "2026-01-01T09:00:00+00:00",\n'
        '    "validation_warnings": [\n'
        '      "print 사용"\n'
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("submit_rationale_raises", "text"): ("전략 등록 완료: strat-1\n"),
    ("submit_rationale_raises", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "submitted": true,\n'
        '    "strategy_id": "strat-1",\n'
        '    "name": "my_strategy",\n'
        '    "version": "1.0.0",\n'
        '    "description": "테스트 전략",\n'
        '    "author_name": "agent",\n'
        '    "author_id": "agent-1",\n'
        '    "filepath": "strategies/my_strategy.py",\n'
        '    "registered_at": "2026-01-01T09:00:00+00:00",\n'
        '    "validation_warnings": []\n'
        "  }\n"
        "}\n"
    ),
    ("list_empty", "text"): ("등록된 전략 없음\n"),
    ("list_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "message": "등록된 전략 없음",\n'
        '    "strategies": []\n'
        "  }\n"
        "}\n"
    ),
    ("list_no_table", "text"): ("등록된 전략 없음\n"),
    ("list_no_table", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "message": "등록된 전략 없음",\n'
        '    "strategies": []\n'
        "  }\n"
        "}\n"
    ),
    ("list_rows", "text"): (
        " strategy_id |         name |      version |       status |  author_name |    "
        "author_id\n"
        "------------------------------------------------------------------------------"
        "---------\n"
        "     strat-1 |  my_strategy |        1.0.0 |   registered |        agent |    "
        "  agent-1\n"
        "     strat-2 |  my_strategy |        1.1.0 |      adopted |        agent |    "
        "  agent-1\n"
    ),
    ("list_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategies": [\n'
        "      {\n"
        '        "strategy_id": "strat-1",\n'
        '        "name": "my_strategy",\n'
        '        "version": "1.0.0",\n'
        '        "status": "registered",\n'
        '        "description": "테스트 전략",\n'
        '        "author_name": "agent",\n'
        '        "author_id": "agent-1",\n'
        '        "registered_at": "2026-01-01T09:00:00+00:00"\n'
        "      },\n"
        "      {\n"
        '        "strategy_id": "strat-2",\n'
        '        "name": "my_strategy",\n'
        '        "version": "1.1.0",\n'
        '        "status": "adopted",\n'
        '        "description": "테스트 전략",\n'
        '        "author_name": "agent",\n'
        '        "author_id": "agent-1",\n'
        '        "registered_at": "2026-01-01T09:00:00+00:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("list_status_filter", "text"): (
        " strategy_id |         name |      version |       status |  author_name |    "
        "author_id\n"
        "------------------------------------------------------------------------------"
        "---------\n"
        "     strat-1 |  my_strategy |        1.0.0 |   registered |        agent |    "
        "  agent-1\n"
        "     strat-2 |  my_strategy |        1.1.0 |      adopted |        agent |    "
        "  agent-1\n"
    ),
    ("list_status_filter", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategies": [\n'
        "      {\n"
        '        "strategy_id": "strat-1",\n'
        '        "name": "my_strategy",\n'
        '        "version": "1.0.0",\n'
        '        "status": "registered",\n'
        '        "description": "테스트 전략",\n'
        '        "author_name": "agent",\n'
        '        "author_id": "agent-1",\n'
        '        "registered_at": "2026-01-01T09:00:00+00:00"\n'
        "      },\n"
        "      {\n"
        '        "strategy_id": "strat-2",\n'
        '        "name": "my_strategy",\n'
        '        "version": "1.1.0",\n'
        '        "status": "adopted",\n'
        '        "description": "테스트 전략",\n'
        '        "author_name": "agent",\n'
        '        "author_id": "agent-1",\n'
        '        "registered_at": "2026-01-01T09:00:00+00:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("set_status_ipc", "text"): ("전략 상태 변경 완료: strat-1 -> adopted\n"),
    ("set_status_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_id": "strat-1",\n'
        '    "status": "adopted"\n'
        "  }\n"
        "}\n"
    ),
    ("set_status_direct", "text"): ("전략 상태 변경 완료: strat-1 -> adopted\n"),
    ("set_status_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_id": "strat-1",\n'
        '    "status": "adopted",\n'
        '    "name": "my_strategy",\n'
        '    "version": "1.0.0"\n'
        "  }\n"
        "}\n"
    ),
    ("set_status_direct_no_record", "text"): (
        "전략 상태 변경 완료: strat-1 -> adopted\n"
    ),
    ("set_status_direct_no_record", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_id": "strat-1",\n'
        '    "status": "adopted",\n'
        '    "name": "",\n'
        '    "version": ""\n'
        "  }\n"
        "}\n"
    ),
    ("info_minimal", "text"): (
        "  이름             : my_strategy\n"
        "  버전             : 1.0.0\n"
        "  상태             : registered\n"
        "  설명             : 테스트 전략\n"
        "  작성자            : agent\n"
        "  작성자 ID         : agent-1\n"
        "  파일 경로          : strategies/my_strategy.py\n"
        "  등록일            : 2026-01-01T09:00:00+00:00\n"
    ),
    ("info_minimal", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_id": "strat-1",\n'
        '    "name": "my_strategy",\n'
        '    "version": "1.0.0",\n'
        '    "status": "registered",\n'
        '    "description": "테스트 전략",\n'
        '    "author_name": "agent",\n'
        '    "author_id": "agent-1",\n'
        '    "filepath": "strategies/my_strategy.py",\n'
        '    "registered_at": "2026-01-01T09:00:00+00:00",\n'
        '    "validation_warnings": []\n'
        "  }\n"
        "}\n"
    ),
    ("info_full", "text"): (
        "  이름             : my_strategy\n"
        "  버전             : 1.0.0\n"
        "  상태             : registered\n"
        "  설명             : 테스트 전략\n"
        "  작성자            : agent\n"
        "  작성자 ID         : agent-1\n"
        "  파일 경로          : strategies/my_strategy.py\n"
        "  등록일            : 2026-01-01T09:00:00+00:00\n"
        "  검증 경고          :\n"
        "    - print 사용\n"
        "    - 전역 상태\n"
        "  투자 근거          : 추세 추종\n"
        "  리스크            :\n"
        "    - 횡보장\n"
        "    - 갭 하락\n"
        "  파라미터           :\n"
        "    window = 20  (이동평균 기간)\n"
        "    threshold = 0.5\n"
        "  다른 버전          :\n"
        "    - strat-0 (archived)\n"
    ),
    ("info_full", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_id": "strat-1",\n'
        '    "name": "my_strategy",\n'
        '    "version": "1.0.0",\n'
        '    "status": "registered",\n'
        '    "description": "테스트 전략",\n'
        '    "author_name": "agent",\n'
        '    "author_id": "agent-1",\n'
        '    "filepath": "strategies/my_strategy.py",\n'
        '    "registered_at": "2026-01-01T09:00:00+00:00",\n'
        '    "validation_warnings": [\n'
        '      "print 사용",\n'
        '      "전역 상태"\n'
        "    ],\n"
        '    "params": {\n'
        '      "window": 20,\n'
        '      "threshold": 0.5\n'
        "    },\n"
        '    "param_schema": {\n'
        '      "window": "이동평균 기간"\n'
        "    },\n"
        '    "rationale": "추세 추종",\n'
        '    "risks": [\n'
        '      "횡보장",\n'
        '      "갭 하락"\n'
        "    ],\n"
        '    "other_versions": [\n'
        "      {\n"
        '        "version": "0.9.0",\n'
        '        "strategy_id": "strat-0",\n'
        '        "status": "archived"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("summary_daily", "text"): (
        "        date | realized_pnl |  trade_count |     win_rate\n"
        "---------------------------------------------------------\n"
        "  2026-01-02 |      15000.0 |            3 |         0.67\n"
        "  2026-01-03 |      -5000.0 |            1 |          0.0\n"
    ),
    ("summary_daily", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_id": "strat-1",\n'
        '    "period": "daily",\n'
        '    "items": [\n'
        "      {\n"
        '        "date": "2026-01-02",\n'
        '        "realized_pnl": 15000.0,\n'
        '        "trade_count": 3,\n'
        '        "win_rate": 0.67\n'
        "      },\n"
        "      {\n"
        '        "date": "2026-01-03",\n'
        '        "realized_pnl": -5000.0,\n'
        '        "trade_count": 1,\n'
        '        "win_rate": 0.0\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("summary_weekly", "text"): (
        "  week_start |     week_end |   week_label | realized_pnl |  trade_count |    "
        " win_rate\n"
        "------------------------------------------------------------------------------"
        "---------\n"
        "  2026-01-05 |   2026-01-11 | 01-05 ~ 01-11 |      42000.0 |            7 |   "
        "      0.57\n"
    ),
    ("summary_weekly", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_id": "strat-1",\n'
        '    "period": "weekly",\n'
        '    "items": [\n'
        "      {\n"
        '        "week_start": "2026-01-05",\n'
        '        "week_end": "2026-01-11",\n'
        '        "realized_pnl": 42000.0,\n'
        '        "trade_count": 7,\n'
        '        "win_rate": 0.57,\n'
        '        "week_label": "01-05 ~ 01-11"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("summary_monthly", "text"): (
        "        year |        month | realized_pnl |  trade_count |     win_rate\n"
        "------------------------------------------------------------------------\n"
        "        2026 |            1 |     120000.0 |           21 |         0.62\n"
    ),
    ("summary_monthly", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_id": "strat-1",\n'
        '    "period": "monthly",\n'
        '    "items": [\n'
        "      {\n"
        '        "year": 2026,\n'
        '        "month": 1,\n'
        '        "realized_pnl": 120000.0,\n'
        '        "trade_count": 21,\n'
        '        "win_rate": 0.62\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("summary_empty", "text"): ("성과 집계 없음\n"),
    ("summary_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_id": "strat-1",\n'
        '    "period": "daily",\n'
        '    "items": []\n'
        "  }\n"
        "}\n"
    ),
    ("performance_full", "text"): (
        "전략 성과: my_strategy (strat-1)\n"
        "  총 거래           : 40\n"
        "  승률             : 60.0%\n"
        "  승리             : 24\n"
        "  패배             : 16\n"
        "  총 손익           : 1,250,000\n"
        "  순 손익           : 1,237,500\n"
        "  총 수수료          : 12,500\n"
        "  평균 수익          : 80,000\n"
        "  평균 손실          : -41,875\n"
        "  수익 팩터          : 2.87\n"
        "  MDD            : 8.3%\n"
        "  MDD 금액         : 415,000\n"
        "  샤프 비율          : 1.42\n"
        "  활성 일수          : 58\n"
        "  첫 거래           : 2026-01-02 09:05:00+00:00\n"
        "  마지막 거래         : 2026-03-31 15:10:00+00:00\n"
    ),
    ("performance_full", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_name": "my_strategy",\n'
        '    "strategy_id": "strat-1",\n'
        '    "metrics": {\n'
        '      "total_trades": 40,\n'
        '      "winning_trades": 24,\n'
        '      "losing_trades": 16,\n'
        '      "win_rate": 0.6,\n'
        '      "total_pnl": 1250000.0,\n'
        '      "total_commission": 12500.0,\n'
        '      "net_pnl": 1237500.0,\n'
        '      "avg_profit": 80000.0,\n'
        '      "avg_loss": -41875.0,\n'
        '      "profit_factor": 2.87,\n'
        '      "max_drawdown": 0.083,\n'
        '      "max_drawdown_amount": 415000.0,\n'
        '      "sharpe_ratio": 1.42,\n'
        '      "first_trade_at": "2026-01-02 09:05:00+00:00",\n'
        '      "last_trade_at": "2026-03-31 15:10:00+00:00",\n'
        '      "active_days": 58\n'
        "    }\n"
        "  }\n"
        "}\n"
    ),
    ("performance_minimal", "text"): (
        "전략 성과: my_strategy (strat-1)\n"
        "  총 거래           : 3\n"
        "  승률             : 0.0%\n"
        "  승리             : 1\n"
        "  패배             : 2\n"
        "  총 손익           : 0\n"
        "  순 손익           : 0\n"
        "  총 수수료          : 0\n"
        "  평균 수익          : 0\n"
        "  평균 손실          : 0\n"
        "  수익 팩터          : 0.00\n"
        "  MDD            : 0.0%\n"
        "  MDD 금액         : 0\n"
        "  샤프 비율          : N/A (거래 30건 미만)\n"
        "  활성 일수          : 0\n"
    ),
    ("performance_minimal", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_name": "my_strategy",\n'
        '    "strategy_id": "strat-1",\n'
        '    "metrics": {\n'
        '      "total_trades": 3,\n'
        '      "winning_trades": 1,\n'
        '      "losing_trades": 2,\n'
        '      "win_rate": 0.0,\n'
        '      "total_pnl": 0.0,\n'
        '      "total_commission": 0.0,\n'
        '      "net_pnl": 0.0,\n'
        '      "avg_profit": 0.0,\n'
        '      "avg_loss": 0.0,\n'
        '      "profit_factor": 0.0,\n'
        '      "max_drawdown": 0.0,\n'
        '      "max_drawdown_amount": 0.0,\n'
        '      "sharpe_ratio": null,\n'
        '      "first_trade_at": null,\n'
        '      "last_trade_at": null,\n'
        '      "active_days": 0\n'
        "    }\n"
        "  }\n"
        "}\n"
    ),
    ("performance_no_capital", "text"): (
        "전략 성과: my_strategy (strat-1)\n"
        "  총 거래           : 3\n"
        "  승률             : 0.0%\n"
        "  승리             : 1\n"
        "  패배             : 2\n"
        "  총 손익           : 0\n"
        "  순 손익           : 0\n"
        "  총 수수료          : 0\n"
        "  평균 수익          : 0\n"
        "  평균 손실          : 0\n"
        "  수익 팩터          : 0.00\n"
        "  MDD            : N/A (할당 예산 없음)\n"
        "  MDD 금액         : 0\n"
        "  샤프 비율          : N/A (거래 30건 미만)\n"
        "  활성 일수          : 0\n"
    ),
    ("performance_no_capital", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "strategy_name": "my_strategy",\n'
        '    "strategy_id": "strat-1",\n'
        '    "metrics": {\n'
        '      "total_trades": 3,\n'
        '      "winning_trades": 1,\n'
        '      "losing_trades": 2,\n'
        '      "win_rate": 0.0,\n'
        '      "total_pnl": 0.0,\n'
        '      "total_commission": 0.0,\n'
        '      "net_pnl": 0.0,\n'
        '      "avg_profit": 0.0,\n'
        '      "avg_loss": 0.0,\n'
        '      "profit_factor": 0.0,\n'
        '      "max_drawdown": null,\n'
        '      "max_drawdown_amount": 0.0,\n'
        '      "sharpe_ratio": null,\n'
        '      "first_trade_at": null,\n'
        '      "last_trade_at": null,\n'
        '      "active_days": 0\n'
        "    }\n"
        "  }\n"
        "}\n"
    ),
}

_STRATEGY_FAILURE_BYTES: dict[tuple[str, str], tuple[str, str, int]] = {
    ("validate_invalid", "text"): (
        "",
        (
            "Error: STRATEGY_VALIDATION_FAILED: Validation failed: strat.py\n"
            "  - 금지된 import: os\n"
            "  - on_step 누락\n"
            "  [warn] print 사용\n"
        ),
        1,
    ),
    ("validate_invalid", "json"): (
        (
            '{"status": "error", "code": "STRATEGY_VALIDATION_FAILED", '
            '"message": "Validation failed: strat.py", "details": '
            '{"errors": ["\\uae08\\uc9c0\\ub41c import: os", '
            '"on_step \\ub204\\ub77d"], "warnings": ["print \\uc0ac\\uc6a9"]}}\n'
        ),
        "",
        1,
    ),
    ("submit_invalid", "text"): (
        "",
        (
            "Error: STRATEGY_VALIDATION_ERROR: Validation failed: strat.py\n"
            "  - 금지된 import: os\n"
            "  - on_step 누락\n"
        ),
        1,
    ),
    ("submit_invalid", "json"): (
        (
            '{"status": "error", "code": "STRATEGY_VALIDATION_ERROR", '
            '"message": "Validation failed: strat.py", "details": '
            '{"stage": "validate", "errors": '
            '["\\uae08\\uc9c0\\ub41c import: os", "on_step \\ub204\\ub77d"]}}\n'
        ),
        "",
        1,
    ),
    ("submit_load_error", "text"): (
        "",
        ("Error: STRATEGY_LOAD_ERROR: Load test failed: SyntaxError: line 3\n"),
        1,
    ),
    ("submit_load_error", "json"): (
        (
            '{"status": "error", "code": "STRATEGY_LOAD_ERROR", '
            '"message": "Load test failed: SyntaxError: line 3", '
            '"details": {"stage": "load"}}\n'
        ),
        "",
        1,
    ),
    ("submit_meta_error", "text"): (
        "",
        (
            "Error: STRATEGY_VALIDATION_ERROR: Invalid meta shape: expected StrategyMet"
            "a, got dict\n"
        ),
        1,
    ),
    ("submit_meta_error", "json"): (
        (
            '{"status": "error", "code": "STRATEGY_VALIDATION_ERROR", '
            '"message": "Invalid meta shape: expected StrategyMeta, got dict", '
            '"details": {"stage": "meta_validation"}}\n'
        ),
        "",
        1,
    ),
    ("submit_register_error", "text"): (
        "",
        ("Error: STRATEGY_ERROR: 이미 등록된 전략\n"),
        1,
    ),
    ("submit_register_error", "json"): (
        (
            '{"status": "error", "code": "STRATEGY_ERROR", '
            '"message": "\\uc774\\ubbf8 \\ub4f1\\ub85d\\ub41c \\uc804\\ub7b5", '
            '"details": {"stage": "register"}}\n'
        ),
        "",
        1,
    ),
}


class TestStrategyOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_STRATEGY_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _STRATEGY_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == (1 if branch == "set_status_ipc" else 0)


class TestStrategyFailureBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_STRATEGY_FAILURE_BYTES) == {
            (branch, mode) for branch in _FAILURE_CASES for mode in ("text", "json")
        }

    @pytest.mark.parametrize(
        ("branch", "mode"),
        [(b, m) for b in _FAILURE_CASES for m in ("text", "json")],
    )
    def test_failure_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_failure(branch, mode)
        stdout, stderr, code = _STRATEGY_FAILURE_BYTES[(branch, mode)]
        assert (result.stdout, result.stderr, result.exit_code) == (
            stdout,
            stderr,
            code,
        )
        assert ipc_send.await_count == 0


_STRATEGY_EDGE_BYTES: dict[tuple[str, str], tuple[str, str, int]] = {
    ("info_odd_params", "json"): (
        (
            "{\n"
            '  "status": "ok",\n'
            '  "message": "",\n'
            '  "data": {\n'
            '    "strategy_id": "strat-1",\n'
            '    "name": "my_strategy",\n'
            '    "version": "1.0.0",\n'
            '    "status": "registered",\n'
            '    "description": "테스트 전략",\n'
            '    "author_name": "agent",\n'
            '    "author_id": "agent-1",\n'
            '    "filepath": "strat.py",\n'
            '    "registered_at": "2026-01-01T09:00:00+00:00",\n'
            '    "validation_warnings": [],\n'
            '    "params": [\n'
            '      "window",\n'
            "      20\n"
            "    ],\n"
            '    "param_schema": null,\n'
            '    "rationale": "모멘텀",\n'
            '    "risks": [\n'
            '      "급락"\n'
            "    ]\n"
            "  }\n"
            "}\n"
        ),
        "",
        0,
    ),
    ("info_odd_params", "text"): (
        (
            "  이름             : my_strategy\n"
            "  버전             : 1.0.0\n"
            "  상태             : registered\n"
            "  설명             : 테스트 전략\n"
            "  작성자            : agent\n"
            "  작성자 ID         : agent-1\n"
            "  파일 경로          : strat.py\n"
            "  등록일            : 2026-01-01T09:00:00+00:00\n"
            "  투자 근거          : 모멘텀\n"
            "  리스크            :\n"
            "    - 급락\n"
            "  파라미터           : ['window', 20]\n"
        ),
        "",
        0,
    ),
    ("info_none_schema", "json"): (
        (
            "{\n"
            '  "status": "ok",\n'
            '  "message": "",\n'
            '  "data": {\n'
            '    "strategy_id": "strat-1",\n'
            '    "name": "my_strategy",\n'
            '    "version": "1.0.0",\n'
            '    "status": "registered",\n'
            '    "description": "테스트 전략",\n'
            '    "author_name": "agent",\n'
            '    "author_id": "agent-1",\n'
            '    "filepath": "strat.py",\n'
            '    "registered_at": "2026-01-01T09:00:00+00:00",\n'
            '    "validation_warnings": [],\n'
            '    "params": {\n'
            '      "window": 20\n'
            "    },\n"
            '    "param_schema": null,\n'
            '    "rationale": "모멘텀",\n'
            '    "risks": [\n'
            '      "급락"\n'
            "    ]\n"
            "  }\n"
            "}\n"
        ),
        "",
        0,
    ),
    ("info_none_schema", "text"): (
        (
            "  이름             : my_strategy\n"
            "  버전             : 1.0.0\n"
            "  상태             : registered\n"
            "  설명             : 테스트 전략\n"
            "  작성자            : agent\n"
            "  작성자 ID         : agent-1\n"
            "  파일 경로          : strat.py\n"
            "  등록일            : 2026-01-01T09:00:00+00:00\n"
            "  투자 근거          : 모멘텀\n"
            "  리스크            :\n"
            "    - 급락\n"
            "  파라미터           :\n"
            "    window = 20\n"
        ),
        "",
        0,
    ),
    ("submit_ok_warnings", "text"): (
        ("전략 등록 완료: strat-1\n"),
        ("  [warn] print 사용\n"),
        0,
    ),
}


class TestStrategyEdgeBytes:
    def test_cases_cover_every_edge(self) -> None:
        assert set(_STRATEGY_EDGE_BYTES) == set(_EDGE_CASES)

    @pytest.mark.parametrize(("branch", "mode"), list(_EDGE_CASES))
    def test_edge_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_edge(branch, mode)
        stdout, stderr, code = _STRATEGY_EDGE_BYTES[(branch, mode)]
        assert (result.stdout, result.stderr, result.exit_code) == (
            stdout,
            stderr,
            code,
        )
        assert ipc_send.await_count == 0
