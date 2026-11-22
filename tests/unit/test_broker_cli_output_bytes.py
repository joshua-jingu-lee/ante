"""broker 5개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. IPC가 응답하는
분기와 서버가 없어 증권사 어댑터에 직접 연결하는 분기
(``IPCServerNotRunningError`` 폴백)를 각각 고정한다. ``reconcile --fix``는
IPC 전용이다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.contracts.ipc_client_errors import IPCServerNotRunningError
from ante.member.models import Member

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_BALANCE: dict[str, Any] = {
    "cash": 1_500_000.0,
    "total_assets": 12_345_678.9,
    "purchase_amount": 9_000_000.0,
    "eval_amount": 10_845_678.9,
    "total_profit_loss": 1_845_678.9,
    "substitute_amount": 0.0,
    "currency": "KRW",
    "position_count": 2,
}

_POSITIONS: list[dict[str, Any]] = [
    {
        "symbol": "005930",
        "name": "삼성전자",
        "quantity": 10.0,
        "avg_price": 70_000.0,
        "current_price": 72_000.0,
        "eval_amount": 720_000.0,
        "profit_loss": 20_000.0,
        "profit_loss_rate": 2.86,
    },
    {
        "symbol": "000660",
        "name": "SK하이닉스",
        "quantity": 5.0,
        "avg_price": 120_000.0,
        "current_price": 118_000.0,
        "eval_amount": 590_000.0,
        "profit_loss": -10_000.0,
        "profit_loss_rate": -1.67,
    },
]

_ORDERS: list[dict[str, Any]] = [
    {
        "order_id": "ORD-0001",
        "symbol": "005930",
        "side": "buy",
        "quantity": 10.0,
        "filled_quantity": 10.0,
        "price": 70_100.0,
        "status": "filled",
        "timestamp": "20260102",
    },
    {
        "order_id": "ORD-0002",
        "symbol": "000660",
        "side": "sell",
        "quantity": 5.0,
        "filled_quantity": 0.0,
        "price": 120_000.0,
        "status": "pending",
        "timestamp": "20260102",
    },
]

_DISCREPANCIES: list[dict[str, Any]] = [
    {"symbol": "005930", "broker_qty": 10.0, "internal_qty": 8.0, "diff": 2.0},
]

_NOT_RUNNING = IPCServerNotRunningError("not running")
_STATUS_ERROR = "증권사 연결 실패: FAKE-ERROR-TOKEN-0000"

_ACCOUNT = ["--account", "acc-1"]
_OH = ["broker", "order-history", *_ACCOUNT]
_RANGE = ["--from", "2026-01-01", "--to", "2026-01-02"]


def _pair(name: str, args: list[str]) -> dict[str, list[str]]:
    return {f"{name}_ipc": args, f"{name}_direct": args}


_CASES: dict[str, list[str]] = {
    **_pair("status", ["broker", "status", *_ACCOUNT]),
    "status_down_ipc": ["broker", "status", *_ACCOUNT],
    "status_error_direct": ["broker", "status", *_ACCOUNT],
    **_pair("balance", ["broker", "balance", *_ACCOUNT]),
    **_pair("positions_empty", ["broker", "positions", *_ACCOUNT]),
    **_pair("positions_rows", ["broker", "positions", *_ACCOUNT]),
    **_pair("orders_empty", list(_OH)),
    **_pair("orders_rows", list(_OH)),
    **_pair("orders_range", [*_OH, *_RANGE]),
    **_pair("reconcile_match", ["broker", "reconcile", *_ACCOUNT]),
    **_pair("reconcile_mismatch", ["broker", "reconcile", *_ACCOUNT]),
    "reconcile_fix": ["broker", "reconcile", *_ACCOUNT, "--fix"],
}


def _ipc_result(branch: str) -> Any:
    if branch.endswith("_direct"):
        return _NOT_RUNNING
    results: dict[str, Any] = {
        "status_ipc": {"connected": True, "healthy": True, "exchange": "KRX"},
        "status_down_ipc": {"connected": False, "healthy": False, "exchange": ""},
        "balance_ipc": _BALANCE,
        "positions_empty_ipc": {"positions": []},
        "positions_rows_ipc": {"positions": _POSITIONS},
        "orders_empty_ipc": {"orders": []},
        "orders_rows_ipc": {"orders": _ORDERS},
        "orders_range_ipc": {"orders": _ORDERS[:1]},
        "reconcile_match_ipc": {
            "total_symbols": 2,
            "discrepancies": [],
            "match": True,
            "fix_applied": False,
            "corrections": 0,
        },
        "reconcile_mismatch_ipc": {
            "total_symbols": 2,
            "discrepancies": _DISCREPANCIES,
            "match": False,
            "fix_applied": False,
            "corrections": 0,
        },
        "reconcile_fix": {
            "total_symbols": 2,
            "discrepancies": _DISCREPANCIES,
            "match": False,
            "fix_applied": True,
            "corrections": 1,
        },
    }
    return results[branch]


def _adapter(branch: str) -> AsyncMock:
    adapter = AsyncMock()
    adapter.is_connected = True
    adapter.exchange = "KRX"
    adapter.health_check = AsyncMock(return_value=True)
    adapter.get_account_balance = AsyncMock(return_value=dict(_BALANCE))
    rows = [] if branch == "positions_empty_direct" else list(_POSITIONS)
    adapter.get_positions = AsyncMock(return_value=rows)
    orders = {"orders_empty_direct": [], "orders_range_direct": _ORDERS[:1]}
    adapter.get_order_history = AsyncMock(
        return_value=list(orders.get(branch, _ORDERS))
    )
    held = [{"symbol": "005930", "quantity": 10}, {"symbol": "000660", "quantity": 5}]
    adapter.get_account_positions = AsyncMock(return_value=held)
    return adapter


def _internal_positions(branch: str) -> list[SimpleNamespace]:
    qty = 8.0 if branch == "reconcile_mismatch_direct" else 10.0
    return [
        SimpleNamespace(symbol="005930", quantity=qty),
        SimpleNamespace(symbol="000660", quantity=5.0),
    ]


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


def _invoke_case(
    branch: str, mode: str, *, mix_stderr: bool = True
) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    ipc_value = _ipc_result(branch)
    if isinstance(ipc_value, Exception):
        ipc_send = AsyncMock(side_effect=ipc_value)
    else:
        ipc_send = AsyncMock(return_value=ipc_value)
    if branch == "status_error_direct":
        get_broker = AsyncMock(side_effect=RuntimeError(_STATUS_ERROR))
    else:
        get_broker = AsyncMock(return_value=(_adapter(branch), AsyncMock()))
    history = AsyncMock()
    history.get_all_positions = AsyncMock(return_value=_internal_positions(branch))

    full_args = ["--format", "json", *_CASES[branch]] if mode == "json" else None
    with ExitStack() as stack:
        for target, value in (
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
            ("ante.cli.commands.broker._get_broker", get_broker),
            ("ante.trade.position.PositionHistory", MagicMock(return_value=history)),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli,
            full_args if full_args is not None else list(_CASES[branch]),
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )
    return result, ipc_send


_BROKER_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("status_ipc", "text"): (
        "  연결 상태  : 연결됨\n  건강 상태  : 정상\n  거래소     : KRX\n"
    ),
    ("status_ipc", "json"): (
        '{\n  "connected": true,\n  "healthy": true,\n  "exchange": "KRX"\n}\n'
    ),
    ("status_direct", "text"): (
        "  연결 상태  : 연결됨\n  건강 상태  : 정상\n  거래소     : KRX\n"
    ),
    ("status_direct", "json"): (
        '{\n  "connected": true,\n  "healthy": true,\n  "exchange": "KRX"\n}\n'
    ),
    ("status_down_ipc", "text"): ("  연결 상태  : 미연결\n  건강 상태  : 이상\n"),
    ("status_down_ipc", "json"): (
        '{\n  "connected": false,\n  "healthy": false,\n  "exchange": ""\n}\n'
    ),
    ("status_error_direct", "text"): (
        "  연결 상태  : 미연결\n"
        "  건강 상태  : 이상\n"
        "  오류       : 증권사 연결 실패: FAKE-ERROR-TOKEN-0000\n"
    ),
    ("status_error_direct", "json"): (
        "{\n"
        '  "connected": false,\n'
        '  "healthy": false,\n'
        '  "error": "증권사 연결 실패: FAKE-ERROR-TOKEN-0000"\n'
        "}\n"
    ),
    ("balance_ipc", "text"): (
        "  cash                :       1,500,000\n"
        "  total_assets        :      12,345,679\n"
        "  purchase_amount     :       9,000,000\n"
        "  eval_amount         :      10,845,679\n"
        "  total_profit_loss   :       1,845,679\n"
        "  substitute_amount   :               0\n"
        "  currency            : KRW\n"
        "  position_count      : 2\n"
    ),
    ("balance_ipc", "json"): (
        "{\n"
        '  "cash": 1500000.0,\n'
        '  "total_assets": 12345678.9,\n'
        '  "purchase_amount": 9000000.0,\n'
        '  "eval_amount": 10845678.9,\n'
        '  "total_profit_loss": 1845678.9,\n'
        '  "substitute_amount": 0.0,\n'
        '  "currency": "KRW",\n'
        '  "position_count": 2\n'
        "}\n"
    ),
    ("balance_direct", "text"): (
        "  cash                :       1,500,000\n"
        "  total_assets        :      12,345,679\n"
        "  purchase_amount     :       9,000,000\n"
        "  eval_amount         :      10,845,679\n"
        "  total_profit_loss   :       1,845,679\n"
        "  substitute_amount   :               0\n"
        "  currency            : KRW\n"
        "  position_count      : 2\n"
    ),
    ("balance_direct", "json"): (
        "{\n"
        '  "cash": 1500000.0,\n'
        '  "total_assets": 12345678.9,\n'
        '  "purchase_amount": 9000000.0,\n'
        '  "eval_amount": 10845678.9,\n'
        '  "total_profit_loss": 1845678.9,\n'
        '  "substitute_amount": 0.0,\n'
        '  "currency": "KRW",\n'
        '  "position_count": 2\n'
        "}\n"
    ),
    ("positions_empty_ipc", "text"): (
        "{'message': '보유 종목 없음', 'positions': []}\n"
    ),
    ("positions_empty_ipc", "json"): (
        '{\n  "message": "보유 종목 없음",\n  "positions": []\n}\n'
    ),
    ("positions_empty_direct", "text"): (
        "{'message': '보유 종목 없음', 'positions': []}\n"
    ),
    ("positions_empty_direct", "json"): (
        '{\n  "message": "보유 종목 없음",\n  "positions": []\n}\n'
    ),
    ("positions_rows_ipc", "text"): (
        "      symbol |     quantity |    avg_price |  eval_amount\n"
        "---------------------------------------------------------\n"
        "      005930 |         10.0 |      70000.0 |     720000.0\n"
        "      000660 |          5.0 |     120000.0 |     590000.0\n"
    ),
    ("positions_rows_ipc", "json"): (
        "{\n"
        '  "positions": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "name": "삼성전자",\n'
        '      "quantity": 10.0,\n'
        '      "avg_price": 70000.0,\n'
        '      "current_price": 72000.0,\n'
        '      "eval_amount": 720000.0,\n'
        '      "profit_loss": 20000.0,\n'
        '      "profit_loss_rate": 2.86\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000660",\n'
        '      "name": "SK하이닉스",\n'
        '      "quantity": 5.0,\n'
        '      "avg_price": 120000.0,\n'
        '      "current_price": 118000.0,\n'
        '      "eval_amount": 590000.0,\n'
        '      "profit_loss": -10000.0,\n'
        '      "profit_loss_rate": -1.67\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("positions_rows_direct", "text"): (
        "      symbol |     quantity |    avg_price |  eval_amount\n"
        "---------------------------------------------------------\n"
        "      005930 |         10.0 |      70000.0 |     720000.0\n"
        "      000660 |          5.0 |     120000.0 |     590000.0\n"
    ),
    ("positions_rows_direct", "json"): (
        "{\n"
        '  "positions": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "name": "삼성전자",\n'
        '      "quantity": 10.0,\n'
        '      "avg_price": 70000.0,\n'
        '      "current_price": 72000.0,\n'
        '      "eval_amount": 720000.0,\n'
        '      "profit_loss": 20000.0,\n'
        '      "profit_loss_rate": 2.86\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000660",\n'
        '      "name": "SK하이닉스",\n'
        '      "quantity": 5.0,\n'
        '      "avg_price": 120000.0,\n'
        '      "current_price": 118000.0,\n'
        '      "eval_amount": 590000.0,\n'
        '      "profit_loss": -10000.0,\n'
        '      "profit_loss_rate": -1.67\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("orders_empty_ipc", "text"): ("  주문/체결 이력 없음\n"),
    ("orders_empty_ipc", "json"): ('{\n  "orders": []\n}\n'),
    ("orders_empty_direct", "text"): ("  주문/체결 이력 없음\n"),
    ("orders_empty_direct", "json"): ('{\n  "orders": []\n}\n'),
    ("orders_rows_ipc", "text"): (
        "  ※ status 는 체결수량 기준 2값(filled/pending)이라 취소 주문도 pending 으로 "
        "보입니다. price 는 체결가/주문가 혼합, timestamp 는 영업일(일자)까지입니다.\n"
        "    order_id |       symbol |         side |     quantity | filled_quantity |"
        "        price |       status |    timestamp\n"
        "-----------------------------------------------------------------------------"
        "-------------------------------------------\n"
        "    ORD-0001 |       005930 |          buy |         10.0 |         10.0 |   "
        "   70100.0 |       filled |     20260102\n"
        "    ORD-0002 |       000660 |         sell |          5.0 |          0.0 |   "
        "  120000.0 |      pending |     20260102\n"
    ),
    ("orders_rows_ipc", "json"): (
        "{\n"
        '  "orders": [\n'
        "    {\n"
        '      "order_id": "ORD-0001",\n'
        '      "symbol": "005930",\n'
        '      "side": "buy",\n'
        '      "quantity": 10.0,\n'
        '      "filled_quantity": 10.0,\n'
        '      "price": 70100.0,\n'
        '      "status": "filled",\n'
        '      "timestamp": "20260102"\n'
        "    },\n"
        "    {\n"
        '      "order_id": "ORD-0002",\n'
        '      "symbol": "000660",\n'
        '      "side": "sell",\n'
        '      "quantity": 5.0,\n'
        '      "filled_quantity": 0.0,\n'
        '      "price": 120000.0,\n'
        '      "status": "pending",\n'
        '      "timestamp": "20260102"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("orders_rows_direct", "text"): (
        "  ※ status 는 체결수량 기준 2값(filled/pending)이라 취소 주문도 pending 으로 "
        "보입니다. price 는 체결가/주문가 혼합, timestamp 는 영업일(일자)까지입니다.\n"
        "    order_id |       symbol |         side |     quantity | filled_quantity |"
        "        price |       status |    timestamp\n"
        "-----------------------------------------------------------------------------"
        "-------------------------------------------\n"
        "    ORD-0001 |       005930 |          buy |         10.0 |         10.0 |   "
        "   70100.0 |       filled |     20260102\n"
        "    ORD-0002 |       000660 |         sell |          5.0 |          0.0 |   "
        "  120000.0 |      pending |     20260102\n"
    ),
    ("orders_rows_direct", "json"): (
        "{\n"
        '  "orders": [\n'
        "    {\n"
        '      "order_id": "ORD-0001",\n'
        '      "symbol": "005930",\n'
        '      "side": "buy",\n'
        '      "quantity": 10.0,\n'
        '      "filled_quantity": 10.0,\n'
        '      "price": 70100.0,\n'
        '      "status": "filled",\n'
        '      "timestamp": "20260102"\n'
        "    },\n"
        "    {\n"
        '      "order_id": "ORD-0002",\n'
        '      "symbol": "000660",\n'
        '      "side": "sell",\n'
        '      "quantity": 5.0,\n'
        '      "filled_quantity": 0.0,\n'
        '      "price": 120000.0,\n'
        '      "status": "pending",\n'
        '      "timestamp": "20260102"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("orders_range_ipc", "text"): (
        "  ※ status 는 체결수량 기준 2값(filled/pending)이라 취소 주문도 pending 으로 "
        "보입니다. price 는 체결가/주문가 혼합, timestamp 는 영업일(일자)까지입니다.\n"
        "    order_id |       symbol |         side |     quantity | filled_quantity |"
        "        price |       status |    timestamp\n"
        "-----------------------------------------------------------------------------"
        "-------------------------------------------\n"
        "    ORD-0001 |       005930 |          buy |         10.0 |         10.0 |   "
        "   70100.0 |       filled |     20260102\n"
    ),
    ("orders_range_ipc", "json"): (
        "{\n"
        '  "orders": [\n'
        "    {\n"
        '      "order_id": "ORD-0001",\n'
        '      "symbol": "005930",\n'
        '      "side": "buy",\n'
        '      "quantity": 10.0,\n'
        '      "filled_quantity": 10.0,\n'
        '      "price": 70100.0,\n'
        '      "status": "filled",\n'
        '      "timestamp": "20260102"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("orders_range_direct", "text"): (
        "  ※ status 는 체결수량 기준 2값(filled/pending)이라 취소 주문도 pending 으로 "
        "보입니다. price 는 체결가/주문가 혼합, timestamp 는 영업일(일자)까지입니다.\n"
        "    order_id |       symbol |         side |     quantity | filled_quantity |"
        "        price |       status |    timestamp\n"
        "-----------------------------------------------------------------------------"
        "-------------------------------------------\n"
        "    ORD-0001 |       005930 |          buy |         10.0 |         10.0 |   "
        "   70100.0 |       filled |     20260102\n"
    ),
    ("orders_range_direct", "json"): (
        "{\n"
        '  "orders": [\n'
        "    {\n"
        '      "order_id": "ORD-0001",\n'
        '      "symbol": "005930",\n'
        '      "side": "buy",\n'
        '      "quantity": 10.0,\n'
        '      "filled_quantity": 10.0,\n'
        '      "price": 70100.0,\n'
        '      "status": "filled",\n'
        '      "timestamp": "20260102"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("reconcile_match_ipc", "text"): (
        "  총 종목 수     : 2\n  대사 결과      : 일치\n"
    ),
    ("reconcile_match_ipc", "json"): (
        "{\n"
        '  "total_symbols": 2,\n'
        '  "discrepancies": [],\n'
        '  "match": true,\n'
        '  "fix_applied": false,\n'
        '  "corrections": 0\n'
        "}\n"
    ),
    ("reconcile_match_direct", "text"): (
        "  총 종목 수     : 2\n  대사 결과      : 일치\n"
    ),
    ("reconcile_match_direct", "json"): (
        "{\n"
        '  "total_symbols": 2,\n'
        '  "discrepancies": [],\n'
        '  "match": true,\n'
        '  "fix_applied": false,\n'
        '  "corrections": 0\n'
        "}\n"
    ),
    ("reconcile_mismatch_ipc", "text"): (
        "  총 종목 수     : 2\n"
        "  대사 결과      : 불일치\n"
        "  불일치 종목:\n"
        "      symbol |   broker_qty | internal_qty |         diff\n"
        "---------------------------------------------------------\n"
        "      005930 |         10.0 |          8.0 |          2.0\n"
    ),
    ("reconcile_mismatch_ipc", "json"): (
        "{\n"
        '  "total_symbols": 2,\n'
        '  "discrepancies": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "broker_qty": 10.0,\n'
        '      "internal_qty": 8.0,\n'
        '      "diff": 2.0\n'
        "    }\n"
        "  ],\n"
        '  "match": false,\n'
        '  "fix_applied": false,\n'
        '  "corrections": 0\n'
        "}\n"
    ),
    ("reconcile_mismatch_direct", "text"): (
        "  총 종목 수     : 2\n"
        "  대사 결과      : 불일치\n"
        "  불일치 종목:\n"
        "      symbol |   broker_qty | internal_qty |         diff\n"
        "---------------------------------------------------------\n"
        "      005930 |         10.0 |          8.0 |          2.0\n"
    ),
    ("reconcile_mismatch_direct", "json"): (
        "{\n"
        '  "total_symbols": 2,\n'
        '  "discrepancies": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "broker_qty": 10.0,\n'
        '      "internal_qty": 8.0,\n'
        '      "diff": 2.0\n'
        "    }\n"
        "  ],\n"
        '  "match": false,\n'
        '  "fix_applied": false,\n'
        '  "corrections": 0\n'
        "}\n"
    ),
    ("reconcile_fix", "text"): (
        "  총 종목 수     : 2\n"
        "  대사 결과      : 불일치\n"
        "  불일치 종목:\n"
        "      symbol |   broker_qty | internal_qty |         diff\n"
        "---------------------------------------------------------\n"
        "      005930 |         10.0 |          8.0 |          2.0\n"
        "  자동 보정      : 1건 수행\n"
    ),
    ("reconcile_fix", "json"): (
        "{\n"
        '  "total_symbols": 2,\n'
        '  "discrepancies": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "broker_qty": 10.0,\n'
        '      "internal_qty": 8.0,\n'
        '      "diff": 2.0\n'
        "    }\n"
        "  ],\n"
        '  "match": false,\n'
        '  "fix_applied": true,\n'
        '  "corrections": 1\n'
        "}\n"
    ),
}


class TestBrokerOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_BROKER_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }
        assert len(_BROKER_OUTPUT_BYTES) == 2 * len(_CASES)

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _BROKER_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == 1

    @pytest.mark.parametrize("mode", ["text", "json"])
    def test_status_error_text_appears_once_on_stdout(self, mode: str) -> None:
        """직접 연결 폴백의 예외 문자열은 지금 stdout에 한 번 그대로 나가고
        stderr에는 나가지 않는다."""
        result, _ = _invoke_case("status_error_direct", mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout.count("FAKE-ERROR-TOKEN-0000") == 1
        assert "FAKE-ERROR-TOKEN-0000" not in result.stderr
