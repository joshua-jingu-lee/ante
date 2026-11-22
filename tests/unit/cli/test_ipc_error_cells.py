"""IPC 오류를 받는 명령의 출구 특성 테스트 (#2738 ⑧-2).

서버 미기동·타임아웃·원격 오류 × 두 모드 가운데 다른 특성 테스트가 덮지 않던
명령, ``rule update``·``strategy set-status``가 받는 원격 ``EXECUTION_ERROR``,
원격 메시지가 빈 문자열인 원격 오류를 잠근다. 기대값은 리터럴이다.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.cli.main import cli
from ante.contracts.cli_registry import all_contracts
from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCRemoteError,
    IPCServerNotRunningError,
)
from ante.member.models import Member, MemberRole, MemberType

_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_SERVER_DOWN = "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
_TIMEOUT = "서버 응답 시간 초과"
_MODES = ("json", "text")

_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("approval", "request", "--type", "strategy_adopt", "--title", "t"),
    ("approval", "reopen", "ap1"),
    ("approval", "cancel-invalid", "ap1"),
    ("approval", "cancel", "ap1"),
    ("approval", "reject", "ap1"),
    ("system", "halt"),
    ("system", "clear-halt"),
    ("bot", "remove", "b1", "--yes"),
    ("bot", "create", "--name", "n", "--strategy", "s", "--account", "acct-1"),
)

_PATHS = {contract.path for contract in all_contracts()}


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke(args: list[str], error: BaseException) -> Result:
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        stack.enter_context(
            patch(
                "ante.cli.commands.ipc_helpers.ipc_send",
                new=AsyncMock(side_effect=error),
            )
        )
        stack.enter_context(
            patch("ante.cli.cold_path.is_active_runtime", return_value=True)
        )
        stack.enter_context(
            patch("ante.cli.commands.bot.is_active_runtime", return_value=True)
        )
        return runner.invoke(cli, args)


def _assert_cell(result: Result, mode: str, code: str, message: str, line: str) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    if mode == "json":
        assert json.loads(result.stdout) == {
            "status": "error",
            "code": code,
            "message": message,
        }
        assert result.stderr == ""
    else:
        assert result.stdout == ""
        assert result.stderr.splitlines() == [line]


def _path(argv: tuple[str, ...]) -> tuple[str, ...]:
    return argv[:2]


def test_commands_are_runtime_ipc_contracts() -> None:
    paths = [_path(argv) for argv in _COMMANDS]
    assert len(paths) == 9
    runtime = {
        contract.path
        for contract in all_contracts()
        if contract.execution == "runtime_ipc"
    }
    assert set(paths) <= runtime
    assert len(set(paths)) == len(paths)


_CELLS = [
    pytest.param(
        IPCServerNotRunningError(_SERVER_DOWN),
        "IPC_SERVER_NOT_RUNNING",
        _SERVER_DOWN,
        f"Error: {_SERVER_DOWN}",
        id="server-down",
    ),
    pytest.param(
        IPCClientTimeoutError(_TIMEOUT),
        "IPC_TIMEOUT",
        _TIMEOUT,
        f"Error: {_TIMEOUT}",
        id="timeout",
    ),
    pytest.param(
        IPCRemoteError("APPROVAL_STATUS_CONFLICT", "이미 처리됨"),
        "APPROVAL_STATUS_CONFLICT",
        "이미 처리됨",
        "Error: APPROVAL_STATUS_CONFLICT: 이미 처리됨",
        id="remote",
    ),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("argv", _COMMANDS, ids=lambda a: "-".join(a[:2]))
@pytest.mark.parametrize(("error", "code", "message", "line"), _CELLS)
def test_ipc_error_cells(
    mode: str,
    argv: tuple[str, ...],
    error: Exception,
    code: str,
    message: str,
    line: str,
) -> None:
    assert _path(argv) in _PATHS
    result = _invoke(["--format", mode, *argv], error)
    _assert_cell(result, mode, code, message, line)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(
            ("rule", "update", "daily_loss_limit", "--account", "acct-1")
            + ("--param", "max=5"),
            id="rule-update",
        ),
        pytest.param(
            ("strategy", "set-status", "s1", "--status", "archived"),
            id="strategy-set-status",
        ),
    ],
)
def test_remote_fallback_code_is_not_rewrapped(
    mode: str, argv: tuple[str, ...]
) -> None:
    result = _invoke(
        ["--format", mode, *argv], IPCRemoteError("EXECUTION_ERROR", "서버 내부 오류")
    )
    _assert_cell(
        result,
        mode,
        "EXECUTION_ERROR",
        "서버 내부 오류",
        "Error: EXECUTION_ERROR: 서버 내부 오류",
    )


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("argv", "json_message", "line"),
    [
        pytest.param(
            ("approval", "approve", "ap1"),
            "BOT_NOT_FOUND: ",
            "Error: BOT_NOT_FOUND: ",
            id="approval-approve",
        ),
        pytest.param(
            ("bot", "start", "b1"),
            "BOT_NOT_FOUND: ",
            "Error: BOT_NOT_FOUND: BOT_NOT_FOUND: ",
            id="bot-start",
        ),
        pytest.param(
            ("broker", "order-history", "--account", "acct-1"),
            "BOT_NOT_FOUND: ",
            "Error: BOT_NOT_FOUND: BOT_NOT_FOUND: ",
            id="broker-order-history",
        ),
        pytest.param(
            ("config", "set", "k", "v"),
            "",
            "Error: BOT_NOT_FOUND: ",
            id="config-set",
        ),
    ],
)
def test_remote_error_with_an_empty_message(
    mode: str, argv: tuple[str, ...], json_message: str, line: str
) -> None:
    result = _invoke(["--format", mode, *argv], IPCRemoteError("BOT_NOT_FOUND", ""))
    _assert_cell(result, mode, "BOT_NOT_FOUND", json_message, line)
