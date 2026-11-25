"""룰 판정 입력 조회가 실패하면 매수를 거부한다. Refs #3047.

스펙: `docs/specs/rule-engine/07-rule-engine-core.md` 「판정 입력 조회 실패」.
Treasury 미주입·Treasury 조회 예외 → `account_not_ready: treasury_unavailable`,
포지션 조회 예외 → `account_not_ready: positions_unavailable`. 매도·정정·
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

ACCOUNT = "domestic"
BOT = "bot1"
SYMBOL = "005930"

TREASURY_REASON = "account_not_ready: treasury_unavailable"
POSITIONS_REASON = "account_not_ready: positions_unavailable"

TREASURY_QUERIES = (
    "get_summary",
    "get_budget",
    "get_daily_snapshot",
    "get_latest_snapshot",
)


@dataclass
class _Budget:
    allocated: float


class StubTreasury:
    """룰 엔진이 읽는 조회 넷을 흉내 내고, 지정한 조회만 예외를 던진다."""

    def __init__(
        self,
        *,
        fail: str | None = None,
        summary: dict[str, float] | None = None,
        budget: float | None = 1_000_000.0,
        prev_snapshot: dict[str, float] | None = None,
        latest_snapshot: dict[str, float] | None = None,
    ) -> None:
        self._fail = fail
        self._summary = summary or {
            "total_profit_loss": 0.0,
            "total_evaluation": 1_000_000.0,
            "ante_eval_amount": 0.0,
        }
        self._budget = budget
        self._prev = prev_snapshot
        self._latest = latest_snapshot

    def _maybe_fail(self, name: str) -> None:
        if self._fail == name:
            raise RuntimeError(f"simulated {name} failure")

    def get_summary(self) -> dict[str, float]:
        self._maybe_fail("get_summary")
        return dict(self._summary)

    def get_budget(self, bot_id: str) -> _Budget | None:
        self._maybe_fail("get_budget")
        return None if self._budget is None else _Budget(self._budget)

    async def get_daily_snapshot(self, date: str) -> dict[str, float] | None:
        self._maybe_fail("get_daily_snapshot")
        return self._prev

    async def get_latest_snapshot(self) -> dict[str, float] | None:
        self._maybe_fail("get_latest_snapshot")
        return self._latest


@dataclass
class _Position:
    bot_id: str
    symbol: str
    quantity: float
    avg_entry_price: float = 50_000.0


class StubTradeService:
    """`get_positions`만 쓰는 TradeService. `fail=True`면 예외를 던진다."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

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
            treasury=StubTreasury(fail=failing), trade_service=StubTradeService()
        )

        await eventbus.publish(_order("buy"))

        _assert_rejected(cap, TREASURY_REASON)

    @pytest.mark.asyncio
    async def test_missing_treasury_rejects_buy_without_rules(self) -> None:
        eventbus, _, cap = _build(treasury=None, trade_service=StubTradeService())

        await eventbus.publish(_order("buy"))

        _assert_rejected(cap, TREASURY_REASON)

    @pytest.mark.asyncio
    async def test_positions_exception_rejects_buy(self) -> None:
        eventbus, _, cap = _build(
            treasury=StubTreasury(), trade_service=StubTradeService(fail=True)
        )

        await eventbus.publish(_order("buy"))

        _assert_rejected(cap, POSITIONS_REASON)

    @pytest.mark.asyncio
    async def test_treasury_reason_wins_when_both_fail(self) -> None:
        eventbus, _, cap = _build(
            treasury=StubTreasury(fail="get_latest_snapshot"),
            trade_service=StubTradeService(fail=True),
        )

        await eventbus.publish(_order("buy"))

        _assert_rejected(cap, TREASURY_REASON)

    @pytest.mark.asyncio
    async def test_exposure_rule_does_not_rescue_failed_query(self) -> None:
        eventbus, engine, cap = _build(
            treasury=StubTreasury(fail="get_summary"),
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
            treasury=StubTreasury(fail=failing), trade_service=StubTradeService()
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
    async def test_positions_exception_allows_sell(self) -> None:
        eventbus, _, cap = _build(
            treasury=StubTreasury(), trade_service=StubTradeService(fail=True)
        )

        await eventbus.publish(_order("sell"))

        assert len(cap.validated) == 1
        assert cap.rejected == []
        assert cap.notifications == []


class TestControls:
    @pytest.mark.asyncio
    async def test_healthy_treasury_over_limit_rejected_by_rule(self) -> None:
        eventbus, engine, cap = _build(
            treasury=StubTreasury(
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
            treasury=StubTreasury(), trade_service=StubTradeService()
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
            treasury=StubTreasury(
                budget=None, prev_snapshot=None, latest_snapshot=None
            ),
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
        eventbus, _, cap = _build(treasury=StubTreasury(), trade_service=None)

        await eventbus.publish(_order("buy"))

        assert len(cap.validated) == 1
        assert cap.rejected == []
        assert cap.notifications == []


class TestModifyUnchanged:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("treasury", "trade_fail"),
        [
            (None, False),
            (StubTreasury(fail="get_latest_snapshot"), False),
            (StubTreasury(), True),
        ],
        ids=["no_treasury", "treasury_exception", "positions_exception"],
    )
    async def test_modify_not_rejected_by_engine(
        self, treasury: Any, trade_fail: bool
    ) -> None:
        eventbus, _, cap = _build(
            treasury=treasury, trade_service=StubTradeService(fail=trade_fail)
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
