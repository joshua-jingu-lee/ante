"""treasury 3·rule 1·config 1 명령의 특성 테스트 (#2683 ⑥).

실제 ``register_all_handlers``와 ``IPCServer._dispatch``를 지난다. 서비스는
호출을 기록하는 대역이다. 자금 배분·거래 규칙·설정은 실자금 경로이므로
서비스가 받은 인자는 값과 타입을 리터럴로 잠근다. CLI 경로 테스트는 실제
``cli.main``의 ``ipc_send``를 이 서버의 ``_dispatch``로 잇는다.
"""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer, IPCServerState
from ante.member.models import Member, MemberRole, MemberType
from tests.unit.ipc.validation_messages import validation_message

ACTOR = "ops-lead"
CLI_MEMBER = "cli-master-7"
RULE_RESULT = {
    "account_id": "acct-2",
    "rule_type": "daily_loss_limit",
    "rule": {"type": "daily_loss_limit", "enabled": False, "params": {}},
    "dropped_items": [],
}


class _Harness:
    def __init__(self) -> None:
        bot = MagicMock()
        bot.config.account_id = "acct-2"
        self.bot = bot
        manager = MagicMock()
        manager.get_bot = MagicMock(return_value=bot)
        self.bot_manager = manager
        treasury = MagicMock()
        treasury.allocate = AsyncMock(return_value=None)
        treasury.deallocate = AsyncMock(return_value=None)
        treasury.set_account_balance = AsyncMock(return_value=None)
        treasury.account_balance = 2500.0
        self.treasury = treasury
        treasury_manager = MagicMock()
        treasury_manager.get = MagicMock(return_value=treasury)
        self.treasury_manager = treasury_manager
        dynamic_config = MagicMock()
        dynamic_config.set = AsyncMock(return_value=None)
        self.dynamic_config = dynamic_config
        self.account = MagicMock()
        self.audit_logger = MagicMock()
        self.audit_logger.log = AsyncMock(return_value=None)
        self.rule_update = AsyncMock(side_effect=lambda **_: dict(RULE_RESULT))
        self.config = MagicMock(name="static-config")
        registry = CommandRegistry()
        register_all_handlers(registry)
        services = ServiceRegistry(
            account=self.account,
            bot_manager=manager,
            treasury_manager=treasury_manager,
            dynamic_config=dynamic_config,
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            strategy_registry=MagicMock(),
            audit_logger=self.audit_logger,
            config=self.config,
        )
        self.services = services
        self.server = IPCServer("/tmp/unused.sock", services, registry)
        self.server._state = IPCServerState.RUNNING

    async def send(self, command: str, args: Any, actor: str = ACTOR) -> dict:
        with patch(
            "ante.rule.config_update.update_account_rule_config", self.rule_update
        ):
            return await self.server._dispatch(
                {"id": "req-1", "command": command, "args": args, "actor": actor}
            )

    def assert_no_service_call(self) -> None:
        self.bot_manager.get_bot.assert_not_called()
        self.treasury_manager.get.assert_not_called()
        self.treasury.allocate.assert_not_awaited()
        self.treasury.deallocate.assert_not_awaited()
        self.treasury.set_account_balance.assert_not_awaited()
        self.dynamic_config.set.assert_not_awaited()
        self.rule_update.assert_not_awaited()
        self.audit_logger.log.assert_not_awaited()


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    return {"id": "req-1", "status": "ok", "result": result}


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "id": "req-1",
        "status": "error",
        "error": {"code": code, "message": message},
    }


def _typed(value: Any) -> tuple[str, Any]:
    return (type(value).__name__, value)


# ── treasury ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "method"),
    [("treasury.allocate", "allocate"), ("treasury.deallocate", "deallocate")],
)
async def test_budget_command_passes_the_bot_and_the_float_amount(
    command: str, method: str
) -> None:
    harness = _Harness()
    response = await harness.send(
        command, {"account_id": "acct-2", "bot_id": "b-7", "amount": 1500.5}
    )
    assert response == _ok({"account_id": "acct-2", "bot_id": "b-7", "success": True})
    harness.bot_manager.get_bot.assert_called_once_with("b-7")
    harness.treasury_manager.get.assert_called_once_with("acct-2")
    service = getattr(harness.treasury, method)
    service.assert_awaited_once_with("b-7", 1500.5)
    assert _typed(service.await_args.args[1]) == ("float", 1500.5)
    harness.audit_logger.log.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0.0, -5.0, 1e308])
