"""룰 판정 입력 조회가 실패하면 매수를 거부한다. Refs #3047.

스펙: `docs/specs/rule-engine/07-rule-engine-core.md` 「판정 입력 조회 실패」.
Treasury 미주입·Treasury 조회 예외 → `account_not_ready: treasury_unavailable`,
포지션·당일 실현 손익 조회 예외 → `account_not_ready: positions_unavailable`. 매도·정정·
값 없음(`None`)은 지금처럼 0으로 채워 평가한다.
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
from ante.rule.global_rules import DailyLossLimitRule, TotalExposureLimitRule
from tests.unit._rule_engine_helpers import TREASURY_QUERIES, StubTreasury

ACCOUNT = "domestic"
BOT = "bot1"
SYMBOL = "005930"

TREASURY_REASON = "account_not_ready: treasury_unavailable"
TRADE_FAILURES = [
    pytest.param({"fail": True}, id="get_positions"),
    pytest.param({"fail_realized": True}, id="get_realized_pnl"),
]
POSITIONS_REASON = "account_not_ready: positions_unavailable"


def _healthy(**overrides: Any) -> StubTreasury:
    kwargs: dict[str, Any] = {
        "summary": {
            "total_profit_loss": 0.0,
            "total_evaluation": 1_000_000.0,
            "ante_eval_amount": 0.0,
        },
        "budget": 1_000_000.0,
    }
    kwargs.update(overrides)
    return StubTreasury(**kwargs)


@dataclass
class _Position:
    bot_id: str
    symbol: str
    quantity: float
    avg_entry_price: float = 50_000.0


class StubTradeService:
    """`get_positions`·`get_realized_pnl`만 쓰는 TradeService.

    `fail=True`면 `get_positions`, `fail_realized=True`면 `get_realized_pnl`이
    예외를 던진다.
    """

    def __init__(self, *, fail: bool = False, fail_realized: bool = False) -> None:
        self._fail = fail
        self._fail_realized = fail_realized

    async def get_positions(
        self,
        bot_id: str,
        include_closed: bool = False,
        *,
        account_id: str | None = None,
    ) -> list[_Position]:
        if self._fail:
            raise RuntimeError("simulated get_positions failure")
        return []

    async def get_realized_pnl(self, *, account_id: str, start: Any, end: Any) -> float:
        if self._fail_realized:
            raise RuntimeError("simulated get_realized_pnl failure")
        return 0.0


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


def _build(
    *,
    treasury: Any,
    trade_service: Any = None,
) -> tuple[EventBus, RuleEngine, _Captured]:
    eventbus = EventBus()
    engine = RuleEngine(
        eventbus=eventbus,
        account_id=ACCOUNT,
        treasury=treasury,
        trade_service=trade_service,
        account=_account(),
        runtime_readiness=_ready_registry(),
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


def _order(side: str = "buy", *, quantity: float = 1.0) -> OrderRequestEvent:
    return OrderRequestEvent(
        account_id=ACCOUNT,
        bot_id=BOT,
        strategy_id="s1",
        symbol=SYMBOL,
        side=side,
        quantity=quantity,
        order_type="limit",
        price=10_000.0,
    )


def _assert_rejected(cap: _Captured, reason: str) -> None:
    assert cap.validated == []
    assert [e.reason for e in cap.rejected] == [reason]
    assert len(cap.notifications) == 1
    assert reason in cap.notifications[0].message


class TestBuyRejectedOnQueryFailure:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("failing", TREASURY_QUERIES)
    async def test_treasury_query_exception_rejects_buy(self, failing: str) -> None:
        eventbus, _, cap = _build(
            treasury=_healthy(fail=failing), trade_service=StubTradeService()
        )

        await eventbus.publish(_order("buy"))

        _assert_rejected(cap, TREASURY_REASON)

    @pytest.mark.asyncio
    async def test_missing_treasury_rejects_buy_without_rules(self) -> None:
        eventbus, _, cap = _build(treasury=None, trade_service=StubTradeService())

        await eventbus.publish(_order("buy"))

        _assert_rejected(cap, TREASURY_REASON)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trade_fail", TRADE_FAILURES)
    async def test_positions_exception_rejects_buy(
        self, trade_fail: dict[str, bool]
    ) -> None:
        eventbus, _, cap = _build(
            treasury=_healthy(), trade_service=StubTradeService(**trade_fail)
        )

        await eventbus.publish(_order("buy"))

        _assert_rejected(cap, POSITIONS_REASON)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trade_fail", TRADE_FAILURES)
    async def test_treasury_reason_wins_when_both_fail(
        self, trade_fail: dict[str, bool]
    ) -> None:
        eventbus, _, cap = _build(
            treasury=_healthy(fail="get_prev_day_snapshot"),
            trade_service=StubTradeService(**trade_fail),
        )

        await eventbus.publish(_order("buy"))

        _assert_rejected(cap, TREASURY_REASON)

    @pytest.mark.asyncio
    async def test_exposure_rule_does_not_rescue_failed_query(self) -> None:
        eventbus, engine, cap = _build(
            treasury=_healthy(fail="get_summary"),
            trade_service=StubTradeService(),
        )
        engine.add_account_rule(
            TotalExposureLimitRule("exp", {"max_exposure_percent": 0.2})
        )

        await eventbus.publish(_order("buy"))

        _assert_rejected(cap, TREASURY_REASON)


class TestSellUnchanged:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("failing", TREASURY_QUERIES)
    async def test_treasury_query_exception_allows_sell(self, failing: str) -> None:
        eventbus, _, cap = _build(
            treasury=_healthy(fail=failing), trade_service=StubTradeService()
        )

        await eventbus.publish(_order("sell"))

        assert len(cap.validated) == 1
        assert cap.rejected == []
        assert cap.notifications == []

    @pytest.mark.asyncio
    async def test_missing_treasury_allows_sell(self) -> None:
        eventbus, _, cap = _build(treasury=None, trade_service=StubTradeService())

        await eventbus.publish(_order("sell"))

        assert len(cap.validated) == 1
        assert cap.rejected == []
        assert cap.notifications == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trade_fail", TRADE_FAILURES)
    async def test_positions_exception_allows_sell(
        self, trade_fail: dict[str, bool]
    ) -> None:
        eventbus, _, cap = _build(
            treasury=_healthy(), trade_service=StubTradeService(**trade_fail)
        )

        await eventbus.publish(_order("sell"))

        assert len(cap.validated) == 1
        assert cap.rejected == []
        assert cap.notifications == []


class TestControls:
    @pytest.mark.asyncio
    async def test_healthy_treasury_over_limit_rejected_by_rule(self) -> None:
        eventbus, engine, cap = _build(
            treasury=_healthy(
                summary={
                    "total_profit_loss": 0.0,
                    "total_evaluation": 1_000_000.0,
                    "ante_eval_amount": 190_000.0,
                }
            ),
            trade_service=StubTradeService(),
        )
        engine.add_account_rule(
            TotalExposureLimitRule("exp", {"max_exposure_percent": 0.2})
        )

        await eventbus.publish(_order("buy", quantity=2.0))

        assert cap.validated == []
        assert len(cap.rejected) == 1
        assert "Total exposure would exceed limit" in cap.rejected[0].reason
        assert len(cap.notifications) == 1

    @pytest.mark.asyncio
    async def test_healthy_treasury_within_limit_validated(self) -> None:
        eventbus, engine, cap = _build(
            treasury=_healthy(), trade_service=StubTradeService()
        )
        engine.add_account_rule(
            TotalExposureLimitRule("exp", {"max_exposure_percent": 0.2})
        )

        await eventbus.publish(_order("buy"))

        assert len(cap.validated) == 1
        assert cap.rejected == []
        assert cap.notifications == []

    @pytest.mark.asyncio
    async def test_missing_snapshots_and_budget_still_validate_buy(self) -> None:
        eventbus, engine, cap = _build(
            treasury=_healthy(budget=None, prev_snapshot=None),
            trade_service=StubTradeService(),
        )
        engine.add_account_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05})
        )

        await eventbus.publish(_order("buy"))

        assert len(cap.validated) == 1
        assert cap.rejected == []
        assert cap.notifications == []

    @pytest.mark.asyncio
    async def test_missing_trade_service_still_validates_buy(self) -> None:
        eventbus, _, cap = _build(treasury=_healthy(), trade_service=None)

        await eventbus.publish(_order("buy"))

        assert len(cap.validated) == 1
        assert cap.rejected == []
        assert cap.notifications == []


class TestModifyUnchanged:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("treasury", "trade_fail"),
        [
            (None, {}),
            (_healthy(fail="get_prev_day_snapshot"), {}),
            (_healthy(), {"fail": True}),
            (_healthy(), {"fail_realized": True}),
        ],
        ids=[
            "no_treasury",
            "treasury_exception",
            "positions_exception",
            "realized_pnl_exception",
        ],
    )
    async def test_modify_not_rejected_by_engine(
        self, treasury: Any, trade_fail: dict[str, bool]
    ) -> None:
        eventbus, _, cap = _build(
            treasury=treasury, trade_service=StubTradeService(**trade_fail)
        )

        for side in ("buy", "sell"):
            await eventbus.publish(
                OrderModifyEvent(
                    account_id=ACCOUNT,
                    bot_id=BOT,
                    strategy_id="s1",
                    order_id=f"o-{side}",
                    symbol=SYMBOL,
                    side=side,
                    quantity=1.0,
                    price=9_000.0,
                )
            )

        assert cap.modify_rejected == []
        assert cap.notifications == []
