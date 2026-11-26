"""규칙 평가가 주문 종목의 보유량을 채우고 포지션 크기 규칙이 매도를 통과시킨다.

Refs #3091.

스펙: `docs/specs/rule-engine/05-rule-context.md`의 `current_position`,
`docs/specs/rule-engine/06-rule-catalog.md`의 `PositionSizeRule` 행.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.readiness import ReadinessFlag, RuntimeReadinessRegistry
from ante.eventbus import EventBus
from ante.eventbus.events import (
    NotificationEvent,
    OrderModifyEvent,
    OrderModifyRejectedEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.rule import RuleEngine
from ante.rule.base import RuleContext, RuleResult
from ante.rule.strategy_rules import PositionSizeRule
from tests.unit._rule_engine_helpers import StubTreasury

ACCOUNT = "domestic"
BOT = "bot1"
STRATEGY = "s1"
SYMBOL = "005930"
OTHER_SYMBOL = "035720"
LIMIT = 100_000.0
PRICE = 50_000.0
POSITIONS_REASON = "account_not_ready: positions_unavailable"


@dataclass
class _Position:
    bot_id: str
    symbol: str
    quantity: float
    avg_entry_price: float = PRICE


class StubTradeService:
    """보유 행을 돌려주고 `get_positions` 호출 수를 세는 TradeService."""

    def __init__(
        self, positions: list[_Position] | None = None, *, fail: bool = False
    ) -> None:
        self._positions = positions or []
        self._fail = fail
        self.positions_calls = 0

    async def get_positions(
        self,
        bot_id: str,
        include_closed: bool = False,
        *,
        account_id: str | None = None,
    ) -> list[_Position]:
        self.positions_calls += 1
        if self._fail:
            raise RuntimeError("simulated get_positions failure")
        return [p for p in self._positions if p.bot_id == bot_id]

    async def get_realized_pnl(self, *, account_id: str, start: Any, end: Any) -> float:
        return 0.0


def _held(quantity: float, symbol: str = SYMBOL) -> _Position:
    return _Position(bot_id=BOT, symbol=symbol, quantity=quantity)


def _account() -> Account:
    return Account(
        account_id=ACCOUNT,
        name=ACCOUNT,
        exchange="KRX",
        currency="KRW",
        broker_type="test",
        trading_mode=TradingMode.VIRTUAL,
        status=AccountStatus.ACTIVE,
    )


def _ready_registry() -> RuntimeReadinessRegistry:
    reg = RuntimeReadinessRegistry()
    reg.mark_ready(ACCOUNT, ReadinessFlag.TREASURY_SYNC)
    return reg


@dataclass
class _Captured:
    validated: list[OrderValidatedEvent] = field(default_factory=list)
    rejected: list[OrderRejectedEvent] = field(default_factory=list)
    notifications: list[NotificationEvent] = field(default_factory=list)
    modify_rejected: list[OrderModifyRejectedEvent] = field(default_factory=list)


def _build(trade_service: Any) -> tuple[EventBus, RuleEngine, _Captured]:
    eventbus = EventBus()
    engine = RuleEngine(
        eventbus=eventbus,
        account_id=ACCOUNT,
        treasury=StubTreasury(
            summary={
                "total_profit_loss": 0.0,
                "total_evaluation": 10_000_000.0,
                "ante_eval_amount": 0.0,
            },
            budget=10_000_000.0,
        ),
        trade_service=trade_service,
        account=_account(),
        runtime_readiness=_ready_registry(),
    )
    engine.add_strategy_rule(
        STRATEGY,
        PositionSizeRule(
            "pos", {"max_position_percent": 1.0, "max_position_amount": LIMIT}
        ),
    )
    engine.start()
    cap = _Captured()
    eventbus.subscribe(OrderValidatedEvent, lambda e: cap.validated.append(e))
    eventbus.subscribe(OrderRejectedEvent, lambda e: cap.rejected.append(e))
    eventbus.subscribe(NotificationEvent, lambda e: cap.notifications.append(e))
    eventbus.subscribe(
        OrderModifyRejectedEvent, lambda e: cap.modify_rejected.append(e)
    )
    return eventbus, engine, cap


def _order(side: str, quantity: float) -> OrderRequestEvent:
    return OrderRequestEvent(
        account_id=ACCOUNT,
        bot_id=BOT,
        strategy_id=STRATEGY,
        symbol=SYMBOL,
        side=side,
        quantity=quantity,
        order_type="limit",
        price=PRICE,
    )


def _assert_validated(cap: _Captured) -> None:
    assert len(cap.validated) == 1
    assert cap.rejected == []


def _assert_position_rejected(cap: _Captured) -> None:
    assert cap.validated == []
    assert len(cap.rejected) == 1
    assert "Position size" in cap.rejected[0].reason


class TestBuyCountsHolding:
    @pytest.mark.asyncio
    async def test_buy_rejected_when_holding_plus_order_exceeds_limit(self) -> None:
        eventbus, _, cap = _build(StubTradeService([_held(2.0)]))

        await eventbus.publish(_order("buy", 1.0))

        _assert_position_rejected(cap)

    @pytest.mark.asyncio
    async def test_buy_without_holding_passes(self) -> None:
        eventbus, _, cap = _build(StubTradeService())

        await eventbus.publish(_order("buy", 1.0))

        _assert_validated(cap)

    @pytest.mark.asyncio
    async def test_other_symbol_holding_is_not_counted(self) -> None:
        eventbus, _, cap = _build(StubTradeService([_held(2.0, OTHER_SYMBOL)]))

        await eventbus.publish(_order("buy", 1.0))

        _assert_validated(cap)

    @pytest.mark.asyncio
    async def test_rows_of_same_symbol_are_summed(self) -> None:
        eventbus, _, cap = _build(StubTradeService([_held(1.0), _held(1.0)]))

        await eventbus.publish(_order("buy", 1.0))

        _assert_position_rejected(cap)

    @pytest.mark.asyncio
    async def test_no_trade_service_counts_no_holding(self) -> None:
        eventbus, _, cap = _build(None)

        await eventbus.publish(_order("buy", 1.0))

        _assert_validated(cap)


class TestSellPasses:
    @pytest.mark.asyncio
    async def test_sell_of_oversized_holding_passes(self) -> None:
        eventbus, _, cap = _build(StubTradeService([_held(3.0)]))

        await eventbus.publish(_order("sell", 3.0))

        _assert_validated(cap)

    @pytest.mark.asyncio
    async def test_modify_sell_over_limit_passes(self) -> None:
        eventbus, _, cap = _build(StubTradeService([_held(3.0)]))

        await eventbus.publish(
            OrderModifyEvent(
                account_id=ACCOUNT,
                bot_id=BOT,
                strategy_id=STRATEGY,
                order_id="o-sell",
                symbol=SYMBOL,
                side="sell",
                quantity=3.0,
                price=PRICE,
            )
        )

        assert cap.modify_rejected == []

    def test_rule_passes_sell_regardless_of_size(self) -> None:
        rule = PositionSizeRule(
            "pos", {"max_position_percent": 1.0, "max_position_amount": LIMIT}
        )
        context = RuleContext(
            bot_id=BOT,
            account_id=ACCOUNT,
            strategy_id=STRATEGY,
            symbol=SYMBOL,
            side="sell",
            quantity=3.0,
            order_type="limit",
            price=PRICE,
            current_price=PRICE,
            current_position=10.0,
            bot_allocated_budget=10_000_000.0,
        )

        assert rule.evaluate(context).result == RuleResult.PASS


class TestPositionsQueryFailure:
    @pytest.mark.asyncio
    async def test_failure_rejects_buy(self) -> None:
        eventbus, _, cap = _build(StubTradeService([_held(2.0)], fail=True))

        await eventbus.publish(_order("buy", 1.0))

        assert cap.validated == []
        assert [e.reason for e in cap.rejected] == [POSITIONS_REASON]

    @pytest.mark.asyncio
    async def test_failure_allows_sell(self) -> None:
        eventbus, _, cap = _build(StubTradeService([_held(3.0)], fail=True))

        await eventbus.publish(_order("sell", 3.0))

        _assert_validated(cap)


class TestSingleQuery:
    @pytest.mark.asyncio
    async def test_one_positions_query_per_order(self) -> None:
        trade_service = StubTradeService([_held(1.0)])
        eventbus, _, cap = _build(trade_service)

        await eventbus.publish(_order("buy", 1.0))

        _assert_validated(cap)
        assert trade_service.positions_calls == 1
