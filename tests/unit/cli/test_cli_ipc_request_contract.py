"""CLI가 보내는 IPC 요청은 계약의 명령이고, 그 명령의 요청 모델을 통과한다 (#2683).

``execution == "runtime_ipc"``인 CLI 계약마다 유효한 호출 한 행씩(보내는 키나 값의
타입을 바꾸는 선택 옵션은 행을 더 둔다)을 실제 ``cli.main``으로 돌린다.
``ipc_send``는 호출을 기록하고 센티널 예외를 내는 대역이다. 판정은 기록된
(명령, 인자)다. 인자는 소켓을 지나는 모양 그대로(JSON 왕복) 판정한다.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from ante.cli.main import cli
from ante.contracts.cli_registry import all_contracts
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.member.models import Member, MemberRole, MemberType

ACCOUNT = "acct-1"
PASSWORD_ENV = "ANTE_TEST_IPC_CONTRACT_PW"
STREAM_COMMANDS = frozenset({"signal.connect"})


@dataclass(frozen=True)
class Row:
    path: tuple[str, ...]
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()

    @property
    def row_id(self) -> str:
        return " ".join((*self.path, *self.argv))


def _rows(path: str, *argvs: tuple[str, ...]) -> list[Row]:
    return [Row(tuple(path.split()), argv) for argv in argvs]


PW = ((PASSWORD_ENV, "pw-1"),)

ROWS: tuple[Row, ...] = (
    *_rows("account suspend", (ACCOUNT,), (ACCOUNT, "--reason", "점검")),
    *_rows("account activate", (ACCOUNT,)),
    *_rows(
        "member register",
        ("--id", "m1", "--type", "agent", "--scopes", "a,b"),
        ("--id", "m1", "--type", "agent", "--org", "o", "--name", "n"),
    ),
    *_rows("member set-emoji", ("m1", "X")),
    *_rows(
        "member update-scopes",
        ("m1", "--scopes", "a,b"),
        ("m1", "--scopes", ""),
        ("m1", "--scopes", " "),
    ),
    *_rows("member suspend", ("m1",)),
    *_rows("member reactivate", ("m1",)),
    *_rows("member revoke", ("m1", "--yes")),
    *_rows("member rotate-token", ("m1",)),
    Row(
        ("member", "reset-password"),
        ("--recovery-key", "rk", "--new-password-env", PASSWORD_ENV),
        PW,
    ),
    Row(("member", "regenerate-recovery-key"), ("--password-env", PASSWORD_ENV), PW),
    *_rows(
        "bot create",
        ("--name", "n", "--strategy", "s", "--account", ACCOUNT),
        ("--name", "n", "--strategy", "s", "--account", ACCOUNT, "--id", "b1"),
        ("--name", "n", "--strategy", "s", "--account", ACCOUNT, "--param", "k=v"),
    ),
    *_rows("bot remove", ("b1", "--yes")),
    *_rows("bot start", ("b1",)),
    *_rows("bot stop", ("b1",)),
    *_rows(
        "bot update",
        (
            "b1",
            "--name",
            "x",
            "--strategy",
            "s2",
            "--interval",
            "30",
            "--budget",
            "100",
            "--auto-restart",
            "--max-restart-attempts",
            "2",
            "--restart-cooldown-seconds",
            "20",
            "--step-timeout-seconds",
            "6",
            "--max-signals-per-step",
            "3",
        ),
        ("b1", "--no-auto-restart"),
    ),
    *_rows("bot status", ("b1",)),
    *_rows("bot list", (), ("--account", ACCOUNT)),
    *_rows("bot info", ("b1",)),
    *_rows("bot positions", ("b1",)),
    *_rows("bot signal-key", ("b1",), ("b1", "--rotate")),
    *_rows(
        "approval request",
        ("--type", "strategy_adopt", "--title", "t"),
        (
            "--type",
            "strategy_adopt",
            "--title",
            "t",
            "--body",
            "b",
            "--params",
            '{"a": 1}',
            "--reference-id",
            "r1",
            "--expires-in",
            "72h",
        ),
    ),
    *_rows("approval approve", ("ap1",)),
    *_rows("approval reject", ("ap1",), ("ap1", "--reason", "r")),
    *_rows("approval cancel", ("ap1",)),
    *_rows("approval cancel-invalid", ("ap1",)),
    *_rows("approval reopen", ("ap1",), ("ap1", "--body", "b", "--params", '{"a": 1}')),
    *_rows("treasury allocate", ("b1", "100", "--account", ACCOUNT)),
    *_rows("treasury deallocate", ("b1", "5.5", "--account", ACCOUNT)),
    *_rows("treasury set-balance", ("100", "--account", ACCOUNT)),
    *_rows(
        "rule update",
        ("daily_loss_limit", "--account", ACCOUNT, "--param", "max=5"),
        ("daily_loss_limit", "--account", ACCOUNT, "--disabled"),
        ("daily_loss_limit", "--account", ACCOUNT, "--params-json", '{"max": 5}'),
    ),
    *_rows("strategy set-status", ("s1", "--status", "archived")),
    *_rows("config set", ("k", "v")),
    *_rows("broker status", ("--account", ACCOUNT)),
    *_rows("broker balance", ("--account", ACCOUNT)),
    *_rows("broker positions", ("--account", ACCOUNT)),
    *_rows(
        "broker order-history",
        ("--account", ACCOUNT),
        ("--account", ACCOUNT, "--from", "2026-01-02", "--to", "2026-01-03"),
    ),
    *_rows("broker reconcile", ("--account", ACCOUNT), ("--account", ACCOUNT, "--fix")),
    *_rows("system halt", (), ("--reason", "r")),
    *_rows("system clear-halt", (), ("--reason", "r")),
)

COMMAND_EXCEPTIONS: dict[tuple[tuple[str, ...], str], str] = {
    (("bot", "signal-key"), "--rotate"): "bot.signal_key.rotate",
}

_MASTER = Member(
    member_id="contract-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Contract Master",
    status="active",
    scopes=[],
)


class _SentError(Exception):
    pass


@dataclass(frozen=True)
class Sent:
    row: Row
    command: str
    args: Any


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke(row: Row) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    async def _send(command: str, args: Any, **_kwargs: Any) -> dict:
        calls.append((command, json.loads(json.dumps(args))))
        raise _SentError

    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        stack.enter_context(
            patch("ante.cli.commands.ipc_helpers.ipc_send", side_effect=_send)
        )
        stack.enter_context(
            patch("ante.cli.cold_path.is_active_runtime", return_value=True)
        )
        stack.enter_context(
            patch("ante.cli.commands.bot.is_active_runtime", return_value=True)
        )
        CliRunner(mix_stderr=False).invoke(
            cli, [*row.path, *row.argv], env=dict(row.env)
        )
    return calls


def record_cli_requests() -> list[Sent]:
    sent: list[Sent] = []
    for row in ROWS:
        calls = _invoke(row)
        if len(calls) != 1:
            raise AssertionError(f"{row.row_id}: ipc_send calls={calls}")
        command, args = calls[0]
        sent.append(Sent(row, command, args))
    return sent


def _runtime_contracts() -> dict[tuple[str, ...], str | None]:
    return {
        contract.path: contract.ipc_command
        for contract in all_contracts()
        if contract.execution == "runtime_ipc"
    }


def _registry() -> CommandRegistry:
    registry = CommandRegistry()
    register_all_handlers(registry)
    return registry


def _expected_command(row: Row, contracts: dict[tuple[str, ...], str | None]) -> str:
    for (path, flag), command in COMMAND_EXCEPTIONS.items():
        if row.path == path and flag in row.argv:
            return command
    expected = contracts[row.path]
    assert expected is not None, row.path
    return expected


@pytest.fixture(scope="module")
def sent() -> list[Sent]:
    return record_cli_requests()


def _judge(registry: CommandRegistry, command: str, args: Any) -> None:
    spec = registry.get(command)
    assert spec is not None
    spec.request_model.model_validate(args)


def test_rows_cover_every_runtime_ipc_contract() -> None:
    contracts = _runtime_contracts()
    assert len(contracts) == 40
    assert {row.path for row in ROWS} == set(contracts)


def test_sent_commands_are_every_registered_command_but_the_stream(
    sent: list[Sent],
) -> None:
    registered = set(_registry().commands)
    assert len(registered) == 42
    assert {item.command for item in sent} == registered - STREAM_COMMANDS


def test_each_row_sends_the_contract_command(sent: list[Sent]) -> None:
    contracts = _runtime_contracts()
    wrong = [
        (item.row.row_id, item.command, _expected_command(item.row, contracts))
        for item in sent
        if item.command != _expected_command(item.row, contracts)
    ]
    assert wrong == []
    used = {
        (path, flag)
        for item in sent
        for (path, flag) in COMMAND_EXCEPTIONS
        if item.row.path == path and flag in item.row.argv
    }
    assert used == set(COMMAND_EXCEPTIONS)
    differs = {
        (item.row.path, item.command)
        for item in sent
        if item.command != contracts[item.row.path]
    }
    assert differs == {(("bot", "signal-key"), "bot.signal_key.rotate")}


def test_sent_args_pass_the_command_request_model(sent: list[Sent]) -> None:
    registry = _registry()
    assert sent
    rejected: list[str] = []
    for item in sent:
        _judge(registry, item.command, item.args)
        try:
            _judge(registry, item.command, {**item.args, "zz_extra": 1})
        except ValidationError:
            rejected.append(item.row.row_id)
    assert rejected == [item.row.row_id for item in sent]


def test_an_empty_scopes_option_sends_an_explicit_empty_list(
    sent: list[Sent],
) -> None:
    args = [
        item.args
        for item in sent
        if item.row.path == ("member", "update-scopes") and "" in item.row.argv
    ]
    assert args == [{"member_id": "m1", "scopes": []}]


def test_a_blank_scopes_option_sends_a_blank_scope_not_an_empty_list(
    sent: list[Sent],
) -> None:
    args = [
        item.args
        for item in sent
        if item.row.path == ("member", "update-scopes") and " " in item.row.argv
    ]
    assert args == [{"member_id": "m1", "scopes": [""]}]
