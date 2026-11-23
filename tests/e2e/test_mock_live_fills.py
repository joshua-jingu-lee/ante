"""mock 브로커의 실전 모드 계좌에서 주문이 실전 경로를 지나고 체결 모드대로 끝난다.

제품은 ``(mock, live)`` 계좌를 거부한다. 하네스의 테스트 주입(``allow_mock_live``)이
하위 프로세스의 가상 전용 집합에서 ``mock``을 뺀다. 계좌 하나에 체결 모드 하나,
봇 하나, 전략 하나를 둔다. 주문은 게이트웨이의 제출 → 주문 추적 → 체결 폴링 →
체결 반영 → 정산을 지난다. 체결 폴링은 부팅 뒤 약 60초에 처음 돈다.

알려진 한계: 시나리오가 KST 자정을 걸치면 주문 추적기가 열린 부분 체결 주문을
만료로 처리할 수 있다. 재시작 뒤의 복구는 다루지 않는다(mock 장부는 메모리뿐이다).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

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
FIRST_POLL_DEADLINE_SECONDS = 100.0
BALANCE_SYNC_DEADLINE_SECONDS = 20.0
UPDATE_CHECKER_MODULE = "ante.update.checker"


@dataclass(frozen=True)
class LiveCase:
    account_id: str
    fill_mode: str
    quantity: int
    initial_cash: int

    @property
    def bot_id(self) -> str:
        return f"e2e-{self.account_id}"

    @property
    def strategy_name(self) -> str:
        return f"e2e_mock_live_{self.fill_mode}"

    @property
    def order_amount(self) -> float:
        return float(PRICE * self.quantity)


IMMEDIATE = LiveCase("liveimm", "immediate", 2, 3_000_000)
PARTIAL = LiveCase("livepart", "partial", 4, 3_100_000)
REJECT = LiveCase("liverej", "reject", 3, 3_200_000)
CASES = (IMMEDIATE, PARTIAL, REJECT)


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

    for case in (IMMEDIATE, PARTIAL):
        budget = wait_until(
            lambda case=case: _budget(daemon, case),
            lambda b, case=case: b["reserved"] == case.order_amount,
            seconds=SUBMIT_DEADLINE_SECONDS,
        )
        assert budget["reserved"] == pytest.approx(case.order_amount), budget
        assert _fills(daemon, case)["total"] == 0

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
        seconds=FIRST_POLL_DEADLINE_SECONDS,
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

    half = PARTIAL.quantity / 2
    fills = wait_until(
        lambda: _fills(daemon, PARTIAL),
        lambda f: f["total"] >= 1,
        seconds=SUBMIT_DEADLINE_SECONDS,
    )
    assert fills["total"] == 1, fills
    budget = _budget(daemon, PARTIAL)
    assert budget["reserved"] == pytest.approx(half * PRICE), budget
    assert budget["spent"] == pytest.approx(half * PRICE), budget
    trades = _trades(daemon, PARTIAL)
    assert [(t["status"], t["quantity"]) for t in trades] == [("filled", half)], trades
    assert _position_quantity(daemon, PARTIAL) == half

    for case in (IMMEDIATE, PARTIAL):
        reconciled = _reconcile(daemon, case)
        assert reconciled["data"]["discrepancies"] == [], reconciled

    for case in CASES:
        stopped = daemon.cli("bot", "stop", case.bot_id)
        assert stopped["data"]["bot"]["status"] == "stopped", stopped

    assert daemon.stop() == 0
    unexpected = [
        a for a in daemon.net_attempts() if UPDATE_CHECKER_MODULE not in a["modules"]
    ]
    assert unexpected == []
