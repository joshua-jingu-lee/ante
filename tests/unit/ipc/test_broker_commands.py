"""broker 5 명령의 특성 테스트 (#2683 ⑦).

실제 ``register_all_handlers``와 ``IPCServer._dispatch``를 지난다. 서비스는
호출을 기록하는 대역이다. 브로커 명령은 실자금 계좌에 닿으므로 브로커·대사기가
받은 인자는 값과 타입을 리터럴로 잠근다. CLI 경로 테스트는 실제 ``cli.main``의
``ipc_send``를 이 서버의 ``_dispatch``로 잇는다. 판정 순서 테스트는 broker 명령
하나와 요청 모델이 없는 명령 하나에 대해 수명주기 → ``required_services`` → 요청
검증 → 핸들러의 순서를 잠근다.
"""

from __future__ import annotations

import json
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

ACTOR = "ops-lead"
CLI_MEMBER = "cli-master-7"
ACCOUNT = "acct-2"
BALANCE = {"cash": 1500000.0, "currency": "KRW"}
POSITIONS = [{"symbol": "005930", "quantity": 3, "avg_price": 70000.0}]
ORDERS = [{"order_id": "o-1", "symbol": "005930", "side": "buy"}]
ACCOUNT_POSITIONS = [{"symbol": "005930", "quantity": 3}]
ADJUSTMENTS = [{"symbol": "005930", "delta": 1}]
MISMATCHES = [{"symbol": "000660"}]
BROKER_COMMANDS = (
    "broker.status",
    "broker.balance",
    "broker.positions",
    "broker.order_history",
    "broker.reconcile",
)


class _Harness:
    def __init__(self, bots: list[dict[str, Any]] | None = None, **missing: None):
        broker = MagicMock()
        broker.is_connected = True
        broker.exchange = "KRX"
        broker.health_check = AsyncMock(return_value=True)
        broker.get_account_balance = AsyncMock(return_value=dict(BALANCE))
        broker.get_positions = AsyncMock(return_value=list(POSITIONS))
        broker.get_order_history = AsyncMock(return_value=list(ORDERS))
        broker.get_account_positions = AsyncMock(return_value=list(ACCOUNT_POSITIONS))
        self.broker = broker
        account = MagicMock()
        account.get_broker = AsyncMock(return_value=broker)
        self.account = account
        reconciler = MagicMock()
        reconciler.reconcile = AsyncMock(return_value=list(ADJUSTMENTS))
        reconciler.compute_account_diff = AsyncMock(return_value=list(MISMATCHES))
        reconciler.detect_account_level = AsyncMock(return_value=list(MISMATCHES))
        self.reconciler = reconciler
        bot_manager = MagicMock()
        bot_manager.list_bots = MagicMock(
            return_value=[{"bot_id": "b-1", "account_id": ACCOUNT}]
            if bots is None
            else bots
        )
        self.bot_manager = bot_manager
        self.audit_logger = MagicMock()
        self.audit_logger.log = AsyncMock(return_value=None)
        services: dict[str, Any] = {
            "account": account,
            "bot_manager": bot_manager,
            "treasury_manager": MagicMock(),
            "dynamic_config": MagicMock(),
            "approval": MagicMock(),
            "reconciler": reconciler,
            "eventbus": MagicMock(),
            "strategy_registry": MagicMock(),
            "audit_logger": self.audit_logger,
        }
        services.update(missing)
        registry = CommandRegistry()
        register_all_handlers(registry)
        self.registry = registry
        self.server = IPCServer(
            "/tmp/unused.sock", ServiceRegistry(**services), registry
        )
        self.server._state = IPCServerState.RUNNING

    async def send(self, command: str, args: Any, actor: str = ACTOR) -> dict:
        return await self.server._dispatch(
            {"id": "req-1", "command": command, "args": args, "actor": actor}
        )

    def assert_no_service_call(self) -> None:
        self.account.get_broker.assert_not_awaited()
        self.bot_manager.list_bots.assert_not_called()
        self.reconciler.reconcile.assert_not_awaited()
        self.reconciler.compute_account_diff.assert_not_awaited()
        self.reconciler.detect_account_level.assert_not_awaited()
        self.audit_logger.log.assert_not_awaited()


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    return {"id": "req-1", "status": "ok", "result": result}


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "id": "req-1",
        "status": "error",
        "error": {"code": code, "message": message},
    }


def _typed(values: tuple[Any, ...]) -> list[tuple[str, Any]]:
    return [(type(v).__name__, v) for v in values]


