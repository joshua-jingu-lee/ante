"""mock 브로커의 실전 모드 계좌에서 주문이 실전 경로를 지나고 체결 모드대로 끝난다.

제품은 ``(mock, live)`` 계좌를 거부한다. 하네스의 테스트 주입(``allow_mock_live``)이
하위 프로세스의 가상 전용 집합에서 ``mock``을 뺀다. 계좌 하나에 체결 모드 하나,
봇 하나, 전략 하나를 둔다. 주문은 게이트웨이의 제출 → 주문 추적 → 체결 폴링 →
체결 반영 → 정산을 지난다. 체결 폴링은 부팅 뒤 약 60초에 처음, 약 120초에 두 번째로
돈다(폴 주기는 ``DEFAULT_POLL_INTERVAL``). 지연 계좌는 두 번째 폴에서 체결되므로 그
계좌의 주문 이력은 CLI로 읽지 않는다(그 조회도 mock의 횟수에 든다). 체결 대기의 기한은
계좌마다 예약이 보인 시각부터 필요한 폴 수 × 폴 주기 + 여유로 잰다. 지연 계좌 하나는
체결 전에 봇을 정지해, 정지가 미체결 주문을 취소하고 두 번째 폴 뒤에도 체결이 없음을
본다(#3049).

알려진 한계: 시나리오가 KST 자정을 걸치면 주문 추적기가 열린 부분 체결 주문을
만료로 처리할 수 있다. 재시작 뒤의 복구는 다루지 않는다(mock 장부는 메모리뿐이다).
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Any

import pytest

from ante.broker.fill_scheduler import DEFAULT_POLL_INTERVAL
from tests.e2e.harness import DaemonHarness, run_json_command, wait_until

SYMBOL = "000001"
PRICE = 10000
STRATEGY_TEMPLATE = '''"""e2e 실전 경로 전략: 지정가로 한 번만 산다."""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta


class LimitBuyOnce(Strategy):
    """첫 스텝에 지정가 매수 신호를 한 번 낸다."""

    meta = StrategyMeta(
        name="{name}",
        version="0.1.0",
        description="e2e mock live limit buy once",
        author_name="agent",
        author_id="agent",
        symbols=["{symbol}"],
        timeframe="1d",
        exchange="TEST",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """아직 신호를 낸 적이 없으면 지정가로 산다."""
        if getattr(self, "_sent", False):
            return []
        self._sent = True
        return [
            Signal(
                symbol="{symbol}",
                side="buy",
                quantity={quantity},
                order_type="limit",
                price={price},
            )
        ]
'''
BUDGET = 500_000
SUBMIT_DEADLINE_SECONDS = 30.0
POLL_MARGIN_SECONDS = 60.0
MIN_FILL_WAIT_SECONDS = 10.0
POLL_SETTLE_SECONDS = 10.0
DELAY_POLLS = 2
BALANCE_SYNC_DEADLINE_SECONDS = 20.0
UPDATE_CHECKER_MODULE = "ante.update.checker"


@dataclass(frozen=True)
class LiveCase:
    account_id: str
    fill_mode: str
    quantity: int
    initial_cash: int
    extra_config: tuple[str, ...] = ()

    @property
    def bot_id(self) -> str:
        return f"e2e-{self.account_id}"

    @property
    def strategy_name(self) -> str:
        return f"e2e_mock_live_{self.account_id}"

    @property
    def order_amount(self) -> float:
        return float(PRICE * self.quantity)


IMMEDIATE = LiveCase("liveimm", "immediate", 2, 3_000_000)
PARTIAL = LiveCase("livepart", "partial", 4, 3_100_000)
REJECT = LiveCase("liverej", "reject", 3, 3_200_000)
DELAYED = LiveCase("livedel", "delayed", 5, 3_300_000, (f"delay_polls={DELAY_POLLS}",))
STOPPED = LiveCase("livestop", "delayed", 6, 3_400_000, (f"delay_polls={DELAY_POLLS}",))
CASES = (IMMEDIATE, PARTIAL, REJECT, DELAYED, STOPPED)
OPEN_CASES = (IMMEDIATE, PARTIAL, DELAYED, STOPPED)


def _create_account_args(case: LiveCase, prices_file: str) -> list[str]:
    return [
        "account",
        "create",
        "--broker-type",
        "mock",
        "--account-id",
        case.account_id,
        "--name",
        f"e2e mock live {case.fill_mode}",
        "--trading-mode",
        "live",
        "--broker-config",
        f"prices_file={prices_file}",
        "--broker-config",
        f"fill_mode={case.fill_mode}",
        "--broker-config",
        f"initial_cash={case.initial_cash}",
        *[arg for item in case.extra_config for arg in ("--broker-config", item)],
    ]


def _budget(daemon: DaemonHarness, case: LiveCase) -> dict[str, Any]:
    budgets = daemon.cli("treasury", "budgets", "--account", case.account_id)
    (budget,) = [b for b in budgets["data"]["budgets"] if b["bot_id"] == case.bot_id]
    return dict(budget)


def _fills(daemon: DaemonHarness, case: LiveCase) -> dict[str, Any]:
    return dict(
        daemon.cli("treasury", "transactions", "--bot", case.bot_id, "--type", "fill")[
            "data"
        ]
    )


def _trades(daemon: DaemonHarness, case: LiveCase) -> list[dict[str, Any]]:
    return list(daemon.cli("trade", "list", "--bot", case.bot_id)["data"]["trades"])


def _position_quantity(daemon: DaemonHarness, case: LiveCase) -> float:
    positions = daemon.cli("bot", "positions", case.bot_id)["data"]["positions"]
    return sum(float(p["quantity"]) for p in positions if p["symbol"] == SYMBOL)


def _account_balance(daemon: DaemonHarness, case: LiveCase) -> float:
    status = daemon.cli("treasury", "status", "--account", case.account_id)
    return float(status["data"]["account_balance"])


def _reconcile(daemon: DaemonHarness, case: LiveCase) -> dict[str, Any]:
    return dict(daemon.cli("broker", "reconcile", "--account", case.account_id))


def _tracked_open_orders(daemon: DaemonHarness, case: LiveCase) -> int:
    """데몬 DB의 주문 추적기에서 그 봇의 열린 주문 수(읽기 전용으로 연다)."""
    uri = f"file:{daemon.config_dir / 'db' / 'ante.db'}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM order_tracker"
            " WHERE bot_id = ? AND status IN ('open', 'partially_filled')",
            (case.bot_id,),
        ).fetchone()
    return int(row[0])


def _fill_deadline(observed_at: float, polls: int) -> float:
    """예약이 보인 시각부터 ``polls``번째 폴까지 남은 기한(초, 하한 있음)."""
    deadline = observed_at + polls * DEFAULT_POLL_INTERVAL + POLL_MARGIN_SECONDS
    return max(deadline - time.monotonic(), MIN_FILL_WAIT_SECONDS)


def test_mock_live_fill_modes(daemon: DaemonHarness) -> None:
    daemon.init()
    prices_file = daemon.root / "prices.json"
    prices_file.write_text(
        json.dumps({"prices": {SYMBOL: PRICE}, "default_price": PRICE}),
        encoding="utf-8",
    )

    rejected = run_json_command(
        daemon.cli_argv(*_create_account_args(IMMEDIATE, str(prices_file))),
        env=daemon.env(),
        cwd=daemon.work_dir,
        expect_failure=True,
    )
    assert rejected.payload["code"] == "ACCOUNT_INVALID_BROKER_TYPE", rejected
    assert daemon.mock_live_pids() == set()

    daemon.allow_mock_live = True
    strategy_ids: dict[str, str] = {}
    for case in CASES:
        created = daemon.cli(*_create_account_args(case, str(prices_file)))
        assert created["status"] == "ok", created
        source = daemon.root / f"{case.strategy_name}.py"
        source.write_text(
            STRATEGY_TEMPLATE.format(
                name=case.strategy_name,
                symbol=SYMBOL,
                quantity=case.quantity,
                price=PRICE,
            ),
            encoding="utf-8",
        )
        submitted = daemon.cli("strategy", "submit", str(source))
        strategy_ids[case.account_id] = submitted["data"]["strategy_id"]

    daemon.start()
    assert daemon.daemon_pid in daemon.mock_live_pids()

    for case in CASES:
        balance = wait_until(
            lambda case=case: _account_balance(daemon, case),
            lambda value, case=case: value == case.initial_cash,
            seconds=BALANCE_SYNC_DEADLINE_SECONDS,
        )
        assert balance == case.initial_cash, case
        daemon.cli(
            "bot",
            "create",
            "--name",
            f"e2e mock live {case.fill_mode}",
            "--strategy",
            strategy_ids[case.account_id],
            "--account",
            case.account_id,
            "--interval",
            "10",
            "--id",
            case.bot_id,
        )
        daemon.cli(
            "treasury",
            "set-balance",
            str(case.initial_cash),
            "--account",
            case.account_id,
        )
        daemon.cli(
            "treasury",
            "allocate",
            case.bot_id,
            str(BUDGET),
            "--account",
            case.account_id,
        )
        started = daemon.cli("bot", "start", case.bot_id)
        assert started["data"]["bot"]["status"] == "running", started
        assert started["data"]["bot"]["trading_mode"] == "live", started

    observed_at: dict[str, float] = {}
    for case in OPEN_CASES:
        budget = wait_until(
            lambda case=case: _budget(daemon, case),
            lambda b, case=case: b["reserved"] == case.order_amount,
            seconds=SUBMIT_DEADLINE_SECONDS,
        )
        observed_at[case.account_id] = time.monotonic()
        assert budget["reserved"] == pytest.approx(case.order_amount), budget
        assert _fills(daemon, case)["total"] == 0

    tracked = wait_until(
        lambda: _tracked_open_orders(daemon, STOPPED),
        lambda count: count == 1,
        seconds=SUBMIT_DEADLINE_SECONDS,
    )
    assert tracked == 1
    stopped = daemon.cli("bot", "stop", STOPPED.bot_id)
    assert stopped["data"]["bot"]["status"] == "stopped", stopped
    assert _tracked_open_orders(daemon, STOPPED) == 0
    stopped_trades = _trades(daemon, STOPPED)
    assert [t["status"] for t in stopped_trades] == ["cancelled"], stopped_trades
    assert _budget(daemon, STOPPED)["reserved"] == 0

    rejected_trades = wait_until(
        lambda: _trades(daemon, REJECT),
        lambda trades: len(trades) > 0,
        seconds=SUBMIT_DEADLINE_SECONDS,
    )
    assert [(t["status"], t["quantity"]) for t in rejected_trades] == [
        ("failed", float(REJECT.quantity))
    ], rejected_trades
    assert _budget(daemon, REJECT)["reserved"] == 0
    assert daemon.cli("bot", "status", REJECT.bot_id)["data"]["bot"]["status"] == (
        "running"
    )

    fills = wait_until(
        lambda: _fills(daemon, IMMEDIATE),
        lambda f: f["total"] >= 1,
        seconds=_fill_deadline(observed_at[IMMEDIATE.account_id], 1),
    )
    assert fills["total"] == 1, fills
    budget = _budget(daemon, IMMEDIATE)
    assert budget["reserved"] == 0, budget
    assert budget["spent"] == pytest.approx(IMMEDIATE.order_amount), budget
    trades = _trades(daemon, IMMEDIATE)
    assert [(t["status"], t["quantity"], t["price"]) for t in trades] == [
        ("filled", float(IMMEDIATE.quantity), float(PRICE))
    ], trades
    assert _position_quantity(daemon, IMMEDIATE) == IMMEDIATE.quantity

    time.sleep(POLL_SETTLE_SECONDS)
    assert _fills(daemon, DELAYED)["total"] == 0
    budget = _budget(daemon, DELAYED)
    assert budget["reserved"] == pytest.approx(DELAYED.order_amount), budget
    assert _trades(daemon, DELAYED) == []
    assert _position_quantity(daemon, DELAYED) == 0

    half = PARTIAL.quantity / 2
    fills = wait_until(
        lambda: _fills(daemon, PARTIAL),
        lambda f: f["total"] >= 1,
        seconds=_fill_deadline(observed_at[PARTIAL.account_id], 1),
    )
    assert fills["total"] == 1, fills
    budget = _budget(daemon, PARTIAL)
    assert budget["reserved"] == pytest.approx(half * PRICE), budget
    assert budget["spent"] == pytest.approx(half * PRICE), budget
    trades_partial = _trades(daemon, PARTIAL)
    assert [(t["status"], t["quantity"]) for t in trades_partial] == [
        ("filled", half)
    ], trades_partial
    assert _position_quantity(daemon, PARTIAL) == half

    for case in (IMMEDIATE, PARTIAL):
        reconciled = _reconcile(daemon, case)
        assert reconciled["data"]["discrepancies"] == [], reconciled

    fills = wait_until(
        lambda: _fills(daemon, DELAYED),
        lambda f: f["total"] >= 1,
        seconds=_fill_deadline(observed_at[DELAYED.account_id], DELAY_POLLS),
    )
    assert fills["total"] == 1, fills
    budget = _budget(daemon, DELAYED)
    assert budget["reserved"] == 0, budget
    assert budget["spent"] == pytest.approx(DELAYED.order_amount), budget
    trades = _trades(daemon, DELAYED)
    assert [(t["status"], t["quantity"], t["price"]) for t in trades] == [
        ("filled", float(DELAYED.quantity), float(PRICE))
    ], trades
    assert _position_quantity(daemon, DELAYED) == DELAYED.quantity
    reconciled = _reconcile(daemon, DELAYED)
    assert reconciled["data"]["discrepancies"] == [], reconciled

    time.sleep(POLL_SETTLE_SECONDS / 2)
    assert _fills(daemon, PARTIAL)["total"] == 1
    assert _trades(daemon, PARTIAL) == trades_partial
    budget = _budget(daemon, PARTIAL)
    assert budget["reserved"] == pytest.approx(half * PRICE), budget
    assert _position_quantity(daemon, PARTIAL) == half
    assert _fills(daemon, STOPPED)["total"] == 0
    assert _trades(daemon, STOPPED) == stopped_trades
    assert _position_quantity(daemon, STOPPED) == 0
    budget = _budget(daemon, STOPPED)
    assert budget["reserved"] == 0, budget
    assert budget["spent"] == 0, budget

    for case in (IMMEDIATE, PARTIAL, REJECT, DELAYED):
        stopped = daemon.cli("bot", "stop", case.bot_id)
        assert stopped["data"]["bot"]["status"] == "stopped", stopped

    assert daemon.stop() == 0
    unexpected = [
        a for a in daemon.net_attempts() if UPDATE_CHECKER_MODULE not in a["modules"]
    ]
    assert unexpected == []
