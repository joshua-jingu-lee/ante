"""``broker`` 명령의 IPC 결과별 출력과 직접 연결 여부 특성 테스트 (#2664 PR ⑥).

명령마다 (서버 정상 / 서버 미기동 / 서버가 거부 / 타임아웃) × (json / text)의
종료 코드·stdout·stderr를 리터럴로 비교하고, 직접 연결(``_get_broker``)이 몇 번
어떤 인자로 일어났는지 단언한다. 브로커·네트워크·사용자 설정에는 닿지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.account.errors import AccountNotFoundError
from ante.broker.exceptions import RateLimitError
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

_ACCOUNT = "acct-9"
_ACCOUNT_MISSING = "계좌 'acct-9'를 찾을 수 없습니다."
_SERVER_DOWN = "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
_TIMEOUT = "서버 응답 시간 초과"
_CIRCUIT = "Circuit breaker OPEN: KIS API 차단 중"
_RATE = "Rate limit 초과: 분당 20회 초과"
_IPC_SEND = "ante.cli.commands.ipc_helpers.ipc_send"
_GET_BROKER = "ante.cli.commands.broker._get_broker"
_POSITION_HISTORY = "ante.trade.position.PositionHistory"
_MODES = ("json", "text")

_COMMANDS: dict[str, list[str]] = {
    "status": ["broker", "status", "--account", _ACCOUNT],
    "balance": ["broker", "balance", "--account", _ACCOUNT],
    "positions": ["broker", "positions", "--account", _ACCOUNT],
    "order-history": ["broker", "order-history", "--account", _ACCOUNT],
    "reconcile": ["broker", "reconcile", "--account", _ACCOUNT],
    "reconcile-fix": ["broker", "reconcile", "--account", _ACCOUNT, "--fix"],
}

_IPC_REQUESTS: dict[str, tuple[str, dict[str, Any]]] = {
    "status": ("broker.status", {"account_id": _ACCOUNT}),
    "balance": ("broker.balance", {"account_id": _ACCOUNT}),
    "positions": ("broker.positions", {"account_id": _ACCOUNT}),
    "order-history": ("broker.order_history", {"account_id": _ACCOUNT}),
    "reconcile": ("broker.reconcile", {"fix": False, "account_id": _ACCOUNT}),
    "reconcile-fix": ("broker.reconcile", {"fix": True, "account_id": _ACCOUNT}),
}

_ORDER = {
    "order_id": "o-1",
    "symbol": "005930",
    "side": "buy",
    "quantity": 3,
    "filled_quantity": 3,
    "price": 70000.0,
    "status": "filled",
    "timestamp": "20260304",
}

_IPC_RESULTS: dict[str, dict[str, Any]] = {
    "status": {"connected": True, "healthy": True, "exchange": "NYSE"},
    "balance": {"cash": 5.0, "currency": "USD"},
    "positions": {
        "positions": [
            {"symbol": "AAPL", "quantity": 1, "avg_price": 2.0, "eval_amount": 3.0}
        ]
    },
    "order-history": {"orders": [{**_ORDER, "order_id": "o-ipc"}]},
    "reconcile": {
        "total_symbols": 1,
        "discrepancies": [],
        "match": True,
        "fix_applied": False,
        "corrections": 0,
    },
    "reconcile-fix": {
        "total_symbols": 1,
        "discrepancies": [],
        "match": True,
        "fix_applied": True,
        "corrections": 2,
    },
}

_DIRECT_RESULTS: dict[str, dict[str, Any]] = {
    "status": {"connected": True, "healthy": True, "exchange": "KRX"},
    "balance": {"cash": 1000.0, "currency": "KRW"},
    "positions": {
        "positions": [
            {
                "symbol": "005930",
                "quantity": 3,
                "avg_price": 70000.0,
                "eval_amount": 216000.0,
            }
        ]
    },
    "order-history": {"orders": [_ORDER]},
    "reconcile": {
        "total_symbols": 1,
        "discrepancies": [
            {"symbol": "005930", "broker_qty": 3.0, "internal_qty": 2.0, "diff": 1.0}
        ],
        "match": False,
        "fix_applied": False,
        "corrections": 0,
    },
}

_ORDER_NOTE = (
    "  ※ status 는 체결수량 기준 2값(filled/pending)이라 취소 주문도 pending 으로 "
    "보입니다. price 는 체결가/주문가 혼합, timestamp 는 영업일(일자)까지입니다."
)
_ORDER_HEADER = (
    "    order_id |       symbol |         side |     quantity | filled_quantity |"
    "        price |       status |    timestamp"
)

_IPC_TEXT: dict[str, list[str]] = {
    "status": ["  연결 상태  : 연결됨", "  건강 상태  : 정상", "  거래소     : NYSE"],
    "balance": [
        "  cash                :               5",
        "  currency            : USD",
    ],
    "positions": [
        "      symbol |     quantity |    avg_price |  eval_amount",
        "-" * 57,
        "        AAPL |            1 |          2.0 |          3.0",
    ],
    "order-history": [
        _ORDER_NOTE,
        _ORDER_HEADER,
        "-" * 120,
        "       o-ipc |       005930 |          buy |            3 |"
        "            3 |      70000.0 |       filled |     20260304",
    ],
    "reconcile": ["  총 종목 수     : 1", "  대사 결과      : 일치"],
    "reconcile-fix": [
        "  총 종목 수     : 1",
        "  대사 결과      : 일치",
        "  자동 보정      : 2건 수행",
    ],
}

_DIRECT_TEXT: dict[str, list[str]] = {
    "status": ["  연결 상태  : 연결됨", "  건강 상태  : 정상", "  거래소     : KRX"],
    "balance": [
        "  cash                :           1,000",
        "  currency            : KRW",
    ],
    "positions": [
        "      symbol |     quantity |    avg_price |  eval_amount",
        "-" * 57,
        "      005930 |            3 |      70000.0 |     216000.0",
    ],
    "order-history": [
        _ORDER_NOTE,
        _ORDER_HEADER,
        "-" * 120,
        "         o-1 |       005930 |          buy |            3 |"
        "            3 |      70000.0 |       filled |     20260304",
    ],
    "reconcile": [
        "  총 종목 수     : 1",
        "  대사 결과      : 불일치",
        "  불일치 종목:",
        "      symbol |   broker_qty | internal_qty |         diff",
        "-" * 57,
        "      005930 |          3.0 |          2.0 |          1.0",
    ],
}

_ERRORS: dict[str, click.ClickException] = {
    "down": IPCServerNotRunningError(_SERVER_DOWN),
    "circuit": IPCRemoteError("BROKER_CIRCUIT_OPEN", _CIRCUIT),
    "rate": IPCRemoteError("BROKER_RATE_LIMITED", _RATE),
    "timeout": IPCClientTimeoutError(_TIMEOUT),
}


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


class _FakePositionHistory:
    def __init__(self, db: object) -> None:
        self.db = db

    async def initialize(self) -> None:
        return None

    async def get_all_positions(
        self, account_id: str | None = None
    ) -> list[SimpleNamespace]:
        assert account_id == _ACCOUNT
        return [SimpleNamespace(symbol="005930", quantity=2.0)]


def _adapter() -> MagicMock:
    direct_positions = _DIRECT_RESULTS["positions"]["positions"]
    adapter = MagicMock()
    adapter.is_connected = True
    adapter.exchange = "KRX"
    adapter.health_check = AsyncMock(return_value=True)
    adapter.get_account_balance = AsyncMock(
        return_value=dict(_DIRECT_RESULTS["balance"])
    )
    adapter.get_positions = AsyncMock(return_value=list(direct_positions))
    adapter.get_order_history = AsyncMock(return_value=[dict(_ORDER)])
    adapter.get_account_positions = AsyncMock(
        return_value=[{"symbol": "005930", "quantity": 3}]
    )
    adapter.disconnect = AsyncMock(return_value=None)
    return adapter


class _Harness:
    def __init__(self, ipc_error: BaseException | None, ipc_value: Any) -> None:
        self.adapter = _adapter()
        self.db = MagicMock()
        self.db.close = AsyncMock(return_value=None)
        self.ipc_send = AsyncMock(side_effect=ipc_error, return_value=ipc_value)
        self.get_broker = AsyncMock(side_effect=self._get_broker)
        self.broker_error: BaseException | None = None
        self.with_db = False

    async def _get_broker(self, account_id: str | None = None) -> tuple[Any, Any]:
        if self.broker_error is not None:
            raise self.broker_error
        return self.adapter, self.db if self.with_db else None

    @property
    def direct_calls(self) -> list[Any]:
        return list(self.get_broker.await_args_list)


def _invoke(mode: str, name: str, harness: _Harness) -> Result:
    harness.with_db = name == "reconcile"
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        stack.enter_context(patch(_IPC_SEND, new=harness.ipc_send))
        stack.enter_context(patch(_GET_BROKER, new=harness.get_broker))
        stack.enter_context(patch(_POSITION_HISTORY, new=_FakePositionHistory))
        return runner.invoke(cli, ["--format", mode, *_COMMANDS[name]])


def _assert_ipc_request(name: str, harness: _Harness) -> None:
    command, args = _IPC_REQUESTS[name]
    assert harness.ipc_send.await_args_list == [
        call(command, args, actor="test-master")
    ]


def _assert_success(
    mode: str, name: str, result: Result, payload: dict[str, Any], text: list[str]
) -> None:
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert result.stderr == ""
    if mode == "json":
        assert json.loads(result.stdout) == payload
    else:
        assert result.stdout.splitlines() == text


def _assert_error(
    mode: str, result: Result, code: str, message: str, line: str
) -> None:
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


def _params(names: Iterator[str] | list[str]) -> list[Any]:
    return [pytest.param(n, m, id=f"{n}-{m}") for n in names for m in _MODES]


@pytest.mark.parametrize(("name", "mode"), _params(list(_COMMANDS)))
def test_server_ok_uses_the_ipc_result(name: str, mode: str) -> None:
    harness = _Harness(None, _IPC_RESULTS[name])

    result = _invoke(mode, name, harness)

    _assert_ipc_request(name, harness)
    assert harness.direct_calls == []
    _assert_success(mode, name, result, _IPC_RESULTS[name], _IPC_TEXT[name])


@pytest.mark.parametrize(
    ("name", "mode"),
    _params(["status", "balance", "positions", "order-history", "reconcile"]),
)
def test_server_down_falls_back_to_a_direct_connection(name: str, mode: str) -> None:
    harness = _Harness(_ERRORS["down"], None)

    result = _invoke(mode, name, harness)

    _assert_ipc_request(name, harness)
    assert harness.direct_calls == [call(_ACCOUNT)]
    _assert_success(mode, name, result, _DIRECT_RESULTS[name], _DIRECT_TEXT[name])


_REFUSALS = ("circuit", "rate", "timeout")


@pytest.mark.parametrize("situation", _REFUSALS)
@pytest.mark.parametrize(
    ("name", "mode"), _params(["status", "balance", "positions", "reconcile"])
)
def test_server_refusal_and_the_direct_connection(
    name: str, mode: str, situation: str
) -> None:
    harness = _Harness(_ERRORS[situation], None)

    result = _invoke(mode, name, harness)

    _assert_ipc_request(name, harness)
    assert harness.direct_calls == [call(_ACCOUNT)]
    _assert_success(mode, name, result, _DIRECT_RESULTS[name], _DIRECT_TEXT[name])


_ORDER_HISTORY_REFUSALS = {
    "circuit": (
        "BROKER_CIRCUIT_OPEN",
        _CIRCUIT,
        f"Error: BROKER_CIRCUIT_OPEN: {_CIRCUIT}",
    ),
    "rate": ("BROKER_RATE_LIMITED", _RATE, f"Error: BROKER_RATE_LIMITED: {_RATE}"),
    "timeout": ("IPC_TIMEOUT", _TIMEOUT, f"Error: IPC_TIMEOUT: {_TIMEOUT}"),
}


@pytest.mark.parametrize("situation", _REFUSALS)
@pytest.mark.parametrize("mode", _MODES)
def test_order_history_refusal_keeps_the_code(mode: str, situation: str) -> None:
    harness = _Harness(_ERRORS[situation], None)

    result = _invoke(mode, "order-history", harness)

    _assert_ipc_request("order-history", harness)
    assert harness.direct_calls == []
    _assert_error(mode, result, *_ORDER_HISTORY_REFUSALS[situation])


_FIX_ERRORS = {
    "down": ("IPC_SERVER_NOT_RUNNING", _SERVER_DOWN, f"Error: {_SERVER_DOWN}"),
    "circuit": (
        "BROKER_CIRCUIT_OPEN",
        _CIRCUIT,
        f"Error: BROKER_CIRCUIT_OPEN: {_CIRCUIT}",
    ),
    "rate": ("BROKER_RATE_LIMITED", _RATE, f"Error: BROKER_RATE_LIMITED: {_RATE}"),
    "timeout": ("IPC_TIMEOUT", _TIMEOUT, f"Error: {_TIMEOUT}"),
}


@pytest.mark.parametrize("situation", list(_FIX_ERRORS))
@pytest.mark.parametrize("mode", _MODES)
def test_reconcile_fix_never_falls_back(mode: str, situation: str) -> None:
    harness = _Harness(_ERRORS[situation], None)

    result = _invoke(mode, "reconcile-fix", harness)

    _assert_ipc_request("reconcile-fix", harness)
    assert harness.direct_calls == []
    _assert_error(mode, result, *_FIX_ERRORS[situation])


@pytest.mark.parametrize(
    ("name", "mode"),
    _params(["status", "balance", "positions", "order-history", "reconcile"]),
)
def test_fallback_account_not_found(name: str, mode: str) -> None:
    harness = _Harness(_ERRORS["down"], None)
    harness.broker_error = AccountNotFoundError(_ACCOUNT_MISSING)

    result = _invoke(mode, name, harness)

    assert harness.direct_calls == [call(_ACCOUNT)]
    _assert_error(
        mode,
        result,
        "ACCOUNT_NOT_FOUND",
        _ACCOUNT_MISSING,
        f"Error: {_ACCOUNT_MISSING}",
    )


_ADAPTER_METHODS = {
    "balance": "get_account_balance",
    "positions": "get_positions",
    "order-history": "get_order_history",
    "reconcile": "get_account_positions",
}


@pytest.mark.parametrize(("name", "mode"), _params(list(_ADAPTER_METHODS)))
def test_fallback_broker_error_keeps_its_code(name: str, mode: str) -> None:
    harness = _Harness(_ERRORS["down"], None)
    method = getattr(harness.adapter, _ADAPTER_METHODS[name])
    method.side_effect = RateLimitError(_RATE)

    result = _invoke(mode, name, harness)

    assert harness.direct_calls == [call(_ACCOUNT)]
    assert method.await_count == 1
    harness.adapter.disconnect.assert_awaited_once()
    _assert_error(mode, result, "BROKER_RATE_LIMITED", _RATE, f"Error: {_RATE}")


@pytest.mark.parametrize("mode", _MODES)
def test_status_fallback_broker_error_is_reported_in_the_result(mode: str) -> None:
    harness = _Harness(_ERRORS["down"], None)
    harness.adapter.health_check.side_effect = RateLimitError(_RATE)

    result = _invoke(mode, "status", harness)

    assert harness.direct_calls == [call(_ACCOUNT)]
    harness.adapter.disconnect.assert_awaited_once()
    _assert_success(
        mode,
        "status",
        result,
        {"connected": False, "healthy": False, "error": _RATE},
        ["  연결 상태  : 미연결", "  건강 상태  : 이상", f"  오류       : {_RATE}"],
    )