def _envelope(fix: bool, bot_count: int, adjustments: list[Any]) -> dict[str, Any]:
    return {
        "account_id": ACCOUNT,
        "fix": fix,
        "bot_count": bot_count,
        "adjustments": adjustments,
        "mismatches": MISMATCHES,
        "total_symbols": 1,
        "discrepancies": MISMATCHES,
        "match": False,
        "fix_applied": fix,
        "corrections": len(adjustments),
    }


# ── 정상 요청 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_asks_the_account_broker() -> None:
    harness = _Harness()
    response = await harness.send("broker.status", {"account_id": ACCOUNT})
    assert response == _ok({"connected": True, "healthy": True, "exchange": "KRX"})
    harness.account.get_broker.assert_awaited_once_with(ACCOUNT)
    harness.broker.health_check.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_balance_returns_the_broker_balance() -> None:
    harness = _Harness()
    response = await harness.send("broker.balance", {"account_id": ACCOUNT})
    assert response == _ok(BALANCE)
    harness.account.get_broker.assert_awaited_once_with(ACCOUNT)
    harness.broker.get_account_balance.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_positions_returns_the_broker_positions() -> None:
    harness = _Harness()
    response = await harness.send("broker.positions", {"account_id": ACCOUNT})
    assert response == _ok({"positions": POSITIONS})
    harness.account.get_broker.assert_awaited_once_with(ACCOUNT)
    harness.broker.get_positions.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dates", "passed"),
    [
        pytest.param(
            {"from_date": "2026-01-02", "to_date": "2026-01-31"},
            [("str", "20260102"), ("str", "20260131")],
            id="both",
        ),
        pytest.param(
            {"from_date": "2026-02-28"},
            [("str", "20260228"), ("NoneType", None)],
            id="from-only",
        ),
        pytest.param({}, [("NoneType", None), ("NoneType", None)], id="none"),
        pytest.param(
            {"from_date": None, "to_date": None},
            [("NoneType", None), ("NoneType", None)],
            id="null",
        ),
    ],
)
async def test_order_history_passes_compact_date_strings(
    dates: dict[str, Any], passed: list[tuple[str, Any]]
) -> None:
    harness = _Harness()
    response = await harness.send(
        "broker.order_history", {"account_id": ACCOUNT, **dates}
    )
    assert response == _ok({"orders": ORDERS})
    harness.account.get_broker.assert_awaited_once_with(ACCOUNT)
    call = harness.broker.get_order_history.await_args
    assert (call.kwargs, _typed(call.args)) == ({}, passed)


@pytest.mark.asyncio
async def test_reconcile_with_fix_corrects_the_single_bot_and_audits() -> None:
    harness = _Harness()
    response = await harness.send(
        "broker.reconcile", {"fix": True, "account_id": ACCOUNT}
    )
    assert response == _ok(_envelope(True, 1, ADJUSTMENTS))
    harness.account.get_broker.assert_awaited_once_with(ACCOUNT)
    harness.reconciler.reconcile.assert_awaited_once_with(
        "b-1", ACCOUNT_POSITIONS, account_id=ACCOUNT, dry_run=False
    )
    harness.reconciler.compute_account_diff.assert_awaited_once_with(
        ACCOUNT_POSITIONS, account_id=ACCOUNT
    )
    harness.audit_logger.log.assert_awaited_once_with(
        member_id=ACTOR, action="broker.reconcile", resource=f"account:{ACCOUNT}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        pytest.param({"fix": False, "account_id": ACCOUNT}, id="fix-false"),
        pytest.param({"account_id": ACCOUNT}, id="fix-absent"),
    ],
)
async def test_reconcile_without_fix_is_a_dry_run(args: dict[str, Any]) -> None:
    harness = _Harness()
    response = await harness.send("broker.reconcile", args)
    assert response == _ok(_envelope(False, 1, ADJUSTMENTS))
    harness.reconciler.reconcile.assert_awaited_once_with(
        "b-1", ACCOUNT_POSITIONS, account_id=ACCOUNT, dry_run=True
    )
    harness.audit_logger.log.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_of_two_bots_only_detects() -> None:
    bots = [
        {"bot_id": "b-1", "account_id": ACCOUNT},
        {"bot_id": "b-2", "account_id": ACCOUNT},
        {"bot_id": "b-3", "account_id": "acct-9"},
    ]
    harness = _Harness(bots=bots)
    response = await harness.send(
        "broker.reconcile", {"fix": True, "account_id": ACCOUNT}
    )
    assert response == _ok(_envelope(True, 2, []))
    harness.reconciler.reconcile.assert_not_awaited()
    harness.reconciler.detect_account_level.assert_awaited_once_with(
        ACCOUNT_POSITIONS, account_id=ACCOUNT
    )
    harness.audit_logger.log.assert_not_awaited()


