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


BROKEN_ITEMS = [
    pytest.param(
        [{"type": "total_exposure_limit"}, 5, {"type": "daily_loss_limit"}],
        id="non_dict_item",
    ),
    pytest.param(
        [
            {"type": "daily_loss_limit", "priority": "1"},
            {"type": "total_exposure_limit", "priority": 2},
        ],
        id="str_priority",
    ),
    pytest.param(
        [
            {"type": "daily_loss_limit", "priority": None},
            {"type": "total_exposure_limit", "priority": 2},
        ],
        id="null_priority",
    ),
    pytest.param([{"type": ["x"]}], id="unhashable_type"),
]
RELOAD_FAILED_TITLE = "계좌 규칙을 다시 읽지 못함 — 이전 규칙 유지"


def _assert_reload_failed_notice(cap: _Captured, value: list[Any]) -> None:
    assert len(cap.notifications) == 1
    note = cap.notifications[0]
    assert note.level == "error"
    assert note.category == "system"
    assert note.title == RELOAD_FAILED_TITLE
    assert "acc1" in note.message
    assert json.dumps(value) not in note.message
    for item in value:
        if not isinstance(item, int):
            assert json.dumps(item) not in note.message
            assert str(item) not in note.message


async def _normal_world(db: Database, config: Any = None) -> _World:
    world = _World(db)
    await world.store_rules()
    await world.start(config)
    return world


@pytest.mark.parametrize("value", BROKEN_ITEMS)
async def test_failed_reload_keeps_previous_rules(db, value: list[Any]) -> None:
    world = await _normal_world(db)
    manager = world.manager
    assert manager is not None
    engine = manager.get("acc1")
    before = list(engine._account_rules)
    assert _rule_types(engine) == ["daily_loss_limit"]
    cap = _Captured(world.bus)

    await engine._on_config_changed(_changed("rule", KEY1, value))

    assert len(engine._account_rules) == len(before)
    assert all(a is b for a, b in zip(engine._account_rules, before, strict=True))
    assert engine.rules_unavailable is False
    _assert_reload_failed_notice(cap, value)


async def test_reload_with_unknown_type_keeps_previous_rules(db) -> None:
    world = await _normal_world(db)
    manager = world.manager
    assert manager is not None
    engine = manager.get("acc1")
    before = list(engine._account_rules)
    cap = _Captured(world.bus)
    value: list[Any] = [{"type": "total_exposure_limit"}, {"type": "nope"}]

    await world.bus.publish(_changed("rule", KEY1, value))

    assert _rule_types(engine) == ["daily_loss_limit"]
    assert all(a is b for a, b in zip(engine._account_rules, before, strict=True))
    assert engine.rules_unavailable is False
    _assert_reload_failed_notice(cap, value)


@pytest.mark.parametrize("value", BROKEN_ITEMS)
async def test_failed_reload_does_not_release(db, value: list[Any]) -> None:
    world = await _broken_world(db, '"off"')
    manager = world.manager
    assert manager is not None
    engine = manager.get("acc1")
    cap = _Captured(world.bus)

    await engine._on_config_changed(_changed("rule", KEY1, value))

    assert engine.rules_unavailable_cause == "not_list"
    assert engine._account_rules == []
    _assert_reload_failed_notice(cap, value)


async def test_global_rule_list_does_not_change_account_rules(db, caplog) -> None:
    world = await _normal_world(db)
    manager = world.manager
    assert manager is not None
    caplog.set_level(logging.INFO, logger="ante.rule.engine")

    await world.bus.publish(
        _changed("global_rule", KEY1, [{"type": "total_exposure_limit"}])
    )
    await world.bus.publish(
        _changed("global_rule", "rules.global", [{"type": "total_exposure_limit"}])
    )

    assert _rule_types(manager.get("acc1")) == ["daily_loss_limit"]
    assert _rule_types(manager.get("acc2")) == ["daily_loss_limit"]
    assert [r for r in caplog.records if "재로딩" in r.getMessage()] == []


async def _item_broken_world(db: Database, value: list[Any], source: str) -> _World:
    world = _World(db)
    await world.dyn.initialize()
    if source == "dynamic":
        await world.store_rules()
        await world.break_acc1(json.dumps(value))
        await world.start()
    else:
        await world.update("acc2")
        await world.start(_StaticSeed({KEY1: value}))
    return world


