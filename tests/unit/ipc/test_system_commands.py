"""system.halt·system.clear_halt의 IPC 응답과 CLI 출력 특성 테스트."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer, IPCServerState
from ante.member.models import Member, MemberRole, MemberType

ACTOR = "ops-lead"
CHANGED_AT = "2026-11-21T09:30:00+00:00"

HALT_ACCOUNTS = [
    {
        "account_id": "acc1",
        "previous_status": "active",
        "status": "suspended",
        "changed": True,
    },
    {
        "account_id": "acc2",
        "previous_status": "suspended",
        "status": "suspended",
        "changed": False,
    },
]

CLEAR_ACCOUNTS = [
    {
        "account_id": "acc1",
        "previous_status": "suspended",
        "status": "active",
        "changed": True,
    },
]


class _Harness:
    def __init__(self) -> None:
        self.account = MagicMock()
        self.account.suspend_all = AsyncMock(return_value=HALT_ACCOUNTS)
        self.account.activate_all = AsyncMock(return_value=CLEAR_ACCOUNTS)
        self.audit_logger = MagicMock()
        self.audit_logger.log = AsyncMock(return_value=None)
        registry = CommandRegistry()
        register_all_handlers(registry)
        services = ServiceRegistry(
            account=self.account,
            bot_manager=MagicMock(),
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            audit_logger=self.audit_logger,
        )
        self.server = IPCServer("/tmp/unused.sock", services, registry)
        self.server._state = IPCServerState.RUNNING

    async def send(self, command: str, args: Any) -> dict:
        return await self.server._dispatch(
            {"id": "req-1", "command": command, "args": args, "actor": ACTOR}
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    monkeypatch.setattr("ante.core.time.format_utc", lambda _dt: CHANGED_AT)
    return _Harness()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "reason"),
    [
        pytest.param({"reason": "긴급 점검"}, "긴급 점검", id="given"),
        pytest.param({}, "IPC halt", id="absent"),
        pytest.param({"reason": ""}, "", id="empty"),
    ],
)
async def test_halt_passes_reason_and_returns_envelope(
    harness: _Harness, args: dict, reason: str
) -> None:
    response = await harness.send("system.halt", args)
    assert response == {
        "id": "req-1",
        "status": "ok",
        "result": {
            "status": "halted",
            "accounts_changed": 1,
            "changed_at": "2026-11-21T09:30:00+00:00",
            "accounts": [
                {
                    "account_id": "acc1",
                    "previous_status": "active",
                    "status": "suspended",
                    "changed": True,
                },
                {
                    "account_id": "acc2",
                    "previous_status": "suspended",
                    "status": "suspended",
                    "changed": False,
                },
            ],
        },
    }
    harness.account.suspend_all.assert_awaited_once_with(
        reason=reason, suspended_by="ops-lead"
    )
    harness.audit_logger.log.assert_awaited_once_with(
        member_id="ops-lead",
        action="system.halt",
        resource="system:kill_switch",
        detail=f"reason={reason}",
        ip="",
    )


CLEARED_RESPONSE = {
    "id": "req-1",
    "status": "ok",
    "result": {
        "status": "halt_cleared",
        "accounts_changed": 1,
        "changed_at": "2026-11-21T09:30:00+00:00",
        "accounts": [
            {
                "account_id": "acc1",
                "previous_status": "suspended",
                "status": "active",
                "changed": True,
            },
        ],
    },
}


@pytest.mark.asyncio
async def test_clear_halt_activates_all_and_returns_envelope(
    harness: _Harness,
) -> None:
    response = await harness.send("system.clear_halt", {})
    assert response == CLEARED_RESPONSE
    harness.account.activate_all.assert_awaited_once_with(activated_by="ops-lead")
    harness.audit_logger.log.assert_awaited_once_with(
        member_id="ops-lead",
        action="system.clear_halt",
        resource="system:kill_switch",
        detail="",
        ip="",
    )


@pytest.mark.asyncio
async def test_clear_halt_with_unknown_key_is_rejected(harness: _Harness) -> None:
    response = await harness.send("system.clear_halt", {"x": 1})
    assert response == {
        "id": "req-1",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "system.clear_halt 인자 검증 실패: x(extra_forbidden)",
        },
    }
    harness.account.activate_all.assert_not_awaited()


_MASTER = Member(
    member_id=ACTOR,
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Ops Lead",
    status="active",
    scopes=[],
)

CLI_RESULT = {
    "status": "halt_cleared",
    "accounts_changed": 1,
    "changed_at": "2026-11-21T09:30:00+00:00",
    "accounts": [
        {
            "account_id": "acc1",
            "previous_status": "suspended",
            "status": "active",
            "changed": True,
        },
    ],
}


JSON_OUTPUT = (
    "{\n"
    '  "status": "ok",\n'
    '  "message": "시스템 정지 해제 — 1개 계좌 ACTIVE 복구 '
    '(봇은 자동 재시작되지 않음)",\n'
    '  "data": {\n'
    '    "status": "halt_cleared",\n'
    '    "accounts_changed": 1,\n'
    '    "changed_at": "2026-11-21T09:30:00+00:00",\n'
    '    "accounts": [\n'
    "      {\n"
    '        "account_id": "acc1",\n'
    '        "previous_status": "suspended",\n'
    '        "status": "active",\n'
    '        "changed": true\n'
    "      }\n"
    "    ]\n"
    "  }\n"
    "}\n"
)


def _set_member(ctx: Any) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke_clear_halt(argv: list[str]) -> tuple[int, str, AsyncMock]:
    send = AsyncMock(return_value=CLI_RESULT)
    with (
        patch("ante.cli.main.authenticate_member", side_effect=_set_member),
        patch("ante.cli.commands.ipc_helpers.ipc_send", new=send),
    ):
        result = CliRunner().invoke(cli, argv)
    return result.exit_code, result.output, send


@pytest.mark.parametrize(
    ("argv", "output"),
    [
        pytest.param(
            ["system", "clear-halt", "--reason", "r"],
            "시스템 정지 해제 — 1개 계좌 ACTIVE 복구 (봇은 자동 재시작되지 않음)\n",
            id="text",
        ),
        pytest.param(
            ["--format", "json", "system", "clear-halt", "--reason", "r"],
            JSON_OUTPUT,
            id="json",
        ),
    ],
)
def test_clear_halt_cli_success_output(argv: list[str], output: str) -> None:
    exit_code, got, _send = _invoke_clear_halt(argv)
    assert (exit_code, got) == (0, output)


def test_clear_halt_cli_sends_no_reason() -> None:
    _code, _out, send = _invoke_clear_halt(["system", "clear-halt", "--reason", "r"])
    send.assert_awaited_once_with("system.clear_halt", {}, actor=ACTOR)
