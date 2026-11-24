"""실행 중인 봇에 결재로 전략을 배정하면 다음 주문이 새 전략의 것이다 (#2838).

전략 A는 첫 스텝에 한 주를, 전략 B는 두 주를 산다. 귀속 ``strategy_id``는
옛 코드가 낸 주문에도 새 id로 찍혀 판별력이 없으므로 체결 수량으로 가른다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.e2e.harness import DaemonHarness, wait_until

STRATEGIES = Path(__file__).resolve().parent / "strategies"
BOT_ID = "e2e-switch"
FILL_SECONDS = 30.0
UPDATE_CHECKER_MODULE = "ante.update.checker"


def _submit(daemon: DaemonHarness, filename: str) -> str:
    submitted = daemon.cli("strategy", "submit", str(STRATEGIES / filename))
    assert submitted["data"]["submitted"] is True
    return str(submitted["data"]["strategy_id"])


def _quantities(daemon: DaemonHarness) -> list[float]:
    trades: list[dict[str, Any]] = daemon.cli("trade", "list", "--bot", BOT_ID)["data"][
        "trades"
    ]
    filled = [t for t in trades if t["status"] == "filled"]
    return sorted(float(t["quantity"]) for t in filled)


def _wait_quantities(daemon: DaemonHarness, count: int) -> list[float]:
    return wait_until(
        lambda: _quantities(daemon), lambda q: len(q) >= count, seconds=FILL_SECONDS
    )


def test_assign_and_update_switch_running_code(daemon: DaemonHarness) -> None:
    daemon.init()
    one = _submit(daemon, "market_buy.py")
    two = _submit(daemon, "market_buy_two.py")
    daemon.start()
    assert daemon.daemon_pid in daemon.guarded_pids()
    adopted = daemon.cli("strategy", "set-status", two, "--status", "adopted")
    assert adopted["data"]["status"] == "adopted"

    daemon.cli(
        "bot",
        "create",
        "--name",
        "e2e switch",
        "--strategy",
        one,
        "--account",
        "test",
        "--interval",
        "10",
        "--id",
        BOT_ID,
    )
    daemon.cli("treasury", "set-balance", "1000000", "--account", "test")
    daemon.cli("treasury", "allocate", BOT_ID, "500000", "--account", "test")
    started = daemon.cli("bot", "start", BOT_ID)
    assert started["data"]["bot"]["status"] == "running"
    assert _wait_quantities(daemon, 1) == [1.0]

    requested = daemon.cli(
        "approval",
        "request",
        "--type",
        "bot_assign_strategy",
        "--title",
        "e2e assign",
        "--params",
        f'{{"bot_id": "{BOT_ID}", "strategy_id": "{two}"}}',
    )
    approval_id = str(requested["data"]["id"])
    daemon.cli("approval", "approve", approval_id)

    assert _wait_quantities(daemon, 2) == [1.0, 2.0]
    info = daemon.cli("bot", "info", BOT_ID)["data"]
    assert info["status"] == "running"
    assert info["strategy_id"] == two

    stopped = daemon.cli("bot", "stop", BOT_ID)
    assert stopped["data"]["bot"]["status"] == "stopped"
    daemon.cli("bot", "update", BOT_ID, "--strategy", one)
    restarted = daemon.cli("bot", "start", BOT_ID)
    assert restarted["data"]["bot"]["status"] == "running"

    assert _wait_quantities(daemon, 3) == [1.0, 1.0, 2.0]

    daemon.cli("bot", "stop", BOT_ID)
    assert daemon.stop() == 0

    unexpected = [
        a for a in daemon.net_attempts() if UPDATE_CHECKER_MODULE not in a["modules"]
    ]
    assert unexpected == []
