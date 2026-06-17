"""RuleEngine 미복구 self-order 반복 매수 가드 회귀 테스트. Refs #2315.

#2314 캐스케이드 방어(defense-in-depth): 매수 주문이 제출됐으나 내부 체결 복구가
지연/실패해 `positions`가 0으로 고정되면, 전략이 동일 매수를 반복 제출해
#1945 캐스케이드(반복매수 → 예산 소진 → 외부매수 오분류 → 재매도)로 진입할 수
있다. RuleEngine은 미복구 outstanding self-buy가 잔존하는 동안 동일 매수의 중복
제출을 차단한다.

차단룰(4조건 AND, `docs/specs/rule-engine/07-rule-engine-core.md` "미복구 매수 가드"):
1. `(account_id, bot_id, symbol, side="buy")` non-terminal buy 중 remaining > 0 존재.
2. 그 주문의 `submitted_at` age ≥ `unrecovered_buy_guard_min_age`(기본 60s).
3. 해당 symbol 내부 position 수량 합 == 0.
4. opt-out `allow_unrecovered_buy_overlap` == false.

테스트 매트릭스(9): ① 차단 / ② terminal 후 허용 / ③ recorded==ordered 허용 /
④ position>0 허용 / ⑤ age<60s 허용 / ⑥ opt-out=true 허용 /
⑦ 다른 account/bot/symbol/side=sell 비차단 / ⑧ order_tracker 미주입 비활성 /
⑨ 조회 예외 fail-closed reject.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.readiness import ReadinessFlag, RuntimeReadinessRegistry
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.rule import RuleEngine

ACCOUNT = "domestic"
BOT = "bot1"
SYMBOL = "005930"


def _gate_account() -> Account:
    """#2398 계층1 gate 용 (test, virtual) account snapshot."""
    return Account(
        account_id=ACCOUNT,
        name=ACCOUNT,
        exchange="KRX",
        currency="KRW",
        broker_type="test",
        trading_mode=TradingMode.VIRTUAL,
        status=AccountStatus.ACTIVE,
    )


def _gate_ready_registry() -> RuntimeReadinessRegistry:
    """(test, virtual) → treasury_sync 만 비면제이므로 ready mark."""
    reg = RuntimeReadinessRegistry()
    reg.mark_ready(ACCOUNT, ReadinessFlag.TREASURY_SYNC)
    return reg


@dataclass
class FakePosition:
    """position 수량 조회에 필요한 최소 PositionSnapshot 형태."""

    bot_id: str
    symbol: str
    quantity: float
    avg_entry_price: float = 60000.0
    realized_pnl: float = 0.0


@dataclass
class FakeOrderRecord:
    """OrderTrackerRecord 의 가드 평가 관련 최소 필드."""

    order_id: str
    ordered_qty: float
    recorded_filled_qty: float
    status: str
    submitted_at: str | None
    symbol: str = SYMBOL
    side: str = "buy"


class FakeOrderTracker:
    """`(account, bot, symbol, side)` 별 non-terminal 주문을 반환하는 가짜 tracker.

    `get_open_orders_for`는 실제 OrderTracker 와 동일하게 keyword 인자를 받으며,
    non-terminal(open/partially_filled) 주문만 보유하도록 시드된다(terminal 주문은
    리스트에서 제외). `raise_on_query=True`면 조회 시 예외를 던져 fail-closed
    경로를 검증한다.
    """

    def __init__(
        self,
        records: dict[tuple[str, str, str, str], list[FakeOrderRecord]] | None = None,
        *,
        raise_on_query: bool = False,
    ) -> None:
        self._records = records or {}
        self._raise = raise_on_query
        self.calls: list[dict[str, str]] = []

    async def get_open_orders_for(
        self, account_id: str, bot_id: str, symbol: str, side: str
    ) -> list[FakeOrderRecord]:
        self.calls.append(
            {
                "account_id": account_id,
                "bot_id": bot_id,
                "symbol": symbol,
                "side": side,
            }
        )
        if self._raise:
            raise RuntimeError("simulated OrderTracker query failure")
        return list(self._records.get((account_id, bot_id, symbol, side), []))

    # _on_order_modify 가 호출하는 인터페이스 — 본 테스트에서는 미사용.
    async def get(self, order_id: str) -> None:  # pragma: no cover - 미사용
        return None


