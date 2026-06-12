"""RuleEngine modify event symbol/side OrderTracker enrich 테스트 (#2045).

``ctx.modify_order()`` 경로의 ``OrderModifyEvent``는 symbol/side가 빈 값이다
(OrderAction에 없음). 이로 인해 RuleEngine/Gateway가 발행하는
``OrderModifyRejectedEvent``도 빈 symbol/side를 전파해 on_order_update의
``modify_rejected`` 필수키(order_id, status, symbol, side, reason) 계약을
위반한다(03-01-strategy-interface.md).

본 모듈은 RuleEngine이 단일 chokepoint(첫 핸들러 priority 100)에서
OrderTracker로 event.symbol/side를 enrich하는지, 그리고 동일 인스턴스 공유로
Gateway pass-through까지 보강이 전파되는지 잠근다:

- (a) RuleEngine rule-reject → OrderModifyRejectedEvent.symbol/side == record
- (b) RuleEngine 룰 평가 예외 거부 → 동일
- (c) rule 통과 → Gateway not-implemented 거부도 enriched (same-instance pass-through)
- (d) order_tracker 미주입 → "" graceful (무회귀)
- (e) record 미발견(None) → "" graceful
- (f) account 불일치 record → enrich 안 함(no-op)
- (g) RuleEngine/RuleEngineManager 기존 생성자(order_tracker 미전달) 무회귀
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ante.account.models import Account, AccountStatus
from ante.eventbus import EventBus
from ante.eventbus.events import OrderModifyEvent, OrderModifyRejectedEvent
from ante.gateway import APIGateway, RateLimitConfig
from ante.rule import RuleEngine, RuleEngineManager
from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult
from ante.trade.order_tracker import OrderTrackerRecord


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


class _ExplodingRule(Rule):
    """평가 시 예외를 던지는 테스트 룰."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        raise RuntimeError("rule explosion for test")


def _make_record(
    *,
    order_id: str = "ord-2045",
    account_id: str = "domestic",
    symbol: str = "005930",
    side: str = "buy",
) -> OrderTrackerRecord:
    return OrderTrackerRecord(
        order_id=order_id,
        account_id=account_id,
        bot_id="bot1",
        strategy_id="s1",
        broker_order_id="brk-1",
        symbol=symbol,
        side=side,
        order_type="limit",
        ordered_qty=10.0,
        recorded_filled_qty=0.0,
        avg_fill_price=0.0,
        status="open",
        submitted_at=None,
        submitted_date="2026-06-01",
    )


def _make_tracker(record: OrderTrackerRecord | None) -> AsyncMock:
    """``get(order_id) -> record`` 를 반환하는 OrderTracker 스텁."""
    tracker = AsyncMock()
    tracker.get = AsyncMock(return_value=record)
    return tracker


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


def _make_engine(
    account_service: AsyncMock,
    eventbus: EventBus,
    order_tracker: AsyncMock | None,
) -> RuleEngine:
    engine = RuleEngine(
        eventbus=eventbus,
        account_id="domestic",
        account_service=account_service,
        order_tracker=order_tracker,
    )
    engine.start()
    return engine


def _make_modify_event(**overrides: object) -> OrderModifyEvent:
    """ctx.modify_order() 경로 — symbol/side 빈 값 (OrderAction에 없음)."""
    defaults: dict[str, object] = {
        "account_id": "domestic",
        "bot_id": "bot1",
        "strategy_id": "s1",
        "order_id": "ord-2045",
        "symbol": "",
        "side": "",
        "quantity": 5.0,
        "price": 70000.0,
        "reason": "adjust",
    }
    defaults.update(overrides)
    return OrderModifyEvent(**defaults)  # type: ignore[arg-type]


# ── (a) RuleEngine rule-reject 경로 enrich ─────────────────────────


async def test_rule_reject_enriches_symbol_side(
    mock_account_service: AsyncMock,
) -> None:
    eventbus = EventBus()
    record = _make_record(symbol="005930", side="buy")
    engine = _make_engine(mock_account_service, eventbus, _make_tracker(record))
    engine.add_account_rule(_RejectingRule("rejecter", {"type": "test"}))

    received: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    await engine._on_order_modify(event)

    assert len(received) == 1
    assert received[0].symbol == "005930"
    assert received[0].side == "buy"
    # 원본 event도 enrich 되어 후속 핸들러가 채워진 값을 본다.
    assert event.symbol == "005930"
    assert event.side == "buy"


# ── (b) RuleEngine 예외 거부 경로 enrich ───────────────────────────


async def test_rule_exception_enriches_symbol_side(
    mock_account_service: AsyncMock,
) -> None:
    eventbus = EventBus()
    record = _make_record(symbol="000660", side="sell")
    engine = _make_engine(mock_account_service, eventbus, _make_tracker(record))
    engine.add_account_rule(_ExplodingRule("boom", {"type": "test"}))

    received: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    await engine._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "Rule evaluation error"
    assert received[0].symbol == "000660"
    assert received[0].side == "sell"


# ── (c) rule 통과 → Gateway not-implemented 거부도 enriched ─────────


