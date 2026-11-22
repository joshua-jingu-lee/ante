"""``approval``·``bot`` 명령의 실패 경로 특성 테스트 (#2664 PR ④).

출구마다 JSON·text 두 모드를 지난다. 기대값은 리터럴이다. JSON은 stdout 전체를
사전으로, text는 stdout·stderr의 줄 전체를 비교한다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import ExitStack, asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.approval.errors import ApprovalStatusConflictError
from ante.bot.exceptions import BotStateConflict
from ante.cli.main import cli
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
_IPC_SEND = "ante.cli.commands.ipc_helpers.ipc_send"
_MODES = ("json", "text")
_BAD_JSON = (
    "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
)


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


def _assert_json(result: Result, envelope: dict[str, str]) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == envelope
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


def _approval_service(**methods: Any) -> Any:
    service = MagicMock()
    service.initialize = AsyncMock()
    for name, mock in methods.items():
        setattr(service, name, mock)
    return [
        patch("ante.cli.commands.approval.open_cli_db", new=_yielding_cm(MagicMock())),
        patch("ante.approval.ApprovalService", return_value=service),
    ]


def _bot_services(*, db: Any = None, accounts: list[Any] | None = None) -> Any:
    account_service = MagicMock()
    account_service.list = AsyncMock(return_value=accounts or [])
    return patch(
        "ante.cli.commands.bot._create_services",
        new=_yielding_cm(
            (db or MagicMock(), MagicMock(), MagicMock(), account_service)
        ),
    )


def _bot_db(**methods: Any) -> Any:
    db = MagicMock()
    for name, mock in methods.items():
        setattr(db, name, mock)
    return db


# ---------------------------------------------------------------- approval


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("args", "code", "message"),
    [
        pytest.param(
            ["approval", "request", "--type", "strategy_adopt", "--title", "t"]
            + ["--params", "{bad"],
            "INVALID_JSON",
            f"잘못된 JSON 형식: {_BAD_JSON}",
            id="request-invalid-json",
        ),
        pytest.param(
            ["approval", "request", "--type", "strategy_adopt", "--title", "t"]
            + ["--params", "[1]"],
            "APPROVAL_VALIDATION_ERROR",
            "--params는 JSON object여야 합니다 (현재 타입: list)",
            id="request-params-not-object",
        ),
        pytest.param(
            ["approval", "request", "--type", "no_such_type", "--title", "t"],
            "APPROVAL_VALIDATION_ERROR",
            "invalid approval type: 'no_such_type'",
            id="request-invalid-type",
        ),
        pytest.param(
            ["approval", "request", "--type", "strategy_adopt", "--title", "t"]
            + ["--expires-in", "3w"],
            "APPROVAL_VALIDATION_ERROR",
            "잘못된 expires-in: 잘못된 expires-in 형식: 3w",
            id="request-invalid-expires-in",
        ),
        pytest.param(
            ["approval", "reopen", "ap1", "--params", "{bad"],
            "INVALID_JSON",
            f"잘못된 JSON 형식: {_BAD_JSON}",
            id="reopen-invalid-json",
        ),
        pytest.param(
            ["approval", "reopen", "ap1", "--params", '"s"'],
            "APPROVAL_VALIDATION_ERROR",
            "--params는 JSON object여야 합니다 (현재 타입: str)",
            id="reopen-params-not-object",
        ),
        pytest.param(
            ["approval", "list", "--status", "nope"],
            "APPROVAL_INVALID_STATUS",
            "잘못된 status 값: 'nope'. 허용값: "
            "['approved', 'cancelled', 'execution_failed', 'expired', "
            "'on_hold', 'pending', 'rejected']",
            id="list-invalid-status",
        ),
        pytest.param(
            ["approval", "list", "--type", "nope"],
            "APPROVAL_INVALID_TYPE",
            "잘못된 type 값: 'nope'. 허용값: "
            "['bot_assign_strategy', 'bot_change_strategy', 'bot_create', "
            "'bot_delete', 'bot_resume', 'bot_stop', 'budget_change', "
            "'rule_change', 'strategy_adopt', 'strategy_retire']",
            id="list-invalid-type",
        ),
        pytest.param(
            ["approval", "audit-types", "--status", "nope"],
            "APPROVAL_INVALID_STATUS",
            "잘못된 status 값: 'nope'. 허용값: "
            "['approved', 'cancelled', 'execution_failed', 'expired', "
            "'on_hold', 'pending', 'rejected']",
            id="audit-types-invalid-status",
        ),
    ],
)
def test_approval_input_errors(
    mode: str, args: list[str], code: str, message: str
) -> None:
    send = AsyncMock()
    result = _invoke(["--format", mode, *args], patch(_IPC_SEND, new=send))
    if mode == "json":
        _assert_json(result, _envelope(code, message))
    else:
        _assert_text(result, [f"Error: {message}"])
    send.assert_not_called()


def test_approval_input_errors_keep_the_default_status_and_type() -> None:
    send = AsyncMock(return_value={"id": "ap-new"})
    result = _invoke(
        ["--format", "json", "approval", "request", "--type", "strategy_adopt"]
        + ["--title", "t", "--params", "{}", "--expires-in", "3d"],
        patch(_IPC_SEND, new=send),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout)["status"] == "ok"
    send.assert_awaited_once()


@pytest.mark.parametrize("mode", _MODES)
def test_approval_info_not_found(mode: str) -> None:
    patches = _approval_service(
        get=AsyncMock(return_value=None),
        list_approvals=AsyncMock(return_value=[]),
    )
    result = _invoke(["--format", mode, "approval", "info", "ap-missing"], *patches)
    message = "결재 요청을 찾을 수 없음: ap-missing"
    if mode == "json":
        _assert_json(result, _envelope("APPROVAL_NOT_FOUND", message))
    else:
        _assert_text(result, [f"Error: {message}"])


@pytest.mark.parametrize("mode", _MODES)
def test_approval_info_ambiguous_prefix(mode: str) -> None:
    rows = [MagicMock(id="abcdef01-1"), MagicMock(id="abcdef02-2")]
    patches = _approval_service(
        get=AsyncMock(return_value=None),
        list_approvals=AsyncMock(return_value=rows),
    )
    result = _invoke(["--format", mode, "approval", "info", "abcdef"], *patches)
    message = "여러 건이 일치합니다: abcdef01, abcdef02"
    if mode == "json":
        _assert_json(result, _envelope("EXECUTION_ERROR", message))
    else:
        _assert_text(result, [f"Error: {message}"])


@pytest.mark.parametrize("mode", _MODES)
def test_approval_review_not_found(mode: str) -> None:
    from ante.approval.errors import ApprovalNotFoundError

    patches = _approval_service(
        add_review=AsyncMock(side_effect=ApprovalNotFoundError("ap-gone")),
    )
    result = _invoke(
        ["--format", mode, "approval", "review", "ap-gone", "--result", "pass"],
        *patches,
    )
    message = "결재 요청을 찾을 수 없음: ap-gone"
    if mode == "json":
        _assert_json(result, _envelope("APPROVAL_NOT_FOUND", message))
    else:
        _assert_text(result, [f"Error: {message}"])


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("args", "methods"),
    [
        pytest.param(
            ["approval", "list"],
            {"list_approvals": AsyncMock(side_effect=RuntimeError("목록 실패"))},
            id="list",
        ),
        pytest.param(
            ["approval", "info", "ap1"],
            {"get": AsyncMock(side_effect=RuntimeError("목록 실패"))},
            id="info",
        ),
        pytest.param(
            ["approval", "review", "ap1", "--result", "warn"],
            {"add_review": AsyncMock(side_effect=RuntimeError("목록 실패"))},
            id="review",
        ),
        pytest.param(
            ["approval", "audit-types"],
            {
                "list_invalid_type_requests": AsyncMock(
                    side_effect=RuntimeError("목록 실패")
                )
            },
            id="audit-types",
        ),
    ],
)
def test_approval_offline_unexpected_error(
    mode: str, args: list[str], methods: dict[str, Any]
) -> None:
    result = _invoke(["--format", mode, *args], *_approval_service(**methods))
    if mode == "json":
        _assert_json(result, _envelope("EXECUTION_ERROR", "목록 실패"))
    else:
        _assert_text(result, ["Error: 목록 실패"])


@pytest.mark.parametrize("mode", _MODES)
def test_approval_review_registered_domain_error(mode: str) -> None:
    error = ApprovalStatusConflictError("ap1", "approved", "review")
    patches = _approval_service(add_review=AsyncMock(side_effect=error))
    result = _invoke(
        ["--format", mode, "approval", "review", "ap1", "--result", "fail"],
        *patches,
    )
    message = "결재 'ap1' 상태 'approved' 에서 'review' 작업을 수행할 수 없습니다."
    if mode == "json":
        _assert_json(result, _envelope("APPROVAL_STATUS_CONFLICT", message))
    else:
        _assert_text(result, [f"Error: {message}"])


_APPROVAL_IPC_ARGS = [
    pytest.param(
        ["approval", "request", "--type", "strategy_adopt", "--title", "t"],
        id="request",
    ),
    pytest.param(
        ["approval", "request", "--type", "strategy_adopt", "--title", "t"]
        + ["--body", "b", "--params", '{"a": 1}', "--reference-id", "r1"]
        + ["--expires-in", "72h"],
        id="request-all-options",
    ),
    pytest.param(["approval", "reopen", "ap1"], id="reopen"),
    pytest.param(
        ["approval", "reopen", "ap1", "--body", "b", "--params", '{"a": 1}'],
        id="reopen-all-options",
    ),
    pytest.param(["approval", "cancel-invalid", "ap1"], id="cancel-invalid"),
    pytest.param(["approval", "cancel", "ap1"], id="cancel"),
    pytest.param(["approval", "approve", "ap1"], id="approve"),
    pytest.param(["approval", "reject", "ap1"], id="reject"),
    pytest.param(["approval", "reject", "ap1", "--reason", "r"], id="reject-reason"),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("args", _APPROVAL_IPC_ARGS)
def test_approval_ipc_unexpected_error(mode: str, args: list[str]) -> None:
    result = _invoke(["--format", mode, *args], _send(RuntimeError("전송 실패")))
    if mode == "json":
        _assert_json(result, _envelope("EXECUTION_ERROR", "전송 실패"))
    else:
        _assert_text(result, ["Error: 전송 실패"])


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("error", "code", "message", "line"),
    [
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
            IPCRemoteError("APPROVAL_STATUS_CONFLICT", "이미 승인됨"),
            "APPROVAL_STATUS_CONFLICT",
            "이미 승인됨",
            "Error: APPROVAL_STATUS_CONFLICT: 이미 승인됨",
            id="remote",
        ),
    ],
)
def test_approval_ipc_errors_pass_through(
    mode: str, error: Exception, code: str, message: str, line: str
) -> None:
    result = _invoke(["--format", mode, "approval", "approve", "ap1"], _send(error))
    _assert_exit(mode, result, code, message, line)


# ---------------------------------------------------------------- bot


_RESTORED = [
    pytest.param(
        IPCClientTimeoutError(_TIMEOUT),
        "IPC_TIMEOUT",
        _TIMEOUT,
        f"Error: IPC_TIMEOUT: {_TIMEOUT}",
        id="timeout",
    ),
    pytest.param(
        IPCRemoteError("BOT_STATE_CONFLICT", "실행 중인 봇"),
        "BOT_STATE_CONFLICT",
        "실행 중인 봇",
        "Error: BOT_STATE_CONFLICT: 실행 중인 봇",
        id="remote",
    ),
]

_SERVER_DOWN_RESTORED = pytest.param(
    IPCServerNotRunningError(_SERVER_DOWN),
    "IPC_SERVER_NOT_RUNNING",
    _SERVER_DOWN,
    f"Error: IPC_SERVER_NOT_RUNNING: {_SERVER_DOWN}",
    id="server-down",
)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["bot", "list"], id="list"),
        pytest.param(["bot", "info", "b1"], id="info"),
        pytest.param(["bot", "signal-key", "b1"], id="signal-key"),
        pytest.param(["bot", "positions", "b1"], id="positions"),
    ],
)
@pytest.mark.parametrize(("error", "code", "message", "line"), _RESTORED)
def test_bot_read_ipc_errors_keep_the_code_prefix(
    mode: str, args: list[str], error: Exception, code: str, message: str, line: str
) -> None:
    result = _invoke(["--format", mode, *args], _send(error))
    _assert_exit(mode, result, code, message, line)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["bot", "signal-key", "b1", "--rotate"], id="rotate"),
        pytest.param(["bot", "start", "b1"], id="start"),
        pytest.param(["bot", "stop", "b1"], id="stop"),
        pytest.param(["bot", "status", "b1"], id="status"),
    ],
)
@pytest.mark.parametrize(
    ("error", "code", "message", "line"), [*_RESTORED, _SERVER_DOWN_RESTORED]
)
def test_bot_runtime_ipc_errors_keep_the_code_prefix(
    mode: str, args: list[str], error: Exception, code: str, message: str, line: str
) -> None:
    result = _invoke(["--format", mode, *args], _send(error))
    _assert_exit(mode, result, code, message, line)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        pytest.param(
            IPCServerNotRunningError(_SERVER_DOWN),
            "IPC_SERVER_NOT_RUNNING",
            _SERVER_DOWN,
            id="server-down",
        ),
        pytest.param(
            IPCClientTimeoutError(_TIMEOUT), "IPC_TIMEOUT", _TIMEOUT, id="timeout"
        ),
        pytest.param(
            IPCRemoteError("BOT_STATE_CONFLICT", "실행 중인 봇"),
            "BOT_STATE_CONFLICT",
            "실행 중인 봇",
            id="remote",
        ),
    ],
)
def test_bot_update_ipc_errors(
    mode: str, error: Exception, code: str, message: str
) -> None:
    result = _invoke(
        ["--format", mode, "bot", "update", "b1", "--name", "n2"], _send(error)
    )
    if mode == "json":
        _assert_json(result, _envelope(code, message))
    else:
        _assert_text(result, [f"Error: {message}"])


@pytest.mark.parametrize("mode", _MODES)
def test_bot_update_without_fields(mode: str) -> None:
    send = AsyncMock()
    result = _invoke(
        ["--format", mode, "bot", "update", "b1"], patch(_IPC_SEND, new=send)
    )
    message = "변경할 필드를 하나 이상 지정하세요."
    if mode == "json":
        _assert_json(result, _envelope("CLI_MISSING_REQUIRED_INPUT", message))
    else:
        _assert_text(result, [f"Error: {message}"])
    send.assert_not_called()


def test_bot_update_with_one_field_is_sent() -> None:
    send = AsyncMock(return_value={"bot_id": "b1"})
    result = _invoke(
        ["--format", "json", "bot", "update", "b1", "--interval", "30"],
        patch(_IPC_SEND, new=send),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == {"bot_id": "b1"}
    send.assert_awaited_once()


@pytest.mark.parametrize("mode", _MODES)
def test_bot_read_server_down_falls_back(mode: str) -> None:
    db = _bot_db(fetch_all=AsyncMock(return_value=[]))
    result = _invoke(
        ["--format", mode, "bot", "list"],
        _send(IPCServerNotRunningError(_SERVER_DOWN)),
        _bot_services(db=db),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    db.fetch_all.assert_awaited_once()


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("args", "patches"),
    [
        pytest.param(
            ["bot", "info", "b-gone"],
            lambda: [
                _send(IPCServerNotRunningError(_SERVER_DOWN)),
                _bot_services(db=_bot_db(fetch_one=AsyncMock(return_value=None))),
            ],
            id="info-fallback",
        ),
        pytest.param(
            ["bot", "info", "b-gone"],
            lambda: [_send(value={"bot": None})],
            id="info-ipc",
        ),
        pytest.param(
            ["bot", "remove", "b-gone", "--yes"],
            lambda: [
                _send(value={"removed": False}),
                patch("ante.cli.commands.bot.is_active_runtime", return_value=True),
            ],
            id="remove",
        ),
        pytest.param(
            ["bot", "signal-key", "b-gone"],
            lambda: [_send(IPCRemoteError("BOT_NOT_FOUND", "Bot not found: b-gone"))],
            id="signal-key-remote",
        ),
        pytest.param(
            ["bot", "positions", "b-gone"],
            lambda: [
                _send(IPCServerNotRunningError(_SERVER_DOWN)),
                patch(
                    "ante.cli.commands.bot.open_cli_db",
                    new=_yielding_cm(_bot_db(fetch_one=AsyncMock(return_value=None))),
                ),
            ],
            id="positions-fallback",
        ),
        pytest.param(
            ["bot", "logs", "b-gone"],
            lambda: [
                patch(
                    "ante.cli.commands.bot.open_cli_db",
                    new=_yielding_cm(_bot_db(fetch_one=AsyncMock(return_value=None))),
                ),
            ],
            id="logs",
        ),
    ],
)
def test_bot_not_found(mode: str, args: list[str], patches: Any) -> None:
    result = _invoke(["--format", mode, *args], *patches())
    message = "봇을 찾을 수 없습니다: b-gone"
    if mode == "json":
        _assert_json(result, _envelope("BOT_NOT_FOUND", message))
    else:
        _assert_text(result, [f"Error: {message}"])


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    "patches",
    [
        pytest.param(
            lambda: [_send(value={"bot_id": "b1", "signal_key": None})], id="ipc"
        ),
        pytest.param(
            lambda: [
                _send(IPCServerNotRunningError(_SERVER_DOWN)),
                _bot_services(
                    db=_bot_db(fetch_one=AsyncMock(return_value={"strategy_id": "s"}))
                ),
                patch(
                    "ante.bot.signal_key.SignalKeyManager",
                    return_value=MagicMock(
                        initialize=AsyncMock(), get_key=AsyncMock(return_value=None)
                    ),
                ),
            ],
            id="fallback",
        ),
    ],
)
def test_bot_signal_key_not_set(mode: str, patches: Any) -> None:
    result = _invoke(["--format", mode, "bot", "signal-key", "b1"], *patches())
    message = "signal key가 설정되지 않았습니다: b1"
    if mode == "json":
        _assert_json(result, _envelope("SIGNAL_KEY_NOT_SET", message))
    else:
        _assert_text(result, [f"Error: {message}"])


def test_bot_signal_key_present_is_not_an_error() -> None:
    result = _invoke(
        ["--format", "json", "bot", "signal-key", "b1"],
        _send(value={"bot_id": "b1", "signal_key": "sk-1"}),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == {"bot_id": "b1", "signal_key": "sk-1"}


@pytest.mark.parametrize("mode", _MODES)
def test_bot_positions_invalid_account(mode: str) -> None:
    db = _bot_db(fetch_one=AsyncMock(return_value={"account_id": "default"}))
    result = _invoke(
        ["--format", mode, "bot", "positions", "b1"],
        _send(IPCServerNotRunningError(_SERVER_DOWN)),
        patch("ante.cli.commands.bot.open_cli_db", new=_yielding_cm(db)),
    )
    message = (
        "봇의 account_id 가 유효하지 않아 포지션을 조회할 수 없습니다:"
        " b1 (account_id='default')"
    )
    if mode == "json":
        _assert_json(result, _envelope("VALIDATION_ERROR", message))
    else:
        _assert_text(result, [f"Error: {message}"])


@pytest.mark.parametrize("mode", _MODES)
def test_bot_create_invalid_param(mode: str) -> None:
    send = AsyncMock()
    result = _invoke(
        ["--format", mode, "bot", "create", "--name", "n", "--strategy", "s"]
        + ["--account", "acct-1", "--param", "novalue"],
        patch(_IPC_SEND, new=send),
    )
    message = "잘못된 파라미터 형식: 'novalue' (key=value 형태로 지정)"
    if mode == "json":
        _assert_json(result, _envelope("BOT_INVALID_PARAM", message))
    else:
        _assert_text(result, [f"Error: {message}"])
    send.assert_not_called()


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("accounts", "message"),
    [
        pytest.param(
            [],
            "활성 계좌가 없습니다. 먼저 계좌를 등록한 뒤 --account <id>로 지정하세요.",
            id="none",
        ),
        pytest.param(
            [MagicMock(account_id="a-1"), MagicMock(account_id="a-2")],
            "활성 계좌가 여러 개입니다. --account <id>로 명시하세요."
            " (가능한 계좌: a-1, a-2)",
            id="many",
        ),
    ],
)
def test_bot_create_without_account(
    mode: str, accounts: list[Any], message: str
) -> None:
    send = AsyncMock()
    result = _invoke(
        ["--format", mode, "bot", "create", "--name", "n", "--strategy", "s"],
        patch(_IPC_SEND, new=send),
        _bot_services(accounts=accounts),
    )
    if mode == "json":
        _assert_json(result, _envelope("BOT_MISSING_REQUIRED_ACCOUNT", message))
    else:
        _assert_text(result, [f"Error: {message}"])
    send.assert_not_called()


def test_bot_create_with_one_active_account_is_sent() -> None:
    send = AsyncMock(return_value={"bot_id": "b-new"})
    result = _invoke(
        ["--format", "json", "bot", "create", "--name", "n", "--strategy", "s"],
        patch(_IPC_SEND, new=send),
        _bot_services(accounts=[MagicMock(account_id="a-1")]),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert send.await_args.args[1]["account_id"] == "a-1"


@pytest.mark.parametrize("mode", _MODES)
def test_bot_remove_without_yes(mode: str) -> None:
    send = AsyncMock()
    result = _invoke(
        ["--format", mode, "bot", "remove", "b1"], patch(_IPC_SEND, new=send)
    )
    message = "위험 명령입니다. --yes를 명시해야 봇을 삭제합니다."
    if mode == "json":
        _assert_json(result, _envelope("CLI_CONFIRMATION_REQUIRED", message))
    else:
        _assert_text(result, [f"Error: {message}"])
    send.assert_not_called()


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("args", "code", "message"),
    [
        pytest.param(
            ["--from", "2026-13-01"],
            "VALIDATION_ERROR",
            "--from는 YYYY-MM-DD 또는 ISO 8601 datetime이어야 합니다",
            id="bad-from",
        ),
        pytest.param(
            ["--to", "어제"],
            "VALIDATION_ERROR",
            "--to는 YYYY-MM-DD 또는 ISO 8601 datetime이어야 합니다",
            id="bad-to",
        ),
        pytest.param(
            ["--from", "2026-03-02", "--to", "2026-03-01"],
            "INVALID_DATE_RANGE",
            "시작일(2026-03-02)이(가) 종료일(2026-03-01) 이후입니다.",
            id="reversed-range",
        ),
    ],
)
def test_bot_logs_input_errors(
    mode: str, args: list[str], code: str, message: str
) -> None:
    opened = MagicMock()
    result = _invoke(
        ["--format", mode, "bot", "logs", "b1", *args],
        patch("ante.cli.commands.bot.open_cli_db", new=opened),
    )
    if mode == "json":
        _assert_json(result, _envelope(code, message))
    else:
        _assert_text(result, [f"Error: {message}"])
    opened.assert_not_called()


_BOT_IPC_ARGS = [
    pytest.param(
        ["bot", "create", "--name", "n", "--strategy", "s", "--account", "acct-1"],
        id="create",
    ),
    pytest.param(
        ["bot", "create", "--name", "n", "--strategy", "s", "--account", "acct-1"]
        + ["--id", "b1"],
        id="create-id",
    ),
    pytest.param(
        ["bot", "create", "--name", "n", "--strategy", "s", "--account", "acct-1"]
        + ["--param", "k=v"],
        id="create-param",
    ),
    pytest.param(["bot", "remove", "b1", "--yes"], id="remove"),
    pytest.param(["bot", "signal-key", "b1"], id="signal-key"),
]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("args", _BOT_IPC_ARGS)
def test_bot_ipc_unexpected_error(mode: str, args: list[str]) -> None:
    result = _invoke(
        ["--format", mode, *args],
        _send(RuntimeError("전송 실패")),
        patch("ante.cli.commands.bot.is_active_runtime", return_value=True),
    )
    if mode == "json":
        _assert_json(result, _envelope("EXECUTION_ERROR", "전송 실패"))
    else:
        _assert_text(result, ["Error: 전송 실패"])


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    ("error", "code", "message", "line"),
    [
        pytest.param(
            IPCServerNotRunningError(_SERVER_DOWN),
            "IPC_SERVER_NOT_RUNNING",
            _SERVER_DOWN,
            f"Error: {_SERVER_DOWN}",
            id="server-down",
        ),
        pytest.param(
            IPCRemoteError("BOT_ALREADY_EXISTS", "이미 있는 봇"),
            "BOT_ALREADY_EXISTS",
            "이미 있는 봇",
            "Error: BOT_ALREADY_EXISTS: 이미 있는 봇",
            id="remote",
        ),
    ],
)
def test_bot_create_ipc_errors_pass_through(
    mode: str, error: Exception, code: str, message: str, line: str
) -> None:
    result = _invoke(
        ["--format", mode, "bot", "create", "--name", "n", "--strategy", "s"]
        + ["--account", "acct-1"],
        _send(error),
    )
    _assert_exit(mode, result, code, message, line)


@pytest.mark.parametrize("mode", _MODES)
def test_bot_remove_registered_domain_error(mode: str) -> None:
    result = _invoke(
        ["--format", mode, "bot", "remove", "b1", "--yes"],
        _send(BotStateConflict("실행 중인 봇은 삭제할 수 없습니다")),
        patch("ante.cli.commands.bot.is_active_runtime", return_value=True),
    )
    message = "실행 중인 봇은 삭제할 수 없습니다"
    if mode == "json":
        _assert_json(result, _envelope("BOT_STATE_CONFLICT", message))
    else:
        _assert_text(result, [f"Error: {message}"])
