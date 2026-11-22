"""실제 데몬 프로세스로 도는 e2e 시나리오."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from ante.ipc.client import IPCClient
from tests.e2e.harness import DaemonHarness, run_json_command

TEST_ACCOUNT = {"account_id": "test", "broker_type": "test", "exchange": "TEST"}
STRATEGY_PATH = Path(__file__).resolve().parent / "strategies" / "round_trip.py"
BOT_ID = "e2e-rt"
FILL_DEADLINE_SECONDS = 30.0
EXPECTED_FILLS = {
    ("buy 000001 1 @ 70,000", 70000.0),
    ("sell 000001 1 @ 71,000", 71000.0),
}
COMMISSION_RATE = 0.00015
SELL_TAX_RATE = 0.0023
EXPECTED_SPENT = 70000 + 70000 * COMMISSION_RATE
EXPECTED_RETURNED = 71000 - 71000 * (COMMISSION_RATE + SELL_TAX_RATE)
UPDATE_CHECKER_MODULE = "ante.update.checker"


def test_boot_and_stop(daemon: DaemonHarness) -> None:
    payload = daemon.init()
    assert payload["token"]
    assert payload["test_account"] == TEST_ACCOUNT

    daemon.start()
    assert daemon.daemon_pid in daemon.guarded_pids()
    accounts = daemon.cli("account", "list")
    assert "test" in {a["account_id"] for a in accounts["data"]["accounts"]}

    marker = "MARKE2E001SECRET"
    client = IPCClient(socket_path=str(daemon.socket_path))
    response = asyncio.run(client.send("system.clear_halt", {"x": marker}, "e2e"))
    assert response["status"] == "error"
    assert response["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "system.clear_halt 인자 검증 실패: x(extra_forbidden)",
    }
    assert marker not in json.dumps(response, ensure_ascii=False)

    rejected = run_json_command(
        daemon.cli_argv("bot", "start", "e2e-no-such-bot"),
        env=daemon.env(),
        cwd=daemon.work_dir,
        expect_failure=True,
    )
    assert rejected.returncode == 1
    assert rejected.payload["code"] == "BOT_NOT_FOUND"

    assert daemon.stop() == 0
    assert not daemon.socket_path.exists()
    assert not daemon.pid_path.exists()


def _wait_for_fills(daemon: DaemonHarness, count: int) -> dict[str, Any]:
    deadline = time.monotonic() + FILL_DEADLINE_SECONDS
    while True:
        payload = daemon.cli(
            "treasury", "transactions", "--bot", BOT_ID, "--type", "fill"
        )
        if payload["total"] >= count or time.monotonic() >= deadline:
            return payload
        time.sleep(0.5)


def test_virtual_round_trip(daemon: DaemonHarness) -> None:
    payload = daemon.init()
    assert payload["token"]
    assert payload["test_account"]["account_id"] == "test"

    validated = daemon.cli("strategy", "validate", str(STRATEGY_PATH))
    assert validated["data"]["valid"] is True
    assert validated["data"]["errors"] == []

    submitted = daemon.cli("strategy", "submit", str(STRATEGY_PATH))
    assert submitted["submitted"] is True
    strategy_id = submitted["strategy_id"]
    assert strategy_id

    daemon.start()
    assert daemon.daemon_pid in daemon.guarded_pids()

    created = daemon.cli(
        "bot",
        "create",
        "--name",
        "e2e round trip",
        "--strategy",
        strategy_id,
        "--account",
        "test",
        "--interval",
        "10",
        "--id",
        BOT_ID,
    )
    assert created["data"]["bot_id"] == BOT_ID

    daemon.cli("treasury", "set-balance", "1000000", "--account", "test")
    daemon.cli("treasury", "allocate", BOT_ID, "500000", "--account", "test")

    started = daemon.cli("bot", "start", BOT_ID)
    assert started["data"]["bot"]["status"] == "running"
    assert started["data"]["bot"]["trading_mode"] == "virtual"

    fills = _wait_for_fills(daemon, len(EXPECTED_FILLS))
    assert fills["total"] == len(EXPECTED_FILLS), fills
    projected = {(i["description"], i["amount"]) for i in fills["items"]}
    assert projected == EXPECTED_FILLS

    budgets = daemon.cli("treasury", "budgets", "--account", "test")
    (budget,) = [b for b in budgets["budgets"] if b["bot_id"] == BOT_ID]
    assert budget["spent"] == pytest.approx(EXPECTED_SPENT, abs=1e-6)
    assert budget["returned"] == pytest.approx(EXPECTED_RETURNED, abs=1e-6)

    stopped = daemon.cli("bot", "stop", BOT_ID)
    assert stopped["data"]["bot"]["status"] == "stopped", stopped

    assert daemon.stop() == 0
    assert not daemon.socket_path.exists()
    assert not daemon.pid_path.exists()

    unexpected = [
        a for a in daemon.net_attempts() if UPDATE_CHECKER_MODULE not in a["modules"]
    ]
    assert unexpected == []
