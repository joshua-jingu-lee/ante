"""trade 2개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. 두 명령은 IPC를
부르지 않는다(사례마다 IPC 호출 0회를 단언한다).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.member.models import Member

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_TRADES = [
    SimpleNamespace(
        trade_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        bot_id="bot-1",
        strategy_id="momentum_v1.0.0",
        symbol="005930",
        side="buy",
        quantity=10.0,
        price=71000.0,
        status="filled",
        timestamp=datetime(2026, 1, 2, 9, 0, tzinfo=UTC),
    ),
    SimpleNamespace(
        trade_id=uuid.UUID("00000000-0000-4000-8000-000000000002"),
        bot_id="bot-2",
        strategy_id="mean_rev_v2.1.0",
        symbol="000660",
        side="sell",
        quantity=3.0,
        price=128500.5,
        status="partial",
        timestamp=None,
    ),
]

_TRADE_ROW: dict[str, Any] = {
    "trade_id": "00000000-0000-4000-8000-000000000001",
    "bot_id": "bot-1",
    "strategy_id": "momentum_v1.0.0",
    "symbol": "005930",
    "side": "buy",
    "quantity": 10.0,
    "price": 71000.0,
    "status": "filled",
    "order_type": "limit",
    "reason": "골든 크로스",
    "commission": 106.5,
    "timestamp": "2026-01-02T09:00:00+00:00",
    "order_id": None,
}

_FILTERS = [
    "--bot",
    "bot-1",
    "--strategy",
    "momentum_v1.0.0",
    "--from",
    "2026-01-01",
    "--to",
    "2026-01-31",
    "--limit",
    "5",
]

_CASES: dict[str, list[str]] = {
    "list_empty": ["trade", "list"],
    "list_rows": ["trade", "list"],
    "list_filtered": ["trade", "list", *_FILTERS],
    "info": ["trade", "info", "00000000-0000-4000-8000-000000000001"],
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
) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    trades = [] if branch == "list_empty" else list(_TRADES)
    service = SimpleNamespace(get_trades=AsyncMock(return_value=trades))
    db = AsyncMock()
    db.fetch_one = AsyncMock(return_value=dict(_TRADE_ROW))

    @asynccontextmanager
    async def _create_service(ctx: Any = None) -> AsyncIterator[tuple[Any, Any]]:
        yield service, db

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield db

    ipc_send = AsyncMock(side_effect=AssertionError("IPC를 부르면 안 된다"))
    args = list(_CASES[branch])
    full_args = ["--format", "json", *args] if mode == "json" else args
    with ExitStack() as stack:
        for target, value in (
            ("ante.cli.commands.trade._create_trade_service", _create_service),
            ("ante.cli.commands.trade.open_cli_db", _open_cli_db),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send


_TRADE_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("list_empty", "text"): ("{'message': '거래 내역 없음', 'trades': []}\n"),
    ("list_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "message": "거래 내역 없음",\n'
        '    "trades": []\n'
        "  }\n"
        "}\n"
    ),
    ("list_rows", "text"): (
        "    trade_id |       bot_id |  strategy_id |       symbol |         side |    "
        " quantity |        price |       status\n"
        "------------------------------------------------------------------------------"
        "---------------------------------------\n"
        "00000000-0000-4000-8000-000000000001 |        bot-1 | momentum_v1.0.0 |       "
        "005930 |          buy |         10.0 |      71000.0 |       filled\n"
        "00000000-0000-4000-8000-000000000002 |        bot-2 | mean_rev_v2.1.0 |       "
        "000660 |         sell |          3.0 |     128500.5 |      partial\n"
    ),
    ("list_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "trades": [\n'
        "      {\n"
        '        "trade_id": "00000000-0000-4000-8000-000000000001",\n'
        '        "bot_id": "bot-1",\n'
        '        "strategy_id": "momentum_v1.0.0",\n'
        '        "symbol": "005930",\n'
        '        "side": "buy",\n'
        '        "quantity": 10.0,\n'
        '        "price": 71000.0,\n'
        '        "status": "filled",\n'
        '        "timestamp": "2026-01-02 09:00:00+00:00"\n'
        "      },\n"
        "      {\n"
        '        "trade_id": "00000000-0000-4000-8000-000000000002",\n'
        '        "bot_id": "bot-2",\n'
        '        "strategy_id": "mean_rev_v2.1.0",\n'
        '        "symbol": "000660",\n'
        '        "side": "sell",\n'
        '        "quantity": 3.0,\n'
        '        "price": 128500.5,\n'
        '        "status": "partial",\n'
        '        "timestamp": ""\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("list_filtered", "text"): (
        "    trade_id |       bot_id |  strategy_id |       symbol |         side |    "
        " quantity |        price |       status\n"
        "------------------------------------------------------------------------------"
        "---------------------------------------\n"
        "00000000-0000-4000-8000-000000000001 |        bot-1 | momentum_v1.0.0 |       "
        "005930 |          buy |         10.0 |      71000.0 |       filled\n"
        "00000000-0000-4000-8000-000000000002 |        bot-2 | mean_rev_v2.1.0 |       "
        "000660 |         sell |          3.0 |     128500.5 |      partial\n"
    ),
    ("list_filtered", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "trades": [\n'
        "      {\n"
        '        "trade_id": "00000000-0000-4000-8000-000000000001",\n'
        '        "bot_id": "bot-1",\n'
        '        "strategy_id": "momentum_v1.0.0",\n'
        '        "symbol": "005930",\n'
        '        "side": "buy",\n'
        '        "quantity": 10.0,\n'
        '        "price": 71000.0,\n'
        '        "status": "filled",\n'
        '        "timestamp": "2026-01-02 09:00:00+00:00"\n'
        "      },\n"
        "      {\n"
        '        "trade_id": "00000000-0000-4000-8000-000000000002",\n'
        '        "bot_id": "bot-2",\n'
        '        "strategy_id": "mean_rev_v2.1.0",\n'
        '        "symbol": "000660",\n'
        '        "side": "sell",\n'
        '        "quantity": 3.0,\n'
        '        "price": 128500.5,\n'
        '        "status": "partial",\n'
        '        "timestamp": ""\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("info", "text"): (
        "  trade_id       : 00000000-0000-4000-8000-000000000001\n"
        "  bot_id         : bot-1\n"
        "  strategy_id    : momentum_v1.0.0\n"
        "  symbol         : 005930\n"
        "  side           : buy\n"
        "  quantity       : 10.0\n"
        "  price          : 71000.0\n"
        "  status         : filled\n"
        "  order_type     : limit\n"
        "  reason         : 골든 크로스\n"
        "  commission     : 106.5\n"
        "  timestamp      : 2026-01-02T09:00:00+00:00\n"
        "  order_id       : None\n"
    ),
    ("info", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "trade_id": "00000000-0000-4000-8000-000000000001",\n'
        '    "bot_id": "bot-1",\n'
        '    "strategy_id": "momentum_v1.0.0",\n'
        '    "symbol": "005930",\n'
        '    "side": "buy",\n'
        '    "quantity": 10.0,\n'
        '    "price": 71000.0,\n'
        '    "status": "filled",\n'
        '    "order_type": "limit",\n'
        '    "reason": "골든 크로스",\n'
        '    "commission": 106.5,\n'
        '    "timestamp": "2026-01-02T09:00:00+00:00",\n'
        '    "order_id": null\n'
        "  }\n"
        "}\n"
    ),
}


class TestTradeOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_TRADE_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }
        assert len(_TRADE_OUTPUT_BYTES) == 2 * len(_CASES)

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _TRADE_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == 0

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_success_output_goes_to_stdout_only(self, branch: str, mode: str) -> None:
        result, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout == _TRADE_OUTPUT_BYTES[(branch, mode)]
        assert result.stderr == ""