async def test_rule_pass_then_gateway_enriched_passthrough(
    mock_account_service: AsyncMock,
) -> None:
    """RuleEngine이 동일 인스턴스를 enrich → Gateway 거부도 채워진 값을 본다."""
    eventbus = EventBus()
    record = _make_record(symbol="035720", side="buy")
    engine = _make_engine(mock_account_service, eventbus, _make_tracker(record))

    gateway = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        rate_config=RateLimitConfig(max_requests=100, window_seconds=60),
    )
    gateway.start()

    received: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    # RuleEngine(p100) → Gateway(p50) 순서를 동일 인스턴스로 시뮬레이션.
    await engine._on_order_modify(event)
    await gateway._on_order_modify(event)

    assert len(received) == 1
    assert received[0].reason == "modify_not_implemented"
    assert received[0].symbol == "035720"
    assert received[0].side == "buy"


# ── (d) order_tracker 미주입 → "" graceful (무회귀) ─────────────────


async def test_no_order_tracker_keeps_empty_graceful(
    mock_account_service: AsyncMock,
) -> None:
    eventbus = EventBus()
    engine = _make_engine(mock_account_service, eventbus, order_tracker=None)
    engine.add_account_rule(_RejectingRule("rejecter", {"type": "test"}))

    received: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    await engine._on_order_modify(event)

    assert len(received) == 1
    assert received[0].symbol == ""
    assert received[0].side == ""


# ── (e) record 미발견(None) → "" graceful ──────────────────────────


async def test_record_not_found_keeps_empty_graceful(
    mock_account_service: AsyncMock,
) -> None:
    eventbus = EventBus()
    engine = _make_engine(mock_account_service, eventbus, _make_tracker(None))
    engine.add_account_rule(_RejectingRule("rejecter", {"type": "test"}))

    received: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    await engine._on_order_modify(event)

    assert len(received) == 1
    assert received[0].symbol == ""
    assert received[0].side == ""


# ── (f) account 불일치 record → enrich 안 함 (no-op) ────────────────


async def test_account_mismatch_record_no_enrich(
    mock_account_service: AsyncMock,
) -> None:
    """다른 account의 record는 cross-account leak 방지를 위해 무시한다."""
    eventbus = EventBus()
    foreign = _make_record(account_id="overseas", symbol="AAPL", side="sell")
    engine = _make_engine(mock_account_service, eventbus, _make_tracker(foreign))
    engine.add_account_rule(_RejectingRule("rejecter", {"type": "test"}))

    received: list[OrderModifyRejectedEvent] = []
    eventbus.subscribe(OrderModifyRejectedEvent, lambda e: received.append(e))

    event = _make_modify_event()
    await engine._on_order_modify(event)

    assert len(received) == 1
    assert received[0].symbol == ""
    assert received[0].side == ""
    assert event.symbol == ""
    assert event.side == ""


# ── (g) 기존 생성자(order_tracker 미전달) 무회귀 ────────────────────


def test_rule_engine_init_without_order_tracker() -> None:
    """RuleEngine은 order_tracker 미전달로도 생성된다 (기존 호출자 무회귀)."""
    engine = RuleEngine(eventbus=EventBus(), account_id="domestic")
    assert engine._order_tracker is None


def test_rule_engine_manager_init_without_order_tracker(
    mock_account_service: AsyncMock,
) -> None:
    """RuleEngineManager는 order_tracker 미전달로도 생성된다 (기존 호출자 무회귀)."""
    manager = RuleEngineManager(
        eventbus=EventBus(),
        account_service=mock_account_service,
    )
    assert manager._order_tracker is None


async def test_rule_engine_manager_injects_order_tracker(
    mock_account_service: AsyncMock,
) -> None:
    """Manager가 생성하는 RuleEngine에 order_tracker가 전달되는지 잠근다."""
    tracker = _make_tracker(_make_record())
    manager = RuleEngineManager(
        eventbus=EventBus(),
        account_service=mock_account_service,
        order_tracker=tracker,
    )
    engine = manager.create_engine("domestic")
    assert engine._order_tracker is tracker


def test_rule_engine_manager_init_without_instrument_service(
    mock_account_service: AsyncMock,
) -> None:
    """#2377: RuleEngineManager는 instrument_service 미전달로도 생성된다(무회귀)."""
    manager = RuleEngineManager(
        eventbus=EventBus(),
        account_service=mock_account_service,
    )
    assert manager._instrument_service is None


async def test_rule_engine_manager_injects_instrument_service(
    mock_account_service: AsyncMock,
) -> None:
    """#2377: Manager가 생성하는 RuleEngine에 instrument_service가 전달되는지 잠근다."""
    from unittest.mock import MagicMock

    from ante.instrument.service import InstrumentService

    instrument_service = InstrumentService(db=MagicMock())
    manager = RuleEngineManager(
        eventbus=EventBus(),
        account_service=mock_account_service,
        instrument_service=instrument_service,
    )
    engine = manager.create_engine("domestic")
    assert engine._instrument_service is instrument_service
