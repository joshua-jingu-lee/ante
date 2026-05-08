"""APIGateway `_on_order_modify` terminal event 발행 테스트 (#1331).

본 모듈은 다음을 잠근다:
- ``_consumed=True`` marker가 붙은 ``OrderModifyEvent``는 Gateway가 추가
  terminal event를 발행하지 않고 즉시 반환한다 (Rule reject 결과 보존).
- marker가 없거나 False면 Gateway가 ``OrderModifyRejectedEvent``
  (reason=``"modify_not_implemented"``)를 1회 발행한다.
- Rule + Gateway end-to-end 시퀀스에서:
    * Rule BLOCK → 1건만 발행, reason은 룰 거부 사유 (``modify_not_implemented`` 아님).
    * Rule 예외 → 1건만 발행, reason=``"Rule evaluation error"``.
    * Rule pass → 1건만 발행, reason=``"modify_not_implemented"``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ante.account.models import Account, AccountStatus
from ante.eventbus import EventBus
from ante.eventbus.events import OrderModifyEvent, OrderModifyRejectedEvent
from ante.gateway import APIGateway, RateLimitConfig
from ante.rule import RuleEngine
from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult


class _BlockingRule(Rule):
    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.BLOCK,
            action=RuleAction.LOG,
            message="rule rejection sentinel",
        )


class _ExplodingRule(Rule):
    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        raise RuntimeError("rule explosion")


@pytest.fixture
def broker() -> AsyncMock:
    b = AsyncMock()
    b.cancel_order = AsyncMock(return_value=True)
    return b


@pytest.fixture
def account_service(broker: AsyncMock) -> AsyncMock:
    svc = AsyncMock()
    svc.get_broker = AsyncMock(return_value=broker)
    # RuleEngine.get(account_id) 호환 — engine fixture에서 별도 사용.
    account = Account(
        account_id="domestic",
        name="국내주식",
        exchange="KRX",
        currency="KRW",
        broker_type="test",
        status=AccountStatus.ACTIVE,
    )
    svc.get = AsyncMock(return_value=account)
    svc.suspend = AsyncMock()
    return svc


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
async def gateway(account_service: AsyncMock, eventbus: EventBus) -> APIGateway:
    gw = APIGateway(
        account_service=account_service,
        eventbus=eventbus,
        rate_config=RateLimitConfig(max_requests=100, window_seconds=60),
    )
    gw.start()
    return gw


@pytest.fixture
def engine(account_service: AsyncMock, eventbus: EventBus) -> RuleEngine:
    eng = RuleEngine(
        eventbus=eventbus,
        account_id="domestic",
        account_service=account_service,
    )
    eng.start()
    return eng


def _make_modify_event(**overrides: object) -> OrderModifyEvent:
    defaults: dict[str, object] = {
        "account_id": "domestic",
        "bot_id": "bot1",
        "strategy_id": "strat-1331",
        "order_id": "ord-gw-1331",
        "symbol": "005930",
        "side": "buy",
        "quantity": 10.0,
        "price": 50000.0,
        "reason": "test reason",
    }
    defaults.update(overrides)
    return OrderModifyEvent(**defaults)  # type: ignore[arg-type]


# ── Gateway 단독 동작 ─────────────────────────────────


async def test_gateway_skips_when_consumed(gateway: APIGateway) -> None:
    """``_consumed=True`` 이벤트는 Gateway가 추가 발행 없이 무시한다."""
    received: list[OrderModifyRejectedEvent] = []
    gateway._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    object.__setattr__(event, "_consumed", True)
    await gateway._on_order_modify(event)

    assert received == []


async def test_gateway_publishes_not_implemented_when_passthrough(
    gateway: APIGateway,
) -> None:
    """marker 미세팅: Gateway는 ``modify_not_implemented`` 거부를 1회 발행한다."""
    received: list[OrderModifyRejectedEvent] = []
    gateway._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    await gateway._on_order_modify(event)

    assert len(received) == 1
    rejected = received[0]
    assert rejected.reason == "modify_not_implemented"
    # 모든 식별자/페이로드 보존 검증.
    assert rejected.account_id == "domestic"
    assert rejected.order_id == "ord-gw-1331"
    assert rejected.bot_id == "bot1"
    assert rejected.strategy_id == "strat-1331"
    assert rejected.symbol == "005930"
    assert rejected.side == "buy"
    assert rejected.quantity == 10.0
    assert rejected.price == 50000.0


async def test_gateway_publishes_when_consumed_explicitly_false(
    gateway: APIGateway,
) -> None:
    """``_consumed=False`` 명시 이벤트도 정상 pass-through (방어 테스트)."""
    received: list[OrderModifyRejectedEvent] = []
    gateway._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    object.__setattr__(event, "_consumed", False)
    await gateway._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "modify_not_implemented"


# ── Rule + Gateway 통합 시퀀스 ─────────────────────────


async def test_rule_block_then_gateway_only_one_terminal(
    engine: RuleEngine, gateway: APIGateway
) -> None:
    """Rule BLOCK 후 Gateway 호출: terminal event 1건, reason은 룰 거부 사유."""
    received: list[OrderModifyRejectedEvent] = []
    # eventbus.publish가 priority 100 RuleEngine → priority 50 Gateway 순서로
    # 호출하지만, 본 테스트는 두 핸들러를 동기로 직접 invoke하여 동일한
    # consumer order를 시뮬레이션한다 — Gateway가 marker를 인식해 추가
    # 발행을 건너뛰는지가 핵심이다.
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_account_rule(_BlockingRule("blocker", {"type": "test"}))
    event = _make_modify_event()

    await engine._on_order_modify(event)
    await gateway._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "rule rejection sentinel"
    assert received[0].reason != "modify_not_implemented"


async def test_rule_exception_then_gateway_only_one_terminal(
    engine: RuleEngine, gateway: APIGateway
) -> None:
    """Rule 평가 예외 후 Gateway: terminal 1건, reason=``Rule evaluation error``."""
    received: list[OrderModifyRejectedEvent] = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_account_rule(_ExplodingRule("boom", {"type": "test"}))
    event = _make_modify_event()

    await engine._on_order_modify(event)
    await gateway._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "Rule evaluation error"


async def test_rule_pass_then_gateway_emits_not_implemented(
    engine: RuleEngine, gateway: APIGateway
) -> None:
    """Rule pass 후 Gateway: terminal 1건, reason=``modify_not_implemented``."""
    received: list[OrderModifyRejectedEvent] = []
    engine._eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()

    await engine._on_order_modify(event)
    await gateway._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "modify_not_implemented"
