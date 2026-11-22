"""bot 11개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. IPC가 응답하는
분기와 서버가 없어 직접 DB를 읽는 분기(``IPCServerNotRunningError`` 폴백,
``remove``는 ``is_active_runtime``)를 각각 고정한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.contracts.ipc_client_errors import IPCServerNotRunningError
from ante.member.models import Member
from tests.unit.cli.conftest import mock_bot_services_factory

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_BOT_ROWS: list[dict[str, Any]] = [
    {
        "bot_id": "bot-1",
        "name": "테스트 봇",
        "strategy_id": "strat-1",
        "account_id": "acc-1",
        "status": "stopped",
        "created_at": "2026-01-01T00:00:00",
    },
    {
        "bot_id": "bot-2",
        "name": "momentum",
        "strategy_id": "strat-2",
        "account_id": "acc-2",
        "status": "running",
        "created_at": "2026-01-02T00:00:00",
    },
]

_BOT_DETAIL: dict[str, Any] = {
    "bot_id": "bot-1",
    "name": "테스트 봇",
    "strategy_id": "strat-1",
    "account_id": "acc-1",
    "status": "stopped",
    "interval_seconds": 60,
    "created_at": "2026-01-01T00:00:00",
}

_POSITIONS: list[dict[str, Any]] = [
    {
        "symbol": "005930",
        "quantity": 10.0,
        "avg_entry_price": 70000.0,
        "realized_pnl": 1500.0,
    },
    {
        "symbol": "000660",
        "quantity": 3.0,
        "avg_entry_price": 120000.0,
        "realized_pnl": 0,
    },
]

_STATUS_FULL: dict[str, Any] = {
    "bot_id": "bot-1",
    "name": "테스트 봇",
    "status": "error",
    "account_id": "acc-1",
    "strategy_id": "strat-1",
    "strategy_name": "모멘텀",
    "interval_seconds": 60,
    "started_at": "2026-01-03T09:00:00",
    "stopped_at": "2026-01-03T10:00:00",
    "error_message": "step timeout",
    "budget": {"allocated": 1000000.0, "available": 250000.0},
    "positions": [
        {"symbol": "005930", "quantity": 10.0, "avg_entry_price": 70000.0},
    ],
}

_STATUS_MIN: dict[str, Any] = {
    "bot_id": "bot-2",
    "name": "momentum",
    "status": "stopped",
    "account_id": "acc-2",
    "strategy_id": "strat-2",
    "interval_seconds": None,
    "budget": {},
    "positions": [],
}

_LOG_ROWS: list[dict[str, Any]] = [
    {
        "event_id": "evt-1",
        "timestamp": "2026-01-03T09:00:00",
        "payload": {"bot_id": "bot-1", "result": "ok", "message": "step 완료"},
    },
    {
        "event_id": "evt-2",
        "timestamp": "2026-01-03T09:01:00",
        "payload": {"bot_id": "bot-1", "result": "error", "message": "주문 거부"},
    },
]

_NOT_RUNNING = IPCServerNotRunningError("not running")
_NO_IPC = frozenset({"remove_cold_path", "logs_empty", "logs_rows"})


def _pair(name: str, args: list[str]) -> dict[str, list[str]]:
    return {f"{name}_ipc": args, f"{name}_direct": args}


_CREATE_ARGS = ["bot", "create", "--name", "새 봇", "--strategy", "strat-1"]

_CASES: dict[str, list[str]] = {
    **_pair("list_empty", ["bot", "list"]),
    **_pair("list_rows", ["bot", "list"]),
    **_pair("list_account", ["bot", "list", "--account", "acc-1"]),
    **_pair("info", ["bot", "info", "bot-1"]),
    "info_minimal_direct": ["bot", "info", "bot-3"],
    "create_account": [*_CREATE_ARGS, "--account", "acc-1", "--id", "bot-9"],
    "create_auto_account": list(_CREATE_ARGS),
    "remove_ipc": ["bot", "remove", "bot-1", "--yes"],
    "remove_cold_path": ["bot", "remove", "bot-1", "--yes"],
    **_pair("signal_key", ["bot", "signal-key", "bot-1"]),
    "signal_key_rotate": ["bot", "signal-key", "bot-1", "--rotate"],
    **_pair("positions_empty", ["bot", "positions", "bot-1"]),
    **_pair("positions_rows", ["bot", "positions", "bot-1"]),
    "update": ["bot", "update", "bot-1", "--name", "새 이름", "--budget", "500000"],
    "logs_empty": ["bot", "logs", "bot-1"],
    "logs_rows": ["bot", "logs", "bot-1", "--limit", "2", "--from", "2026-01-03"],
    "start": ["bot", "start", "bot-1"],
    "stop": ["bot", "stop", "bot-1"],
    "status_full": ["bot", "status", "bot-1"],
    "status_min": ["bot", "status", "bot-2"],
}


def _ipc_result(branch: str) -> Any:
    if branch.endswith("_direct") or branch == "remove_cold_path":
        return _NOT_RUNNING
    results: dict[str, Any] = {
        "list_empty_ipc": {"bots": []},
        "list_rows_ipc": {"bots": _BOT_ROWS},
        "list_account_ipc": {"bots": _BOT_ROWS[:1]},
        "info_ipc": {"bot": _BOT_DETAIL},
        "create_account": {
            "bot_id": "bot-9",
            "name": "새 봇",
            "strategy_id": "strat-1",
            "account_id": "acc-1",
            "status": "created",
        },
        "create_auto_account": {
            "bot_id": "bot-3",
            "name": "새 봇",
            "strategy_id": "strat-1",
            "account_id": "acc-solo",
            "status": "created",
        },
        "remove_ipc": {"removed": True, "bot_id": "bot-1"},
        "signal_key_ipc": {"bot_id": "bot-1", "signal_key": "sk-ipc-abc"},
        "signal_key_rotate": {
            "bot_id": "bot-1",
            "signal_key": "sk-new-xyz",
            "rotated": True,
        },
        "positions_empty_ipc": {"positions": []},
        "positions_rows_ipc": {"positions": _POSITIONS},
        "update": {
            "bot_id": "bot-1",
            "updates": {"name": "새 이름", "budget": 500000.0},
            "bot": {"bot_id": "bot-1", "name": "새 이름", "status": "stopped"},
        },
        "start": {"bot": {"bot_id": "bot-1", "status": "running", "name": "테스트 봇"}},
        "stop": {"bot": {"bot_id": "bot-1", "status": "stopped", "name": "테스트 봇"}},
        "status_full": {"bot": _STATUS_FULL},
        "status_min": {"bot": _STATUS_MIN},
    }
    return results.get(branch)


def _db_for(branch: str) -> AsyncMock:
    db = AsyncMock()
    rows: list[dict[str, Any]] = []
    one: dict[str, Any] | None = None
    if branch == "list_rows_direct":
        rows = _BOT_ROWS
    elif branch == "list_account_direct":
        rows = _BOT_ROWS[:1]
    elif branch == "info_direct":
        one = _BOT_DETAIL
    elif branch == "info_minimal_direct":
        one = {
            "bot_id": "bot-3",
            "name": "legacy",
            "strategy_id": "strat-3",
            "status": "stopped",
        }
    elif branch == "signal_key_direct":
        one = {"strategy_id": "strat-1"}
    elif branch.startswith("positions_"):
        one = {"account_id": "acc-1"}
    elif branch.startswith("logs_"):
        one = {"1": 1}
    db.fetch_all = AsyncMock(return_value=rows)
    db.fetch_one = AsyncMock(return_value=one)
    return db


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


def _invoke_case(branch: str, mode: str) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    db = _db_for(branch)
    account_service = AsyncMock()
    account_service.list = AsyncMock(
        return_value=[SimpleNamespace(account_id="acc-solo")]
    )
    ipc_value = _ipc_result(branch)
    if isinstance(ipc_value, Exception):
        ipc_send = AsyncMock(side_effect=ipc_value)
    else:
        ipc_send = AsyncMock(return_value=ipc_value)

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield db

    skm = AsyncMock()
    skm.get_key = AsyncMock(return_value="sk-direct-def")
    positions = (
        [SimpleNamespace(**p) for p in _POSITIONS]
        if branch == "positions_rows_direct"
        else []
    )
    trade_service = AsyncMock()
    trade_service.get_positions = AsyncMock(return_value=positions)
    store = AsyncMock()
    store.query = AsyncMock(return_value=_LOG_ROWS if branch == "logs_rows" else [])
    store.count = AsyncMock(return_value=7 if branch == "logs_rows" else 0)
    cold_path = AsyncMock(return_value={"removed": True, "cold_path": True})

    full_args = ["--format", "json", *_CASES[branch]] if mode == "json" else None
    with ExitStack() as stack:
        for target, value in (
            (
                "ante.cli.commands.bot._create_services",
                mock_bot_services_factory(
                    db, MagicMock(), AsyncMock(), account_service
                ),
            ),
            ("ante.cli.commands.bot.open_cli_db", _open_cli_db),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
            (
                "ante.cli.commands.bot.is_active_runtime",
                MagicMock(return_value=branch != "remove_cold_path"),
            ),
            ("ante.cli.commands.bot._run_bot_remove_cold_path", cold_path),
            ("ante.bot.signal_key.SignalKeyManager", MagicMock(return_value=skm)),
            (
                "ante.trade.position.PositionHistory",
                MagicMock(return_value=AsyncMock()),
            ),
            ("ante.trade.recorder.TradeRecorder", MagicMock(return_value=AsyncMock())),
            ("ante.trade.performance.PerformanceTracker", MagicMock()),
            ("ante.trade.service.TradeService", MagicMock(return_value=trade_service)),
            ("ante.eventbus.history.EventHistoryStore", MagicMock(return_value=store)),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner().invoke(
            cli,
            full_args if full_args is not None else list(_CASES[branch]),
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )
    return result, ipc_send


_BOT_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("list_empty_ipc", "text"): ("{'message': '등록된 봇이 없습니다.', 'bots': []}\n"),
    ("list_empty_ipc", "json"): (
        '{\n  "message": "등록된 봇이 없습니다.",\n  "bots": []\n}\n'
    ),
    ("list_empty_direct", "text"): (
        "{'message': '등록된 봇이 없습니다.', 'bots': []}\n"
    ),
    ("list_empty_direct", "json"): (
        '{\n  "message": "등록된 봇이 없습니다.",\n  "bots": []\n}\n'
    ),
    ("list_rows_ipc", "text"): (
        "      bot_id |         name |  strategy_id |   account_id |       "
        "status |   created_at\n"
        "------------------------------------------------------------------"
        "---------------------\n"
        "       bot-1 |        테스트 봇 |      strat-1 |        acc-1 |   "
        "   stopped | 2026-01-01T00:00:00\n"
        "       bot-2 |     momentum |      strat-2 |        acc-2 |      r"
        "unning | 2026-01-02T00:00:00\n"
    ),
    ("list_rows_ipc", "json"): (
        "{\n"
        '  "bots": [\n'
        "    {\n"
        '      "bot_id": "bot-1",\n'
        '      "name": "테스트 봇",\n'
        '      "strategy_id": "strat-1",\n'
        '      "account_id": "acc-1",\n'
        '      "status": "stopped",\n'
        '      "created_at": "2026-01-01T00:00:00"\n'
        "    },\n"
        "    {\n"
        '      "bot_id": "bot-2",\n'
        '      "name": "momentum",\n'
        '      "strategy_id": "strat-2",\n'
        '      "account_id": "acc-2",\n'
        '      "status": "running",\n'
        '      "created_at": "2026-01-02T00:00:00"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("list_rows_direct", "text"): (
        "      bot_id |         name |  strategy_id |   account_id |       "
        "status |   created_at\n"
        "------------------------------------------------------------------"
        "---------------------\n"
        "       bot-1 |        테스트 봇 |      strat-1 |        acc-1 |   "
        "   stopped | 2026-01-01T00:00:00\n"
        "       bot-2 |     momentum |      strat-2 |        acc-2 |      r"
        "unning | 2026-01-02T00:00:00\n"
    ),
    ("list_rows_direct", "json"): (
        "{\n"
        '  "bots": [\n'
        "    {\n"
        '      "bot_id": "bot-1",\n'
        '      "name": "테스트 봇",\n'
        '      "strategy_id": "strat-1",\n'
        '      "account_id": "acc-1",\n'
        '      "status": "stopped",\n'
        '      "created_at": "2026-01-01T00:00:00"\n'
        "    },\n"
        "    {\n"
        '      "bot_id": "bot-2",\n'
        '      "name": "momentum",\n'
        '      "strategy_id": "strat-2",\n'
        '      "account_id": "acc-2",\n'
        '      "status": "running",\n'
        '      "created_at": "2026-01-02T00:00:00"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("list_account_ipc", "text"): (
        "      bot_id |         name |  strategy_id |   account_id |       "
        "status |   created_at\n"
        "------------------------------------------------------------------"
        "---------------------\n"
        "       bot-1 |        테스트 봇 |      strat-1 |        acc-1 |   "
        "   stopped | 2026-01-01T00:00:00\n"
    ),
    ("list_account_ipc", "json"): (
        "{\n"
        '  "bots": [\n'
        "    {\n"
        '      "bot_id": "bot-1",\n'
        '      "name": "테스트 봇",\n'
        '      "strategy_id": "strat-1",\n'
        '      "account_id": "acc-1",\n'
        '      "status": "stopped",\n'
        '      "created_at": "2026-01-01T00:00:00"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("list_account_direct", "text"): (
        "      bot_id |         name |  strategy_id |   account_id |       "
        "status |   created_at\n"
        "------------------------------------------------------------------"
        "---------------------\n"
        "       bot-1 |        테스트 봇 |      strat-1 |        acc-1 |   "
        "   stopped | 2026-01-01T00:00:00\n"
    ),
    ("list_account_direct", "json"): (
        "{\n"
        '  "bots": [\n'
        "    {\n"
        '      "bot_id": "bot-1",\n'
        '      "name": "테스트 봇",\n'
        '      "strategy_id": "strat-1",\n'
        '      "account_id": "acc-1",\n'
        '      "status": "stopped",\n'
        '      "created_at": "2026-01-01T00:00:00"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("info_ipc", "text"): (
        "  Bot ID    : bot-1\n"
        "  이름      : 테스트 봇\n"
        "  전략      : strat-1\n"
        "  계좌      : acc-1\n"
        "  상태      : stopped\n"
        "  생성일    : 2026-01-01T00:00:00\n"
    ),
    ("info_ipc", "json"): (
        "{\n"
        '  "bot_id": "bot-1",\n'
        '  "name": "테스트 봇",\n'
        '  "strategy_id": "strat-1",\n'
        '  "account_id": "acc-1",\n'
        '  "status": "stopped",\n'
        '  "interval_seconds": 60,\n'
        '  "created_at": "2026-01-01T00:00:00"\n'
        "}\n"
    ),
    ("info_direct", "text"): (
        "  Bot ID    : bot-1\n"
        "  이름      : 테스트 봇\n"
        "  전략      : strat-1\n"
        "  계좌      : acc-1\n"
        "  상태      : stopped\n"
        "  생성일    : 2026-01-01T00:00:00\n"
    ),
    ("info_direct", "json"): (
        "{\n"
        '  "bot_id": "bot-1",\n'
        '  "name": "테스트 봇",\n'
        '  "strategy_id": "strat-1",\n'
        '  "account_id": "acc-1",\n'
        '  "status": "stopped",\n'
        '  "interval_seconds": 60,\n'
        '  "created_at": "2026-01-01T00:00:00"\n'
        "}\n"
    ),
    ("info_minimal_direct", "text"): (
        "  Bot ID    : bot-3\n"
        "  이름      : legacy\n"
        "  전략      : strat-3\n"
        "  계좌      : test\n"
        "  상태      : stopped\n"
        "  생성일    : None\n"
    ),
    ("info_minimal_direct", "json"): (
        "{\n"
        '  "bot_id": "bot-3",\n'
        '  "name": "legacy",\n'
        '  "strategy_id": "strat-3",\n'
        '  "status": "stopped"\n'
        "}\n"
    ),
    ("create_account", "text"): ("봇 생성 완료: bot-9\n"),
    ("create_account", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "봇 생성 완료: bot-9",\n'
        '  "data": {\n'
        '    "bot_id": "bot-9",\n'
        '    "name": "새 봇",\n'
        '    "strategy_id": "strat-1",\n'
        '    "account_id": "acc-1",\n'
        '    "status": "created"\n'
        "  }\n"
        "}\n"
    ),
    ("create_auto_account", "text"): ("봇 생성 완료: bot-3\n"),
    ("create_auto_account", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "봇 생성 완료: bot-3",\n'
        '  "data": {\n'
        '    "bot_id": "bot-3",\n'
        '    "name": "새 봇",\n'
        '    "strategy_id": "strat-1",\n'
        '    "account_id": "acc-solo",\n'
        '    "status": "created"\n'
        "  }\n"
        "}\n"
    ),
    ("remove_ipc", "text"): ("봇 삭제 완료: bot-1\n"),
    ("remove_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "봇 삭제 완료: bot-1",\n'
        '  "data": {\n'
        '    "removed": true,\n'
        '    "bot_id": "bot-1"\n'
        "  }\n"
        "}\n"
    ),
    ("remove_cold_path", "text"): ("봇 삭제 완료(cold-path): bot-1\n"),
    ("remove_cold_path", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "봇 삭제 완료(cold-path): bot-1",\n'
        '  "data": {\n'
        '    "removed": true,\n'
        '    "cold_path": true\n'
        "  }\n"
        "}\n"
    ),
    ("signal_key_ipc", "text"): ("  Bot ID     : bot-1\n  Signal Key : sk-ipc-abc\n"),
    ("signal_key_ipc", "json"): (
        '{\n  "bot_id": "bot-1",\n  "signal_key": "sk-ipc-abc"\n}\n'
    ),
    ("signal_key_direct", "text"): (
        "  Bot ID     : bot-1\n  Signal Key : sk-direct-def\n"
    ),
    ("signal_key_direct", "json"): (
        '{\n  "bot_id": "bot-1",\n  "signal_key": "sk-direct-def"\n}\n'
    ),
    ("signal_key_rotate", "text"): ("시그널 키 재발급 완료: bot-1\n"),
    ("signal_key_rotate", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "시그널 키 재발급 완료: bot-1",\n'
        '  "data": {\n'
        '    "bot_id": "bot-1",\n'
        '    "signal_key": "sk-new-xyz",\n'
        '    "rotated": true\n'
        "  }\n"
        "}\n"
    ),
    ("positions_empty_ipc", "text"): (
        "{'message': '보유 포지션 없음', 'positions': []}\n"
    ),
    ("positions_empty_ipc", "json"): (
        '{\n  "message": "보유 포지션 없음",\n  "positions": []\n}\n'
    ),
    ("positions_empty_direct", "text"): (
        "{'message': '보유 포지션 없음', 'positions': []}\n"
    ),
    ("positions_empty_direct", "json"): (
        '{\n  "message": "보유 포지션 없음",\n  "positions": []\n}\n'
    ),
    ("positions_rows_ipc", "text"): (
        "      symbol |     quantity | avg_entry_price | realized_pnl\n"
        "------------------------------------------------------------\n"
        "      005930 |         10.0 |      70000.0 |       1500.0\n"
        "      000660 |          3.0 |     120000.0 |            0\n"
    ),
    ("positions_rows_ipc", "json"): (
        "{\n"
        '  "positions": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "quantity": 10.0,\n'
        '      "avg_entry_price": 70000.0,\n'
        '      "realized_pnl": 1500.0\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000660",\n'
        '      "quantity": 3.0,\n'
        '      "avg_entry_price": 120000.0,\n'
        '      "realized_pnl": 0\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("positions_rows_direct", "text"): (
        "      symbol |     quantity | avg_entry_price | realized_pnl\n"
        "------------------------------------------------------------\n"
        "      005930 |         10.0 |      70000.0 |       1500.0\n"
        "      000660 |          3.0 |     120000.0 |            0\n"
    ),
    ("positions_rows_direct", "json"): (
        "{\n"
        '  "positions": [\n'
        "    {\n"
        '      "symbol": "005930",\n'
        '      "quantity": 10.0,\n'
        '      "avg_entry_price": 70000.0,\n'
        '      "realized_pnl": 1500.0\n'
        "    },\n"
        "    {\n"
        '      "symbol": "000660",\n'
        '      "quantity": 3.0,\n'
        '      "avg_entry_price": 120000.0,\n'
        '      "realized_pnl": 0\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("update", "text"): ("봇 설정 수정 완료: bot-1\n"),
    ("update", "json"): (
        "{\n"
        '  "bot_id": "bot-1",\n'
        '  "updates": {\n'
        '    "name": "새 이름",\n'
        '    "budget": 500000.0\n'
        "  },\n"
        '  "bot": {\n'
        '    "bot_id": "bot-1",\n'
        '    "name": "새 이름",\n'
        '    "status": "stopped"\n'
        "  }\n"
        "}\n"
    ),
    ("logs_empty", "text"): ("(logs 없음)\n"),
    ("logs_empty", "json"): (
        '{\n  "bot_id": "bot-1",\n  "logs": [],\n  "total": 0\n}\n'
    ),
    ("logs_rows", "text"): (
        "   timestamp |       result |      message\n"
        "------------------------------------------\n"
        "2026-01-03T09:00:00 |           ok |      step 완료\n"
        "2026-01-03T09:01:00 |        error |        주문 거부\n"
    ),
    ("logs_rows", "json"): (
        "{\n"
        '  "bot_id": "bot-1",\n'
        '  "logs": [\n'
        "    {\n"
        '      "event_id": "evt-1",\n'
        '      "timestamp": "2026-01-03T09:00:00",\n'
        '      "result": "ok",\n'
        '      "message": "step 완료"\n'
        "    },\n"
        "    {\n"
        '      "event_id": "evt-2",\n'
        '      "timestamp": "2026-01-03T09:01:00",\n'
        '      "result": "error",\n'
        '      "message": "주문 거부"\n'
        "    }\n"
        "  ],\n"
        '  "total": 7\n'
        "}\n"
    ),
    ("start", "text"): ("봇 시작 완료: bot-1\n"),
    ("start", "json"): (
        "{\n"
        '  "bot": {\n'
        '    "bot_id": "bot-1",\n'
        '    "status": "running",\n'
        '    "name": "테스트 봇"\n'
        "  }\n"
        "}\n"
    ),
    ("stop", "text"): ("봇 중지 완료: bot-1\n"),
    ("stop", "json"): (
        "{\n"
        '  "bot": {\n'
        '    "bot_id": "bot-1",\n'
        '    "status": "stopped",\n'
        '    "name": "테스트 봇"\n'
        "  }\n"
        "}\n"
    ),
    ("status_full", "text"): (
        "  Bot ID       : bot-1\n"
        "  Name         : 테스트 봇\n"
        "  Status       : error\n"
        "  Account ID   : acc-1\n"
        "  Strategy ID  : strat-1\n"
        "  Strategy Name: 모멘텀\n"
        "  Interval     : 60s\n"
        "  Started At   : 2026-01-03T09:00:00\n"
        "  Stopped At   : 2026-01-03T10:00:00\n"
        "  Error        : step timeout\n"
        "  Budget:\n"
        "    allocated: 1000000.0\n"
        "    available: 250000.0\n"
        "  Positions (1):\n"
        "    005930: qty=10.0, avg=70000.0\n"
    ),
    ("status_full", "json"): (
        "{\n"
        '  "bot": {\n'
        '    "bot_id": "bot-1",\n'
        '    "name": "테스트 봇",\n'
        '    "status": "error",\n'
        '    "account_id": "acc-1",\n'
        '    "strategy_id": "strat-1",\n'
        '    "strategy_name": "모멘텀",\n'
        '    "interval_seconds": 60,\n'
        '    "started_at": "2026-01-03T09:00:00",\n'
        '    "stopped_at": "2026-01-03T10:00:00",\n'
        '    "error_message": "step timeout",\n'
        '    "budget": {\n'
        '      "allocated": 1000000.0,\n'
        '      "available": 250000.0\n'
        "    },\n"
        '    "positions": [\n'
        "      {\n"
        '        "symbol": "005930",\n'
        '        "quantity": 10.0,\n'
        '        "avg_entry_price": 70000.0\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("status_min", "text"): (
        "  Bot ID       : bot-2\n"
        "  Name         : momentum\n"
        "  Status       : stopped\n"
        "  Account ID   : acc-2\n"
        "  Strategy ID  : strat-2\n"
    ),
    ("status_min", "json"): (
        "{\n"
        '  "bot": {\n'
        '    "bot_id": "bot-2",\n'
        '    "name": "momentum",\n'
        '    "status": "stopped",\n'
        '    "account_id": "acc-2",\n'
        '    "strategy_id": "strat-2",\n'
        '    "interval_seconds": null,\n'
        '    "budget": {},\n'
        '    "positions": []\n'
        "  }\n"
        "}\n"
    ),
}


class TestBotOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_BOT_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }
        assert len(_BOT_OUTPUT_BYTES) == 2 * len(_CASES)

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _BOT_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == (0 if branch in _NO_IPC else 1)
