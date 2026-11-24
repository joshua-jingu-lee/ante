"""#3002 저장된 계좌 규칙이 깨져 있으면 규칙 로드가 기본 규칙으로 가지 않는다."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.account.models import Account, TradingMode
from ante.account.readiness import ALL_FLAGS, RuntimeReadinessRegistry, is_flag_exempt
from ante.config.dynamic import DynamicConfigService
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.rule.config_update import update_account_rule_config
from ante.rule.manager import RuleEngineManager
from tests.unit._readiness_gate_helpers import make_account

BROKEN_VALUES = [
    '"off"',
    "{}",
    "null",
    "{",
    '[{"type":"daily_loss_limit","x":NaN}]',
]


def _registry(accounts: list[Account]) -> RuntimeReadinessRegistry:
    reg = RuntimeReadinessRegistry()
    for account in accounts:
        for flag in ALL_FLAGS:
            if is_flag_exempt(
                flag,
                broker_type=account.broker_type,
                trading_mode=account.trading_mode,
            ):
                continue
            reg.mark_ready(account.account_id, flag)
    return reg


def _account_service(accounts: list[Account]) -> MagicMock:
    by_id = {a.account_id: a for a in accounts}
    svc = MagicMock()
    svc.get = AsyncMock(side_effect=lambda account_id: by_id[account_id])
    return svc


def _request(account_id: str, *, side: str = "buy", reason: str = "") -> Any:
    return OrderRequestEvent(
        account_id=account_id,
        bot_id="bot1",
        strategy_id="s1",
        symbol="005930",
        side=side,
        quantity=1.0,
        order_type="limit",
        price=50000.0,
        reason=reason,
    )


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "t.db"))
    await database.connect()
    yield database
    await database.close()


async def _setup(db: Database, broken: str | None):
    bus = EventBus()
    accounts = [
        make_account("acc1", broker_type="test", trading_mode=TradingMode.VIRTUAL),
        make_account("acc2", broker_type="test", trading_mode=TradingMode.VIRTUAL),
    ]
    account_service = _account_service(accounts)
    dyn = DynamicConfigService(db, bus)
    await dyn.initialize()
    for account in accounts:
        await update_account_rule_config(
            account_service=account_service,
            dynamic_config=dyn,
            account_id=account.account_id,
            rule_type="daily_loss_limit",
            params={"max_daily_loss_percent": 0.03},
            changed_by="test",
        )
    if broken is not None:
        await db.execute(
            "UPDATE dynamic_config SET value=? WHERE key=?",
            (broken, "accounts.acc1.rules"),
        )
    manager = RuleEngineManager(
        eventbus=bus,
        account_service=account_service,
        runtime_readiness=_registry(accounts),
    )
    await manager.initialize_all(accounts, dynamic_config=dyn)
    return bus, manager, dyn, account_service


@pytest.mark.parametrize("broken", BROKEN_VALUES)
async def test_broken_value_blocks_orders_of_that_account(db, broken: str) -> None:
    bus, _manager, _dyn, _svc = await _setup(db, broken)
    validated: list[OrderValidatedEvent] = []
    rejected: list[OrderRejectedEvent] = []
    bus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
    bus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

    await bus.publish(_request("acc1"))

    assert validated == []
    assert len(rejected) == 1
    assert "rules_unavailable" in rejected[0].reason


@pytest.mark.parametrize("broken", BROKEN_VALUES)
async def test_rule_update_overwrites_broken_value(db, broken: str) -> None:
    _bus, _manager, dyn, account_service = await _setup(db, broken)

    await update_account_rule_config(
        account_service=account_service,
        dynamic_config=dyn,
        account_id="acc1",
        rule_type="daily_loss_limit",
        params={"max_daily_loss_percent": 0.03},
        changed_by="test",
    )

    stored = await dyn.get("accounts.acc1.rules")
    assert isinstance(stored, list)