@pytest.mark.parametrize(
    ("command", "method"),
    [("treasury.allocate", "allocate"), ("treasury.deallocate", "deallocate")],
)
async def test_budget_amount_range_is_left_to_the_service(
    command: str, method: str, amount: float
) -> None:
    harness = _Harness()
    response = await harness.send(
        command, {"account_id": "acct-2", "bot_id": "b-7", "amount": amount}
    )
    assert response["status"] == "ok"
    getattr(harness.treasury, method).assert_awaited_once_with("b-7", amount)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "method"),
    [("treasury.allocate", "allocate"), ("treasury.deallocate", "deallocate")],
)
async def test_budget_command_for_another_account_bot_is_the_handler_error(
    command: str, method: str
) -> None:
    harness = _Harness()
    harness.bot.config.account_id = "acct-3"
    response = await harness.send(
        command, {"account_id": "acct-2", "bot_id": "b-7", "amount": 1500.5}
    )
    assert response == _error(
        "VALIDATION_ERROR",
        f"(ipc.{command}) bot_id='b-7' 의 account_id는 'acct-3' 인데 요청은 "
        "'acct-2' 입니다. 다른 계좌의 예산을 변경할 수 없습니다.",
    )
    getattr(harness.treasury, method).assert_not_awaited()
    harness.treasury_manager.get.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["treasury.allocate", "treasury.deallocate"])
async def test_budget_command_for_a_missing_bot(command: str) -> None:
    harness = _Harness()
    harness.bot_manager.get_bot.return_value = None
    response = await harness.send(
        command, {"account_id": "acct-2", "bot_id": "b-0", "amount": 1500.5}
    )
    assert response == _error("BOT_NOT_FOUND", "Bot not found: b-0")
    harness.treasury_manager.get.assert_not_called()


@pytest.mark.asyncio
async def test_set_balance_passes_the_balance_and_audits_it() -> None:
    harness = _Harness()
    response = await harness.send(
        "treasury.set_balance", {"account_id": "acct-2", "balance": 1234567.5}
    )
    assert response["status"] == "ok"
    result = dict(response["result"])
    assert isinstance(result.pop("updated_at"), str)
    assert result == {"account_id": "acct-2", "total_balance": 2500.0}
    harness.treasury_manager.get.assert_called_once_with("acct-2")
    harness.treasury.set_account_balance.assert_awaited_once_with(1234567.5)
    assert _typed(harness.treasury.set_account_balance.await_args.args[0]) == (
        "float",
        1234567.5,
    )
    harness.audit_logger.log.assert_awaited_once_with(
        member_id=ACTOR,
        action="treasury.set_balance",
        resource="treasury:acct-2",
        detail="balance=1,234,568",
        ip="",
    )


@pytest.mark.asyncio
async def test_set_balance_of_zero_is_left_to_the_service() -> None:
    harness = _Harness()
    response = await harness.send(
        "treasury.set_balance", {"account_id": "acct-2", "balance": 0.0}
    )
    assert response["status"] == "ok"
    harness.treasury.set_account_balance.assert_awaited_once_with(0.0)


# ── rule ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_update_passes_every_field_and_audits() -> None:
    harness = _Harness()
    response = await harness.send(
        "rule.update",
        {
            "account_id": "acct-2",
            "rule_type": "daily_loss_limit",
            "enabled": False,
            "params": {"max_loss_pct": 3.5, "nested": {"k": [1, "v"]}},
        },
    )
    assert response == _ok(dict(RULE_RESULT))
    harness.rule_update.assert_awaited_once_with(
        account_service=harness.account,
        dynamic_config=harness.dynamic_config,
        account_id="acct-2",
        rule_type="daily_loss_limit",
        enabled=False,
        params={"max_loss_pct": 3.5, "nested": {"k": [1, "v"]}},
        changed_by=ACTOR,
        config=harness.config,
        audit_logger=None,
        eventbus=harness.services.eventbus,
    )
    harness.audit_logger.log.assert_awaited_once_with(
        member_id=ACTOR,
        action="account.rule.update",
        resource="account:acct-2:rule:daily_loss_limit",
        detail="rule update: daily_loss_limit enabled=False",
        ip="",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [{}, {"enabled": None}], ids=["missing", "null"])
