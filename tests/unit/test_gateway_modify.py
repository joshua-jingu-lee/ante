"""APIGateway ``_on_order_modify`` broker 위임 테스트 (#2391, v1=price-only).

본 모듈은 다음을 잠근다 (#1331 ``_consumed`` 보존 + #2391 price-only 위임):

- ``_consumed=True`` marker 가 붙은 ``OrderModifyEvent`` 는 Gateway 가 추가
  terminal event 를 발행하지 않고 즉시 반환한다 (Rule reject 결과 보존).
- price-only 정상 흐름(buy 가격↓/sell) → broker.modify_order 위임 + 성공 시
  ``OrderModifyExecutedEvent`` 발행 (ordered_qty 유지, 신규 price).
- v1 fail-closed: 수량 변경·예산증가 buy·부분체결/터미널·무효 인자·orgno 미상
  각각 거부 사유 + broker 미호출. ``event.quantity==0.0`` price-only 허용.
- broker False → ``modify_failed``, 기타 예외 → str(e).
- Rule + Gateway end-to-end: Rule BLOCK → 1건만(룰 사유), Rule 예외 → 1건만
  (``Rule evaluation error``), Rule pass → Gateway 위임.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ante.account.models import Account, AccountStatus
from ante.broker.exceptions import ModifyOrgnoUnavailableError
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderModifyEvent,
    OrderModifyExecutedEvent,
    OrderModifyRejectedEvent,
)
from ante.gateway import APIGateway, RateLimitConfig
from ante.rule import RuleEngine
from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult
from ante.trade.order_tracker import OrderTrackerRecord


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


def _make_record(
    *,
    order_id: str = "ord-gw-2391",
    account_id: str = "domestic",
    symbol: str = "005930",
    side: str = "buy",
    status: str = "open",
    ordered_qty: float = 10.0,
    order_price: float | None = 50000.0,
    broker_order_id: str = "brk-1",
    bot_id: str = "bot1",
    order_type: str = "limit",
) -> OrderTrackerRecord:
    return OrderTrackerRecord(
        order_id=order_id,
        account_id=account_id,
        bot_id=bot_id,
        strategy_id="strat-2391",
        broker_order_id=broker_order_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        ordered_qty=ordered_qty,
        recorded_filled_qty=0.0,
        avg_fill_price=0.0,
        status=status,
        submitted_at=None,
        submitted_date="2026-06-01",
        order_price=order_price,
    )


def _make_tracker(record: OrderTrackerRecord | None) -> AsyncMock:
    tracker = AsyncMock()
    tracker.get = AsyncMock(return_value=record)
    return tracker


@pytest.fixture
def broker() -> AsyncMock:
    b = AsyncMock()
    b.modify_order = AsyncMock(return_value=True)
    return b


@pytest.fixture
def account_service(broker: AsyncMock) -> AsyncMock:
    svc = AsyncMock()
    svc.get_broker = AsyncMock(return_value=broker)
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


def _make_gateway(
    account_service: AsyncMock,
    eventbus: EventBus,
    tracker: AsyncMock | None,
) -> APIGateway:
    gw = APIGateway(
        account_service=account_service,
        eventbus=eventbus,
        rate_config=RateLimitConfig(max_requests=100, window_seconds=60),
        order_tracker=tracker,
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
        "strategy_id": "strat-2391",
        "order_id": "ord-gw-2391",
        "symbol": "005930",
        "side": "buy",
        "quantity": 0.0,  # price-only 기본 (Bot 이 action.quantity or 0.0 로 접음).
        "price": 45000.0,  # buy 가격↓ (order_price 50000 이하).
        "reason": "test reason",
    }
    defaults.update(overrides)
    return OrderModifyEvent(**defaults)  # type: ignore[arg-type]


# ── Gateway 단독 — _consumed 보존 ─────────────────────────


async def test_gateway_skips_when_consumed(
    account_service: AsyncMock, eventbus: EventBus
) -> None:
    """``_consumed=True`` 이벤트는 Gateway 가 추가 발행/broker 호출 없이 무시한다."""
    broker = AsyncMock()
    account_service.get_broker = AsyncMock(return_value=broker)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(_make_record()))

    rejected: list[OrderModifyRejectedEvent] = []
    executed: list[OrderModifyExecutedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))
    eventbus.subscribe(OrderModifyExecutedEvent, lambda e: executed.append(e))

    event = _make_modify_event()
    object.__setattr__(event, "_consumed", True)
    await gateway._on_order_modify(event)

    assert rejected == []
    assert executed == []
    broker.modify_order.assert_not_awaited()


# ── Gateway 단독 — price-only 성공 ────────────────────────


async def test_gateway_price_only_buy_down_executes(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """price-only buy 가격↓ → broker 위임 + Executed 발행, ordered_qty 유지."""
    record = _make_record(side="buy", order_price=50000.0, ordered_qty=10.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    executed: list[OrderModifyExecutedEvent] = []
    eventbus.subscribe(OrderModifyExecutedEvent, lambda e: executed.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(executed) == 1
    assert executed[0].order_id == "ord-gw-2391"
    assert executed[0].symbol == "005930"
    assert executed[0].side == "buy"
    assert executed[0].quantity == 10.0  # ordered_qty 유지.
    assert executed[0].price == 45000.0
    broker.modify_order.assert_awaited_once_with(
        "brk-1", quantity=10.0, price=45000.0, order_type="limit"
    )


async def test_gateway_price_only_sell_executes(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """sell 정정은 reserve 없음 → 가격 방향 무관 통과."""
    record = _make_record(side="sell", order_price=50000.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    executed: list[OrderModifyExecutedEvent] = []
    eventbus.subscribe(OrderModifyExecutedEvent, lambda e: executed.append(e))

    # sell 은 가격↑ 도 허용.
    event = _make_modify_event(side="sell", quantity=0.0, price=60000.0)
    await gateway._on_order_modify(event)

    assert len(executed) == 1
    assert executed[0].side == "sell"
    broker.modify_order.assert_awaited_once()


async def test_gateway_quantity_unchanged_explicit_executes(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """quantity 가 명시되어도 ordered_qty 와 같으면(수량 불변) 허용."""
    record = _make_record(side="buy", order_price=50000.0, ordered_qty=10.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    executed: list[OrderModifyExecutedEvent] = []
    eventbus.subscribe(OrderModifyExecutedEvent, lambda e: executed.append(e))

    event = _make_modify_event(quantity=10.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(executed) == 1
    broker.modify_order.assert_awaited_once()


# ── Gateway 단독 — v1 fail-closed (broker 미호출) ─────────


@pytest.mark.parametrize(
    "bad_price",
    [
        0.0,
        -100.0,
        None,
        float("nan"),
        float("inf"),
        pytest.param(10**10000, id="huge_int"),
    ],
)
async def test_gateway_invalid_price_rejected(
    account_service: AsyncMock,
    eventbus: EventBus,
    broker: AsyncMock,
    bad_price: object,
) -> None:
    """finite price>0 아니면 ``modify_invalid_args`` + broker 미호출."""
    gateway = _make_gateway(account_service, eventbus, _make_tracker(_make_record()))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=bad_price)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_invalid_args"
    broker.modify_order.assert_not_awaited()


async def test_gateway_negative_quantity_rejected(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """quantity<0 무효 → ``modify_invalid_args`` + broker 미호출."""
    gateway = _make_gateway(account_service, eventbus, _make_tracker(_make_record()))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=-5.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_invalid_args"
    broker.modify_order.assert_not_awaited()


async def test_gateway_quantity_change_rejected(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """quantity>0 && != ordered_qty → ``modify_qty_change_unsupported`` (#2393)."""
    record = _make_record(ordered_qty=10.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=7.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_qty_change_unsupported"
    assert rejected[0].symbol == "005930"
    assert rejected[0].side == "buy"
    broker.modify_order.assert_not_awaited()


async def test_gateway_budget_increase_buy_rejected(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """buy 가격↑(new_price > order_price) → ``modify_budget_increase_unsupported``."""
    record = _make_record(side="buy", order_price=50000.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(side="buy", quantity=0.0, price=60000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_budget_increase_unsupported"
    broker.modify_order.assert_not_awaited()


async def test_gateway_buy_missing_order_price_rejected(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """buy 정정 + order_price None(legacy) → fail-closed."""
    record = _make_record(side="buy", order_price=None)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(side="buy", quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_budget_increase_unsupported"
    broker.modify_order.assert_not_awaited()


@pytest.mark.parametrize(
    "status", ["partially_filled", "filled", "cancelled", "rejected", "expired"]
)
async def test_gateway_partial_or_terminal_rejected(
    account_service: AsyncMock,
    eventbus: EventBus,
    broker: AsyncMock,
    status: str,
) -> None:
    """status != open → ``modify_partial_or_terminal_unsupported``."""
    record = _make_record(status=status)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_partial_or_terminal_unsupported"
    broker.modify_order.assert_not_awaited()


async def test_gateway_record_not_found_rejected(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """record 미발견 → ``modify_partial_or_terminal_unsupported`` + broker 미호출."""
    gateway = _make_gateway(account_service, eventbus, _make_tracker(None))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_partial_or_terminal_unsupported"
    broker.modify_order.assert_not_awaited()


async def test_gateway_no_tracker_rejected(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """order_tracker 미주입 → fail-closed + broker 미호출."""
    gateway = _make_gateway(account_service, eventbus, None)

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_partial_or_terminal_unsupported"
    broker.modify_order.assert_not_awaited()


async def test_gateway_orgno_unavailable_rejected(
    account_service: AsyncMock, eventbus: EventBus
) -> None:
    """broker 가 ModifyOrgnoUnavailableError → ``modify_orgno_unavailable``."""
    broker = AsyncMock()
    broker.modify_order = AsyncMock(
        side_effect=ModifyOrgnoUnavailableError("orgno 미상")
    )
    account_service.get_broker = AsyncMock(return_value=broker)
    record = _make_record(order_price=50000.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_orgno_unavailable"


async def test_gateway_broker_false_rejected(
    account_service: AsyncMock, eventbus: EventBus
) -> None:
    """broker 가 False 반환 → ``modify_failed``."""
    broker = AsyncMock()
    broker.modify_order = AsyncMock(return_value=False)
    account_service.get_broker = AsyncMock(return_value=broker)
    record = _make_record(order_price=50000.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_failed"


async def test_gateway_broker_exception_rejected(
    account_service: AsyncMock, eventbus: EventBus
) -> None:
    """broker 가 기타 예외 → str(e) 거부 사유."""
    broker = AsyncMock()
    broker.modify_order = AsyncMock(side_effect=RuntimeError("boom"))
    account_service.get_broker = AsyncMock(return_value=broker)
    record = _make_record(order_price=50000.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))

    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "boom"


# ── Rule + Gateway 통합 시퀀스 ─────────────────────────


async def test_rule_block_then_gateway_only_one_terminal(
    engine: RuleEngine, account_service: AsyncMock, eventbus: EventBus
) -> None:
    """Rule BLOCK 후 Gateway 호출: terminal event 1건, reason 은 룰 거부 사유."""
    gateway = _make_gateway(account_service, eventbus, _make_tracker(_make_record()))
    received: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_account_rule(_BlockingRule("blocker", {"type": "test"}))
    event = _make_modify_event()

    await engine._on_order_modify(event)
    await gateway._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "rule rejection sentinel"


async def test_rule_exception_then_gateway_only_one_terminal(
    engine: RuleEngine, account_service: AsyncMock, eventbus: EventBus
) -> None:
    """Rule 평가 예외 후 Gateway: terminal 1건, reason=``Rule evaluation error``."""
    gateway = _make_gateway(account_service, eventbus, _make_tracker(_make_record()))
    received: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    engine.add_account_rule(_ExplodingRule("boom", {"type": "test"}))
    event = _make_modify_event()

    await engine._on_order_modify(event)
    await gateway._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "Rule evaluation error"


async def test_rule_pass_then_gateway_executes(
    engine: RuleEngine,
    account_service: AsyncMock,
    eventbus: EventBus,
    broker: AsyncMock,
) -> None:
    """Rule pass 후 Gateway: price-only 정정 완료 1건 발행."""
    gateway = _make_gateway(account_service, eventbus, _make_tracker(_make_record()))
    executed: list[OrderModifyExecutedEvent] = []
    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyExecutedEvent, lambda e: executed.append(e))
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)

    await engine._on_order_modify(event)
    await gateway._on_order_modify(event)

    assert rejected == []
    assert len(executed) == 1
    assert executed[0].price == 45000.0


# ── Gateway 단독 — 리뷰 보강 회귀(terminal 보장 / 수량 finite) ──


@pytest.mark.parametrize(
    "bad_qty",
    [float("nan"), float("inf"), None, "10", pytest.param(10**10000, id="huge_int")],
)
async def test_gateway_non_finite_quantity_rejected(
    account_service: AsyncMock,
    eventbus: EventBus,
    broker: AsyncMock,
    bad_qty: object,
) -> None:
    """비숫자/비유한(NaN/Inf)/None quantity → ``modify_invalid_args`` + broker 미호출.

    NaN 은 ``<0``·``>0`` 모두 false 라 검증 없이는 price-only 로 브로커까지 통과하고,
    str/None 은 비교에서 TypeError → terminal 이벤트 소실되므로 비교 전 fail-closed.
    """
    record = _make_record(side="buy", order_price=50000.0, ordered_qty=10.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))
    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=bad_qty, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_invalid_args"
    broker.modify_order.assert_not_awaited()


async def test_gateway_broker_lookup_failure_rejects(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """broker 미캐시·connect/auth 실패로 ``_get_broker`` 가 예외를 던져도 terminal
    ``OrderModifyRejectedEvent`` 가 반드시 발행되어야 한다(EventBus 핸들러 에러로
    소실 금지 — 정정은 성공/거부 중 하나의 terminal update 보장)."""
    account_service.get_broker.side_effect = ConnectionError("broker down")
    record = _make_record(side="buy", order_price=50000.0, ordered_qty=10.0)
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))
    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1  # terminal 보장 — 소실 금지.
    broker.modify_order.assert_not_awaited()


async def test_gateway_other_bot_order_rejected(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """같은 계좌 내 타 봇 주문 정정 → ``modify_not_owner`` + broker 미호출(봇 격리)."""
    record = _make_record(side="buy", order_price=50000.0, bot_id="other-bot")
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))
    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(bot_id="bot1", quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_not_owner"
    broker.modify_order.assert_not_awaited()


async def test_gateway_non_limit_order_rejected(
    account_service: AsyncMock, eventbus: EventBus, broker: AsyncMock
) -> None:
    """비지정가(market 등) 주문 정정 → ``modify_unsupported_order_type``

    + broker 미호출.
    """
    record = _make_record(side="buy", order_price=50000.0, order_type="market")
    gateway = _make_gateway(account_service, eventbus, _make_tracker(record))
    rejected: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: rejected.append(e))

    event = _make_modify_event(quantity=0.0, price=45000.0)
    await gateway._on_order_modify(event)

    assert len(rejected) == 1
    assert rejected[0].reason == "modify_unsupported_order_type"
    broker.modify_order.assert_not_awaited()
