"""시장가 매수의 규칙 평가가 주입된 시세를 쓰고, 조회 실패는 매수를 거부한다.

Refs #3097.

스펙: `docs/specs/rule-engine/05-rule-context.md`의 `current_price`,
`docs/specs/rule-engine/07-rule-engine-core.md` 「시장가 매수 시세 (#3097)」.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any
from unittest.mock import AsyncMock

import pytest

import ante.rule.engine as engine_mod
from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.readiness import ReadinessFlag, RuntimeReadinessRegistry
from ante.core import Database, clock
from ante.eventbus import EventBus
from ante.eventbus.events import (
    NotificationEvent,
    OrderApprovedEvent,
    OrderModifyEvent,
    OrderModifyRejectedEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.gateway.gateway import APIGateway
from ante.rule import RuleEngine, RuleEngineManager
from ante.rule.global_rules import TotalExposureLimitRule
from ante.rule.strategy_rules import PositionSizeRule, UnrealizedLossLimitRule
from ante.treasury import Treasury
from tests.unit._rule_engine_helpers import StubTreasury, StubTreasuryManager

ACCOUNT = "domestic"
BOT = "bot1"
STRATEGY = "s1"
SYMBOL = "005930"
QUOTE = 50_000.0
PREFIX = "market_buy_quote_unavailable: "
TREASURY_REASON = "account_not_ready: treasury_unavailable"
POSITIONS_REASON = "account_not_ready: positions_unavailable"


@dataclass
class _Position:
    bot_id: str
    symbol: str
    quantity: float
    avg_entry_price: float


class StubTradeService:
    def __init__(
        self,
        positions: list[_Position] | None = None,
        *,
        fail: bool = False,
        fail_realized: bool = False,
    ) -> None:
        self._positions = positions or []
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
        return [p for p in self._positions if p.bot_id == bot_id]

    async def get_realized_pnl(self, *, account_id: str, start: Any, end: Any) -> float:
        if self._fail_realized:
            raise RuntimeError("simulated get_realized_pnl failure")
        return 0.0


class CountingResolver:
    """호출 수를 세고 ``value``를 돌려주거나 ``exc``를 던진다."""

    def __init__(self, value: Any = QUOTE, exc: BaseException | None = None) -> None:
        self.value = value
        self.exc = exc
        self.calls: list[str] = []

    async def __call__(self, symbol: str) -> Any:
        self.calls.append(symbol)
        if self.exc is not None:
            raise self.exc
        return self.value


class BlockingResolver:
    """``release``가 설정될 때까지 끝나지 않는 조회."""

    def __init__(self, value: Any = QUOTE, exc: BaseException | None = None) -> None:
        self.release = asyncio.Event()
        self.value = value
        self.exc = exc
        self.calls = 0
        self.finished = False
        self.cancelled = False

    async def __call__(self, symbol: str) -> Any:
        self.calls += 1
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.finished = True
        if self.exc is not None:
            raise self.exc
        return self.value


class _UnrenderableError(Exception):
    def __str__(self) -> str:
        raise ValueError("no str")


class _FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.t = start

    def now(self, tz: tzinfo | None) -> datetime:
        return clock.SystemClock().now(tz)

    def monotonic(self) -> float:
        return self.t


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


def _treasury(**overrides: Any) -> StubTreasury:
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
class _Captured:
    validated: list[OrderValidatedEvent] = field(default_factory=list)
    rejected: list[OrderRejectedEvent] = field(default_factory=list)
    notifications: list[NotificationEvent] = field(default_factory=list)
    modify_rejected: list[OrderModifyRejectedEvent] = field(default_factory=list)


def _build(
    *,
    resolver: Callable[[str], Awaitable[Any]] | None = None,
    treasury: Any = None,
    trade_service: Any = None,
    eventbus: EventBus | None = None,
) -> tuple[EventBus, RuleEngine, _Captured]:
    bus = eventbus or EventBus()
    engine = RuleEngine(
        eventbus=bus,
        account_id=ACCOUNT,
        treasury=treasury if treasury is not None else _treasury(),
        trade_service=trade_service or StubTradeService(),
        account=_account(),
        runtime_readiness=_ready_registry(),
    )
    if resolver is not None:
        engine.set_market_price_resolver(resolver)
    engine.start()
    cap = _Captured()
    bus.subscribe(OrderValidatedEvent, lambda e: cap.validated.append(e))
    bus.subscribe(OrderRejectedEvent, lambda e: cap.rejected.append(e))
    bus.subscribe(NotificationEvent, lambda e: cap.notifications.append(e))
    bus.subscribe(OrderModifyRejectedEvent, lambda e: cap.modify_rejected.append(e))
    return bus, engine, cap


def _order(
    side: str = "buy",
    *,
    order_type: str = "market",
    quantity: float = 1.0,
    price: float | None = None,
    stop_price: float | None = None,
) -> OrderRequestEvent:
    return OrderRequestEvent(
        account_id=ACCOUNT,
        bot_id=BOT,
        strategy_id=STRATEGY,
        symbol=SYMBOL,
        side=side,
        quantity=quantity,
        order_type=order_type,
        price=price,
        stop_price=stop_price,
    )


async def _publish(bus: EventBus, event: Any, guard: float = 5.0) -> None:
    await asyncio.wait_for(bus.publish(event), guard)


async def _until(predicate: Callable[[], bool], guard: float = 2.0) -> None:
    async def _spin() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(_spin(), guard)


# ── (a) 재현: 시장가 노출·포지션 ────────────────────────────────────────


class TestMarketBuyUsesQuote:
    @pytest.mark.asyncio
    async def test_market_exposure_over_limit_rejected(self) -> None:
        resolver = CountingResolver(QUOTE)
        bus, engine, cap = _build(resolver=resolver)
        engine.add_account_rule(
            TotalExposureLimitRule("exp", {"max_exposure_percent": 0.2})
        )

        await _publish(bus, _order(quantity=1000.0))

        assert cap.validated == []
        assert len(cap.rejected) == 1
        assert not cap.rejected[0].reason.startswith(PREFIX)
        assert resolver.calls == [SYMBOL]

    @pytest.mark.asyncio
    async def test_market_position_over_limit_rejected(self) -> None:
        resolver = CountingResolver(QUOTE)
        bus, engine, cap = _build(resolver=resolver)
        engine.add_strategy_rule(
            STRATEGY,
            PositionSizeRule(
                "pos", {"max_position_percent": 1.0, "max_position_amount": 100_000.0}
            ),
        )

        await _publish(bus, _order(quantity=3.0))

        assert cap.validated == []
        assert len(cap.rejected) == 1
        assert not cap.rejected[0].reason.startswith(PREFIX)

    @pytest.mark.asyncio
    async def test_market_buy_within_limits_validated(self) -> None:
        bus, engine, cap = _build(resolver=CountingResolver(QUOTE))
        engine.add_account_rule(
            TotalExposureLimitRule("exp", {"max_exposure_percent": 0.2})
        )

        await _publish(bus, _order(quantity=2.0))

        assert len(cap.validated) == 1
        assert cap.validated[0].price is None
        assert cap.rejected == []

    @pytest.mark.asyncio
    async def test_held_position_unrealized_uses_quote(self) -> None:
        """(b) 보유 종목 시장가 매수의 미실현이 시세로 계산되어 과대 거부가 풀린다."""
        trade = StubTradeService(
            [_Position(BOT, SYMBOL, quantity=10.0, avg_entry_price=60_000.0)]
        )
        bus, engine, cap = _build(
            resolver=CountingResolver(59_000.0), trade_service=trade
        )
        engine.add_strategy_rule(
            STRATEGY,
            UnrealizedLossLimitRule("unr", {"max_unrealized_loss_percent": 0.1}),
        )

        await _publish(bus, _order(quantity=1.0))

        assert cap.rejected == []
        assert len(cap.validated) == 1


# ── (c) 조회하지 않는 주문 ──────────────────────────────────────────────


NO_QUOTE_ORDERS = [
    pytest.param(_order("buy", order_type="limit", price=10_000.0), id="limit-buy"),
    pytest.param(_order("sell", order_type="limit", price=10_000.0), id="limit-sell"),
    pytest.param(
        _order("buy", order_type="stop_limit", price=10_000.0, stop_price=9_000.0),
        id="stop-limit-buy",
    ),
    pytest.param(_order("sell", order_type="market"), id="market-sell"),
    pytest.param(
        _order("buy", order_type="stop", stop_price=9_000.0), id="stop-buy-register"
    ),
]


class TestNoQuoteForOtherOrders:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("event", NO_QUOTE_ORDERS)
    async def test_resolver_not_called(self, event: OrderRequestEvent) -> None:
        resolver = CountingResolver(QUOTE)
        bus, _, cap = _build(resolver=resolver)

        await _publish(bus, event)

        assert resolver.calls == []
        assert len(cap.validated) == 1

    @pytest.mark.asyncio
    async def test_modify_does_not_call_resolver(self) -> None:
        resolver = CountingResolver(QUOTE)
        bus, _, cap = _build(resolver=resolver)

        await _publish(
            bus,
            OrderModifyEvent(
                account_id=ACCOUNT,
                bot_id=BOT,
                strategy_id=STRATEGY,
                order_id="o-1",
                symbol=SYMBOL,
                side="buy",
                quantity=1.0,
                price=10_000.0,
            ),
        )

        assert resolver.calls == []
        assert cap.modify_rejected == []


# ── (d) 조회 실패 ───────────────────────────────────────────────────────


FAILURES = [
    pytest.param(None, "resolver not configured", id="not-configured"),
    pytest.param(CountingResolver(exc=RuntimeError("boom")), "boom", id="exception"),
    pytest.param(
        CountingResolver(exc=RuntimeError()), "RuntimeError", id="exception-empty"
    ),
    pytest.param(
        CountingResolver(exc=_UnrenderableError()),
        "<unrenderable _UnrenderableError>",
        id="exception-unrenderable",
    ),
    pytest.param(
        CountingResolver(None), "non-finite or non-positive quote None", id="none"
    ),
    pytest.param(CountingResolver(0), "non-finite or non-positive quote 0", id="zero"),
    pytest.param(
        CountingResolver(-1.0), "non-finite or non-positive quote -1.0", id="negative"
    ),
    pytest.param(
        CountingResolver(math.nan), "non-finite or non-positive quote nan", id="nan"
    ),
    pytest.param(
        CountingResolver(math.inf), "non-finite or non-positive quote inf", id="inf"
    ),
    pytest.param(
        CountingResolver("50000"),
        "non-finite or non-positive quote '50000'",
        id="string",
    ),
    pytest.param(
        CountingResolver(True), "non-finite or non-positive quote True", id="bool"
    ),
]


class TestQuoteFailureRejectsBuy:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("resolver", "detail"), FAILURES)
    async def test_market_buy_rejected(self, resolver: Any, detail: str) -> None:
        bus, _, cap = _build(resolver=resolver)

        await _publish(bus, _order("buy"))

        assert cap.validated == []
        assert [e.reason for e in cap.rejected] == [PREFIX + detail]
        assert cap.notifications == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("resolver", "detail"), FAILURES)
    async def test_market_sell_passes(self, resolver: Any, detail: str) -> None:
        bus, _, cap = _build(resolver=resolver)

        await _publish(bus, _order("sell"))

        assert cap.rejected == []
        assert len(cap.validated) == 1

    @pytest.mark.asyncio
    async def test_timeout_rejects_buy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(engine_mod, "_MARKET_PRICE_TIMEOUT_SECONDS", 0.05)
        resolver = BlockingResolver()
        bus, engine, cap = _build(resolver=resolver)

        await _publish(bus, _order("buy"))

        assert [e.reason for e in cap.rejected] == [PREFIX + "timeout"]
        assert cap.notifications == []
        resolver.release.set()
        await engine.aclose()

    @pytest.mark.asyncio
    async def test_resolver_timeout_error_is_exception_detail(self) -> None:
        bus, _, cap = _build(resolver=CountingResolver(exc=TimeoutError("slow")))

        await _publish(bus, _order("buy"))

        assert [e.reason for e in cap.rejected] == [PREFIX + "slow"]


# ── (e) 판정 순서 ───────────────────────────────────────────────────────


class TestFailureOrder:
    @pytest.mark.asyncio
    async def test_treasury_failure_wins_and_skips_quote(self) -> None:
        resolver = CountingResolver(exc=RuntimeError("boom"))
        bus, _, cap = _build(resolver=resolver, treasury=_treasury(fail="get_summary"))

        await _publish(bus, _order("buy"))

        assert [e.reason for e in cap.rejected] == [TREASURY_REASON]
        assert len(cap.notifications) == 1
        assert resolver.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "trade_fail",
        [{"fail": True}, {"fail_realized": True}],
        ids=["get_positions", "get_realized_pnl"],
    )
    async def test_positions_failure_wins_over_quote(
        self, trade_fail: dict[str, bool]
    ) -> None:
        resolver = CountingResolver(exc=RuntimeError("boom"))
        bus, _, cap = _build(
            resolver=resolver, trade_service=StubTradeService(**trade_fail)
        )

        await _publish(bus, _order("buy"))

        assert [e.reason for e in cap.rejected] == [POSITIONS_REASON]
        assert len(cap.notifications) == 1
        assert resolver.calls == [SYMBOL]


# ── (f) 시간 제한·합류·종료 ─────────────────────────────────────────────


class TestInflightLookup:
    @pytest.mark.asyncio
    async def test_timeout_does_not_cancel_lookup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(engine_mod, "_MARKET_PRICE_TIMEOUT_SECONDS", 0.05)
        resolver = BlockingResolver()
        bus, engine, cap = _build(resolver=resolver)

        await _publish(bus, _order("buy"))
        assert [e.reason for e in cap.rejected] == [PREFIX + "timeout"]

        (task, _started) = engine._market_price_inflight[SYMBOL]
        resolver.release.set()
        assert await asyncio.wait_for(task, 1.0) == QUOTE
        assert resolver.finished is True
        assert resolver.cancelled is False

    @pytest.mark.asyncio
    async def test_concurrent_orders_join_one_lookup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(engine_mod, "_MARKET_PRICE_TIMEOUT_SECONDS", 0.05)
        resolver = BlockingResolver()
        bus, engine, cap = _build(resolver=resolver)

        await asyncio.wait_for(
            asyncio.gather(bus.publish(_order("buy")), bus.publish(_order("buy"))),
            5.0,
        )

        assert resolver.calls == 1
        assert [e.reason for e in cap.rejected] == [PREFIX + "timeout"] * 2
        resolver.release.set()
        await engine.aclose()

    @pytest.mark.asyncio
    async def test_joined_order_waits_only_remaining_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeClock(100.0)
        waits: list[float] = []

        async def _spy_wait(aws: Any, *, timeout: float | None = None) -> Any:
            waits.append(float(timeout or 0.0))
            return set(), set(aws)

        resolver = BlockingResolver()
        bus, engine, cap = _build(resolver=resolver)
        with clock.use_clock(fake):
            monkeypatch.setattr(engine_mod.asyncio, "wait", _spy_wait)
            await bus.publish(_order("buy"))
            await asyncio.sleep(0)
            fake.t = 107.0
            await bus.publish(_order("buy"))
            fake.t = 110.5
            await bus.publish(_order("buy"))
            monkeypatch.undo()

        assert waits == [pytest.approx(10.0), pytest.approx(3.0)]
        assert resolver.calls == 1
        assert [e.reason for e in cap.rejected] == [PREFIX + "timeout"] * 3
        resolver.release.set()
        await engine.aclose()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stale", ["exception", "result"])
    async def test_done_task_in_table_is_not_joined(self, stale: str) -> None:
        resolver = CountingResolver(QUOTE)
        bus, engine, cap = _build(resolver=resolver)
        done: asyncio.Future[float] = asyncio.get_running_loop().create_future()
        if stale == "exception":
            done.set_exception(RuntimeError("stale"))
        else:
            done.set_result(1.0)
        engine._market_price_inflight[SYMBOL] = (done, clock.monotonic())  # type: ignore[assignment]
        engine.add_account_rule(
            TotalExposureLimitRule("exp", {"max_exposure_percent": 0.2})
        )

        await _publish(bus, _order("buy", quantity=10.0))

        assert resolver.calls == [SYMBOL]
        assert cap.validated == []
        assert len(cap.rejected) == 1
        assert not cap.rejected[0].reason.startswith(PREFIX)
        if stale == "exception":
            done.exception()

    @pytest.mark.asyncio
    async def test_done_callback_keeps_newer_entry(self) -> None:
        _, engine, _ = _build(resolver=CountingResolver(QUOTE))
        loop = asyncio.get_running_loop()
        old: asyncio.Future[float] = loop.create_future()
        old.set_result(1.0)
        newer: asyncio.Future[float] = loop.create_future()
        engine._market_price_inflight[SYMBOL] = (newer, 0.0)  # type: ignore[assignment]

        engine._on_market_price_done(SYMBOL, old)  # type: ignore[arg-type]

        assert engine._market_price_inflight[SYMBOL][0] is newer
        newer.cancel()

    @pytest.mark.asyncio
    async def test_unawaited_failure_is_logged_and_retrieved(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(engine_mod, "_MARKET_PRICE_TIMEOUT_SECONDS", 0.05)
        resolver = BlockingResolver(exc=RuntimeError("late boom"))
        bus, engine, cap = _build(resolver=resolver)
        caplog.set_level(logging.WARNING)

        await _publish(bus, _order("buy"))
        (task, _started) = engine._market_price_inflight[SYMBOL]
        resolver.release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1.0)
        await asyncio.sleep(0)
        del task
        gc.collect()

        assert SYMBOL not in engine._market_price_inflight
        assert any(
            r.name == "ante.rule.engine"
            and r.levelno == logging.WARNING
            and "late boom" in r.getMessage()
            for r in caplog.records
        )
        assert not any("never retrieved" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_aclose_cancels_inflight_and_rejects_after(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(engine_mod, "_MARKET_PRICE_TIMEOUT_SECONDS", 0.05)
        resolver = BlockingResolver()
        bus, engine, cap = _build(resolver=resolver)
        caplog.set_level(logging.WARNING)

        await _publish(bus, _order("buy"))
        await asyncio.wait_for(engine.aclose(), 1.0)
        await asyncio.sleep(0)

        assert engine._market_price_inflight == {}
        assert resolver.cancelled is True
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)

        await _publish(bus, _order("buy"))

        assert resolver.calls == 1
        assert [e.reason for e in cap.rejected] == [
            PREFIX + "timeout",
            PREFIX + "engine closed",
        ]

    @pytest.mark.asyncio
    async def test_aclose_while_order_waits_rejects_engine_closed(self) -> None:
        resolver = BlockingResolver()
        bus, engine, cap = _build(resolver=resolver)

        waiting = asyncio.create_task(bus.publish(_order("buy")))
        await _until(lambda: resolver.calls > 0)
        await asyncio.wait_for(engine.aclose(), 1.0)
        await asyncio.wait_for(waiting, 1.0)

        assert [e.reason for e in cap.rejected] == [PREFIX + "engine closed"]

    @pytest.mark.asyncio
    async def test_manager_injects_and_closes(self) -> None:
        bus = EventBus()
        manager = RuleEngineManager(
            eventbus=bus,
            account_service=AsyncMock(),
            treasury_manager=StubTreasuryManager(_treasury()),
            trade_service=StubTradeService(),
            runtime_readiness=_ready_registry(),
        )
        engine = manager.create_engine(ACCOUNT, None, account=_account())
        resolver = BlockingResolver()
        manager.set_market_price_resolver(ACCOUNT, resolver)
        with pytest.raises(KeyError):
            manager.set_market_price_resolver("missing", resolver)

        waiting = asyncio.create_task(bus.publish(_order("buy")))
        await _until(lambda: resolver.calls > 0)
        await asyncio.wait_for(manager.aclose(), 1.0)
        await asyncio.wait_for(waiting, 1.0)

        assert engine._market_price_inflight == {}
        assert resolver.cancelled is True


# ── (g) 실제 게이트웨이: 캐시 미스 1회 ──────────────────────────────────


class _AccountService:
    def __init__(self, broker: Any) -> None:
        self._broker = broker

    async def get_broker(self, account_id: str) -> Any:
        return self._broker


@pytest.mark.asyncio
async def test_rule_and_treasury_share_one_broker_quote(tmp_path: Any) -> None:
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    try:
        bus = EventBus()
        broker = AsyncMock()
        broker.get_current_price = AsyncMock(return_value=QUOTE)
        gateway = APIGateway(account_service=_AccountService(broker), eventbus=bus)  # type: ignore[arg-type]

        async def _resolver(symbol: str) -> float:
            return await gateway.get_current_price(symbol, account_id=ACCOUNT)

        treasury = Treasury(
            db=db,
            eventbus=bus,
            account_id=ACCOUNT,
            currency="KRW",
            order_reserve_price_resolver=_resolver,
            runtime_readiness=_ready_registry(),
        )
        await treasury.initialize()
        await treasury.set_account_balance(10_000_000.0)
        await treasury.allocate(BOT, 1_000_000.0)
        _, _, cap = _build(resolver=_resolver, treasury=treasury, eventbus=bus)
        approved: list[OrderApprovedEvent] = []
        bus.subscribe(OrderApprovedEvent, approved.append)

        await _publish(bus, _order("buy", quantity=2.0))

        assert cap.rejected == []
        assert len(approved) == 1
        assert broker.get_current_price.await_count == 1
    finally:
        await db.close()