class FakeTradeService:
    """symbol 별 position 을 반환하는 가짜 TradeService.

    `get_positions`는 실제 `TradeService.get_positions`와 동일하게 `bot_id`
    positional + keyword-only `account_id`(기본 None)를 받는다.
    `raise_on_query=True`면 예외를 던져 fail-closed 경로를 검증한다.
    """

    def __init__(
        self,
        positions: dict[str, list[FakePosition]] | None = None,
        *,
        raise_on_query: bool = False,
    ) -> None:
        self._positions = positions or {}
        self._raise = raise_on_query
        self.calls: list[dict[str, object]] = []

    async def get_positions(
        self,
        bot_id: str,
        include_closed: bool = False,
        *,
        account_id: str | None = None,
    ) -> list[FakePosition]:
        self.calls.append({"bot_id": bot_id, "account_id": account_id})
        if self._raise:
            raise RuntimeError("simulated get_positions failure")
        scoped = self._positions.get(account_id or "", [])
        return [p for p in scoped if p.bot_id == bot_id]


def _iso_age(seconds: float) -> str:
    """현재로부터 ``seconds`` 초 전의 tz-aware ISO 문자열."""
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


@dataclass
class _Captured:
    rejected: list[OrderRejectedEvent] = field(default_factory=list)
    validated: list[OrderValidatedEvent] = field(default_factory=list)


def _build_engine(
    eventbus: EventBus,
    *,
    order_tracker: FakeOrderTracker | None,
    trade_service: FakeTradeService | None,
    allow_overlap: bool = False,
    min_age: float = 60.0,
) -> RuleEngine:
    return RuleEngine(
        eventbus=eventbus,
        account_id=ACCOUNT,
        trade_service=trade_service,
        order_tracker=order_tracker,
        unrecovered_buy_guard_min_age=min_age,
        allow_unrecovered_buy_overlap=allow_overlap,
        # #2398: 계층1 gate 통과(미복구 매수 가드 동작만 검증하도록 readiness 통과).
        account=_gate_account(),
        runtime_readiness=_gate_ready_registry(),
    )


def _capture(eventbus: EventBus) -> _Captured:
    cap = _Captured()
    eventbus.subscribe(OrderRejectedEvent, lambda e: cap.rejected.append(e))
    eventbus.subscribe(OrderValidatedEvent, lambda e: cap.validated.append(e))
    return cap


def _buy_order(
    *,
    account_id: str = ACCOUNT,
    bot_id: str = BOT,
    symbol: str = SYMBOL,
    side: str = "buy",
) -> OrderRequestEvent:
    return OrderRequestEvent(
        account_id=account_id,
        bot_id=bot_id,
        strategy_id="s1",
        symbol=symbol,
        side=side,
        quantity=10.0,
        order_type="market",
        price=50000.0,
    )


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


