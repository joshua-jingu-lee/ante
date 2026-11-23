"""배정·교체 결재가 전략의 채택 상태를 두 단계에서 확인하는지 고정한다.

실제 DB, 실제 ``StrategyRegistry``·``BotManager``, ``main._init_approval``로
조립한 실제 ``ApprovalService``를 쓴다.

Refs #2582
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ante.approval import ApprovalValidationError
from ante.bot import BotConfig, BotManager, BotStatus
from ante.core import Database
from ante.eventbus import EventBus
from ante.main import Services, _init_approval
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Strategy,
    StrategyContext,
    StrategyMeta,
)
from ante.strategy.registry import StrategyRegistry, StrategyStatus

GHOST = "ghost_v9.9.9"
REGISTERED = "registered_only_v1.0.0"
ADOPTED = "adopted_one_v1.0.0"
ORIGINAL = "original"


class _FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        import polars as pl

        return pl.DataFrame({"close": [100.0]})

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class _FakePortfolioView(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1000000.0, "available": 500000.0}


class _FakeOrderView(OrderView):
    def get_open_orders(self, bot_id):
        return []


class _SimpleStrategy(Strategy):
    meta = StrategyMeta(name="simple", version="1.0.0", description="test")

    async def on_step(self, context):
        return []


@dataclass
class _Env:
    s: Services
    db: Database
    registry: StrategyRegistry
    manager: BotManager


async def _register(registry: StrategyRegistry, tmp_path: Path, name: str) -> str:
    path = tmp_path / f"{name}.py"
    path.write_text("# strategy\n", encoding="utf-8")
    record = await registry.register(
        path, StrategyMeta(name=name, version="1.0.0", description="t")
    )
    return record.strategy_id


@pytest.fixture
async def env(tmp_path):
    db = Database(str(tmp_path / "ante.db"))
    await db.connect()
    eventbus = EventBus()
    registry = StrategyRegistry(db)
    await registry.initialize()
    manager = BotManager(eventbus=eventbus, db=db)
    await manager.initialize()

    assert await _register(registry, tmp_path, "registered_only") == REGISTERED
    assert await _register(registry, tmp_path, "adopted_one") == ADOPTED
    await registry.update_status(ADOPTED, StrategyStatus.ADOPTED)

    ctx = StrategyContext(
        bot_id="bot1",
        data_provider=_FakeDataProvider(),
        portfolio=_FakePortfolioView(),
        order_view=_FakeOrderView(),
    )
    await manager.create_bot(
        BotConfig(
            bot_id="bot1",
            strategy_id=ORIGINAL,
            interval_seconds=999,
            account_id="acc-test",
        ),
        _SimpleStrategy,
        ctx,
    )

    s = Services(
        config={"approval.auto_approve": {}},
        db=db,
        eventbus=eventbus,
        strategy_registry=registry,
        bot_manager=manager,
    )
    await _init_approval(s)
    try:
        yield _Env(s=s, db=db, registry=registry, manager=manager)
    finally:
        task = s.approval_expire_task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for bot in list(manager._bots.values()):
            if bot._task and not bot._task.done():
                bot._task.cancel()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(manager.stop_all(), timeout=5.0)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(db.close(), timeout=5.0)


async def _stop_bot1(env: _Env) -> None:
    await env.manager.start_bot("bot1")
    await env.manager.stop_bot("bot1")
    assert env.manager.get_bot("bot1").status == BotStatus.STOPPED


async def _create(env: _Env, type_: str, strategy_id: str) -> Any:
    return await env.s.approval_service.create(
        type=type_,
        requester="agent",
        title="t",
        params={"bot_id": "bot1", "strategy_id": strategy_id},
    )


async def _db_strategy(env: _Env) -> tuple[str, str]:
    row = await env.db.fetch_one(
        "SELECT strategy_id, config_json FROM bots WHERE bot_id = 'bot1'"
    )
    assert row is not None
    return row["strategy_id"], json.loads(row["config_json"])["strategy_id"]


async def _assert_unchanged(env: _Env) -> None:
    assert env.manager.get_bot("bot1").config.strategy_id == ORIGINAL
    assert await _db_strategy(env) == (ORIGINAL, ORIGINAL)


TYPES = ["bot_assign_strategy", "bot_change_strategy"]


@pytest.mark.parametrize("type_", TYPES)
async def test_missing_strategy_fails_validation(env, type_):
    """(a)·(e) 존재하지 않는 전략은 사전 검증에서 막힌다."""
    if type_ == "bot_change_strategy":
        await _stop_bot1(env)
    with pytest.raises(ApprovalValidationError) as exc_info:
        await _create(env, type_, GHOST)
    assert str(exc_info.value) == f"전략을 찾을 수 없습니다: {GHOST}"
    await _assert_unchanged(env)


@pytest.mark.parametrize("type_", TYPES)
async def test_registered_strategy_fails_validation(env, type_):
    """(b)·(e) 등록만 된 전략은 사전 검증에서 막힌다."""
    if type_ == "bot_change_strategy":
        await _stop_bot1(env)
    with pytest.raises(ApprovalValidationError) as exc_info:
        await _create(env, type_, REGISTERED)
    assert str(exc_info.value) == f"전략이 adopted 상태가 아닙니다: {REGISTERED}"
    await _assert_unchanged(env)


@pytest.mark.parametrize("type_", TYPES)
async def test_adopted_strategy_is_assigned(env, type_):
    """(c) 채택된 전략은 승인 뒤 배정된다."""
    if type_ == "bot_change_strategy":
        await _stop_bot1(env)
    request = await _create(env, type_, ADOPTED)
    await env.s.approval_service.approve(request.id)
    stored = await env.s.approval_service.get(request.id)
    assert stored.status == "approved"
    assert [h["action"] for h in stored.history] == [
        "created",
        "approved",
        "executed",
    ]
    assert env.manager.get_bot("bot1").config.strategy_id == ADOPTED
    assert await _db_strategy(env) == (ADOPTED, ADOPTED)


@pytest.mark.parametrize("type_", TYPES)
async def test_archived_between_request_and_approval_fails_execution(env, type_):
    """(d)·(e) 요청과 승인 사이에 폐기되면 실행에서 거부된다."""
    if type_ == "bot_change_strategy":
        await _stop_bot1(env)
    request = await _create(env, type_, ADOPTED)
    await env.registry.update_status(ADOPTED, StrategyStatus.ARCHIVED)
    await env.s.approval_service.approve(request.id)
    stored = await env.s.approval_service.get(request.id)
    assert stored.status == "execution_failed"
    assert stored.history[-1]["action"] == "execution_failed"
    assert (
        stored.history[-1]["detail"]
        == f"전략이 adopted 상태가 아닙니다: {ADOPTED} (archived)"
    )
    await _assert_unchanged(env)


async def test_bot_create_with_registered_strategy_fails_validation(env):
    """(f) 대조군: bot_create는 등록만 된 전략을 같은 메시지로 거부한다."""
    with pytest.raises(ApprovalValidationError) as exc_info:
        await env.s.approval_service.create(
            type="bot_create",
            requester="agent",
            title="t",
            params={
                "config": {
                    "bot_id": "bot2",
                    "strategy_id": REGISTERED,
                    "account_id": "acc-test",
                }
            },
        )
    assert str(exc_info.value) == f"전략이 adopted 상태가 아닙니다: {REGISTERED}"
