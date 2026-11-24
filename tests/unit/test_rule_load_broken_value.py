"""#3002 저장된 계좌 규칙이 깨져 있으면 규칙 로드가 기본 규칙으로 가지 않는다."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.account.models import Account, TradingMode
from ante.account.readiness import ALL_FLAGS, RuntimeReadinessRegistry, is_flag_exempt
from ante.config.dynamic import DynamicConfigService
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    ConfigChangedEvent,
    NotificationEvent,
    OrderModifyEvent,
    OrderModifyRejectedEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.main import _notify_rules_unavailable
from ante.rule.config_update import update_account_rule_config
from ante.rule.defaults import resolve_effective_rules
from ante.rule.manager import RuleEngineManager
from tests.unit._readiness_gate_helpers import make_account

KEY1 = "accounts.acc1.rules"
BROKEN_VALUES = [
    pytest.param('"off"', "not_list", id="string"),
    pytest.param("{}", "not_list", id="dict"),
    pytest.param("null", "not_list", id="null"),
    pytest.param("{", "read_error", id="unparsable"),
    pytest.param('[{"type":"daily_loss_limit","x":NaN}]', "read_error", id="nan"),
]
RULE_PARAMS = {"max_daily_loss_percent": 0.03}


class _Captured:
    def __init__(self, bus: EventBus) -> None:
        self.validated: list[OrderValidatedEvent] = []
        self.rejected: list[OrderRejectedEvent] = []
        self.modify_rejected: list[OrderModifyRejectedEvent] = []
        self.notifications: list[NotificationEvent] = []
        bus.subscribe(OrderValidatedEvent, self.validated.append)
        bus.subscribe(OrderRejectedEvent, self.rejected.append)
        bus.subscribe(OrderModifyRejectedEvent, self.modify_rejected.append)
        bus.subscribe(NotificationEvent, self.notifications.append)

    def rules_rejections(self, account_id: str) -> list[OrderRejectedEvent]:
        return [
            e
            for e in self.rejected
            if e.account_id == account_id and "rules_unavailable" in e.reason
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


def _modify(account_id: str) -> OrderModifyEvent:
    return OrderModifyEvent(
        account_id=account_id,
        bot_id="bot1",
        strategy_id="s1",
        order_id="ord-1",
        symbol="005930",
        side="buy",
        quantity=1.0,
        price=50000.0,
    )


class _StaticSeed:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "t.db"))
    await database.connect()
    yield database
    await database.close()


class _World:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.bus = EventBus()
        self.accounts = [
            make_account("acc1", broker_type="test", trading_mode=TradingMode.VIRTUAL),
            make_account("acc2", broker_type="test", trading_mode=TradingMode.VIRTUAL),
        ]
        self.account_service = _account_service(self.accounts)
        self.dyn = DynamicConfigService(db, self.bus)
        self.manager: RuleEngineManager | None = None

    async def store_rules(self) -> None:
        await self.dyn.initialize()
        for account in self.accounts:
            await self.update(account.account_id)

    async def update(self, account_id: str) -> None:
        await update_account_rule_config(
            account_service=self.account_service,
            dynamic_config=self.dyn,
            account_id=account_id,
            rule_type="daily_loss_limit",
            params=dict(RULE_PARAMS),
            changed_by="test",
        )

    async def break_acc1(self, raw: str) -> None:
        await self.db.execute(
            "UPDATE dynamic_config SET value=? WHERE key=?", (raw, KEY1)
        )

    async def start(self, config: Any = None) -> RuleEngineManager:
        manager = RuleEngineManager(
            eventbus=self.bus,
            account_service=self.account_service,
            runtime_readiness=_registry(self.accounts),
        )
        await manager.initialize_all(
            self.accounts, config=config, dynamic_config=self.dyn
        )
        self.manager = manager
        return manager


async def _broken_world(db: Database, raw: str, config: Any = None) -> _World:
    world = _World(db)
    await world.store_rules()
    await world.break_acc1(raw)
    await world.start(config)
    return world


def _rule_types(engine: Any) -> list[Any]:
    return [rule.config.get("type") for rule in engine._account_rules]


@pytest.mark.parametrize(("broken", "cause"), BROKEN_VALUES)
async def test_broken_value_blocks_orders_of_that_account(
    db, caplog, broken: str, cause: str
) -> None:
    caplog.set_level(logging.INFO)
    seed = _StaticSeed({KEY1: [{"type": "daily_loss_limit", **RULE_PARAMS}]})
    world = await _broken_world(db, broken, config=seed)
    manager = world.manager
    assert manager is not None
    cap = _Captured(world.bus)

    acc1 = manager.get("acc1")
    acc2 = manager.get("acc2")
    assert acc1.rules_unavailable is True
    assert acc1.rules_unavailable_cause == cause
    assert acc1._account_rules == []
    assert acc2.rules_unavailable is False
    assert _rule_types(acc2) == ["daily_loss_limit"]
    assert manager.rules_unavailable_accounts() == {"acc1": cause}

    errors = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and r.name == "ante.rule.manager"
    ]
    assert len(errors) == 1
    assert "acc1" in errors[0].getMessage()
    assert cause in errors[0].getMessage()
    assert "off" not in caplog.text

    await world.bus.publish(_request("acc1"))

    assert cap.validated == []
    assert len(cap.rejected) == 1
    assert "rules_unavailable" in cap.rejected[0].reason
    assert len(cap.notifications) == 1
    assert cap.notifications[0].level == "error"
    assert "rules_unavailable" in cap.notifications[0].message

    await world.bus.publish(_request("acc2"))
    assert cap.rules_rejections("acc2") == []


async def test_liquidation_sell_is_blocked_with_liquidation_alert(db) -> None:
    world = await _broken_world(db, '"off"')
    cap = _Captured(world.bus)

    await world.bus.publish(_request("acc1", side="sell", reason="liquidation:bot"))

    assert cap.validated == []
    assert len(cap.rules_rejections("acc1")) == 1
    assert len(cap.notifications) == 1
    assert cap.notifications[0].title.startswith("청산 차단")
    assert "rules_unavailable" in cap.notifications[0].message


async def test_modify_is_rejected_and_consumed(db) -> None:
    world = await _broken_world(db, '"off"')
    cap = _Captured(world.bus)

    blocked = _modify("acc1")
    await world.bus.publish(blocked)
    assert len(cap.modify_rejected) == 1
    assert "rules_unavailable" in cap.modify_rejected[0].reason
    assert getattr(blocked, "_consumed", False) is True

    normal = _modify("acc2")
    await world.bus.publish(normal)
    assert all(e.account_id != "acc2" for e in cap.modify_rejected)
    assert getattr(normal, "_consumed", False) is False


async def test_absent_row_keeps_defaults(db) -> None:
    bus = EventBus()
    accounts = [
        make_account("kis", broker_type="kis-domestic"),
        make_account("plain", broker_type="test", trading_mode=TradingMode.VIRTUAL),
    ]
    dyn = DynamicConfigService(db, bus)
    await dyn.initialize()
    manager = RuleEngineManager(eventbus=bus, account_service=MagicMock())
    await manager.initialize_all(accounts, dynamic_config=dyn)

    assert _rule_types(manager.get("kis")) == ["trading_hours"]
    assert _rule_types(manager.get("plain")) == []
    assert manager.rules_unavailable_accounts() == {}


def test_kis_domestic_default_is_trading_hours_only() -> None:
    account = make_account("kis", broker_type="kis-domestic")
    assert [r["type"] for r in resolve_effective_rules(account, None)] == [
        "trading_hours"
    ]


@pytest.mark.parametrize(("broken", "cause"), BROKEN_VALUES)
async def test_rule_update_releases_the_block(
    db, caplog, broken: str, cause: str
) -> None:
    world = await _broken_world(db, broken)
    manager = world.manager
    assert manager is not None
    cap = _Captured(world.bus)
    caplog.set_level(logging.INFO, logger="ante.rule.engine")

    await world.update("acc1")

    stored = await world.dyn.get(KEY1)
    assert isinstance(stored, list)
    row = await db.fetch_one("SELECT category FROM dynamic_config WHERE key=?", (KEY1,))
    assert row is not None
    assert row["category"] == "rule"
    engine = manager.get("acc1")
    assert engine.rules_unavailable is False
    assert _rule_types(engine) == ["daily_loss_limit"]
    released = [r for r in caplog.records if "해제" in r.getMessage()]
    assert len(released) == 1
    assert "daily_loss_limit" in released[0].getMessage()

    await world.bus.publish(_request("acc1"))
    assert cap.rules_rejections("acc1") == []

    fresh = await world.start()
    assert fresh.rules_unavailable_accounts() == {}
    assert _rule_types(fresh.get("acc1")) == ["daily_loss_limit"]


def _changed(category: str, key: str, value: Any) -> ConfigChangedEvent:
    return ConfigChangedEvent(category=category, key=key, new_value=json.dumps(value))


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(_changed("rule", KEY1, "off"), id="not_list"),
        pytest.param(_changed("rule", KEY1, {"type": "x"}), id="dict"),
        pytest.param(
            _changed("rule", "accounts.acc2.rules", [{"type": "daily_loss_limit"}]),
            id="other_key",
        ),
        pytest.param(
            _changed("global_rule", KEY1, [{"type": "daily_loss_limit"}]),
            id="global_rule",
        ),
    ],
)
async def test_other_changes_do_not_release(db, event: ConfigChangedEvent) -> None:
    world = await _broken_world(db, '"off"')
    manager = world.manager
    assert manager is not None

    await world.bus.publish(event)

    assert manager.get("acc1").rules_unavailable is True


async def test_failed_reload_does_not_release(db, monkeypatch) -> None:
    world = await _broken_world(db, '"off"')
    manager = world.manager
    assert manager is not None
    engine = manager.get("acc1")

    def _boom(_configs: Any) -> None:
        raise RuntimeError("reload failed")

    monkeypatch.setattr(engine, "load_rules_from_config", _boom)
    with pytest.raises(RuntimeError):
        await engine._on_config_changed(
            _changed("rule", KEY1, [{"type": "daily_loss_limit", **RULE_PARAMS}])
        )

    assert engine.rules_unavailable is True


def _services(manager: Any, bus: EventBus | None) -> Any:
    return SimpleNamespace(rule_engine_manager=manager, eventbus=bus)


@pytest.mark.parametrize(
    ("broken", "cause", "phrase"),
    [
        ('"off"', "not_list", "규칙 목록 형식이 아니어서"),
        ("{", "read_error", "재기동으로 풀릴 수 있습니다"),
    ],
)
async def test_startup_notification_per_blocked_account(
    db, broken: str, cause: str, phrase: str
) -> None:
    world = await _broken_world(db, broken)
    cap = _Captured(world.bus)

    await _notify_rules_unavailable(_services(world.manager, world.bus))

    assert len(cap.notifications) == 1
    note = cap.notifications[0]
    assert note.level == "error"
    assert note.category == "system"
    assert note.title == "계좌 규칙을 읽지 못함 — 주문 차단"
    assert "acc1" in note.message
    assert phrase in note.message
    assert "ante config history accounts.acc1.rules" in note.message
    assert broken not in note.message


async def test_startup_notification_none_when_nothing_blocked(db) -> None:
    world = _World(db)
    await world.store_rules()
    manager = await world.start()
    cap = _Captured(world.bus)

    await _notify_rules_unavailable(_services(manager, world.bus))
    await _notify_rules_unavailable(_services(None, world.bus))

    assert cap.notifications == []