class TestUnrecoveredBuyGuard:
    @pytest.mark.asyncio
    async def test_case1_block_unrecovered_open_self_buy(
        self, eventbus: EventBus
    ) -> None:
        """① 미복구 open self-buy(age≥60s) + position==0 + opt-out=false → 차단."""
        tracker = FakeOrderTracker(
            {
                (ACCOUNT, BOT, SYMBOL, "buy"): [
                    FakeOrderRecord(
                        order_id="o1",
                        ordered_qty=1.0,
                        recorded_filled_qty=0.0,
                        status="open",
                        submitted_at=_iso_age(120.0),
                    )
                ]
            }
        )
        trade = FakeTradeService({ACCOUNT: []})  # position 없음 → 수량 0
        engine = _build_engine(eventbus, order_tracker=tracker, trade_service=trade)
        engine.start()
        cap = _capture(eventbus)

        await eventbus.publish(_buy_order())

        assert len(cap.rejected) == 1
        assert len(cap.validated) == 0
        assert "Unrecovered buy guard" in cap.rejected[0].reason
        # position 조회가 자기 계좌로 스코핑되어 호출됐는지 확인.
        assert trade.calls[-1]["account_id"] == ACCOUNT

    @pytest.mark.asyncio
    async def test_case2_terminal_order_allows(self, eventbus: EventBus) -> None:
        """② 주문 terminal(취소/만료) 후 → 허용.

        terminal 주문은 `get_open_orders_for`(non-terminal only)에서 제외되므로
        tracker 가 빈 리스트를 반환한다 → 조건① 미충족 → 통과.
        """
        tracker = FakeOrderTracker({(ACCOUNT, BOT, SYMBOL, "buy"): []})
        trade = FakeTradeService({ACCOUNT: []})
        engine = _build_engine(eventbus, order_tracker=tracker, trade_service=trade)
        engine.start()
        cap = _capture(eventbus)

        await eventbus.publish(_buy_order())

        assert len(cap.rejected) == 0
        assert len(cap.validated) == 1

    @pytest.mark.asyncio
    async def test_case3_recorded_equals_ordered_allows(
        self, eventbus: EventBus
    ) -> None:
        """③ recorded==ordered(복구 완료) → 허용 (remaining=0 → 조건① 미충족)."""
        tracker = FakeOrderTracker(
            {
                (ACCOUNT, BOT, SYMBOL, "buy"): [
                    FakeOrderRecord(
                        order_id="o1",
                        ordered_qty=1.0,
                        recorded_filled_qty=1.0,
                        status="partially_filled",
                        submitted_at=_iso_age(120.0),
                    )
                ]
            }
        )
        trade = FakeTradeService({ACCOUNT: []})
        engine = _build_engine(eventbus, order_tracker=tracker, trade_service=trade)
        engine.start()
        cap = _capture(eventbus)

        await eventbus.publish(_buy_order())

        assert len(cap.rejected) == 0
        assert len(cap.validated) == 1

    @pytest.mark.asyncio
    async def test_case4_position_held_allows_scaling_in(
        self, eventbus: EventBus
    ) -> None:
        """④ position>0(합법적 분할매수/피라미딩) → 허용 (조건③ 미충족)."""
        tracker = FakeOrderTracker(
            {
                (ACCOUNT, BOT, SYMBOL, "buy"): [
                    FakeOrderRecord(
                        order_id="o1",
                        ordered_qty=1.0,
                        recorded_filled_qty=0.0,
                        status="open",
                        submitted_at=_iso_age(120.0),
                    )
                ]
            }
        )
        trade = FakeTradeService(
            {ACCOUNT: [FakePosition(bot_id=BOT, symbol=SYMBOL, quantity=5.0)]}
        )
        engine = _build_engine(eventbus, order_tracker=tracker, trade_service=trade)
        engine.start()
        cap = _capture(eventbus)

        await eventbus.publish(_buy_order())

        assert len(cap.rejected) == 0
        assert len(cap.validated) == 1

    @pytest.mark.asyncio
    async def test_case5_age_below_threshold_allows(self, eventbus: EventBus) -> None:
        """⑤ outstanding age < 60s(빠른 연속 주문) → 허용 (조건② 미충족)."""
        tracker = FakeOrderTracker(
            {
                (ACCOUNT, BOT, SYMBOL, "buy"): [
                    FakeOrderRecord(
                        order_id="o1",
                        ordered_qty=1.0,
                        recorded_filled_qty=0.0,
                        status="open",
                        submitted_at=_iso_age(5.0),  # 5초 전 → threshold 미만
                    )
                ]
            }
        )
        trade = FakeTradeService({ACCOUNT: []})
        engine = _build_engine(eventbus, order_tracker=tracker, trade_service=trade)
        engine.start()
        cap = _capture(eventbus)

        await eventbus.publish(_buy_order())

        assert len(cap.rejected) == 0
        assert len(cap.validated) == 1

    @pytest.mark.asyncio
    async def test_case6_opt_out_allows(self, eventbus: EventBus) -> None:
        """⑥ opt-out(allow_unrecovered_buy_overlap=true) → 허용 (조건④ 미충족).

        계좌 기본 opt-out 과 봇 단위 override 둘 다 검증한다.
        """
        tracker = FakeOrderTracker(
            {
                (ACCOUNT, BOT, SYMBOL, "buy"): [
                    FakeOrderRecord(
                        order_id="o1",
                        ordered_qty=1.0,
                        recorded_filled_qty=0.0,
                        status="open",
                        submitted_at=_iso_age(120.0),
                    )
                ]
            }
        )
        trade = FakeTradeService({ACCOUNT: []})

        # (a) 계좌 기본 opt-out=true.
        engine = _build_engine(
            eventbus, order_tracker=tracker, trade_service=trade, allow_overlap=True
        )
        engine.start()
        cap = _capture(eventbus)
        await eventbus.publish(_buy_order())
        assert len(cap.rejected) == 0
        assert len(cap.validated) == 1

        # (b) 계좌 기본은 false 이나 봇 단위 override=true.
        eventbus2 = EventBus()
        engine2 = _build_engine(
            eventbus2, order_tracker=tracker, trade_service=trade, allow_overlap=False
        )
        engine2.set_unrecovered_buy_overlap(BOT, True)
        engine2.start()
        cap2 = _capture(eventbus2)
        await eventbus2.publish(_buy_order())
        assert len(cap2.rejected) == 0
        assert len(cap2.validated) == 1

    @pytest.mark.asyncio
    async def test_case7_other_keys_not_blocked(self, eventbus: EventBus) -> None:
        """⑦ 다른 account/bot/symbol/side=sell → 비차단.

        tracker 는 `(ACCOUNT, BOT, SYMBOL, "buy")` 에만 미복구 주문을 시드한다.
        다른 키로 들어오는 주문은 조건①을 충족하지 못해 통과한다.
        """
        tracker = FakeOrderTracker(
            {
                (ACCOUNT, BOT, SYMBOL, "buy"): [
                    FakeOrderRecord(
                        order_id="o1",
                        ordered_qty=1.0,
                        recorded_filled_qty=0.0,
                        status="open",
                        submitted_at=_iso_age(120.0),
                    )
                ]
            }
        )
        trade = FakeTradeService({ACCOUNT: []})
        engine = _build_engine(eventbus, order_tracker=tracker, trade_service=trade)
        engine.start()
        cap = _capture(eventbus)

        # 다른 bot.
        await eventbus.publish(_buy_order(bot_id="bot2"))
        # 다른 symbol.
        await eventbus.publish(_buy_order(symbol="069500"))
        # side=sell (가드는 buy 전용; sell 은 inventory 검증 룰 대상 아님).
        await eventbus.publish(_buy_order(side="sell"))

        # 셋 모두 차단되지 않아야 한다.
        assert len(cap.rejected) == 0
        assert len(cap.validated) == 3

    @pytest.mark.asyncio
    async def test_case8_no_order_tracker_disables_guard(
        self, eventbus: EventBus
    ) -> None:
        """⑧ order_tracker 미주입 → 가드 비활성(허용).

        reconciler #1950 패턴 동형: tracker 미주입 시 self-check 생략 = allow.
        """
        trade = FakeTradeService({ACCOUNT: []})
        engine = _build_engine(eventbus, order_tracker=None, trade_service=trade)
        engine.start()
        cap = _capture(eventbus)

        await eventbus.publish(_buy_order())

        # tracker 미주입 → 가드는 일찍 None 반환(비활성)하고 통과시킨다.
        # (이후 evaluate 경로의 unrealized-PnL 계산이 get_positions 를 부르는 것은
        #  가드와 무관한 정상 흐름이므로 calls 자체로는 가드 활성 여부를 단정하지
        #  않는다 — reject 부재 + validated 발행으로 비활성을 확인한다.)
        assert len(cap.rejected) == 0
        assert len(cap.validated) == 1

    @pytest.mark.asyncio
    async def test_case9_query_exception_fail_closed_reject(
        self, eventbus: EventBus
    ) -> None:
        """⑨ OrderTracker/get_positions 조회 예외 → fail-closed reject (audit trail).

        가드 게이트는 조회 예외를 silent-pass 하지 않고 catch-all 로 전파시켜
        generic reject 를 강제 발행한다(#1302 fail-open 방지 invariant 보존).
        """
        # (a) OrderTracker 조회 예외.
        tracker = FakeOrderTracker(raise_on_query=True)
        trade = FakeTradeService({ACCOUNT: []})
        engine = _build_engine(eventbus, order_tracker=tracker, trade_service=trade)
        engine.start()
        cap = _capture(eventbus)

        await eventbus.publish(_buy_order())

        assert len(cap.rejected) == 1
        assert len(cap.validated) == 0
        assert "preflight error" in cap.rejected[0].reason

        # (b) get_positions 조회 예외 (OrderTracker 는 미복구 주문을 정상 반환).
        tracker2 = FakeOrderTracker(
            {
                (ACCOUNT, BOT, SYMBOL, "buy"): [
                    FakeOrderRecord(
                        order_id="o1",
                        ordered_qty=1.0,
                        recorded_filled_qty=0.0,
                        status="open",
                        submitted_at=_iso_age(120.0),
                    )
                ]
            }
        )
        trade2 = FakeTradeService(raise_on_query=True)
        eventbus2 = EventBus()
        engine2 = _build_engine(eventbus2, order_tracker=tracker2, trade_service=trade2)
        engine2.start()
        cap2 = _capture(eventbus2)

        await eventbus2.publish(_buy_order())

        assert len(cap2.rejected) == 1
        assert len(cap2.validated) == 0
        assert "preflight error" in cap2.rejected[0].reason