@pytest.mark.parametrize("source", ["dynamic", "seed"])
@pytest.mark.parametrize("value", BROKEN_ITEMS)
async def test_broken_item_blocks_only_that_account_at_startup(
    db, caplog, value: list[Any], source: str
) -> None:
    caplog.set_level(logging.INFO)
    world = await _item_broken_world(db, value, source)
    manager = world.manager
    assert manager is not None
    cap = _Captured(world.bus)

    acc1 = manager.get("acc1")
    acc2 = manager.get("acc2")
    assert acc1.rules_unavailable_cause == "invalid_item"
    assert acc1._account_rules == []
    assert acc2.rules_unavailable is False
    assert _rule_types(acc2) == ["daily_loss_limit"]
    assert manager.rules_unavailable_accounts() == {"acc1": "invalid_item"}
    errors = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and r.name == "ante.rule.manager"
    ]
    assert len(errors) == 1
    assert "acc1" in errors[0].getMessage()
    assert "invalid_item" in errors[0].getMessage()

    await world.bus.publish(_request("acc1"))
    await world.bus.publish(_request("acc1", side="sell", reason="liquidation:bot"))
    blocked = _modify("acc1")
    await world.bus.publish(blocked)

    assert cap.validated == []
    assert len(cap.rules_rejections("acc1")) == 2
    assert len(cap.modify_rejected) == 1
    assert "rules_unavailable" in cap.modify_rejected[0].reason
    assert getattr(blocked, "_consumed", False) is True

    await world.bus.publish(_request("acc2"))
    assert cap.rules_rejections("acc2") == []


async def test_broken_item_log_names_effective_position_without_values(
    db, caplog
) -> None:
    bus = EventBus()
    account = make_account("kis", broker_type="kis-domestic")
    dyn = DynamicConfigService(db, bus)
    await dyn.initialize()
    await dyn.set(
        "accounts.kis.rules",
        [{"type": "daily_loss_limit", "max_daily_loss_percent": 0.0371}, 5],
        category="rule",
        changed_by="test",
    )
    caplog.set_level(logging.INFO, logger="ante.rule.engine")
    manager = RuleEngineManager(eventbus=bus, account_service=MagicMock())
    await manager.initialize_all([account], dynamic_config=dyn)

    assert manager.rules_unavailable_accounts() == {"kis": "invalid_item"}
    built = [r for r in caplog.records if "룰 항목을 만들지 못함" in r.getMessage()]
    assert len(built) == 1
    message = built[0].getMessage()
    assert "effective_index=2(기본 룰 병합 뒤 위치)" in message
    assert "item=int" in message
    assert "type=None" in message
    assert "0.0371" not in caplog.text


async def test_startup_notification_for_broken_item(db) -> None:
    value: list[Any] = [{"type": "daily_loss_limit"}, 5]
    world = await _item_broken_world(db, value, "dynamic")
    cap = _Captured(world.bus)

    await _notify_rules_unavailable(_services(world.manager, world.bus))

    assert len(cap.notifications) == 1
    note = cap.notifications[0]
    assert note.level == "error"
    assert note.category == "system"
    assert "acc1" in note.message
    assert "규칙으로 만들 수 없는 항목" in note.message
    assert "복원되지 않습니다" not in note.message
    assert json.dumps(value) not in note.message


async def test_rule_update_of_that_type_releases_str_priority(db) -> None:
    value = [
        {"type": "daily_loss_limit", "priority": "1"},
        {"type": "total_exposure_limit", "priority": 2},
    ]
    world = await _item_broken_world(db, value, "dynamic")
    manager = world.manager
    assert manager is not None

    await world.update("acc1")

    engine = manager.get("acc1")
    assert engine.rules_unavailable is False
    assert sorted(_rule_types(engine)) == ["daily_loss_limit", "total_exposure_limit"]


STORED_LIMIT = {"type": "daily_loss_limit", "enabled": True, **RULE_PARAMS}
DROP_LOGGER = "ante.rule.config_update"


async def _update_with_bus(world: _World) -> dict[str, Any]:
    return await update_account_rule_config(
        account_service=world.account_service,
        dynamic_config=world.dyn,
        account_id="acc1",
        rule_type="daily_loss_limit",
        params=dict(RULE_PARAMS),
        changed_by="test",
        eventbus=world.bus,
    )