async def test_rule_update_without_enabled_passes_none_and_audits_the_saved_value(
    enabled: dict[str, Any],
) -> None:
    harness = _Harness()
    response = await harness.send(
        "rule.update",
        {"account_id": "acct-2", "rule_type": "daily_loss_limit", **enabled},
    )
    assert response == _ok(dict(RULE_RESULT))
    kwargs = harness.rule_update.await_args.kwargs
    assert (kwargs["enabled"], kwargs["params"]) == (None, {})
    harness.audit_logger.log.assert_awaited_once_with(
        member_id=ACTOR,
        action="account.rule.update",
        resource="account:acct-2:rule:daily_loss_limit",
        detail="rule update: daily_loss_limit enabled=False",
        ip="",
    )


# ── 요청 모델이 거부하는 요청 ───────────────────────────────────────────────

ALLOCATE = {"account_id": "acct-2", "bot_id": "b-7", "amount": 1500.5}
SET_BALANCE = {"account_id": "acct-2", "balance": 1234567.5}
RULE = {"account_id": "acct-2", "rule_type": "daily_loss_limit"}
CONFIG = {"key": "k.x", "value": "v"}


def _rejected(command: str, loc: str, kind: str) -> dict[str, Any]:
    return _error("VALIDATION_ERROR", validation_message(command, (loc, kind)))


def _without(args: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in args.items() if k != key}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "args", "loc", "kind"),
    [
        ("treasury.allocate", {**ALLOCATE, "amount": "100"}, "amount", "float_type"),
        ("treasury.allocate", {**ALLOCATE, "amount": True}, "amount", "float_type"),
        ("treasury.allocate", {**ALLOCATE, "amount": None}, "amount", "float_type"),
        (
            "treasury.allocate",
            {**ALLOCATE, "amount": float("nan")},
            "amount",
            "finite_number",
        ),
        (
            "treasury.deallocate",
            {**ALLOCATE, "amount": float("inf")},
            "amount",
            "finite_number",
        ),
        ("treasury.deallocate", _without(ALLOCATE, "amount"), "amount", "missing"),
        (
            "treasury.deallocate",
            {**ALLOCATE, "account_id": "default"},
            "account_id",
            "invalid_account_id",
        ),
        (
            "treasury.allocate",
            _without(ALLOCATE, "account_id"),
            "account_id",
            "missing",
        ),
        ("treasury.allocate", {**ALLOCATE, "bot_id": 7}, "bot_id", "string_type"),
        (
            "treasury.set_balance",
            {**SET_BALANCE, "balance": float("-inf")},
            "balance",
            "finite_number",
        ),
        (
            "treasury.set_balance",
            {**SET_BALANCE, "balance": "0"},
            "balance",
            "float_type",
        ),
        (
            "treasury.set_balance",
            {**SET_BALANCE, "account_id": ""},
            "account_id",
            "invalid_account_id",
        ),
        ("rule.update", {**RULE, "enabled": "false"}, "enabled", "bool_type"),
        ("rule.update", {**RULE, "enabled": 0}, "enabled", "bool_type"),
        ("rule.update", {**RULE, "params": None}, "params", "dict_type"),
        ("rule.update", {**RULE, "params": []}, "params", "dict_type"),
        ("rule.update", _without(RULE, "rule_type"), "rule_type", "missing"),
        (
            "rule.update",
            {**RULE, "account_id": "bad_id!"},
            "account_id",
            "invalid_account_id",
        ),
        ("config.set", {**CONFIG, "value": 5}, "value", "string_type"),
        ("config.set", {**CONFIG, "value": None}, "value", "string_type"),
        ("config.set", {**CONFIG, "category": None}, "category", "string_type"),
        ("config.set", _without(CONFIG, "key"), "key", "missing"),
        ("config.set", {**CONFIG, "zz_extra": 1}, "zz_extra", "extra_forbidden"),
    ],
)
async def test_request_outside_the_model_is_rejected(
    command: str, args: dict[str, Any], loc: str, kind: str
) -> None:
    harness = _Harness()
    response = await harness.send(command, args)
    assert response == _rejected(command, loc, kind)
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "args", "method"),
    [
        ("treasury.allocate", {**ALLOCATE, "amount": 5}, "allocate"),
        ("treasury.deallocate", {**ALLOCATE, "amount": 5}, "deallocate"),
        ("treasury.set_balance", {**SET_BALANCE, "balance": 5}, "set_account_balance"),
    ],
)
async def test_treasury_amount_of_a_json_integer_reaches_the_service_as_a_float(
    command: str, args: dict[str, Any], method: str
) -> None:
    harness = _Harness()
    response = await harness.send(command, args)
    assert response["status"] == "ok"
    amount = getattr(harness.treasury, method).await_args.args[-1]
    assert _typed(amount) == ("float", 5.0)