class TestUnrecoveredBuyAgeHelper:
    """`_unrecovered_buy_age_seconds` 의 age 산정 불가 케이스 회귀."""

    def test_none_submitted_at_returns_none(self) -> None:
        assert RuleEngine._unrecovered_buy_age_seconds(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert RuleEngine._unrecovered_buy_age_seconds("") is None

    def test_unparseable_returns_none(self) -> None:
        assert RuleEngine._unrecovered_buy_age_seconds("not-a-timestamp") is None

    def test_naive_datetime_returns_none(self) -> None:
        """naive(tz 미인지) datetime 은 오프셋 모호성으로 산정 불가."""
        naive = datetime.now().replace(tzinfo=None).isoformat()  # noqa: DTZ005
        assert RuleEngine._unrecovered_buy_age_seconds(naive) is None

    def test_aware_past_returns_positive_age(self) -> None:
        age = RuleEngine._unrecovered_buy_age_seconds(_iso_age(100.0))
        assert age is not None
        assert age >= 100.0

    def test_future_timestamp_clamped_to_zero(self) -> None:
        """미래 timestamp(음수 age)는 0.0 으로 클램프되어 threshold 를 넘지 않는다."""
        future = (datetime.now(UTC) + timedelta(seconds=300)).isoformat()
        assert RuleEngine._unrecovered_buy_age_seconds(future) == 0.0
