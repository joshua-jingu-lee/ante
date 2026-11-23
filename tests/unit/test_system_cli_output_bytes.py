"""system 4개 명령(start 제외) × 성공 분기 × {text, json}의 출력 바이트를 고정한다
(#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. ``halt``·
``clear-halt`` 는 IPC를 한 번 부르고 ``stop``·``status`` 는 부르지 않는다(사례마다
호출 횟수를 단언한다). ``system start`` 는 자식 프로세스의 출력을 흘리므로 성공
출력을 ``CommandResult`` 로 옮기지 않는다(``test_cli_system_start_json_stdout.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.account.models import AccountStatus
from ante.member.models import Member

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_KILL_SWITCH: dict[str, Any] = {
    "status": "halted",
    "accounts_changed": 2,
    "changed_at": "2026-01-02T09:00:00Z",
    "accounts": [
        {"account_id": "acct-1", "changed": True},
        {"account_id": "acct-2", "changed": True},
        {"account_id": "acct-3", "changed": False},
    ],
}

_CASES: dict[str, list[str]] = {
    "stop": ["system", "stop"],
    "status_active": ["system", "status"],
    "status_suspended": ["system", "status"],
    "status_no_row": ["system", "status"],
    "halt": ["system", "halt", "--reason", "drill"],
    "halt_no_reason": ["system", "halt"],
    "clear_halt": ["system", "clear-halt"],
    "clear_halt_with_reason": ["system", "clear-halt", "--reason", "post-drill"],
}

_IPC_CALLS = {
    "halt": 1,
    "halt_no_reason": 1,
    "clear_halt": 1,
    "clear_halt_with_reason": 1,
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
) -> tuple[Result, AsyncMock, MagicMock]:
    from ante.cli.main import cli

    statuses = [AccountStatus.ACTIVE, AccountStatus.ACTIVE]
    if branch == "status_suspended":
        statuses.append(AccountStatus.SUSPENDED)
    accounts = [SimpleNamespace(status=s) for s in statuses]

    class _FakeAccountService:
        def __init__(self, db: Any, eventbus: Any) -> None:
            self.db = db

        async def initialize(self) -> None:
            return None

        async def list(self) -> list[Any]:
            return accounts

    row = None if branch == "status_no_row" else {"cnt": 3}
    db = SimpleNamespace(fetch_one=AsyncMock(return_value=row))

    @asynccontextmanager
    async def _create_services(ctx: Any = None) -> AsyncIterator[tuple[Any, Any]]:
        yield db, object()

    payload = dict(_KILL_SWITCH)
    if branch.startswith("clear_halt"):
        payload["status"] = "halt_cleared"
    ipc_send = AsyncMock(return_value=payload)
    kill = MagicMock()
    args = list(_CASES[branch])
    full_args = ["--format", "json", *args] if mode == "json" else args
    with ExitStack() as stack:
        for target, value in (
            ("ante.cli.commands.system._create_services", _create_services),
            ("ante.account.service.AccountService", _FakeAccountService),
            ("ante.main.read_pid_file", lambda config: 12345),
            ("ante.cli.commands.system._is_process_alive", lambda pid: True),
            ("ante.cli.commands.system.os.kill", kill),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send, kill


_SYSTEM_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("stop", "text"): ("종료 시그널 전송 완료\n"),
    ("stop", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "종료 시그널 전송 완료",\n'
        '  "data": {\n'
        '    "pid": 12345\n'
        "  }\n"
        "}\n"
    ),
    ("status_active", "text"): ("  거래 상태  : active\n  봇 수     : 3\n"),
    ("status_active", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "trading_state": "active",\n'
        '    "bot_count": 3\n'
        "  }\n"
        "}\n"
    ),
    ("status_suspended", "text"): ("  거래 상태  : suspended\n  봇 수     : 3\n"),
    ("status_suspended", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "trading_state": "suspended",\n'
        '    "bot_count": 3\n'
        "  }\n"
        "}\n"
    ),
    ("status_no_row", "text"): ("  거래 상태  : active\n  봇 수     : 0\n"),
    ("status_no_row", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "trading_state": "active",\n'
        '    "bot_count": 0\n'
        "  }\n"
        "}\n"
    ),
    ("halt", "text"): ("시스템 HALTED — 2개 계좌 거래 중지\n"),
    ("halt", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "시스템 HALTED — 2개 계좌 거래 중지",\n'
        '  "data": {\n'
        '    "status": "halted",\n'
        '    "accounts_changed": 2,\n'
        '    "changed_at": "2026-01-02T09:00:00Z",\n'
        '    "accounts": [\n'
        "      {\n"
        '        "account_id": "acct-1",\n'
        '        "changed": true\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acct-2",\n'
        '        "changed": true\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acct-3",\n'
        '        "changed": false\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("halt_no_reason", "text"): ("시스템 HALTED — 2개 계좌 거래 중지\n"),
    ("halt_no_reason", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "시스템 HALTED — 2개 계좌 거래 중지",\n'
        '  "data": {\n'
        '    "status": "halted",\n'
        '    "accounts_changed": 2,\n'
        '    "changed_at": "2026-01-02T09:00:00Z",\n'
        '    "accounts": [\n'
        "      {\n"
        '        "account_id": "acct-1",\n'
        '        "changed": true\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acct-2",\n'
        '        "changed": true\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acct-3",\n'
        '        "changed": false\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("clear_halt", "text"): (
        "시스템 정지 해제 — 2개 계좌 ACTIVE 복구 (봇은 자동 재시작되지 않음)\n"
    ),
    ("clear_halt", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "시스템 정지 해제 — 2개 계좌 ACTIVE 복구 (봇은 자동 재시작되지 '
        '않음)",\n'
        '  "data": {\n'
        '    "status": "halt_cleared",\n'
        '    "accounts_changed": 2,\n'
        '    "changed_at": "2026-01-02T09:00:00Z",\n'
        '    "accounts": [\n'
        "      {\n"
        '        "account_id": "acct-1",\n'
        '        "changed": true\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acct-2",\n'
        '        "changed": true\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acct-3",\n'
        '        "changed": false\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("clear_halt_with_reason", "text"): (
        "시스템 정지 해제 — 2개 계좌 ACTIVE 복구 (봇은 자동 재시작되지 않음)\n"
    ),
    ("clear_halt_with_reason", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "시스템 정지 해제 — 2개 계좌 ACTIVE 복구 (봇은 자동 재시작되지 '
        '않음)",\n'
        '  "data": {\n'
        '    "status": "halt_cleared",\n'
        '    "accounts_changed": 2,\n'
        '    "changed_at": "2026-01-02T09:00:00Z",\n'
        '    "accounts": [\n'
        "      {\n"
        '        "account_id": "acct-1",\n'
        '        "changed": true\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acct-2",\n'
        '        "changed": true\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acct-3",\n'
        '        "changed": false\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
}


class TestSystemOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_SYSTEM_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send, kill = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _SYSTEM_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == _IPC_CALLS.get(branch, 0)
        assert kill.call_count == int(branch == "stop")

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_success_output_goes_to_stdout_only(self, branch: str, mode: str) -> None:
        result, _, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout == _SYSTEM_OUTPUT_BYTES[(branch, mode)]
        assert result.stderr == ""

    @pytest.mark.parametrize(
        ("branch", "method", "params"),
        [
            ("halt", "system.halt", {"reason": "drill"}),
            ("halt_no_reason", "system.halt", {"reason": ""}),
            ("clear_halt", "system.clear_halt", {}),
            ("clear_halt_with_reason", "system.clear_halt", {"reason": "post-drill"}),
        ],
    )
    def test_ipc_request(
        self, branch: str, method: str, params: dict[str, Any]
    ) -> None:
        _, ipc_send, _ = _invoke_case(branch, "json")
        ipc_send.assert_awaited_once_with(method, params, actor="test-master")