@pytest.mark.asyncio
async def test_rule_update_params_of_any_value_reach_the_service() -> None:
    harness = _Harness()
    params = {"a": None, "b": [1, "x"], "c": {"d": False}, "e": float("nan")}
    response = await harness.send("rule.update", {**RULE, "params": params})
    assert response == _ok(dict(RULE_RESULT))
    passed = harness.rule_update.await_args.kwargs["params"]
    assert list(passed) == ["a", "b", "c", "e"]
    assert passed["a"] is None
    assert (passed["b"], passed["c"]) == ([1, "x"], {"d": False})
    assert passed["e"] != passed["e"]


@pytest.mark.asyncio
async def test_rejected_value_is_not_in_the_response_or_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "MARKCONFIGVALUE01x"
    harness = _Harness()
    response = await harness.send(
        "config.set", {"key": marker, "value": "v", "zz_extra": marker}
    )
    assert response == _rejected("config.set", "zz_extra", "extra_forbidden")
    assert marker not in json.dumps(response, ensure_ascii=False)
    assert marker not in caplog.text
    harness.assert_no_service_call()


# ── config ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_set_passes_the_string_value_in_the_user_category() -> None:
    harness = _Harness()
    response = await harness.send("config.set", {"key": "k.x", "value": "5"})
    assert response == _ok({"key": "k.x", "value": "5"})
    harness.dynamic_config.set.assert_awaited_once_with(
        "k.x", "5", category="user", changed_by=ACTOR
    )
    harness.audit_logger.log.assert_not_awaited()


@pytest.mark.asyncio
async def test_config_set_passes_a_given_category() -> None:
    harness = _Harness()
    response = await harness.send(
        "config.set", {"key": "k.x", "value": "v", "category": "system"}
    )
    assert response == _ok({"key": "k.x", "value": "v"})
    harness.dynamic_config.set.assert_awaited_once_with(
        "k.x", "v", category="system", changed_by=ACTOR
    )


# ── CLI → _dispatch → 서비스 ────────────────────────────────────────────────


_CLI_MEMBER = Member(
    member_id=CLI_MEMBER,
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="CLI Master",
    status="active",
    scopes=[],
)


def _set_member(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _CLI_MEMBER


def _run_cli(
    harness: _Harness, argv: list[str]
) -> tuple[list[tuple[str, Any, str]], str]:
    sent: list[tuple[str, Any, str]] = []

    async def _send(command: str, args: Any, actor: str = "cli", **_: Any) -> dict:
        wire = json.loads(json.dumps(args))
        sent.append((command, wire, actor))
        response = await harness.send(command, wire, actor=actor)
        assert response["status"] == "ok", response
        return dict(response["result"])

    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_member)
        )
        stack.enter_context(
            patch("ante.cli.commands.ipc_helpers.ipc_send", side_effect=_send)
        )
        stack.enter_context(
            patch("ante.cli.cold_path.is_active_runtime", return_value=True)
        )
        result = CliRunner(mix_stderr=False).invoke(cli, argv)
    assert result.exit_code == 0, (result.output, result.stderr)
    return sent, result.output


