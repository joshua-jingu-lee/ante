"""mock 계좌의 봇이 시작되고 시장가 주문이 가격 파일의 가격으로 체결된다."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from tests.e2e.harness import DaemonHarness

STRATEGY_PATH = Path(__file__).resolve().parent / "strategies" / "market_buy.py"
ACCOUNT_ID = "mock1"
BOT_ID = "e2e-mock"
SYMBOL = "000001"
PRICE = 12345
FILL_DEADLINE_SECONDS = 30.0
EXPECTED_FILLS = {(f"buy {SYMBOL} 1 @ 12,345", float(PRICE))}
EXPECTED_TRADES = {("buy", SYMBOL, 1.0, float(PRICE))}
EXPECTED_POSITION_QUANTITY = 1.0
UPDATE_CHECKER_MODULE = "ante.update.checker"


def _wait_for_fills(daemon: DaemonHarness, count: int) -> dict[str, Any]:
    deadline = time.monotonic() + FILL_DEADLINE_SECONDS
    while True:
        payload = daemon.cli(
            "treasury", "transactions", "--bot", BOT_ID, "--type", "fill"
        )["data"]
        if payload["total"] >= count or time.monotonic() >= deadline:
            return payload
        time.sleep(0.5)


def test_mock_account_market_fill(daemon: DaemonHarness) -> None:
    daemon.init()

    prices_file = daemon.root / "prices.json"
    prices_file.write_text(json.dumps({"prices": {SYMBOL: PRICE}}), encoding="utf-8")
    created_account = daemon.cli(
        "account",
        "create",
        "--broker-type",
        "mock",
        "--account-id",
        ACCOUNT_ID,
        "--name",
        "e2e mock",
        "--trading-mode",
        "virtual",
        "--broker-config",
        f"prices_file={prices_file}",
    )
    assert created_account["status"] == "ok", created_account

    submitted = daemon.cli("strategy", "submit", str(STRATEGY_PATH))
    strategy_id = submitted["data"]["strategy_id"]
    assert strategy_id

    daemon.start()
    assert daemon.daemon_pid in daemon.guarded_pids()

    accounts = daemon.cli("account", "list")["data"]["accounts"]
    (account,) = [a for a in accounts if a["account_id"] == ACCOUNT_ID]
    assert account["broker_type"] == "mock"
    assert account["exchange"] == "TEST"

    created = daemon.cli(
        "bot",
        "create",
        "--name",
        "e2e mock market buy",
        "--strategy",
        strategy_id,
        "--account",
        ACCOUNT_ID,
        "--interval",
        "10",
        "--id",
        BOT_ID,
    )
    assert created["data"]["bot_id"] == BOT_ID

    daemon.cli("treasury", "set-balance", "1000000", "--account", ACCOUNT_ID)
    daemon.cli("treasury", "allocate", BOT_ID, "500000", "--account", ACCOUNT_ID)

    started = daemon.cli("bot", "start", BOT_ID)
    assert started["data"]["bot"]["status"] == "running"
    assert started["data"]["bot"]["trading_mode"] == "virtual"

    fills = _wait_for_fills(daemon, len(EXPECTED_FILLS))
    assert fills["total"] == len(EXPECTED_FILLS), fills
    projected = {(i["description"], i["amount"]) for i in fills["items"]}
    assert projected == EXPECTED_FILLS

    trades = daemon.cli("trade", "list", "--bot", BOT_ID)["data"]["trades"]
    recorded = {(t["side"], t["symbol"], t["quantity"], t["price"]) for t in trades}
    assert recorded == EXPECTED_TRADES, trades
    assert {t["status"] for t in trades} == {"filled"}

    positions = daemon.cli("bot", "positions", BOT_ID)["data"]["positions"]
    held = [(p["symbol"], float(p["quantity"])) for p in positions]
    assert held == [(SYMBOL, EXPECTED_POSITION_QUANTITY)], positions

    stopped = daemon.cli("bot", "stop", BOT_ID)
    assert stopped["data"]["bot"]["status"] == "stopped", stopped

    assert daemon.stop() == 0
    assert not daemon.socket_path.exists()
    assert not daemon.pid_path.exists()

    unexpected = [
        a for a in daemon.net_attempts() if UPDATE_CHECKER_MODULE not in a["modules"]
    ]
    assert unexpected == []
