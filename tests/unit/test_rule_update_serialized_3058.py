"""#3058 같은 계좌의 rule update 두 건이 겹쳐도 두 변경이 모두 저장된다.

실제 IPCServer와 소켓 클라이언트 둘로 보내고, 끼어드는 지점은 이벤트로 고정한다.
다른 계좌의 갱신은 잠금을 쥔 갱신을 기다리지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.ipc.client import IPCClient
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer
from tests.unit.test_rule_config_keys_2583 import KEY1, _World

DAILY = {"max_daily_loss_percent": 0.05}
EXPOSURE = {"max_exposure_percent": 0.5}


class _Gate:
    """첫 요청(A)을 저장값 읽기 직후 붙잡고, 둘째 요청(B)의 진행을 관측한다."""

    def __init__(self, world: _World) -> None:
        self.a_read = asyncio.Event()
        self.release = asyncio.Event()
        self.b_entered = asyncio.Event()
        self.b_called = asyncio.Event()
        self.b_read = asyncio.Event()
        self._tasks: list[asyncio.Task[Any] | None] = []
        self._a_gated = False
        self._b_seen = False
        real_account_get = world.account_service.get
        real_dyn_get = world.dyn.get

        async def account_get(account_id: str) -> Any:
            result = await real_account_get(account_id)
            self._tasks.append(asyncio.current_task())
            if len(self._tasks) == 2:
                self.b_entered.set()
            return result

        async def dyn_get(key: str, *args: Any) -> Any:
            task = asyncio.current_task()
            is_b = len(self._tasks) >= 2 and task is self._tasks[1]
            first_b = is_b and not self._b_seen
            if first_b:
                self._b_seen = True
                self.b_called.set()
            try:
                return await real_dyn_get(key, *args)
            finally:
                if first_b:
                    self.b_read.set()
                if self._tasks and task is self._tasks[0] and not self._a_gated:
                    self._a_gated = True
                    self.a_read.set()
                    await self.release.wait()

        world.account_service.get = account_get
        world.dyn.get = dyn_get  # type: ignore[method-assign]

    async def release_after_b_parks(self) -> None:
        await self.b_entered.wait()
        if self.b_called.is_set():
            await self.b_read.wait()
        self.release.set()


@pytest.fixture
async def world(tmp_path: Path):
    database = Database(str(tmp_path / "t.db"))
    await database.connect()
    w = _World(database)
    await w.dyn.initialize()
    yield w
    await database.close()


@pytest.fixture
async def client(world: _World):
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    svc_registry = ServiceRegistry(
        account=world.account_service,
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=world.dyn,
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=world.bus,
        audit_logger=MagicMock(log=AsyncMock()),
        config=None,
    )
    socket_dir = tempfile.mkdtemp(prefix="ipc3058", dir="/tmp")
    socket_path = str(Path(socket_dir) / "t.sock")
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        yield IPCClient(socket_path, timeout=10)
    finally:
        await server.stop()


def _send(
    client: IPCClient, rule_type: str, params: dict[str, Any], account_id: str = "acc1"
) -> asyncio.Task[dict[str, Any]]:
    args = {"account_id": account_id, "rule_type": rule_type, "params": params}
    return asyncio.create_task(client.send("rule.update", args, actor="bob"))


async def _stored(world: _World, key: str = KEY1) -> Any:
    row = await world.db.fetch_one(
        "SELECT value FROM dynamic_config WHERE key=?", (key,)
    )
    return None if row is None else json.loads(row["value"])


async def _overlap(
    world: _World,
    client: IPCClient,
    first: tuple[str, dict[str, Any]],
    second: tuple[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    gate = _Gate(world)
    a = _send(client, *first)
    await asyncio.wait_for(gate.a_read.wait(), 10)
    b = _send(client, *second)
    await asyncio.wait_for(gate.release_after_b_parks(), 10)
    return list(await asyncio.wait_for(asyncio.gather(a, b), 10))


async def test_sequential_updates_of_two_types_keep_both(
    world: _World, client: IPCClient
) -> None:
    await _send(client, "daily_loss_limit", DAILY)
    await _send(client, "total_exposure_limit", EXPOSURE)

    types = [item["type"] for item in await _stored(world)]
    assert types == ["daily_loss_limit", "total_exposure_limit"]


async def test_overlapping_updates_of_two_types_keep_both(
    world: _World, client: IPCClient
) -> None:
    await world.start()

    responses = await _overlap(
        world,
        client,
        ("daily_loss_limit", DAILY),
        ("total_exposure_limit", EXPOSURE),
    )

    assert [r["status"] for r in responses] == ["ok", "ok"], responses
    types = [item["type"] for item in await _stored(world)]
    assert types == ["daily_loss_limit", "total_exposure_limit"]
    engine_types = sorted(str(r.config["type"]) for r in world.engine()._account_rules)
    assert engine_types == ["daily_loss_limit", "total_exposure_limit"]


async def test_overlapping_updates_of_one_type_store_one_of_the_two_values(
    world: _World, client: IPCClient
) -> None:
    responses = await _overlap(
        world,
        client,
        ("daily_loss_limit", {"max_daily_loss_percent": 0.05}),
        ("daily_loss_limit", {"max_daily_loss_percent": 0.07}),
    )

    assert [r["status"] for r in responses] == ["ok", "ok"], responses
    assert await _stored(world) == [
        {"type": "daily_loss_limit", "enabled": True, "max_daily_loss_percent": 0.07}
    ]


async def test_other_account_update_does_not_wait_for_a_held_account(
    world: _World, client: IPCClient
) -> None:
    gate = _Gate(world)
    a = _send(client, "daily_loss_limit", DAILY)
    await asyncio.wait_for(gate.a_read.wait(), 10)

    other = await asyncio.wait_for(
        _send(client, "total_exposure_limit", EXPOSURE, account_id="acc2"), 5
    )

    assert other["status"] == "ok", other
    stored = await _stored(world, "accounts.acc2.rules")
    assert [item["type"] for item in stored] == ["total_exposure_limit"]
    gate.release.set()
    assert (await asyncio.wait_for(a, 10))["status"] == "ok"


async def test_failed_write_releases_the_account_for_the_next_update(
    world: _World, client: IPCClient
) -> None:
    real_set = world.dyn.set
    calls = 0

    async def failing_set(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("write failed")
        await real_set(*args, **kwargs)

    world.dyn.set = failing_set  # type: ignore[method-assign]

    failed = await _send(client, "daily_loss_limit", DAILY)
    after = await asyncio.wait_for(_send(client, "total_exposure_limit", EXPOSURE), 5)

    assert failed["status"] == "error", failed
    assert after["status"] == "ok", after
    assert [item["type"] for item in await _stored(world)] == ["total_exposure_limit"]