# ── 판정 순서: 수명주기 → required_services → 요청 검증 → 핸들러 ──────────────


@pytest.mark.asyncio
async def test_shutting_down_rejects_a_mutating_broker_command_before_its_args() -> (
    None
):
    harness = _Harness()
    harness.server._state = IPCServerState.SHUTTING_DOWN
    response = await harness.send(
        "broker.reconcile", {"fix": True, "account_id": "default"}
    )
    assert response == _error(
        "SERVICE_UNAVAILABLE", "서버가 종료 중입니다. 변경 명령을 받지 않습니다."
    )
    harness.assert_no_service_call()


@pytest.mark.asyncio
async def test_a_missing_service_rejects_a_broker_command_before_its_args() -> None:
    harness = _Harness(audit_logger=None)
    response = await harness.send(
        "broker.reconcile", {"fix": True, "account_id": "default"}
    )
    assert response == _error(
        "SERVICE_NOT_CONFIGURED", "의존 서비스가 구성되지 않았습니다: audit_logger"
    )
    harness.assert_no_service_call()


@pytest.mark.asyncio
async def test_a_read_only_broker_command_runs_while_shutting_down() -> None:
    harness = _Harness()
    harness.server._state = IPCServerState.SHUTTING_DOWN
    response = await harness.send("broker.balance", {"account_id": ACCOUNT})
    assert response == _ok(BALANCE)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", BROKER_COMMANDS)
async def test_an_invalid_account_id_is_rejected_before_the_broker(
    command: str,
) -> None:
    harness = _Harness()
    response = await harness.send(command, {"account_id": "default"})
    assert (response["status"], response["error"]["code"]) == (
        "error",
        "VALIDATION_ERROR",
    )
    harness.assert_no_service_call()


class _ModelLess:
    def __init__(self) -> None:
        self.received: list[Any] = []

    async def __call__(self, svc: ServiceRegistry, args: Any, actor: str) -> dict:
        self.received.append(args)
        return {"actor": actor}


def _model_less_server(**missing: None) -> tuple[IPCServer, _ModelLess]:
    handler = _ModelLess()
    registry = CommandRegistry()
    registry.register(
        "demo.raw",
        handler,
        is_mutating=True,
        required_services=frozenset({"audit_logger"}),
    )
    services: dict[str, Any] = {
        "account": MagicMock(),
        "bot_manager": MagicMock(),
        "treasury_manager": MagicMock(),
        "dynamic_config": MagicMock(),
        "approval": MagicMock(),
        "reconciler": MagicMock(),
        "eventbus": MagicMock(),
        "audit_logger": MagicMock(),
    }
    services.update(missing)
    server = IPCServer("/tmp/unused.sock", ServiceRegistry(**services), registry)
    server._state = IPCServerState.RUNNING
    return server, handler


RAW_ARGS = {"account_id": "default", "zz_extra": [1, "x"], "fix": "false"}


async def _send_raw(server: IPCServer) -> dict:
    return await server._dispatch(
        {"id": "req-1", "command": "demo.raw", "args": RAW_ARGS, "actor": ACTOR}
    )


@pytest.mark.asyncio
async def test_a_model_less_command_gets_its_raw_args() -> None:
    server, handler = _model_less_server()
    response = await _send_raw(server)
    assert response == _ok({"actor": ACTOR})
    assert handler.received == [RAW_ARGS]
    assert type(handler.received[0]) is dict


@pytest.mark.asyncio
async def test_a_model_less_command_is_rejected_while_shutting_down() -> None:
    server, handler = _model_less_server()
    server._state = IPCServerState.SHUTTING_DOWN
    response = await _send_raw(server)
    assert response == _error(
        "SERVICE_UNAVAILABLE", "서버가 종료 중입니다. 변경 명령을 받지 않습니다."
    )
    assert handler.received == []


@pytest.mark.asyncio
async def test_a_model_less_command_without_its_service_is_not_configured() -> None:
    server, handler = _model_less_server(audit_logger=None)
    response = await _send_raw(server)
    assert response == _error(
        "SERVICE_NOT_CONFIGURED", "의존 서비스가 구성되지 않았습니다: audit_logger"
    )
    assert handler.received == []


# ── CLI → _dispatch → 브로커 ────────────────────────────────────────────────


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


