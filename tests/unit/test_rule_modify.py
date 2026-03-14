"""OrderModifyEvent 룰 검증 테스트."""

import pytest

from ante.config.system_state import SystemState
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderModifyEvent, OrderModifyRejectedEvent
from ante.rule import RuleEngine
from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult


class AlwaysRejectRule(Rule):
    """테스트용: 항상 REJECT하는 룰."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.REJECT,
            action=RuleAction.NOTIFY,
            message="Always reject for testing",
        )


class AlwaysPassRule(Rule):
    """테스트용: 항상 PASS하는 룰."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.PASS,
            action=RuleAction.LOG,
            message="Always pass",
        )


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def system_state(db):
    state = SystemState(db=db, eventbus=EventBus())
    await state.initialize()
    return state


@pytest.fixture
async def engine(system_state):
    eventbus = EventBus()
    engine = RuleEngine(eventbus=eventbus, system_state=system_state)
    await engine.start()
    return engine


def _make_modify_event(**kwargs):
    defaults = {
        "bot_id": "bot1",
        "strategy_id": "s1",
        "order_id": "ord-1",
        "symbol": "005930",
        "side": "buy",
        "quantity": 10.0,
        "price": 50000.0,
    }
    defaults.update(kwargs)
    return OrderModifyEvent(**defaults)


async def test_modify_passes_when_no_rules(engine):
    """룰이 없으면 정정 요청이 통과한다."""
    received = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))
    await engine._on_order_modify(_make_modify_event())
    assert len(received) == 0


async def test_modify_rejected_by_global_rule(engine):
    """전역 룰 위반 시 정정이 거부된다."""
    received = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_global_rule(AlwaysRejectRule("reject", {"type": "test"}))
    await engine._on_order_modify(_make_modify_event())

    assert len(received) == 1
    assert received[0].order_id == "ord-1"
    assert received[0].reason == "Always reject for testing"


async def test_modify_passes_with_pass_rule(engine):
    """룰 통과 시 거부 이벤트가 발행되지 않는다."""
    received = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_global_rule(AlwaysPassRule("pass", {"type": "test"}))
    await engine._on_order_modify(_make_modify_event())

    assert len(received) == 0


async def test_modify_rejected_event_has_correct_fields(engine):
    """거부 이벤트에 올바른 필드가 포함된다."""
    received = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_global_rule(AlwaysRejectRule("reject", {"type": "test"}))

    event = _make_modify_event(
        bot_id="bot1",
        strategy_id="strat1",
        order_id="ord-99",
        symbol="005930",
        side="buy",
        quantity=5.0,
        price=70000.0,
    )
    await engine._on_order_modify(event)

    assert len(received) == 1
    rejected = received[0]
    assert rejected.bot_id == "bot1"
    assert rejected.strategy_id == "strat1"
    assert rejected.order_id == "ord-99"
    assert rejected.symbol == "005930"
    assert rejected.side == "buy"
    assert rejected.quantity == 5.0
    assert rejected.price == 70000.0


async def test_strategy_specific_rule_applied_to_modify(engine):
    """전략별 룰도 정정 요청에 적용된다."""
    received = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_strategy_rule("strat1", AlwaysRejectRule("reject", {"type": "test"}))

    event = _make_modify_event(strategy_id="strat1")
    await engine._on_order_modify(event)

    assert len(received) == 1


async def test_other_strategy_rule_not_applied(engine):
    """다른 전략의 룰은 적용되지 않는다."""
    received = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_strategy_rule("strat2", AlwaysRejectRule("reject", {"type": "test"}))

    event = _make_modify_event(strategy_id="strat1")
    await engine._on_order_modify(event)

    assert len(received) == 0