@pytest.mark.parametrize(
    ("verb", "command", "method", "line"),
    [
        ("allocate", "treasury.allocate", "allocate", "예산 할당 완료: b-7 <- 1,500원"),
        (
            "deallocate",
            "treasury.deallocate",
            "deallocate",
            "예산 회수 완료: b-7 -> 1,500원",
        ),
    ],
)
def test_cli_budget_command_sends_a_float_amount(
    verb: str, command: str, method: str, line: str
) -> None:
    harness = _Harness()
    sent, output = _run_cli(
        harness, ["treasury", verb, "b-7", "1500", "--account", "acct-2"]
    )
    assert sent == [
        (
            command,
            {"account_id": "acct-2", "bot_id": "b-7", "amount": 1500.0},
            CLI_MEMBER,
        )
    ]
    assert _typed(sent[0][1]["amount"]) == ("float", 1500.0)
    service = getattr(harness.treasury, method)
    service.assert_awaited_once_with("b-7", 1500.0)
    assert _typed(service.await_args.args[1]) == ("float", 1500.0)
    assert output == line + "\n"


def test_cli_set_balance_sends_a_float_balance() -> None:
    harness = _Harness()
    sent, output = _run_cli(
        harness, ["treasury", "set-balance", "1234567", "--account", "acct-2"]
    )
    assert sent == [
        (
            "treasury.set_balance",
            {"account_id": "acct-2", "balance": 1234567.0},
            CLI_MEMBER,
        )
    ]
    assert _typed(sent[0][1]["balance"]) == ("float", 1234567.0)
    harness.treasury.set_account_balance.assert_awaited_once_with(1234567.0)
    assert output == "계좌 잔고 설정 완료: acct-2 1,234,567\n"


def test_cli_rule_update_sends_every_field() -> None:
    harness = _Harness()
    sent, _output = _run_cli(
        harness,
        [
            "rule",
            "update",
            "daily_loss_limit",
            "--account",
            "acct-2",
            "--disabled",
            "--param",
            "max_loss_pct=3.5",
        ],
    )
    assert sent == [
        (
            "rule.update",
            {
                "account_id": "acct-2",
                "rule_type": "daily_loss_limit",
                "enabled": False,
                "params": {"max_loss_pct": 3.5},
            },
            CLI_MEMBER,
        )
    ]
    kwargs = harness.rule_update.await_args.kwargs
    assert (kwargs["enabled"], kwargs["params"]) == (False, {"max_loss_pct": 3.5})


def test_cli_rule_update_without_a_flag_leaves_enabled_out() -> None:
    harness = _Harness()
    sent, _output = _run_cli(
        harness, ["rule", "update", "daily_loss_limit", "--account", "acct-2"]
    )
    assert sent == [
        (
            "rule.update",
            {"account_id": "acct-2", "rule_type": "daily_loss_limit", "params": {}},
            CLI_MEMBER,
        )
    ]
    assert harness.rule_update.await_args.kwargs["enabled"] is None


def test_cli_rule_update_with_the_enabled_flag_sends_true() -> None:
    harness = _Harness()
    sent, _output = _run_cli(
        harness,
        ["rule", "update", "daily_loss_limit", "--account", "acct-2", "--enabled"],
    )
    assert sent == [
        (
            "rule.update",
            {
                "account_id": "acct-2",
                "rule_type": "daily_loss_limit",
                "enabled": True,
                "params": {},
            },
            CLI_MEMBER,
        )
    ]
    assert harness.rule_update.await_args.kwargs["enabled"] is True


def test_cli_config_set_of_a_number_sends_a_string() -> None:
    harness = _Harness()
    sent, _output = _run_cli(harness, ["config", "set", "k.x", "5"])
    assert sent == [("config.set", {"key": "k.x", "value": "5"}, CLI_MEMBER)]
    harness.dynamic_config.set.assert_awaited_once_with(
        "k.x", "5", category="user", changed_by=CLI_MEMBER
    )