def test_cli_status_sends_the_account() -> None:
    harness = _Harness()
    sent, output = _run_cli(harness, ["broker", "status", "--account", ACCOUNT])
    assert sent == [("broker.status", {"account_id": ACCOUNT}, CLI_MEMBER)]
    harness.account.get_broker.assert_awaited_once_with(ACCOUNT)
    assert output == (
        "  연결 상태  : 연결됨\n  건강 상태  : 정상\n  거래소     : KRX\n"
    )


def test_cli_balance_sends_the_account() -> None:
    harness = _Harness()
    sent, output = _run_cli(harness, ["broker", "balance", "--account", ACCOUNT])
    assert sent == [("broker.balance", {"account_id": ACCOUNT}, CLI_MEMBER)]
    assert output == (
        "  cash                :       1,500,000\n  currency            : KRW\n"
    )


def test_cli_positions_sends_the_account() -> None:
    harness = _Harness()
    sent, _output = _run_cli(
        harness, ["--format", "json", "broker", "positions", "--account", ACCOUNT]
    )
    assert sent == [("broker.positions", {"account_id": ACCOUNT}, CLI_MEMBER)]
    harness.broker.get_positions.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("options", "args", "passed"),
    [
        pytest.param(
            ["--from", "2026-01-02", "--to", "2026-01-31"],
            {"from_date": "2026-01-02", "to_date": "2026-01-31", "account_id": ACCOUNT},
            [("str", "20260102"), ("str", "20260131")],
            id="both",
        ),
        pytest.param(
            [],
            {"account_id": ACCOUNT},
            [("NoneType", None), ("NoneType", None)],
            id="none",
        ),
    ],
)
def test_cli_order_history_sends_iso_dates(
    options: list[str], args: dict[str, Any], passed: list[tuple[str, Any]]
) -> None:
    harness = _Harness()
    sent, _output = _run_cli(
        harness,
        ["--format", "json", "broker", "order-history", "--account", ACCOUNT, *options],
    )
    assert sent == [("broker.order_history", args, CLI_MEMBER)]
    assert list(sent[0][1]) == list(args)
    call = harness.broker.get_order_history.await_args
    assert (call.kwargs, _typed(call.args)) == ({}, passed)


@pytest.mark.parametrize(
    ("options", "fix", "dry_run"),
    [
        pytest.param(["--fix"], True, False, id="fix"),
        pytest.param([], False, True, id="no-fix"),
    ],
)
def test_cli_reconcile_sends_a_boolean_fix(
    options: list[str], fix: bool, dry_run: bool
) -> None:
    harness = _Harness()
    sent, output = _run_cli(
        harness, ["broker", "reconcile", "--account", ACCOUNT, *options]
    )
    assert sent == [
        ("broker.reconcile", {"fix": fix, "account_id": ACCOUNT}, CLI_MEMBER)
    ]
    assert type(sent[0][1]["fix"]) is bool
    harness.reconciler.reconcile.assert_awaited_once_with(
        "b-1", ACCOUNT_POSITIONS, account_id=ACCOUNT, dry_run=dry_run
    )
    corrected = "  자동 보정      : 1건 수행\n" if fix else ""
    assert output == (
        "  총 종목 수     : 1\n"
        "  대사 결과      : 불일치\n"
        "  불일치 종목:\n"
        "      symbol |   broker_qty | internal_qty |         diff\n"
        "---------------------------------------------------------\n"
        "      000660 |              |              |             \n" + corrected
    )


# ── 지금의 동작을 적는 테스트 (요청 모델이 메시지를 바꾼다) ─────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("command", BROKER_COMMANDS)
async def test_invalid_account_id_message(command: str) -> None:
    harness = _Harness()
    response = await harness.send(command, {"account_id": "bad_id!"})
    assert response == _error(
        "VALIDATION_ERROR",
        f"(ipc.{command}) 유효한 account_id가 필요합니다: 'bad_id!'. "
        "fallback (default, '', None) 또는 형식 위반 값은 사용할 수 없습니다.",
    )
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        (
            "from_date",
            "20260102",
            "'20260102'은(는) YYYY-MM-DD 형식이어야 합니다 (zero-padded).",
        ),
        ("to_date", "2026-02-30", "'2026-02-30'은(는) 유효한 달력 날짜가 아닙니다."),
    ],
)
async def test_invalid_iso_date_message(key: str, value: str, message: str) -> None:
    harness = _Harness()
    response = await harness.send(
        "broker.order_history", {"account_id": ACCOUNT, key: value}
    )
    assert response == _error("VALIDATION_ERROR", message)
    harness.account.get_broker.assert_not_awaited()
