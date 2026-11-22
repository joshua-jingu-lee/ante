"""``treasury``·``strategy`` 명령의 실패 경로 특성 테스트 (#2664 PR ⑤).

출구마다 JSON·text 두 모드를 지난다. 기대값은 리터럴이다. JSON은 stdout 전체를
사전으로, text는 stdout·stderr의 줄 전체를 비교한다. ``strategy validate``와
``strategy submit``의 검증 단계는 옮기지 않는 잔여 출구라 지금 출력(JSON의
``data``·``fmt.output``, text의 상세 줄)을 그대로 잠근다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.account.errors import AccountNotFoundError
from ante.cli.main import cli
from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCRemoteError,
    IPCServerNotRunningError,
)
from ante.core.database import ReadOnlyDatabaseError
from ante.member.models import Member, MemberRole, MemberType
from ante.strategy.base import StrategyMeta
from ante.strategy.exceptions import (
    IncompatibleExchangeError,
    StrategyError,
    StrategyLoadError,
    StrategyNotFoundError,
)
from ante.strategy.validator import ValidationResult
from ante.treasury.exceptions import TreasuryNotConfiguredError

_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_ACCOUNT = "acct-9"
_ACCOUNT_MISSING = "계좌 'acct-9'를 찾을 수 없습니다."
_SERVER_DOWN = "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
_TIMEOUT = "서버 응답 시간 초과"
_IPC_SEND = "ante.cli.commands.ipc_helpers.ipc_send"
_ACTIVE = "ante.cli.cold_path.is_active_runtime"
_TREASURY_CM = "ante.cli.commands.treasury._create_treasury"
_MANAGER_CM = "ante.cli.commands.treasury._create_treasury_manager"
_REGISTRY_CM = "ante.cli.commands.strategy._create_registry"
_MODES = ("json", "text")


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke(args: list[str], *patches: Any) -> Result:
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        for p in patches:
            stack.enter_context(p)
        return runner.invoke(cli, args)


def _envelope(code: str, message: str) -> dict[str, str]:
    return {"status": "error", "code": code, "message": message}


def _assert_json(result: Result, payload: dict[str, Any]) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == payload
    assert result.stderr == ""


def _assert_text(result: Result, stderr_lines: list[str]) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert result.stderr.splitlines() == stderr_lines


def _assert_exit(mode: str, result: Result, code: str, message: str, line: str) -> None:
    if mode == "json":
        _assert_json(result, _envelope(code, message))
    else:
        _assert_text(result, [line])


def _send(error: BaseException | None = None, value: Any = None) -> Any:
    return patch(_IPC_SEND, new=AsyncMock(side_effect=error, return_value=value))


def _yielding_cm(value: Any) -> Callable[..., Any]:
    @asynccontextmanager
    async def _open(*args: object, **kwargs: object) -> AsyncIterator[Any]:
        yield value

    return _open


def _raising_cm(error: BaseException) -> Callable[..., Any]:
    @asynccontextmanager
    async def _open(*args: object, **kwargs: object) -> AsyncIterator[Any]:
        raise error
        yield

    return _open


# ---------------------------------------------------------------- treasury


_TREASURY_READS = [
    pytest.param(["treasury", "status", "--account", _ACCOUNT], id="status"),
    pytest.param(["treasury", "budgets", "--account", _ACCOUNT], id="budgets"),
    pytest.param(
        ["treasury", "snapshot", "--account", _ACCOUNT, "--date", "2026-03-04"],
        id="snapshot",
    ),
    pytest.param(
        ["treasury", "portfolio", "value", "--account", _ACCOUNT], id="portfolio-value"
    ),
    pytest.param(
        ["treasury", "portfolio", "history", "--account", _ACCOUNT],
        id="portfolio-history",
    ),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("args", _TREASURY_READS)
def test_treasury_read_account_not_found(mode: str, args: list[str]) -> None:
    result = _invoke(
        ["--format", mode, *args],
        patch(_TREASURY_CM, new=_raising_cm(AccountNotFoundError(_ACCOUNT_MISSING))),
    )
    _assert_exit(
        mode,
        result,
        "ACCOUNT_NOT_FOUND",
        _ACCOUNT_MISSING,
        f"Error: ACCOUNT_NOT_FOUND: {_ACCOUNT_MISSING}",
    )


@pytest.mark.parametrize("mode", _MODES)
def test_treasury_set_balance_offline_account_not_found(mode: str) -> None:
    result = _invoke(
        ["--format", mode, "treasury", "set-balance", "2500", "--account", _ACCOUNT],
        patch(_ACTIVE, return_value=False),
        patch(_TREASURY_CM, new=_raising_cm(AccountNotFoundError(_ACCOUNT_MISSING))),
    )
    _assert_exit(
        mode,
        result,
        "ACCOUNT_NOT_FOUND",
        _ACCOUNT_MISSING,
        f"Error: ACCOUNT_NOT_FOUND: {_ACCOUNT_MISSING}",
    )


_TREASURY_CATCH_ALL = [
    pytest.param(
        ["treasury", "budgets", "--account", _ACCOUNT],
        [patch(_TREASURY_CM, new=_raising_cm(RuntimeError("예산 조회 실패")))],
        id="budgets-account",
    ),
    pytest.param(
        ["treasury", "budgets"],
        [patch(_MANAGER_CM, new=_raising_cm(RuntimeError("예산 조회 실패")))],
        id="budgets-all",
    ),
    pytest.param(
        ["treasury", "portfolio", "value", "--account", _ACCOUNT],
        [patch(_TREASURY_CM, new=_raising_cm(RuntimeError("예산 조회 실패")))],
        id="portfolio-value",
    ),
    pytest.param(
        ["treasury", "portfolio", "history"],
        [patch(_MANAGER_CM, new=_raising_cm(RuntimeError("예산 조회 실패")))],
        id="portfolio-history",
    ),
    pytest.param(
        ["treasury", "set-balance", "2500", "--account", _ACCOUNT],
        [
            patch(_ACTIVE, return_value=False),
            patch(_TREASURY_CM, new=_raising_cm(RuntimeError("예산 조회 실패"))),
        ],
        id="set-balance-offline",
    ),
    pytest.param(
        ["treasury", "set-balance", "2500", "--account", _ACCOUNT],
        [patch(_ACTIVE, return_value=True), _send(RuntimeError("예산 조회 실패"))],
        id="set-balance-ipc",
    ),
    pytest.param(
        ["treasury", "allocate", "bot-7", "1500", "--account", _ACCOUNT],
        [_send(RuntimeError("예산 조회 실패"))],
        id="allocate",
    ),
    pytest.param(
        ["treasury", "deallocate", "bot-7", "1500", "--account", _ACCOUNT],
        [_send(RuntimeError("예산 조회 실패"))],
        id="deallocate",
    ),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("args", "patches"), _TREASURY_CATCH_ALL)
def test_treasury_unexpected_error(
    mode: str, args: list[str], patches: list[Any]
) -> None:
    result = _invoke(["--format", mode, *args], *patches)
    _assert_exit(
        mode,
        result,
        "EXECUTION_ERROR",
        "예산 조회 실패",
        "Error: EXECUTION_ERROR: 예산 조회 실패",
    )


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    "args",
    [
        pytest.param(
            ["treasury", "budgets", "--account", _ACCOUNT], id="budgets-account"
        ),
        pytest.param(
            ["treasury", "portfolio", "value", "--account", _ACCOUNT],
            id="portfolio-value",
        ),
        pytest.param(
            ["treasury", "portfolio", "history", "--account", _ACCOUNT],
            id="portfolio-history",
        ),
    ],
)
def test_treasury_catch_all_keeps_a_registered_code(mode: str, args: list[str]) -> None:
    error = TreasuryNotConfiguredError("자금 관리 미구성")
    result = _invoke(
        ["--format", mode, *args], patch(_TREASURY_CM, new=_raising_cm(error))
    )
    _assert_exit(
        mode,
        result,
        "TREASURY_NOT_CONFIGURED",
        "자금 관리 미구성",
        "Error: TREASURY_NOT_CONFIGURED: 자금 관리 미구성",
    )


_TREASURY_IPC = [
    pytest.param(
        ["treasury", "set-balance", "2500", "--account", _ACCOUNT], id="set-balance"
    ),
    pytest.param(
        ["treasury", "allocate", "bot-7", "1500", "--account", _ACCOUNT], id="allocate"
    ),
    pytest.param(
        ["treasury", "deallocate", "bot-7", "1500", "--account", _ACCOUNT],
        id="deallocate",
    ),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("args", _TREASURY_IPC)
@pytest.mark.parametrize(
    ("error", "code", "message", "line"),
    [
        pytest.param(
            IPCServerNotRunningError(_SERVER_DOWN),
            "IPC_SERVER_NOT_RUNNING",
            _SERVER_DOWN,
            f"Error: IPC_SERVER_NOT_RUNNING: {_SERVER_DOWN}",
            id="server-down",
        ),
        pytest.param(
            IPCClientTimeoutError(_TIMEOUT),
            "IPC_TIMEOUT",
            _TIMEOUT,
            f"Error: IPC_TIMEOUT: {_TIMEOUT}",
            id="timeout",
        ),
        pytest.param(
            IPCRemoteError("TREASURY_INSUFFICIENT_BALANCE", "미할당 잔액 부족"),
            "TREASURY_INSUFFICIENT_BALANCE",
            "미할당 잔액 부족",
            "Error: TREASURY_INSUFFICIENT_BALANCE: 미할당 잔액 부족",
            id="remote",
        ),
        pytest.param(
            click.ClickException("클릭 오류"),
            "IPC_ERROR",
            "클릭 오류",
            "Error: 클릭 오류",
            id="click",
        ),
    ],
)
def test_treasury_ipc_errors(
    mode: str,
    args: list[str],
    error: Exception,
    code: str,
    message: str,
    line: str,
) -> None:
    result = _invoke(
        ["--format", mode, *args], patch(_ACTIVE, return_value=True), _send(error)
    )
    _assert_exit(mode, result, code, message, line)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    "args",
    [
        pytest.param(
            ["treasury", "allocate", "bot-7", "1500", "--account", _ACCOUNT],
            id="allocate",
        ),
        pytest.param(
            ["treasury", "deallocate", "bot-7", "1500", "--account", _ACCOUNT],
            id="deallocate",
        ),
    ],
)
def test_treasury_mutation_account_not_found(mode: str, args: list[str]) -> None:
    result = _invoke(
        ["--format", mode, *args], _send(AccountNotFoundError(_ACCOUNT_MISSING))
    )
    _assert_exit(
        mode,
        result,
        "ACCOUNT_NOT_FOUND",
        _ACCOUNT_MISSING,
        f"Error: ACCOUNT_NOT_FOUND: {_ACCOUNT_MISSING}",
    )


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("command", "code", "message"),
    [
        pytest.param(
            "allocate",
            "TREASURY_ALLOCATE_FAILED",
            "예산 할당 실패: 미할당 자금 부족 또는 금액 오류 (요청: 1,500원)",
            id="allocate",
        ),
        pytest.param(
            "deallocate",
            "TREASURY_DEALLOCATE_FAILED",
            "예산 회수 실패: 가용 예산 부족 (요청: 1,500원)",
            id="deallocate",
        ),
    ],
)
def test_treasury_mutation_rejected(
    mode: str, command: str, code: str, message: str
) -> None:
    result = _invoke(
        ["--format", mode, "treasury", command, "bot-7", "1500"]
        + ["--account", _ACCOUNT],
        _send(value={"success": False}),
    )
    _assert_exit(mode, result, code, message, f"Error: {code}: {message}")


@pytest.mark.parametrize(
    "command",
    [
        pytest.param("allocate", id="allocate"),
        pytest.param("deallocate", id="deallocate"),
    ],
)
def test_treasury_mutation_accepted(command: str) -> None:
    result = _invoke(
        ["--format", "json", "treasury", command, "bot-7", "1500"]
        + ["--account", _ACCOUNT],
        _send(value={"success": True}),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout)["status"] == "ok"


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("bound", ["--from", "--to"])
def test_treasury_snapshot_option_conflict(mode: str, bound: str) -> None:
    result = _invoke(
        ["--format", mode, "treasury", "snapshot", "--account", _ACCOUNT]
        + ["--date", "2026-03-04", bound, "2026-03-01"],
        patch(_TREASURY_CM, new=_raising_cm(AssertionError("열지 않는다"))),
    )
    message = "--date와 --from/--to 옵션은 동시에 사용할 수 없습니다."
    _assert_exit(
        mode,
        result,
        "CLI_OPTION_CONFLICT",
        message,
        f"Error: CLI_OPTION_CONFLICT: {message}",
    )


def _snapshot_treasury(**methods: Any) -> Any:
    treasury_obj = MagicMock()
    for name, mock in methods.items():
        setattr(treasury_obj, name, mock)
    return patch(_TREASURY_CM, new=_yielding_cm((treasury_obj, MagicMock())))


@pytest.mark.parametrize("mode", _MODES)
def test_treasury_snapshot_not_found(mode: str) -> None:
    result = _invoke(
        ["--format", mode, "treasury", "snapshot", "--account", _ACCOUNT]
        + ["--date", "2026-03-04"],
        _snapshot_treasury(get_daily_snapshot=AsyncMock(return_value=None)),
    )
    message = "2026-03-04 날짜의 스냅샷이 없습니다."
    _assert_exit(
        mode,
        result,
        "SNAPSHOT_NOT_FOUND",
        message,
        f"Error: SNAPSHOT_NOT_FOUND: {message}",
    )


def test_treasury_snapshot_range_is_not_a_missing_snapshot() -> None:
    result = _invoke(
        ["--format", "json", "treasury", "snapshot", "--account", _ACCOUNT]
        + ["--from", "2026-03-01"],
        _snapshot_treasury(get_snapshots=AsyncMock(return_value=[])),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout)["data"] == {"snapshots": []}


# ---------------------------------------------------------------- strategy


def _registry(**methods: Any) -> Any:
    registry = MagicMock()
    registry.initialize = AsyncMock()
    for name, mock in methods.items():
        setattr(registry, name, mock)
    return registry


def _with_registry(**methods: Any) -> Any:
    return patch(_REGISTRY_CM, new=_yielding_cm((_registry(**methods), MagicMock())))


def _record(name: str = "momentum") -> Any:
    record = MagicMock()
    record.strategy_id = f"{name}_v1"
    record.name = name
    return record


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_list_invalid_status(mode: str) -> None:
    result = _invoke(
        ["--format", mode, "strategy", "list", "--status", "nope"],
        patch(_REGISTRY_CM, new=_raising_cm(AssertionError("열지 않는다"))),
    )
    message = "잘못된 status 값: 'nope'. 허용값: ['adopted', 'archived', 'registered']"
    _assert_exit(
        mode,
        result,
        "STRATEGY_VALIDATION_ERROR",
        message,
        f"Error: STRATEGY_VALIDATION_ERROR: {message}",
    )


_LOOKUPS = [
    pytest.param(["strategy", "list"], "list_strategies", id="list"),
    pytest.param(["strategy", "info", "momentum"], "get_by_name", id="info"),
    pytest.param(
        ["strategy", "summary", "momentum_v1", "--period", "weekly"],
        "get",
        id="summary",
    ),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(("args", "method"), _LOOKUPS)
@pytest.mark.parametrize(
    "error",
    [
        pytest.param(RuntimeError("조회 실패"), id="runtime"),
        pytest.param(StrategyNotFoundError("조회 실패"), id="registered"),
    ],
)
def test_strategy_lookup_catch_all(
    mode: str, args: list[str], method: str, error: Exception
) -> None:
    result = _invoke(
        ["--format", mode, *args],
        _with_registry(**{method: AsyncMock(side_effect=error)}),
    )
    _assert_exit(
        mode, result, "STRATEGY_ERROR", "조회 실패", "Error: STRATEGY_ERROR: 조회 실패"
    )


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("args", "method"),
    [
        pytest.param(["strategy", "list"], "list_strategies", id="list"),
        pytest.param(["strategy", "info", "momentum"], "get_by_name", id="info"),
    ],
)
def test_strategy_lookup_operational_error(
    mode: str, args: list[str], method: str
) -> None:
    error = sqlite3.OperationalError("disk I/O error")
    result = _invoke(
        ["--format", mode, *args],
        _with_registry(**{method: AsyncMock(side_effect=error)}),
    )
    _assert_exit(
        mode,
        result,
        "STRATEGY_ERROR",
        "disk I/O error",
        "Error: STRATEGY_ERROR: disk I/O error",
    )


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_list_passes_click_exceptions_through(mode: str) -> None:
    error = click.ClickException("클릭 오류")
    result = _invoke(
        ["--format", mode, "strategy", "list"],
        _with_registry(list_strategies=AsyncMock(side_effect=error)),
    )
    _assert_exit(mode, result, "IPC_ERROR", "클릭 오류", "Error: 클릭 오류")


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_info_missing_table_is_not_found(mode: str) -> None:
    error = sqlite3.OperationalError("no such table: strategies")
    result = _invoke(
        ["--format", mode, "strategy", "info", "momentum"],
        _with_registry(get_by_name=AsyncMock(side_effect=error)),
    )
    message = "전략을 찾을 수 없습니다: momentum"
    _assert_exit(
        mode,
        result,
        "STRATEGY_NOT_FOUND",
        message,
        f"Error: STRATEGY_NOT_FOUND: {message}",
    )


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("args", "method", "value", "name"),
    [
        pytest.param(
            ["strategy", "info", "momentum"], "get_by_name", [], "momentum", id="info"
        ),
        pytest.param(
            ["strategy", "summary", "momentum_v1", "--period", "monthly"],
            "get",
            None,
            "momentum_v1",
            id="summary",
        ),
    ],
)
def test_strategy_lookup_not_found(
    mode: str, args: list[str], method: str, value: Any, name: str
) -> None:
    result = _invoke(
        ["--format", mode, *args],
        _with_registry(**{method: AsyncMock(return_value=value)}),
    )
    message = f"전략을 찾을 수 없습니다: {name}"
    _assert_exit(
        mode,
        result,
        "STRATEGY_NOT_FOUND",
        message,
        f"Error: STRATEGY_NOT_FOUND: {message}",
    )


_SET_STATUS = ["strategy", "set-status", "momentum_v1", "--status", "archived"]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        pytest.param(
            ValueError("허용되지 않는 전이: archived -> archived"),
            "STRATEGY_INVALID_STATUS_TRANSITION",
            "허용되지 않는 전이: archived -> archived",
            id="transition",
        ),
        pytest.param(
            StrategyNotFoundError("전략 없음: momentum_v1"),
            "STRATEGY_NOT_FOUND",
            "전략 없음: momentum_v1",
            id="code-attribute",
        ),
        pytest.param(
            RuntimeError("상태 변경 실패"),
            "STRATEGY_ERROR",
            "상태 변경 실패",
            id="runtime",
        ),
        pytest.param(
            ReadOnlyDatabaseError("상태 변경 실패"),
            "STRATEGY_ERROR",
            "상태 변경 실패",
            id="registered-without-code",
        ),
    ],
)
def test_strategy_set_status_offline_errors(
    mode: str, error: Exception, code: str, message: str
) -> None:
    result = _invoke(
        ["--format", mode, *_SET_STATUS],
        patch(_ACTIVE, return_value=False),
        _with_registry(update_status=AsyncMock(side_effect=error)),
    )
    _assert_exit(mode, result, code, message, f"Error: {code}: {message}")


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("error", "code", "message", "line"),
    [
        pytest.param(
            IPCServerNotRunningError(_SERVER_DOWN),
            "IPC_SERVER_NOT_RUNNING",
            _SERVER_DOWN,
            f"Error: IPC_SERVER_NOT_RUNNING: {_SERVER_DOWN}",
            id="server-down",
        ),
        pytest.param(
            IPCClientTimeoutError(_TIMEOUT),
            "IPC_TIMEOUT",
            _TIMEOUT,
            f"Error: IPC_TIMEOUT: {_TIMEOUT}",
            id="timeout",
        ),
        pytest.param(
            IPCRemoteError("STRATEGY_NOT_FOUND", "전략 없음: momentum_v1"),
            "STRATEGY_NOT_FOUND",
            "전략 없음: momentum_v1",
            "Error: STRATEGY_NOT_FOUND: 전략 없음: momentum_v1",
            id="remote",
        ),
        pytest.param(
            ValueError("허용되지 않는 전이"),
            "STRATEGY_INVALID_STATUS_TRANSITION",
            "허용되지 않는 전이",
            "Error: STRATEGY_INVALID_STATUS_TRANSITION: 허용되지 않는 전이",
            id="transition",
        ),
        pytest.param(
            click.ClickException("클릭 오류"),
            "IPC_ERROR",
            "클릭 오류",
            "Error: 클릭 오류",
            id="click",
        ),
    ],
)
def test_strategy_set_status_ipc_errors(
    mode: str, error: Exception, code: str, message: str, line: str
) -> None:
    result = _invoke(
        ["--format", mode, *_SET_STATUS],
        patch(_ACTIVE, return_value=True),
        _send(error),
    )
    _assert_exit(mode, result, code, message, line)


def _perf_patches(
    *, records: Any = None, account_row: Any = None, error: Any = None
) -> list[Any]:
    registry = _registry(
        get_by_name=AsyncMock(
            side_effect=error, return_value=[_record()] if records is None else records
        )
    )
    db = MagicMock()
    db.fetch_one = AsyncMock(return_value=account_row)
    return [
        patch("ante.cli.commands.strategy.open_cli_db", new=_yielding_cm(db)),
        patch("ante.strategy.registry.StrategyRegistry", return_value=registry),
    ]


_PERF = ["strategy", "performance", "momentum", "--account-id", _ACCOUNT]


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_performance_missing_account(mode: str) -> None:
    result = _invoke(
        ["--format", mode, "strategy", "performance", "momentum"],
        *_perf_patches(error=AssertionError("조회하지 않는다")),
    )
    message = "계좌 ID를 지정해야 합니다. --account-id <id> 옵션을 사용하세요."
    _assert_exit(
        mode,
        result,
        "STRATEGY_MISSING_REQUIRED_ACCOUNT",
        message,
        f"Error: STRATEGY_MISSING_REQUIRED_ACCOUNT: {message}",
    )


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_performance_account_not_found(mode: str) -> None:
    result = _invoke(["--format", mode, *_PERF], *_perf_patches(account_row=None))
    _assert_exit(
        mode,
        result,
        "ACCOUNT_NOT_FOUND",
        _ACCOUNT_MISSING,
        f"Error: ACCOUNT_NOT_FOUND: {_ACCOUNT_MISSING}",
    )


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("patches", "code", "message"),
    [
        pytest.param(
            {"records": []},
            "STRATEGY_NOT_FOUND",
            "전략을 찾을 수 없습니다: momentum",
            id="no-records",
        ),
        pytest.param(
            {"error": sqlite3.OperationalError("no such table: strategies")},
            "STRATEGY_NOT_FOUND",
            "전략을 찾을 수 없습니다: momentum",
            id="missing-table",
        ),
        pytest.param(
            {"error": sqlite3.OperationalError("disk I/O error")},
            "STRATEGY_ERROR",
            "disk I/O error",
            id="operational",
        ),
        pytest.param(
            {"error": RuntimeError("성과 조회 실패")},
            "STRATEGY_ERROR",
            "성과 조회 실패",
            id="runtime",
        ),
        pytest.param(
            {"error": StrategyNotFoundError("성과 조회 실패")},
            "STRATEGY_ERROR",
            "성과 조회 실패",
            id="registered",
        ),
    ],
)
def test_strategy_performance_errors(
    mode: str, patches: dict[str, Any], code: str, message: str
) -> None:
    result = _invoke(["--format", mode, *_PERF], *_perf_patches(**patches))
    _assert_exit(mode, result, code, message, f"Error: {code}: {message}")


# ------------------------------------------------- strategy validate·submit


def _strategy_file(tmp_path: Path) -> str:
    path = tmp_path / "momentum.py"
    path.write_text("# strategy\n", encoding="utf-8")
    return str(path)


def _validator(result: ValidationResult) -> Any:
    validator = MagicMock()
    validator.validate = MagicMock(return_value=result)
    return patch("ante.strategy.validator.StrategyValidator", return_value=validator)


_INVALID = ValidationResult(
    valid=False, errors=["on_step 없음", "meta 없음"], warnings=["print 사용"]
)


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_validate_failure_keeps_its_details(mode: str, tmp_path: Path) -> None:
    path = _strategy_file(tmp_path)
    result = _invoke(
        ["--format", mode, "strategy", "validate", path], _validator(_INVALID)
    )
    if mode == "json":
        _assert_json(
            result,
            {
                "status": "error",
                "code": "STRATEGY_VALIDATION_FAILED",
                "message": f"Validation failed: {path}",
                "data": {
                    "valid": False,
                    "errors": ["on_step 없음", "meta 없음"],
                    "warnings": ["print 사용"],
                },
            },
        )
    else:
        _assert_text(
            result,
            [
                f"Error: Validation failed: {path}",
                "  - on_step 없음",
                "  - meta 없음",
                "  [warn] print 사용",
            ],
        )


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_submit_validation_failure_keeps_its_details(
    mode: str, tmp_path: Path
) -> None:
    path = _strategy_file(tmp_path)
    result = _invoke(
        ["--format", mode, "strategy", "submit", path], _validator(_INVALID)
    )
    if mode == "json":
        _assert_json(
            result,
            {
                "submitted": False,
                "stage": "validate",
                "code": "STRATEGY_VALIDATION_ERROR",
                "errors": ["on_step 없음", "meta 없음"],
            },
        )
    else:
        _assert_text(
            result,
            [f"Error: Validation failed: {path}", "  - on_step 없음", "  - meta 없음"],
        )


_VALID = ValidationResult(valid=True, errors=[], warnings=[])


def _loader(*, error: Exception | None = None, cls: Any = None) -> Any:
    return patch(
        "ante.strategy.loader.StrategyLoader.load",
        side_effect=error,
        return_value=cls,
    )


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_submit_load_failure(mode: str, tmp_path: Path) -> None:
    path = _strategy_file(tmp_path)
    result = _invoke(
        ["--format", mode, "strategy", "submit", path],
        _validator(_VALID),
        _loader(error=StrategyLoadError("모듈을 불러올 수 없습니다")),
    )
    if mode == "json":
        _assert_json(
            result,
            {
                "submitted": False,
                "stage": "load",
                "code": "STRATEGY_LOAD_ERROR",
                "error": "모듈을 불러올 수 없습니다",
            },
        )
    else:
        _assert_text(
            result,
            ["Error: STRATEGY_LOAD_ERROR: Load test failed: 모듈을 불러올 수 없습니다"],
        )


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_submit_meta_shape(mode: str, tmp_path: Path) -> None:
    path = _strategy_file(tmp_path)
    strategy_cls = MagicMock()
    strategy_cls.meta = {"name": "momentum"}
    result = _invoke(
        ["--format", mode, "strategy", "submit", path],
        _validator(_VALID),
        _loader(cls=strategy_cls),
    )
    if mode == "json":
        _assert_json(
            result,
            {
                "submitted": False,
                "stage": "meta_validation",
                "code": "STRATEGY_VALIDATION_ERROR",
                "error": "meta는 StrategyMeta 인스턴스여야 합니다 (받은 타입: dict)",
            },
        )
    else:
        _assert_text(
            result,
            [
                "Error: STRATEGY_VALIDATION_ERROR: "
                "Invalid meta shape: expected StrategyMeta, got dict"
            ],
        )


def _registering_class() -> Any:
    strategy_cls = MagicMock()
    strategy_cls.meta = StrategyMeta(
        name="momentum", version="1.0.0", description="test"
    )
    return strategy_cls


@pytest.mark.parametrize("mode", _MODES)
def test_strategy_submit_register_failure(mode: str, tmp_path: Path) -> None:
    path = _strategy_file(tmp_path)
    error = IncompatibleExchangeError("거래소가 맞지 않습니다")
    result = _invoke(
        ["--format", mode, "strategy", "submit", path],
        _validator(_VALID),
        _loader(cls=_registering_class()),
        _with_registry(register=AsyncMock(side_effect=error)),
    )
    if mode == "json":
        _assert_json(
            result,
            {
                "submitted": False,
                "stage": "register",
                "code": "STRATEGY_INCOMPATIBLE_EXCHANGE",
                "error": "거래소가 맞지 않습니다",
            },
        )
    else:
        _assert_text(
            result, ["Error: STRATEGY_INCOMPATIBLE_EXCHANGE: 거래소가 맞지 않습니다"]
        )


def test_strategy_submit_register_failure_without_a_code(tmp_path: Path) -> None:
    path = _strategy_file(tmp_path)
    result = _invoke(
        ["--format", "json", "strategy", "submit", path],
        _validator(_VALID),
        _loader(cls=_registering_class()),
        _with_registry(register=AsyncMock(side_effect=StrategyError("등록 실패"))),
    )
    _assert_json(
        result,
        {
            "submitted": False,
            "stage": "register",
            "code": "STRATEGY_ERROR",
            "error": "등록 실패",
        },
    )


def test_exceptions_raised_by_treasury_and_strategy_map_to_their_specs() -> None:
    from ante.contracts import cli_errors
    from ante.contracts.helpers import error_spec_for_exception
    from ante.strategy.exceptions import StrategyValidationError

    classes = [
        cli_errors.CliOptionConflictError,
        cli_errors.CliStrategyError,
        cli_errors.SnapshotNotFoundError,
        cli_errors.StrategyInvalidStatusTransitionError,
        cli_errors.StrategyMissingRequiredAccountError,
        cli_errors.TreasuryAllocateFailedError,
        cli_errors.TreasuryDeallocateFailedError,
        StrategyLoadError,
        StrategyNotFoundError,
        StrategyValidationError,
    ]
    table = {}
    for cls in classes:
        spec = error_spec_for_exception(cls("m"))
        table[cls.__name__] = (spec.code, spec.category, spec.exit_code)
    assert table == {
        "CliOptionConflictError": ("CLI_OPTION_CONFLICT", "validation", 1),
        "CliStrategyError": ("STRATEGY_ERROR", "internal", 1),
        "SnapshotNotFoundError": ("SNAPSHOT_NOT_FOUND", "not_found", 1),
        "StrategyInvalidStatusTransitionError": (
            "STRATEGY_INVALID_STATUS_TRANSITION",
            "state_conflict",
            1,
        ),
        "StrategyMissingRequiredAccountError": (
            "STRATEGY_MISSING_REQUIRED_ACCOUNT",
            "validation",
            1,
        ),
        "TreasuryAllocateFailedError": ("TREASURY_ALLOCATE_FAILED", "validation", 1),
        "TreasuryDeallocateFailedError": (
            "TREASURY_DEALLOCATE_FAILED",
            "validation",
            1,
        ),
        "StrategyLoadError": ("STRATEGY_LOAD_ERROR", "validation", 1),
        "StrategyNotFoundError": ("STRATEGY_NOT_FOUND", "not_found", 1),
        "StrategyValidationError": ("STRATEGY_VALIDATION_ERROR", "validation", 1),
    }


def test_the_residual_validate_code_is_registered_without_an_exception() -> None:
    from ante.contracts import error_registry
    from ante.contracts.errors import ErrorSpec

    specs = [
        (v.code, v.category, v.exit_code)
        for v in vars(error_registry).values()
        if isinstance(v, ErrorSpec) and v.code == "STRATEGY_VALIDATION_FAILED"
    ]
    mapped = [
        cls.__name__
        for cls, spec in error_registry.EXCEPTION_TO_SPEC.items()
        if spec.code == "STRATEGY_VALIDATION_FAILED"
    ]
    assert specs == [("STRATEGY_VALIDATION_FAILED", "validation", 1)]
    assert mapped == []


def test_strategy_submit_register_failure_without_a_code_text(tmp_path: Path) -> None:
    path = _strategy_file(tmp_path)
    result = _invoke(
        ["--format", "text", "strategy", "submit", path],
        _validator(_VALID),
        _loader(cls=_registering_class()),
        _with_registry(register=AsyncMock(side_effect=StrategyError("등록 실패"))),
    )
    _assert_text(result, ["Error: STRATEGY_ERROR: 등록 실패"])


_PAIRED_IPC_ARGS = [
    pytest.param(
        ["treasury", "allocate", "b1", "100", "--account", "acct-1"], id="allocate"
    ),
    pytest.param(
        ["treasury", "deallocate", "b1", "5.5", "--account", "acct-1"],
        id="deallocate",
    ),
    pytest.param(
        ["treasury", "set-balance", "100", "--account", "acct-1"], id="set-balance"
    ),
    pytest.param(
        ["treasury", "allocate", "bot-1", "1000", "--account", "acc-1"],
        id="allocate-acc-1",
    ),
    pytest.param(
        ["treasury", "deallocate", "bot-1", "1000", "--account", "acc-1"],
        id="deallocate-acc-1",
    ),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("args", _PAIRED_IPC_ARGS)
def test_treasury_ipc_send_failure_without_a_message(
    mode: str, args: list[str]
) -> None:
    result = _invoke(
        ["--format", mode, *args],
        patch(_ACTIVE, return_value=True),
        _send(RuntimeError()),
    )
    _assert_exit(mode, result, "EXECUTION_ERROR", "", "Error: EXECUTION_ERROR: ")


@pytest.mark.parametrize("mode", _MODES)
def test_treasury_allocate_rejected_for_a_large_amount(mode: str) -> None:
    result = _invoke(
        ["--format", mode, "treasury", "allocate", "bot-1", "999999999"]
        + ["--account", "acc-1"],
        _send(value={"success": False}),
    )
    message = "예산 할당 실패: 미할당 자금 부족 또는 금액 오류 (요청: 999,999,999원)"
    _assert_exit(
        mode,
        result,
        "TREASURY_ALLOCATE_FAILED",
        message,
        f"Error: TREASURY_ALLOCATE_FAILED: {message}",
    )