def _drop_warnings(caplog: Any) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == DROP_LOGGER and r.levelno >= logging.WARNING
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(
            [{"type": "daily_loss_limit"}, 5], [STORED_LIMIT], id="non_dict_after"
        ),
        pytest.param(
            [5, {"type": "daily_loss_limit"}], [STORED_LIMIT], id="non_dict_before"
        ),
        pytest.param(
            [{"type": "total_exposure_limit"}, "x", {"type": "daily_loss_limit"}],
            [{"type": "total_exposure_limit"}, STORED_LIMIT],
            id="non_dict_between",
        ),
        pytest.param(
            [{"type": ["daily_loss_limit"]}, {"type": "daily_loss_limit"}],
            [STORED_LIMIT],
            id="list_type",
        ),
        pytest.param(
            [{"type": {"a": 1}}, {"type": "total_exposure_limit"}],
            [{"type": "total_exposure_limit"}, STORED_LIMIT],
            id="dict_type",
        ),
    ],
)
async def test_rule_update_drops_unwritable_item_and_releases(
    db, value: list[Any], expected: list[Any]
) -> None:
    world = await _item_broken_world(db, value, "dynamic")
    manager = world.manager
    assert manager is not None
    assert manager.get("acc1").rules_unavailable_cause == "invalid_item"
    cap = _Captured(world.bus)

    await world.update("acc1")

    assert await world.dyn.get(KEY1) == expected
    engine = manager.get("acc1")
    assert engine.rules_unavailable is False
    assert sorted(_rule_types(engine)) == sorted(item["type"] for item in expected)
    assert [n.title for n in cap.notifications] == []
    await world.bus.publish(_request("acc1"))
    assert cap.rules_rejections("acc1") == []

    fresh = await world.start()
    assert fresh.rules_unavailable_accounts() == {}


async def test_dropped_item_is_logged_once_without_values(db, caplog) -> None:
    value: list[Any] = [
        {"type": "daily_loss_limit", "max_daily_loss_percent": 0.0371},
        9876543,
        {"type": ["x", "7.0371"]},
    ]
    world = await _item_broken_world(db, value, "dynamic")
    cap = _Captured(world.bus)
    caplog.set_level(logging.INFO)

    await _update_with_bus(world)

    warnings = _drop_warnings(caplog)
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "acc1" in message
    assert "stored_index=1" in message
    assert "stored_index=2" in message
    assert "item=int" in message
    assert "item=dict" in message
    assert "type=list" in message
    for marker in ("9876543", "7.0371", "0.0371"):
        assert marker not in caplog.text
    dropped = [n for n in cap.notifications if n.category == "system"]
    assert len(dropped) == 1
    note = dropped[0]
    assert note.level == "warning"
    assert "acc1" in note.message
    assert "2건" in note.message
    assert "ante config history accounts.acc1.rules" in note.message
    assert "경고 로그에서 위치를 확인" in note.message
    for marker in ("9876543", "7.0371", "0.0371"):
        assert marker not in note.message
        assert marker not in note.title


async def test_nothing_dropped_has_no_warning_or_notice(db, caplog) -> None:
    world = await _item_broken_world(
        db, [{"type": "daily_loss_limit", "priority": "1"}], "dynamic"
    )
    cap = _Captured(world.bus)
    caplog.set_level(logging.INFO)

    await _update_with_bus(world)

    assert _drop_warnings(caplog) == []
    assert cap.notifications == []
    assert world.manager is not None
    assert world.manager.get("acc1").rules_unavailable is False


async def test_failed_write_drops_nothing_and_says_nothing(db, caplog) -> None:
    value: list[Any] = [{"type": "daily_loss_limit"}, 5]
    world = await _item_broken_world(db, value, "dynamic")
    cap = _Captured(world.bus)
    caplog.set_level(logging.INFO)
    world.dyn.set = AsyncMock(side_effect=RuntimeError("disk"))  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await _update_with_bus(world)

    assert _drop_warnings(caplog) == []
    assert cap.notifications == []
    assert await world.dyn.get(KEY1) == value
    assert world.manager is not None
    assert world.manager.get("acc1").rules_unavailable_cause == "invalid_item"


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
