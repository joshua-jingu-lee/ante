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
import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from ante.cli.main import cli
from ante.core import clock
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.requests import AccountId, BrokerOrderHistoryRequest, IPCRequest
from ante.ipc.server import IPCServer, IPCServerState
from ante.member.models import Member, MemberRole, MemberType
from tests.unit.ipc.validation_messages import validation_message

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


_KST = timezone(timedelta(hours=9))


class _FixedClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self, tz: tzinfo | None) -> datetime:
        return self._at.astimezone(tz or UTC)

    def monotonic(self) -> float:
        return 1000.0


@contextmanager
def _kst_noon(year: int, month: int, day: int) -> Iterator[None]:
    with clock.use_clock(_FixedClock(datetime(year, month, day, 12, tzinfo=_KST))):
        yield


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
        account.ensure_reconcile_applicable = AsyncMock(return_value=None)
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


def _envelope(
    fix: bool, bot_count: int, adjustments: list[Any], *, fix_applied: bool
) -> dict[str, Any]:
    return {
        "account_id": ACCOUNT,
        "fix": fix,
        "bot_count": bot_count,
        "adjustments": adjustments,
        "mismatches": MISMATCHES,
        "total_symbols": 1,
        "discrepancies": MISMATCHES,
        "match": False,
        "fix_applied": fix_applied,
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
    assert response == _ok(_envelope(True, 1, ADJUSTMENTS, fix_applied=True))
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
    assert response == _ok(_envelope(False, 1, ADJUSTMENTS, fix_applied=False))
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
    assert response == _ok(_envelope(True, 2, [], fix_applied=False))
    harness.reconciler.reconcile.assert_not_awaited()
    harness.reconciler.detect_account_level.assert_awaited_once_with(
        ACCOUNT_POSITIONS, account_id=ACCOUNT
    )
    harness.audit_logger.log.assert_not_awaited()


def _judged_by_the_account(harness: _Harness, broker_type: str, mode: str) -> None:
    """대역 계좌 서비스의 판정을 실제 ``ensure_reconcile_applicable``로 바꾼다."""
    from types import MethodType

    from ante.account.models import Account, TradingMode
    from ante.account.service import AccountService

    account = Account(
        account_id=ACCOUNT,
        name="n",
        exchange="KRX",
        currency="KRW",
        broker_type=broker_type,
        trading_mode=TradingMode(mode),
    )
    harness.account.get = AsyncMock(return_value=account)
    harness.account.ensure_reconcile_applicable = AsyncMock(
        side_effect=MethodType(
            AccountService.ensure_reconcile_applicable, harness.account
        )
    )


_TWO_BOTS = [
    {"bot_id": "b-1", "account_id": ACCOUNT},
    {"bot_id": "b-2", "account_id": ACCOUNT},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("broker_type", ["test", "kis-domestic", "mock"])
@pytest.mark.parametrize("fix", [True, False])
@pytest.mark.parametrize("bots", [None, _TWO_BOTS], ids=["one-bot", "two-bots"])
async def test_reconcile_of_a_virtual_account_is_rejected_before_the_broker(
    broker_type: str, fix: bool, bots: list[dict[str, Any]] | None
) -> None:
    harness = _Harness(bots=bots)
    _judged_by_the_account(harness, broker_type, "virtual")
    response = await harness.send(
        "broker.reconcile", {"fix": fix, "account_id": ACCOUNT}
    )
    assert response == _error(
        "ACCOUNT_RECONCILE_NOT_APPLICABLE",
        f"계좌 '{ACCOUNT}'는 가상 계좌라 브로커와 대사하지 않습니다. "
        "가상 계좌의 포지션은 내부 기록이 기준입니다.",
    )
    harness.account.ensure_reconcile_applicable.assert_awaited_once_with(ACCOUNT)
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize("fix", [True, False])
async def test_reconcile_of_a_live_account_passes_the_check(fix: bool) -> None:
    harness = _Harness()
    _judged_by_the_account(harness, "kis-domestic", "live")
    response = await harness.send(
        "broker.reconcile", {"fix": fix, "account_id": ACCOUNT}
    )
    assert response == _ok(_envelope(fix, 1, ADJUSTMENTS, fix_applied=fix))
    harness.account.ensure_reconcile_applicable.assert_awaited_once_with(ACCOUNT)
    harness.account.get_broker.assert_awaited_once_with(ACCOUNT)
    harness.reconciler.reconcile.assert_awaited_once_with(
        "b-1", ACCOUNT_POSITIONS, account_id=ACCOUNT, dry_run=not fix
    )


@pytest.mark.asyncio
async def test_reconcile_of_a_missing_account_keeps_its_not_found_error() -> None:
    from ante.account.errors import AccountNotFoundError

    harness = _Harness()
    harness.account.ensure_reconcile_applicable = AsyncMock(
        side_effect=AccountNotFoundError(f"계좌 '{ACCOUNT}'를 찾을 수 없습니다.")
    )
    response = await harness.send(
        "broker.reconcile", {"fix": True, "account_id": ACCOUNT}
    )
    assert response == _error(
        "ACCOUNT_NOT_FOUND", f"계좌 '{ACCOUNT}'를 찾을 수 없습니다."
    )
    harness.assert_no_service_call()


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


class _DemoAccountRequest(IPCRequest):
    account_id: AccountId


class _DemoHandler:
    def __init__(self) -> None:
        self.received: list[Any] = []

    async def __call__(self, svc: ServiceRegistry, args: Any, actor: str) -> dict:
        self.received.append(args)
        return {"actor": actor}


def _demo_server(**missing: None) -> tuple[IPCServer, _DemoHandler]:
    handler = _DemoHandler()
    registry = CommandRegistry()
    registry.register(
        "demo.raw",
        handler,
        is_mutating=True,
        request_model=_DemoAccountRequest,
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


async def _send_raw(server: IPCServer, args: Any = RAW_ARGS) -> dict:
    return await server._dispatch(
        {"id": "req-1", "command": "demo.raw", "args": args, "actor": ACTOR}
    )


@pytest.mark.asyncio
async def test_a_demo_command_gets_its_validated_model() -> None:
    server, handler = _demo_server()
    response = await _send_raw(server, {"account_id": "acct-1"})
    assert response == _ok({"actor": ACTOR})
    assert handler.received == [_DemoAccountRequest(account_id="acct-1")]


@pytest.mark.asyncio
async def test_a_demo_command_rejects_raw_args_before_its_handler() -> None:
    server, handler = _demo_server()
    response = await _send_raw(server)
    assert (response["status"], response["error"]["code"]) == (
        "error",
        "VALIDATION_ERROR",
    )
    assert handler.received == []


@pytest.mark.asyncio
async def test_a_demo_command_is_rejected_while_shutting_down() -> None:
    server, handler = _demo_server()
    server._state = IPCServerState.SHUTTING_DOWN
    response = await _send_raw(server)
    assert response == _error(
        "SERVICE_UNAVAILABLE", "서버가 종료 중입니다. 변경 명령을 받지 않습니다."
    )
    assert handler.received == []


@pytest.mark.asyncio
async def test_a_demo_command_without_its_service_is_not_configured() -> None:
    server, handler = _demo_server(audit_logger=None)
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


# ── 요청 모델 밖의 요청 ──────────────────────────────────────────────────────


def _rejected(command: str, loc: str, kind: str) -> dict[str, Any]:
    return _error("VALIDATION_ERROR", validation_message(command, (loc, kind)))


@pytest.mark.asyncio
@pytest.mark.parametrize("command", BROKER_COMMANDS)
async def test_invalid_account_id_message(command: str) -> None:
    harness = _Harness()
    response = await harness.send(command, {"account_id": "bad_id!"})
    assert response == _rejected(command, "account_id", "invalid_account_id")
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "value"),
    [("from_date", "20260102"), ("to_date", "2026-02-30")],
)
async def test_invalid_iso_date_message(key: str, value: str) -> None:
    harness = _Harness()
    response = await harness.send(
        "broker.order_history", {"account_id": ACCOUNT, key: value}
    )
    assert response == _rejected("broker.order_history", key, "invalid_iso_date")
    harness.account.get_broker.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "passed"),
    [
        pytest.param("2028-02-29", "20280229", id="leap-day"),
        pytest.param("2026-12-31", "20261231", id="year-end"),
    ],
)
async def test_a_valid_iso_date_next_to_a_rejected_one_reaches_the_broker(
    value: str, passed: str
) -> None:
    harness = _Harness()
    with _kst_noon(2026, 6, 11):
        response = await harness.send(
            "broker.order_history", {"account_id": ACCOUNT, "to_date": value}
        )
    assert response == _ok({"orders": ORDERS})
    call = harness.broker.get_order_history.await_args
    assert _typed(call.args) == [("NoneType", None), ("str", passed)]


