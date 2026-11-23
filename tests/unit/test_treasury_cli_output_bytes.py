"""treasury 9개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. ``set-balance``는
서버가 가동 중일 때의 IPC 분기와 정지했을 때의 직접 실행 분기를 각각
고정한다. 시각이 출력에 들어가는 분기는 ``manual_clock``으로 시계를 고정한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.member.models import Member
from ante.treasury.models import BotBudget

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)


_NOW = datetime(2026, 1, 5, 9, 30, tzinfo=UTC)

pytestmark = pytest.mark.parametrize("manual_clock", [_NOW], indirect=True)


@pytest.fixture(autouse=True)
def _fixed_clock(manual_clock: Any) -> Any:
    """모듈의 모든 테스트를 ``_NOW`` 고정 시계 위에서 돌린다."""
    return manual_clock


def _summary(**overrides: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "currency": "KRW",
        "account_balance": 10_000_000.0,
        "purchasable_amount": 9_500_000.0,
        "total_evaluation": 12_500_000.0,
        "purchase_amount": 2_000_000.0,
        "eval_amount": 2_500_000.0,
        "total_profit_loss": 500_000.0,
        "total_allocated": 3_000_000.0,
        "total_reserved": 120_000.0,
        "total_available": 2_880_000.0,
        "unallocated": 7_000_000.0,
        "bot_count": 2,
        "external_purchase_amount": 0.0,
        "external_eval_amount": 0.0,
        "ante_purchase_amount": 2_000_000.0,
        "ante_eval_amount": 2_500_000.0,
        "ante_profit_loss": 500_000.0,
        "budget_exceeds_purchasable": False,
        "account_number": "",
        "is_demo_trading": False,
        "last_sync_time": None,
    }
    summary.update(overrides)
    return summary


def _snap(
    account_id: str, date: str, total: float, pnl: float, ret: float, upnl: float
) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "snapshot_date": date,
        "total_asset": total,
        "ante_eval_amount": 2_500_000.0,
        "ante_purchase_amount": 2_000_000.0,
        "unallocated": 7_000_000.0,
        "account_balance": 10_000_000.0,
        "total_allocated": 3_000_000.0,
        "bot_count": 2,
        "daily_pnl": pnl,
        "daily_return": ret,
        "net_trade_amount": 0.0,
        "unrealized_pnl": upnl,
        "created_at": f"{date} 15:40:00",
    }


_SNAP_UP = _snap("acc-1", "2026-01-02", 12_650_000.0, 150_000.0, 1.2, 500_000.0)
_SNAP_DOWN = _snap("acc-1", "2026-01-03", 12_400_000.0, -250_000.0, -1.98, 250_000.0)
_SNAP_FIRST = _snap("acc-1", "2026-01-01", 12_500_000.0, 0.0, 0.0, 400_000.0)
_SNAP_OTHER = _snap("acc-2", "2026-01-02", 3_000_000.0, -30_000.0, -1.0, -10_000.0)

_UPDATED = datetime(2026, 1, 3, 9, 0, tzinfo=UTC)
_BUDGETS_1 = [
    BotBudget(
        bot_id="bot-1",
        account_id="acc-1",
        allocated=1_000_000.0,
        available=800_000.0,
        reserved=50_000.0,
        spent=150_000.0,
        last_updated=_UPDATED,
    ),
    BotBudget(
        bot_id="bot-2",
        account_id="acc-1",
        allocated=500_000.0,
        available=500_000.0,
        last_updated=_UPDATED,
    ),
]
_BUDGETS_2 = [
    BotBudget(
        bot_id="bot-3",
        account_id="acc-2",
        allocated=2_000_000.0,
        available=1_900_000.0,
        returned=100_000.0,
        last_updated=_UPDATED,
    ),
]

_TX_ROWS: list[dict[str, Any]] = [
    {
        "id": 12,
        "account_id": "acc-1",
        "transaction_type": "allocate",
        "bot_id": "bot-1",
        "amount": 1_000_000.0,
        "description": "예산 할당",
        "created_at": "2026-01-02 09:00:00",
    },
    {
        "id": 11,
        "account_id": "acc-2",
        "transaction_type": "deallocate",
        "bot_id": None,
        "amount": -50_000.0,
        "description": "",
        "created_at": "2026-01-01 15:00:00",
    },
]


class _FakeTreasury:
    def __init__(
        self,
        account_id: str,
        *,
        summary: dict[str, Any] | None = None,
        budgets: list[BotBudget] | None = None,
        daily: dict[str, Any] | None = None,
        latest: dict[str, Any] | None = None,
        snapshots: list[dict[str, Any]] | None = None,
    ) -> None:
        self.account_id = account_id
        self.account_balance = 10_000_000.0
        self._summary = summary or _summary()
        self._budgets = budgets or []
        self._daily = daily
        self._latest = latest
        self._snapshots = snapshots or []

    def get_summary(self) -> dict[str, Any]:
        return dict(self._summary)

    def list_budgets(self) -> list[BotBudget]:
        return list(self._budgets)

    async def get_daily_snapshot(self, snapshot_date: str) -> dict[str, Any] | None:
        return self._daily

    async def get_latest_snapshot(self) -> dict[str, Any] | None:
        return self._latest

    async def get_snapshots(self, start: str, end: str) -> list[dict[str, Any]]:
        return list(self._snapshots)

    async def set_account_balance(self, amount: float) -> None:
        self.account_balance = amount


_SET_BALANCE = ["treasury", "set-balance", "15000000", "--account", "acc-1"]
_TX_FILTERS = [
    "--account",
    "acc-1",
    "--type",
    "allocate",
    "--bot",
    "bot-1",
    "--from",
    "2026-01-01",
    "--to",
    "2026-01-31",
    "--limit",
    "5",
    "--offset",
    "1",
]
_SNAPSHOT = ["treasury", "snapshot", "--account", "acc-1"]
_RANGE = [*_SNAPSHOT, "--from", "2026-01-01", "--to", "2026-01-03"]
_HISTORY = ["treasury", "portfolio", "history"]

_CASES: dict[str, list[str]] = {
    "status": ["treasury", "status", "--account", "acc-1"],
    "transactions_no_table": ["treasury", "transactions"],
    "transactions_empty": ["treasury", "transactions"],
    "transactions_rows": ["treasury", "transactions"],
    "transactions_filtered": ["treasury", "transactions", *_TX_FILTERS],
    "budgets_empty": ["treasury", "budgets"],
    "budgets_all": ["treasury", "budgets"],
    "budgets_account": ["treasury", "budgets", "--account", "acc-1"],
    "set_balance_ipc": list(_SET_BALANCE),
    "set_balance_direct": list(_SET_BALANCE),
    "allocate": ["treasury", "allocate", "bot-1", "100000", "--account", "acc-1"],
    "deallocate": ["treasury", "deallocate", "bot-1", "50000", "--account", "acc-1"],
    "snapshot_date": [*_SNAPSHOT, "--date", "2026-01-02"],
    "snapshot_today": list(_SNAPSHOT),
    "snapshot_range": list(_RANGE),
    "snapshot_range_empty": list(_RANGE),
    "snapshot_from_only": [*_SNAPSHOT, "--from", "2026-01-01"],
    "value_account": ["treasury", "portfolio", "value", "--account", "acc-1"],
    "value_all": ["treasury", "portfolio", "value"],
    "value_empty": ["treasury", "portfolio", "value"],
    "history_account": [
        *_HISTORY,
        "--account",
        "acc-1",
        "--from",
        "2026-01-01",
        "--to",
        "2026-01-03",
    ],
    "history_all": list(_HISTORY),
    "history_empty": list(_HISTORY),
}

_IPC_RESULTS: dict[str, dict[str, Any]] = {
    "set_balance_ipc": {
        "account_id": "acc-1",
        "total_balance": 15_000_000.0,
        "updated_at": "2026-01-05T09:30:00+00:00",
    },
    "allocate": {"account_id": "acc-1", "bot_id": "bot-1", "success": True},
    "deallocate": {"account_id": "acc-1", "bot_id": "bot-1", "success": True},
}
_IPC_BRANCHES = frozenset(_IPC_RESULTS)


def _treasuries(branch: str) -> list[_FakeTreasury]:
    if branch.startswith("budgets_"):
        if branch == "budgets_empty":
            return [_FakeTreasury("acc-1")]
        return [
            _FakeTreasury("acc-1", budgets=_BUDGETS_1),
            _FakeTreasury("acc-2", budgets=_BUDGETS_2),
        ]
    if branch == "snapshot_date":
        return [_FakeTreasury("acc-1", daily=_SNAP_UP)]
    if branch == "snapshot_today":
        return [_FakeTreasury("acc-1", latest=_SNAP_DOWN)]
    if branch in ("snapshot_range", "snapshot_from_only"):
        rows = [_SNAP_FIRST, _SNAP_UP, _SNAP_DOWN]
        return [_FakeTreasury("acc-1", snapshots=rows)]
    if branch.startswith("value_"):
        if branch == "value_empty":
            return []
        second = _FakeTreasury("acc-2", summary=_summary(total_evaluation=3_000_000.0))
        return [_FakeTreasury("acc-1", latest=_SNAP_DOWN), second]
    if branch.startswith("history_"):
        if branch == "history_empty":
            return []
        return [
            _FakeTreasury("acc-1", snapshots=[_SNAP_FIRST, _SNAP_UP]),
            _FakeTreasury("acc-2", snapshots=[_SNAP_OTHER]),
        ]
    return [_FakeTreasury("acc-1")]


def _tx_db(branch: str) -> AsyncMock:
    db = AsyncMock()
    if branch == "transactions_no_table":
        error = Exception("no such table: treasury_transactions")
        db.fetch_one = AsyncMock(side_effect=error)
        db.fetch_all = AsyncMock(side_effect=error)
        return db
    rows = _TX_ROWS if branch in ("transactions_rows", "transactions_filtered") else []
    total = {"transactions_rows": 7, "transactions_filtered": 1}.get(branch, 0)
    db.fetch_one = AsyncMock(return_value={"cnt": total})
    db.fetch_all = AsyncMock(return_value=rows)
    return db


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

    treasuries = _treasuries(branch)
    db = _tx_db(branch)

    @asynccontextmanager
    async def _create_treasury(
        account_id: str | None = None, *, ctx: Any = None
    ) -> AsyncIterator[tuple[Any, Any]]:
        match = [t for t in treasuries if t.account_id == account_id]
        yield (match or treasuries)[0], AsyncMock()

    @asynccontextmanager
    async def _create_manager(ctx: Any = None) -> AsyncIterator[tuple[Any, Any]]:
        yield SimpleNamespace(list_all=lambda: list(treasuries)), AsyncMock()

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield db

    if branch in _IPC_RESULTS:
        ipc_send = AsyncMock(return_value=_IPC_RESULTS[branch])
    else:
        ipc_send = AsyncMock(side_effect=AssertionError("IPC를 부르면 안 된다"))

    full_args = ["--format", "json", *_CASES[branch]] if mode == "json" else None
    with ExitStack() as stack:
        for target, value in (
            ("ante.cli.commands.treasury._create_treasury", _create_treasury),
            ("ante.cli.commands.treasury._create_treasury_manager", _create_manager),
            ("ante.cli.commands.treasury.open_cli_db", _open_cli_db),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
            (
                "ante.cli.cold_path.is_active_runtime",
                MagicMock(return_value=branch == "set_balance_ipc"),
            ),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli,
            full_args if full_args is not None else list(_CASES[branch]),
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )
    return result, ipc_send


_TREASURY_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("status", "text"): (
        "  계좌 잔고      :      10,000,000\n"
        "  매수 가능      :       9,500,000\n"
        "  총 평가액      :      12,500,000\n"
        "  총 손익        :         500,000\n"
        "  총 할당        :       3,000,000\n"
        "  총 예약        :         120,000\n"
        "  미할당         :       7,000,000\n"
        "  봇 수          :               2\n"
    ),
    ("status", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "currency": "KRW",\n'
        '    "account_balance": 10000000.0,\n'
        '    "purchasable_amount": 9500000.0,\n'
        '    "total_evaluation": 12500000.0,\n'
        '    "purchase_amount": 2000000.0,\n'
        '    "eval_amount": 2500000.0,\n'
        '    "total_profit_loss": 500000.0,\n'
        '    "total_allocated": 3000000.0,\n'
        '    "total_reserved": 120000.0,\n'
        '    "total_available": 2880000.0,\n'
        '    "unallocated": 7000000.0,\n'
        '    "bot_count": 2,\n'
        '    "external_purchase_amount": 0.0,\n'
        '    "external_eval_amount": 0.0,\n'
        '    "ante_purchase_amount": 2000000.0,\n'
        '    "ante_eval_amount": 2500000.0,\n'
        '    "ante_profit_loss": 500000.0,\n'
        '    "budget_exceeds_purchasable": false,\n'
        '    "account_number": "",\n'
        '    "is_demo_trading": false,\n'
        '    "last_sync_time": null\n'
        "  }\n"
        "}\n"
    ),
    ("transactions_no_table", "text"): ("(no data)\n"),
    ("transactions_no_table", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "items": [],\n'
        '    "total": 0\n'
        "  }\n"
        "}\n"
    ),
    ("transactions_empty", "text"): ("(no data)\n"),
    ("transactions_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "items": [],\n'
        '    "total": 0\n'
        "  }\n"
        "}\n"
    ),
    ("transactions_rows", "text"): (
        "  created_at |   account_id |         type |       bot_id |       amount\n"
        "------------------------------------------------------------------------\n"
        "2026-01-02 09:00:00 |        acc-1 |     allocate |        bot-1 |    1000000"
        ".0\n"
        "2026-01-01 15:00:00 |        acc-2 |   deallocate |         None |     -50000"
        ".0\n"
    ),
    ("transactions_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "items": [\n'
        "      {\n"
        '        "id": 12,\n'
        '        "account_id": "acc-1",\n'
        '        "type": "allocate",\n'
        '        "bot_id": "bot-1",\n'
        '        "amount": 1000000.0,\n'
        '        "description": "예산 할당",\n'
        '        "created_at": "2026-01-02 09:00:00"\n'
        "      },\n"
        "      {\n"
        '        "id": 11,\n'
        '        "account_id": "acc-2",\n'
        '        "type": "deallocate",\n'
        '        "bot_id": null,\n'
        '        "amount": -50000.0,\n'
        '        "description": "",\n'
        '        "created_at": "2026-01-01 15:00:00"\n'
        "      }\n"
        "    ],\n"
        '    "total": 7\n'
        "  }\n"
        "}\n"
    ),
    ("transactions_filtered", "text"): (
        "  created_at |   account_id |         type |       bot_id |       amount\n"
        "------------------------------------------------------------------------\n"
        "2026-01-02 09:00:00 |        acc-1 |     allocate |        bot-1 |    1000000"
        ".0\n"
        "2026-01-01 15:00:00 |        acc-2 |   deallocate |         None |     -50000"
        ".0\n"
    ),
    ("transactions_filtered", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "items": [\n'
        "      {\n"
        '        "id": 12,\n'
        '        "account_id": "acc-1",\n'
        '        "type": "allocate",\n'
        '        "bot_id": "bot-1",\n'
        '        "amount": 1000000.0,\n'
        '        "description": "예산 할당",\n'
        '        "created_at": "2026-01-02 09:00:00"\n'
        "      },\n"
        "      {\n"
        '        "id": 11,\n'
        '        "account_id": "acc-2",\n'
        '        "type": "deallocate",\n'
        '        "bot_id": null,\n'
        '        "amount": -50000.0,\n'
        '        "description": "",\n'
        '        "created_at": "2026-01-01 15:00:00"\n'
        "      }\n"
        "    ],\n"
        '    "total": 1\n'
        "  }\n"
        "}\n"
    ),
    ("budgets_empty", "text"): ("(no data)\n"),
    ("budgets_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "budgets": []\n'
        "  }\n"
        "}\n"
    ),
    ("budgets_all", "text"): (
        "  account_id |       bot_id |    allocated |    available |     reserved\n"
        "------------------------------------------------------------------------\n"
        "       acc-1 |        bot-1 |    1000000.0 |     800000.0 |      50000.0\n"
        "       acc-1 |        bot-2 |     500000.0 |     500000.0 |          0.0\n"
        "       acc-2 |        bot-3 |    2000000.0 |    1900000.0 |          0.0\n"
    ),
    ("budgets_all", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "budgets": [\n'
        "      {\n"
        '        "bot_id": "bot-1",\n'
        '        "account_id": "acc-1",\n'
        '        "allocated": 1000000.0,\n'
        '        "available": 800000.0,\n'
        '        "reserved": 50000.0,\n'
        '        "spent": 150000.0,\n'
        '        "returned": 0.0,\n'
        '        "last_updated": "2026-01-03T09:00:00+00:00"\n'
        "      },\n"
        "      {\n"
        '        "bot_id": "bot-2",\n'
        '        "account_id": "acc-1",\n'
        '        "allocated": 500000.0,\n'
        '        "available": 500000.0,\n'
        '        "reserved": 0.0,\n'
        '        "spent": 0.0,\n'
        '        "returned": 0.0,\n'
        '        "last_updated": "2026-01-03T09:00:00+00:00"\n'
        "      },\n"
        "      {\n"
        '        "bot_id": "bot-3",\n'
        '        "account_id": "acc-2",\n'
        '        "allocated": 2000000.0,\n'
        '        "available": 1900000.0,\n'
        '        "reserved": 0.0,\n'
        '        "spent": 0.0,\n'
        '        "returned": 100000.0,\n'
        '        "last_updated": "2026-01-03T09:00:00+00:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("budgets_account", "text"): (
        "  account_id |       bot_id |    allocated |    available |     reserved\n"
        "------------------------------------------------------------------------\n"
        "       acc-1 |        bot-1 |    1000000.0 |     800000.0 |      50000.0\n"
        "       acc-1 |        bot-2 |     500000.0 |     500000.0 |          0.0\n"
    ),
    ("budgets_account", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "budgets": [\n'
        "      {\n"
        '        "bot_id": "bot-1",\n'
        '        "account_id": "acc-1",\n'
        '        "allocated": 1000000.0,\n'
        '        "available": 800000.0,\n'
        '        "reserved": 50000.0,\n'
        '        "spent": 150000.0,\n'
        '        "returned": 0.0,\n'
        '        "last_updated": "2026-01-03T09:00:00+00:00"\n'
        "      },\n"
        "      {\n"
        '        "bot_id": "bot-2",\n'
        '        "account_id": "acc-1",\n'
        '        "allocated": 500000.0,\n'
        '        "available": 500000.0,\n'
        '        "reserved": 0.0,\n'
        '        "spent": 0.0,\n'
        '        "returned": 0.0,\n'
        '        "last_updated": "2026-01-03T09:00:00+00:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("set_balance_ipc", "text"): ("계좌 잔고 설정 완료: acc-1 15,000,000\n"),
    ("set_balance_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "account_id": "acc-1",\n'
        '    "total_balance": 15000000.0,\n'
        '    "updated_at": "2026-01-05T09:30:00+00:00"\n'
        "  }\n"
        "}\n"
    ),
    ("set_balance_direct", "text"): ("계좌 잔고 설정 완료: acc-1 15,000,000\n"),
    ("set_balance_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "account_id": "acc-1",\n'
        '    "total_balance": 15000000.0,\n'
        '    "updated_at": "2026-01-05T09:30:00+00:00"\n'
        "  }\n"
        "}\n"
    ),
    ("allocate", "text"): ("예산 할당 완료: bot-1 <- 100,000원\n"),
    ("allocate", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "예산 할당 완료: bot-1 <- 100,000원",\n'
        '  "data": {\n'
        '    "bot_id": "bot-1",\n'
        '    "amount": 100000.0,\n'
        '    "account_id": "acc-1"\n'
        "  }\n"
        "}\n"
    ),
    ("deallocate", "text"): ("예산 회수 완료: bot-1 -> 50,000원\n"),
    ("deallocate", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "예산 회수 완료: bot-1 -> 50,000원",\n'
        '  "data": {\n'
        '    "bot_id": "bot-1",\n'
        '    "amount": 50000.0,\n'
        '    "account_id": "acc-1"\n'
        "  }\n"
        "}\n"
    ),
    ("snapshot_date", "text"): (
        "일별 자산 스냅샷 (2026-01-02)\n"
        "  총 자산:           12,650,000원\n"
        "  Ante 관리:          2,500,000원 (매입: 2,000,000원)\n"
        "  미할당:             7,000,000원\n"
        "  당일 손익:    +       150,000원 (+1.20%)\n"
        "  미실현 손익:         +500,000원\n"
        "  보유 종목:    2개 봇\n"
    ),
    ("snapshot_date", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "account_id": "acc-1",\n'
        '    "snapshot_date": "2026-01-02",\n'
        '    "total_asset": 12650000.0,\n'
        '    "ante_eval_amount": 2500000.0,\n'
        '    "ante_purchase_amount": 2000000.0,\n'
        '    "unallocated": 7000000.0,\n'
        '    "account_balance": 10000000.0,\n'
        '    "total_allocated": 3000000.0,\n'
        '    "bot_count": 2,\n'
        '    "daily_pnl": 150000.0,\n'
        '    "daily_return": 1.2,\n'
        '    "net_trade_amount": 0.0,\n'
        '    "unrealized_pnl": 500000.0,\n'
        '    "created_at": "2026-01-02 15:40:00"\n'
        "  }\n"
        "}\n"
    ),
    ("snapshot_today", "text"): (
        "일별 자산 스냅샷 (2026-01-03)\n"
        "  총 자산:           12,400,000원\n"
        "  Ante 관리:          2,500,000원 (매입: 2,000,000원)\n"
        "  미할당:             7,000,000원\n"
        "  당일 손익:          -250,000원 (-1.98%)\n"
        "  미실현 손익:         +250,000원\n"
        "  보유 종목:    2개 봇\n"
    ),
    ("snapshot_today", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "account_id": "acc-1",\n'
        '    "snapshot_date": "2026-01-03",\n'
        '    "total_asset": 12400000.0,\n'
        '    "ante_eval_amount": 2500000.0,\n'
        '    "ante_purchase_amount": 2000000.0,\n'
        '    "unallocated": 7000000.0,\n'
        '    "account_balance": 10000000.0,\n'
        '    "total_allocated": 3000000.0,\n'
        '    "bot_count": 2,\n'
        '    "daily_pnl": -250000.0,\n'
        '    "daily_return": -1.98,\n'
        '    "net_trade_amount": 0.0,\n'
        '    "unrealized_pnl": 250000.0,\n'
        '    "created_at": "2026-01-03 15:40:00"\n'
        "  }\n"
        "}\n"
    ),
    ("snapshot_range", "text"): (
        "일별 자산 스냅샷 (2026-01-01 ~ 2026-01-03)\n"
        "            날짜            총 자산           당일 손익        수익률\n"
        "  --------------------------------------------------------\n"
        "    2026-01-01      12,500,000 +             0 +     0.00%\n"
        "    2026-01-02      12,650,000 +       150,000 +     1.20%\n"
        "    2026-01-03      12,400,000       -250,000     -1.98%\n"
    ),
    ("snapshot_range", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "snapshots": [\n'
        "      {\n"
        '        "account_id": "acc-1",\n'
        '        "snapshot_date": "2026-01-01",\n'
        '        "total_asset": 12500000.0,\n'
        '        "ante_eval_amount": 2500000.0,\n'
        '        "ante_purchase_amount": 2000000.0,\n'
        '        "unallocated": 7000000.0,\n'
        '        "account_balance": 10000000.0,\n'
        '        "total_allocated": 3000000.0,\n'
        '        "bot_count": 2,\n'
        '        "daily_pnl": 0.0,\n'
        '        "daily_return": 0.0,\n'
        '        "net_trade_amount": 0.0,\n'
        '        "unrealized_pnl": 400000.0,\n'
        '        "created_at": "2026-01-01 15:40:00"\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acc-1",\n'
        '        "snapshot_date": "2026-01-02",\n'
        '        "total_asset": 12650000.0,\n'
        '        "ante_eval_amount": 2500000.0,\n'
        '        "ante_purchase_amount": 2000000.0,\n'
        '        "unallocated": 7000000.0,\n'
        '        "account_balance": 10000000.0,\n'
        '        "total_allocated": 3000000.0,\n'
        '        "bot_count": 2,\n'
        '        "daily_pnl": 150000.0,\n'
        '        "daily_return": 1.2,\n'
        '        "net_trade_amount": 0.0,\n'
        '        "unrealized_pnl": 500000.0,\n'
        '        "created_at": "2026-01-02 15:40:00"\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acc-1",\n'
        '        "snapshot_date": "2026-01-03",\n'
        '        "total_asset": 12400000.0,\n'
        '        "ante_eval_amount": 2500000.0,\n'
        '        "ante_purchase_amount": 2000000.0,\n'
        '        "unallocated": 7000000.0,\n'
        '        "account_balance": 10000000.0,\n'
        '        "total_allocated": 3000000.0,\n'
        '        "bot_count": 2,\n'
        '        "daily_pnl": -250000.0,\n'
        '        "daily_return": -1.98,\n'
        '        "net_trade_amount": 0.0,\n'
        '        "unrealized_pnl": 250000.0,\n'
        '        "created_at": "2026-01-03 15:40:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("snapshot_range_empty", "text"): ("(스냅샷 없음)\n"),
    ("snapshot_range_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "snapshots": []\n'
        "  }\n"
        "}\n"
    ),
    ("snapshot_from_only", "text"): (
        "일별 자산 스냅샷 (2026-01-01 ~ 2026-01-03)\n"
        "            날짜            총 자산           당일 손익        수익률\n"
        "  --------------------------------------------------------\n"
        "    2026-01-01      12,500,000 +             0 +     0.00%\n"
        "    2026-01-02      12,650,000 +       150,000 +     1.20%\n"
        "    2026-01-03      12,400,000       -250,000     -1.98%\n"
    ),
    ("snapshot_from_only", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "snapshots": [\n'
        "      {\n"
        '        "account_id": "acc-1",\n'
        '        "snapshot_date": "2026-01-01",\n'
        '        "total_asset": 12500000.0,\n'
        '        "ante_eval_amount": 2500000.0,\n'
        '        "ante_purchase_amount": 2000000.0,\n'
        '        "unallocated": 7000000.0,\n'
        '        "account_balance": 10000000.0,\n'
        '        "total_allocated": 3000000.0,\n'
        '        "bot_count": 2,\n'
        '        "daily_pnl": 0.0,\n'
        '        "daily_return": 0.0,\n'
        '        "net_trade_amount": 0.0,\n'
        '        "unrealized_pnl": 400000.0,\n'
        '        "created_at": "2026-01-01 15:40:00"\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acc-1",\n'
        '        "snapshot_date": "2026-01-02",\n'
        '        "total_asset": 12650000.0,\n'
        '        "ante_eval_amount": 2500000.0,\n'
        '        "ante_purchase_amount": 2000000.0,\n'
        '        "unallocated": 7000000.0,\n'
        '        "account_balance": 10000000.0,\n'
        '        "total_allocated": 3000000.0,\n'
        '        "bot_count": 2,\n'
        '        "daily_pnl": 150000.0,\n'
        '        "daily_return": 1.2,\n'
        '        "net_trade_amount": 0.0,\n'
        '        "unrealized_pnl": 500000.0,\n'
        '        "created_at": "2026-01-02 15:40:00"\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acc-1",\n'
        '        "snapshot_date": "2026-01-03",\n'
        '        "total_asset": 12400000.0,\n'
        '        "ante_eval_amount": 2500000.0,\n'
        '        "ante_purchase_amount": 2000000.0,\n'
        '        "unallocated": 7000000.0,\n'
        '        "account_balance": 10000000.0,\n'
        '        "total_allocated": 3000000.0,\n'
        '        "bot_count": 2,\n'
        '        "daily_pnl": -250000.0,\n'
        '        "daily_return": -1.98,\n'
        '        "net_trade_amount": 0.0,\n'
        '        "unrealized_pnl": 250000.0,\n'
        '        "created_at": "2026-01-03 15:40:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("value_account", "text"): (
        "  총 자산        :      12,400,000\n"
        "  당일 손익      :        -250,000\n"
        "  수익률         :         -0.0202\n"
        "  미실현 손익    :         250,000\n"
    ),
    ("value_account", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "total_value": 12400000.0,\n'
        '    "daily_pnl": -250000.0,\n'
        '    "daily_return": -0.020161290322580645,\n'
        '    "unrealized_pnl": 250000.0,\n'
        '    "accounts": [\n'
        "      {\n"
        '        "account_id": "acc-1",\n'
        '        "total_value": 12400000.0,\n'
        '        "daily_pnl": -250000.0,\n'
        '        "daily_return": -1.98,\n'
        '        "unrealized_pnl": 250000.0,\n'
        '        "snapshot_date": "2026-01-03",\n'
        '        "updated_at": "2026-01-03 15:40:00"\n'
        "      }\n"
        "    ],\n"
        '    "updated_at": "2026-01-05T09:30:00+00:00"\n'
        "  }\n"
        "}\n"
    ),
    ("value_all", "text"): (
        "  총 자산        :      15,400,000\n"
        "  당일 손익      :        -250,000\n"
        "  수익률         :         -0.0162\n"
        "  미실현 손익    :         250,000\n"
    ),
    ("value_all", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "total_value": 15400000.0,\n'
        '    "daily_pnl": -250000.0,\n'
        '    "daily_return": -0.016233766233766232,\n'
        '    "unrealized_pnl": 250000.0,\n'
        '    "accounts": [\n'
        "      {\n"
        '        "account_id": "acc-1",\n'
        '        "total_value": 12400000.0,\n'
        '        "daily_pnl": -250000.0,\n'
        '        "daily_return": -1.98,\n'
        '        "unrealized_pnl": 250000.0,\n'
        '        "snapshot_date": "2026-01-03",\n'
        '        "updated_at": "2026-01-03 15:40:00"\n'
        "      },\n"
        "      {\n"
        '        "account_id": "acc-2",\n'
        '        "total_value": 3000000.0,\n'
        '        "daily_pnl": 0.0,\n'
        '        "daily_return": 0.0,\n'
        '        "unrealized_pnl": 0.0,\n'
        '        "updated_at": "2026-01-05T09:30:00+00:00"\n'
        "      }\n"
        "    ],\n"
        '    "updated_at": "2026-01-05T09:30:00+00:00"\n'
        "  }\n"
        "}\n"
    ),
    ("value_empty", "text"): (
        "  총 자산        :               0\n"
        "  당일 손익      :               0\n"
        "  수익률         :          0.0000\n"
        "  미실현 손익    :               0\n"
    ),
    ("value_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "total_value": 0,\n'
        '    "daily_pnl": 0,\n'
        '    "daily_return": 0.0,\n'
        '    "unrealized_pnl": 0,\n'
        '    "accounts": [],\n'
        '    "updated_at": "2026-01-05T09:30:00+00:00"\n'
        "  }\n"
        "}\n"
    ),
    ("history_account", "text"): (
        "        date |  total_asset |    daily_pnl | daily_return\n"
        "---------------------------------------------------------\n"
        "  2026-01-01 |   12500000.0 |          0.0 |          0.0\n"
        "  2026-01-02 |   12650000.0 |     150000.0 | 0.011857707509881422\n"
    ),
    ("history_account", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "data": [\n'
        "      {\n"
        '        "date": "2026-01-01",\n'
        '        "total_asset": 12500000.0,\n'
        '        "daily_pnl": 0.0,\n'
        '        "daily_return": 0.0,\n'
        '        "unrealized_pnl": 400000.0\n'
        "      },\n"
        "      {\n"
        '        "date": "2026-01-02",\n'
        '        "total_asset": 12650000.0,\n'
        '        "daily_pnl": 150000.0,\n'
        '        "daily_return": 0.011857707509881422,\n'
        '        "unrealized_pnl": 500000.0\n'
        "      }\n"
        "    ],\n"
        '    "start_date": "2026-01-01",\n'
        '    "end_date": "2026-01-03"\n'
        "  }\n"
        "}\n"
    ),
    ("history_all", "text"): (
        "        date |  total_asset |    daily_pnl | daily_return\n"
        "---------------------------------------------------------\n"
        "  2026-01-01 |   12500000.0 |          0.0 |          0.0\n"
        "  2026-01-02 |   15650000.0 |     120000.0 | 0.0076677316293929714\n"
    ),
    ("history_all", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "data": [\n'
        "      {\n"
        '        "date": "2026-01-01",\n'
        '        "total_asset": 12500000.0,\n'
        '        "daily_pnl": 0.0,\n'
        '        "daily_return": 0.0,\n'
        '        "unrealized_pnl": 400000.0\n'
        "      },\n"
        "      {\n"
        '        "date": "2026-01-02",\n'
        '        "total_asset": 15650000.0,\n'
        '        "daily_pnl": 120000.0,\n'
        '        "daily_return": 0.0076677316293929714,\n'
        '        "unrealized_pnl": 490000.0\n'
        "      }\n"
        "    ],\n"
        '    "start_date": "2025-12-06",\n'
        '    "end_date": "2026-01-05"\n'
        "  }\n"
        "}\n"
    ),
    ("history_empty", "text"): ("(no data)\n"),
    ("history_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "data": [],\n'
        '    "start_date": "2025-12-06",\n'
        '    "end_date": "2026-01-05"\n'
        "  }\n"
        "}\n"
    ),
}


class TestTreasuryOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_TREASURY_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }
        assert len(_TREASURY_OUTPUT_BYTES) == 2 * len(_CASES)

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _TREASURY_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == (1 if branch in _IPC_BRANCHES else 0)


_FAKE_CREDENTIALS = {
    "app_key": "FAKE-APP-KEY-0000",
    "app_secret": "FAKE-APP-SECRET-0000",
    "account_no": "FAKE-ACCOUNT-NO-0000",
}


@pytest.mark.parametrize("mode", ["text", "json"])
def test_status_never_prints_account_credentials(mode: str) -> None:
    """실제 ``_create_treasury``를 지나는 ``status``는 계좌의 자격 증명과
    계좌번호를 어느 스트림에도 내지 않는다(``account_number``는 빈 값)."""
    from ante.cli.main import cli

    account = SimpleNamespace(
        account_id="acc-1",
        currency="KRW",
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        credentials=dict(_FAKE_CREDENTIALS),
    )
    service = AsyncMock()
    service.get = AsyncMock(return_value=account)

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    args = ["treasury", "status", "--account", "acc-1"]
    with (
        patch("ante.cli.commands.treasury.open_cli_db", new=_open_cli_db),
        patch("ante.account.service.AccountService", return_value=service),
        patch("ante.treasury.treasury.Treasury.initialize", new=AsyncMock()),
    ):
        result = CliRunner(mix_stderr=False).invoke(
            cli,
            ["--format", "json", *args] if mode == "json" else args,
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output
    for value in _FAKE_CREDENTIALS.values():
        assert value not in result.stdout
        assert value not in result.stderr
    expected = 1 if mode == "json" else 0
    assert result.stdout.count('"account_number": ""') == expected
    assert result.stdout.count("account_number") == expected
    assert "account_number" not in result.stderr
