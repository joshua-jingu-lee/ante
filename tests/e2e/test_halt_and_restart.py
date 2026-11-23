"""킬 스위치로 계좌를 정지·해제하는 시나리오와 데몬 재시작 뒤 자금 상태의 보존."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.e2e.harness import DaemonHarness, run_json_command, wait_until

STRATEGY_PATH = Path(__file__).resolve().parent / "strategies" / "limit_buy_once.py"
BOT_ID = "e2e-lifecycle"
ACCOUNT_BALANCE = 1000000
ALLOCATION = 500000
STATE_SECONDS = 10.0
HOLD_SECONDS = 2.5
FILL_SECONDS = 30.0
UPDATE_CHECKER_MODULE = "ante.update.checker"
BUDGET_FIELDS = ("allocated", "available", "reserved", "spent", "returned")
TREASURY_FIELDS = (
    "account_balance",
    "total_allocated",
    "total_reserved",
    "total_available",
    "unallocated",
    "bot_count",
)


def _start_bot(daemon: DaemonHarness) -> None:
    daemon.init()
    submitted = daemon.cli("strategy", "submit", str(STRATEGY_PATH))
    strategy_id = submitted["data"]["strategy_id"]
    daemon.start()
    daemon.cli(
        "bot",
        "create",
        "--name",
        "e2e lifecycle",
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
    daemon.cli("treasury", "allocate", BOT_ID, str(ALLOCATION), "--account", "test")
    started = daemon.cli("bot", "start", BOT_ID)
    assert started["data"]["bot"]["status"] == "running"


def _account_status(daemon: DaemonHarness) -> str:
    return str(daemon.cli("account", "info", "test")["data"]["status"])


def _bot_status(daemon: DaemonHarness) -> str:
    return str(daemon.cli("bot", "info", BOT_ID)["data"]["status"])


def _stop_and_check_network(daemon: DaemonHarness) -> None:
    assert daemon.stop() == 0
    unexpected = [
        a for a in daemon.net_attempts() if UPDATE_CHECKER_MODULE not in a["modules"]
    ]
    assert unexpected == []


def test_halt_stops_bot_and_clear_halt_leaves_it_stopped(
    daemon: DaemonHarness,
) -> None:
    _start_bot(daemon)
    assert _account_status(daemon) == "active"

    halted = daemon.cli("system", "halt", "--reason", "e2e")["data"]
    assert halted["status"] == "halted"
    assert [(a["account_id"], a["status"]) for a in halted["accounts"]] == [
        ("test", "suspended")
    ]
    assert _account_status(daemon) == "suspended"
    status = wait_until(
        lambda: _bot_status(daemon), lambda s: s == "stopped", seconds=STATE_SECONDS
    )
    assert status == "stopped"

    cleared = daemon.cli("system", "clear-halt", "--reason", "e2e")["data"]
    assert cleared["status"] == "halt_cleared"
    assert [(a["account_id"], a["status"]) for a in cleared["accounts"]] == [
        ("test", "active")
    ]
    assert _account_status(daemon) == "active"
    held = wait_until(
        lambda: _bot_status(daemon), lambda s: s != "stopped", seconds=HOLD_SECONDS
    )
    assert held == "stopped"

    restarted = daemon.cli("bot", "start", BOT_ID)
    assert restarted["data"]["bot"]["status"] == "running"
    assert _bot_status(daemon) == "running"

    stopped = daemon.cli("bot", "stop", BOT_ID)
    assert stopped["data"]["bot"]["status"] == "stopped"
    _stop_and_check_network(daemon)


def _funds(daemon: DaemonHarness) -> dict[str, Any]:
    budgets = daemon.cli("treasury", "budgets", "--account", "test")
    (budget,) = [b for b in budgets["data"]["budgets"] if b["bot_id"] == BOT_ID]
    status = daemon.cli("treasury", "status", "--account", "test")["data"]
    ledger = daemon.cli("treasury", "transactions", "--bot", BOT_ID)["data"]
    return {
        "budget": {k: budget[k] for k in BUDGET_FIELDS},
        "treasury": {k: status[k] for k in TREASURY_FIELDS},
        "ledger_total": ledger["total"],
        "ledger": sorted(ledger["items"], key=lambda i: i["id"]),
    }


def test_restart_preserves_budget_and_ledger(daemon: DaemonHarness) -> None:
    _start_bot(daemon)
    fills = wait_until(
        lambda: daemon.cli(
            "treasury", "transactions", "--bot", BOT_ID, "--type", "fill"
        )["data"],
        lambda p: p["total"] >= 1,
        seconds=FILL_SECONDS,
    )
    assert fills["total"] == 1, fills
    stopped = daemon.cli("bot", "stop", BOT_ID)
    assert stopped["data"]["bot"]["status"] == "stopped"
    bot_before = daemon.cli("bot", "info", BOT_ID)["data"]
    before = _funds(daemon)
    assert before["budget"]["reserved"] == 0
    assert before["budget"]["spent"] > 0
    assert sorted(i["type"] for i in before["ledger"]) == ["allocate", "fill"]

    old_pid = daemon.daemon_pid
    daemon.restart()
    assert daemon.daemon_pid != old_pid
    assert daemon.daemon_pid in daemon.guarded_pids()

    after = _funds(daemon)
    assert after == before
    assert after["budget"]["reserved"] == 0
    assert after["treasury"]["total_reserved"] == 0
    _assert_bot_restored(daemon, bot_before)
    _stop_and_check_network(daemon)


def _assert_bot_restored(daemon: DaemonHarness, before: dict[str, Any]) -> None:
    restored = daemon.cli("bot", "info", BOT_ID)["data"]
    assert restored["status"] == "created"
    for key in ("strategy_id", "account_id", "name", "config"):
        assert restored[key] == before[key], key
    listed = daemon.cli("bot", "list")["data"]["bots"]
    assert [b["bot_id"] for b in listed] == [BOT_ID]
    duplicate = run_json_command(
        daemon.cli_argv(
            "bot",
            "create",
            "--name",
            "dup",
            "--strategy",
            before["strategy_id"],
            "--account",
            "test",
            "--id",
            BOT_ID,
        ),
        env=daemon.env(),
        cwd=daemon.work_dir,
        expect_failure=True,
    )
    assert duplicate.payload["code"] == "BOT_ALREADY_EXISTS"
