"""RuleEngine `_on_order_modify` `_consumed` transient marker 테스트 (#1331).

본 모듈은 RuleEngine이 `OrderModifyEvent`를 거부할 때 ``_consumed=True`` 를
실제로 set하는지 검증한다. ``hasattr`` guard가 살아있으면 marker가
영원히 set되지 않아 후속 Gateway가 추가 ``OrderModifyRejectedEvent`` 를
발행하는 dead-code 상태로 회귀할 수 있다 (Codex 2차 review 발견).

세 가지 거부 경로를 잠근다:
- BLOCK 결과 → marker set + reject event 발행
- REJECT 결과 → marker set + reject event 발행
- 룰 평가 예외 → marker set + ``"Rule evaluation error"`` reject 발행
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ante.account.models import Account, AccountStatus
from ante.eventbus import EventBus
from ante.eventbus.events import OrderModifyEvent, OrderModifyRejectedEvent
from ante.rule import RuleEngine
from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult


class _RejectingRule(Rule):
    """REJECT 결과를 반환하는 테스트 룰."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.REJECT,
            action=RuleAction.NOTIFY,
            message="modify rejected for test",
        )


class _BlockingRule(Rule):
    """BLOCK 결과를 반환하는 테스트 룰."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.BLOCK,
            action=RuleAction.LOG,
            message="modify blocked for test",
        )


class _ExplodingRule(Rule):
    """평가 시 예외를 던지는 테스트 룰."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        raise RuntimeError("rule explosion for test")


@pytest.fixture
def mock_account_service() -> AsyncMock:
    service = AsyncMock()
    account = Account(
        account_id="domestic",
        name="국내주식",
        exchange="KRX",
        currency="KRW",
        broker_type="test",
        status=AccountStatus.ACTIVE,
    )
    service.get = AsyncMock(return_value=account)
    service.suspend = AsyncMock()
    return service


@pytest.fixture
async def engine(mock_account_service: AsyncMock) -> RuleEngine:
    eventbus = EventBus()
    engine = RuleEngine(
        eventbus=eventbus,
        account_id="domestic",
        account_service=mock_account_service,
    )
    engine.start()
    return engine


def _make_modify_event(**overrides: object) -> OrderModifyEvent:
    defaults: dict[str, object] = {
        "account_id": "domestic",
        "bot_id": "bot1",
        "strategy_id": "s1",
        "order_id": "ord-1331",
        "symbol": "005930",
        "side": "buy",
        "quantity": 10.0,
        "price": 50000.0,
    }
    defaults.update(overrides)
    return OrderModifyEvent(**defaults)  # type: ignore[arg-type]


async def test_modify_block_marks_consumed(engine: RuleEngine) -> None:
    """BLOCK 경로: ``OrderModifyRejectedEvent`` 발행 + ``_consumed=True``."""
    received: list[OrderModifyRejectedEvent] = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_account_rule(_BlockingRule("blocker", {"type": "test"}))
    event = _make_modify_event()
    await engine._on_order_modify(event)

    assert len(received) == 1
    assert received[0].order_id == "ord-1331"
    # transient marker는 dataclass 필드가 아니므로 ``getattr`` default로 확인.
    assert getattr(event, "_consumed", False) is True


async def test_modify_reject_marks_consumed(engine: RuleEngine) -> None:
    """REJECT 경로: ``OrderModifyRejectedEvent`` 발행 + ``_consumed=True``."""
    received: list[OrderModifyRejectedEvent] = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_account_rule(_RejectingRule("rejecter", {"type": "test"}))
    event = _make_modify_event()
    await engine._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "modify rejected for test"
    assert getattr(event, "_consumed", False) is True


async def test_modify_rule_exception_marks_consumed(engine: RuleEngine) -> None:
    """룰 평가 예외 경로: ``"Rule evaluation error"`` 발행 + ``_consumed=True``."""
    received: list[OrderModifyRejectedEvent] = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_account_rule(_ExplodingRule("boom", {"type": "test"}))
    event = _make_modify_event()
    await engine._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "Rule evaluation error"
    assert getattr(event, "_consumed", False) is True


async def test_modify_pass_does_not_mark_consumed(engine: RuleEngine) -> None:
    """룰 통과 시 marker는 set되지 않아 Gateway pass-through가 가능해야 한다."""
    received: list[OrderModifyRejectedEvent] = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    await engine._on_order_modify(event)

    assert len(received) == 0
    # 룰 거부가 없었으므로 marker는 미세팅 (False default).
    assert getattr(event, "_consumed", False) is False
