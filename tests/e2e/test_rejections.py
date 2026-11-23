"""주문 거절 시나리오: 예산 부족(Treasury)과 포지션 크기 규칙(규칙 엔진)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.e2e.harness import DaemonHarness, wait_until

STRATEGY_PATH = Path(__file__).resolve().parent / "strategies" / "limit_buy_once.py"
BOT_ID = "e2e-reject"
ORDER_AMOUNT = 70000
ACCOUNT_BALANCE = 5000000
SETTLE_SECONDS = 30.0
BUDGET_REJECT_PREFIX = "insufficient_budget"
RULE_REJECT_PREFIX = "Position size would exceed limit"
UPDATE_CHECKER_MODULE = "ante.update.checker"


def _start_bot(daemon: DaemonHarness, allocation: int) -> None:
    submitted = daemon.cli("strategy", "submit", str(STRATEGY_PATH))
    strategy_id = submitted["data"]["strategy_id"]
    daemon.start()
    daemon.cli(
        "bot",
        "create",
        "--name",
        "e2e reject",
        "--strategy",
        strategy_id,
        "--account",
        "test",
        "--interval",
        "10",
        "--id",
        BOT_ID,
    )
    daemon.cli("treasury", "set-balance", str(ACCOUNT_BALANCE), "--account", "test")
    daemon.cli("treasury", "allocate", BOT_ID, str(allocation), "--account", "test")
    started = daemon.cli("bot", "start", BOT_ID)
    assert started["data"]["bot"]["status"] == "running"
    assert started["data"]["bot"]["trading_mode"] == "virtual"


def _outcome(daemon: DaemonHarness) -> dict[str, Any]:
    trades = daemon.cli("trade", "list", "--bot", BOT_ID)["data"]["trades"]
    fills = daemon.cli("treasury", "transactions", "--bot", BOT_ID, "--type", "fill")
    return {
        "rejected": [t for t in trades if t["status"] == "rejected"],
        "fills": fills["data"]["total"],
    }


def _assert_rejected_without_effect(
    daemon: DaemonHarness, allocation: int, reason_prefix: str
) -> None:
    outcome = wait_until(
        lambda: _outcome(daemon),
        lambda o: bool(o["rejected"]) or o["fills"] > 0,
        seconds=SETTLE_SECONDS,
    )
    assert outcome["fills"] == 0, outcome
    assert len(outcome["rejected"]) == 1, outcome
    (row,) = outcome["rejected"]
    assert (row["side"], row["quantity"], row["price"]) == ("buy", 1.0, ORDER_AMOUNT)

    info = daemon.cli("trade", "info", row["trade_id"])["data"]
    assert info["status"] == "rejected"
    assert info["reason"].startswith(reason_prefix), info

    budgets = daemon.cli("treasury", "budgets", "--account", "test")
    (budget,) = [b for b in budgets["data"]["budgets"] if b["bot_id"] == BOT_ID]
    assert budget["allocated"] == allocation
    assert budget["reserved"] == 0
    assert budget["spent"] == 0

    bot = daemon.cli("bot", "info", BOT_ID)["data"]
    assert bot["status"] == "running", bot

    assert daemon.stop() == 0
    unexpected = [
        a for a in daemon.net_attempts() if UPDATE_CHECKER_MODULE not in a["modules"]
    ]
    assert unexpected == []


def test_budget_shortfall_rejects_order(daemon: DaemonHarness) -> None:
    daemon.init()
    allocation = ORDER_AMOUNT // 2
    _start_bot(daemon, allocation)
    _assert_rejected_without_effect(daemon, allocation, BUDGET_REJECT_PREFIX)


def test_position_size_rule_rejects_order(daemon: DaemonHarness) -> None:
    daemon.init()
    limit = ORDER_AMOUNT // 2
    updated = daemon.cli(
        "rule",
        "update",
        "position_size",
        "--account",
        "test",
        "--param",
        f"max_position_amount={limit}",
    )
    assert updated["data"]["rule"] == {
        "type": "position_size",
        "enabled": True,
        "params": {"max_position_amount": limit},
    }
    allocation = ORDER_AMOUNT * 20
    _start_bot(daemon, allocation)
    _assert_rejected_without_effect(daemon, allocation, RULE_REJECT_PREFIX)