@pytest.mark.asyncio
async def test_an_inverted_date_range_is_rejected_before_the_broker() -> None:
    harness = _Harness()
    response = await harness.send(
        "broker.order_history",
        {"account_id": ACCOUNT, "from_date": "2026-02-01", "to_date": "2026-01-01"},
    )
    assert response == _error(
        "INVALID_DATE_RANGE",
        "조회 시작일(2026-02-01)이(가) 조회 종료일(2026-01-01) 이후입니다.",
    )
    harness.account.get_broker.assert_not_awaited()
    harness.broker.get_order_history.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "passed", "today"),
    [
        pytest.param(
            {"from_date": "2026-01-01", "to_date": "2026-01-01"},
            [("str", "20260101"), ("str", "20260101")],
            (2026, 6, 11),
            id="same-day",
        ),
        pytest.param(
            {"from_date": "2026-02-01"},
            [("str", "20260201"), ("NoneType", None)],
            (2026, 6, 11),
            id="from-only",
        ),
        pytest.param(
            {"to_date": "2026-01-01"},
            [("NoneType", None), ("str", "20260101")],
            (2026, 1, 5),
            id="to-only",
        ),
    ],
)
async def test_a_range_that_is_not_inverted_reaches_the_broker(
    args: dict[str, str],
    passed: list[tuple[str, Any]],
    today: tuple[int, int, int],
) -> None:
    harness = _Harness()
    with _kst_noon(*today):
        response = await harness.send(
            "broker.order_history", {"account_id": ACCOUNT, **args}
        )
    assert response == _ok({"orders": ORDERS})
    call = harness.broker.get_order_history.await_args
    assert _typed(call.args) == passed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "message"),
    [
        pytest.param(
            {"from_date": "2026-06-12"},
            "조회 시작일(2026-06-12)이(가) 기본 조회 종료일(2026-06-11) 이후입니다.",
            id="from-only-future",
        ),
        pytest.param(
            {"to_date": "2026-06-03"},
            "기본 조회 시작일(2026-06-04)이(가) 조회 종료일(2026-06-03) 이후입니다.",
            id="to-only-before-default-start",
        ),
    ],
)
async def test_a_one_sided_range_inverted_by_its_default_is_rejected_before_the_broker(
    args: dict[str, str], message: str
) -> None:
    harness = _Harness()
    with _kst_noon(2026, 6, 11):
        response = await harness.send(
            "broker.order_history", {"account_id": ACCOUNT, **args}
        )
    assert response == _error("INVALID_DATE_RANGE", message)
    harness.account.get_broker.assert_not_awaited()
    harness.broker.get_order_history.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "passed"),
    [
        pytest.param(
            {"from_date": "2026-06-11"},
            [("str", "20260611"), ("NoneType", None)],
            id="from-only-today",
        ),
        pytest.param(
            {"to_date": "2026-06-04"},
            [("NoneType", None), ("str", "20260604")],
            id="to-only-default-start",
        ),
    ],
)
async def test_a_one_sided_range_on_its_default_boundary_reaches_the_broker(
    args: dict[str, str], passed: list[tuple[str, Any]]
) -> None:
    harness = _Harness()
    with _kst_noon(2026, 6, 11):
        response = await harness.send(
            "broker.order_history", {"account_id": ACCOUNT, **args}
        )
    assert response == _ok({"orders": ORDERS})
    call = harness.broker.get_order_history.await_args
    assert (call.kwargs, _typed(call.args)) == ({}, passed)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "args", "loc", "kind"),
    [
        ("broker.status", {}, "account_id", "missing"),
        ("broker.balance", {"account_id": None}, "account_id", "string_type"),
        ("broker.positions", {"account_id": 7}, "account_id", "string_type"),
        (
            "broker.status",
            {"account_id": ACCOUNT, "zz_extra": 1},
            "zz_extra",
            "extra_forbidden",
        ),
        ("broker.balance", ["x"], "args", "model_type"),
        (
            "broker.order_history",
            {"account_id": ACCOUNT, "from_date": 20260102},
            "from_date",
            "string_type",
        ),
        (
            "broker.order_history",
            {"account_id": ACCOUNT, "to_date": True},
            "to_date",
            "string_type",
        ),
        (
            "broker.reconcile",
            {"account_id": ACCOUNT, "fix": "false"},
            "fix",
            "bool_type",
        ),
        ("broker.reconcile", {"account_id": ACCOUNT, "fix": 1}, "fix", "bool_type"),
        (
            "broker.reconcile",
            {"account_id": ACCOUNT, "fix": None},
            "fix",
            "bool_type",
        ),
        ("broker.reconcile", {"fix": True}, "account_id", "missing"),
    ],
)
async def test_request_outside_the_model_is_rejected(
    command: str, args: Any, loc: str, kind: str
) -> None:
    harness = _Harness()
    response = await harness.send(command, args)
    assert response == _rejected(command, loc, kind)
    harness.assert_no_service_call()


@pytest.mark.asyncio
async def test_rejected_value_is_not_in_the_response_or_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "MARKBROKERDATE01x"
    harness = _Harness()
    response = await harness.send(
        "broker.order_history",
        {"account_id": f"{marker}!", "from_date": f"{marker}-01"},
    )
    assert response == _error(
        "VALIDATION_ERROR",
        validation_message(
            "broker.order_history",
            ("account_id", "invalid_account_id"),
            ("from_date", "invalid_iso_date"),
        ),
    )
    assert marker not in json.dumps(response, ensure_ascii=False)
    assert marker not in caplog.text
    harness.assert_no_service_call()


def test_iso_date_error_message_is_a_fixed_text() -> None:
    with pytest.raises(ValidationError) as rejected:
        BrokerOrderHistoryRequest.model_validate(
            {"account_id": ACCOUNT, "from_date": "MARKDATE01-99"}
        )
    assert [(e["type"], e["msg"]) for e in rejected.value.errors()] == [
        ("invalid_iso_date", "invalid iso date")
    ]
