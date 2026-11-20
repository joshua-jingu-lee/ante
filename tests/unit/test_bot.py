"""Bot 모듈 단위 테스트."""

import asyncio
from typing import Any

import polars as pl
import pytest

from ante.bot import Bot, BotConfig, BotError, BotManager, BotStatus
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    AccountSuspendedEvent,
    BotErrorEvent,
    BotStartedEvent,
    BotStepCompletedEvent,
    BotStopEvent,
    BotStoppedEvent,
    OrderCancelEvent,
    OrderCancelFailedEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
)
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Signal,
    Strategy,
    StrategyContext,
    StrategyMeta,
)

# ── Fake 구현체 ──────────────────────────────────


class FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        return pl.DataFrame({"close": [100.0]})

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class FakePortfolioView(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1000000.0, "available": 500000.0}


class FakeOrderView(OrderView):
    def get_open_orders(self, bot_id):
        return []


class SimpleStrategy(Strategy):
    """테스트용 간단한 전략."""

    meta = StrategyMeta(name="simple", version="1.0.0", description="test")

    async def on_step(self, context):
        return []


class BuyStrategy(Strategy):
    """매수 시그널을 반환하는 전략."""

    meta = StrategyMeta(name="buy", version="1.0.0", description="test")

    async def on_step(self, context):
        return [
            Signal(
                symbol="005930",
                side="buy",
                quantity=10.0,
                reason="test buy",
            )
        ]


class ErrorStrategy(Strategy):
    """에러를 발생시키는 전략."""

    meta = StrategyMeta(name="error", version="1.0.0", description="test")
    call_count = 0

    async def on_step(self, context):
        ErrorStrategy.call_count += 1
        raise RuntimeError("strategy error")


class FillReactStrategy(Strategy):
    """체결 시 후속 시그널을 반환하는 전략."""

    meta = StrategyMeta(name="fill_react", version="1.0.0", description="test")

    async def on_step(self, context):
        return []

    async def on_fill(self, fill):
        return [
            Signal(
                symbol=fill["symbol"],
                side="sell",
                quantity=fill["quantity"],
                reason="stop loss after fill",
            )
        ]


# ── Fixtures ─────────────────────────────────────


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
def ctx():
    return StrategyContext(
        bot_id="bot1",
        data_provider=FakeDataProvider(),
        portfolio=FakePortfolioView(),
        order_view=FakeOrderView(),
    )


@pytest.fixture
def simple_config():
    return BotConfig(
        bot_id="bot1",
        strategy_id="simple_v1.0.0",
        interval_seconds=10,  # 테스트용: 최소 유효 간격
        account_id="acc-test",
    )


# ── BotConfig / BotStatus ────────────────────────


class TestBotConfig:
    def test_defaults(self):
        """BotConfig 기본값."""
        c = BotConfig(bot_id="b1", strategy_id="s1", account_id="acc-test")
        assert c.name == ""
        assert c.account_id == "acc-test"
        assert c.interval_seconds == 60

    def test_name_field(self):
        """BotConfig name 필드 설정."""
        c = BotConfig(
            bot_id="b1", strategy_id="s1", name="테스트 봇", account_id="acc-test"
        )
        assert c.name == "테스트 봇"

    def test_bot_status_values(self):
        """BotStatus 값."""
        assert BotStatus.CREATED == "created"
        assert BotStatus.RUNNING == "running"
        assert BotStatus.ERROR == "error"
        assert BotStatus.DELETED == "deleted"

    def test_interval_min_valid(self):
        """최소 간격 10초 허용."""
        c = BotConfig(
            bot_id="b1", strategy_id="s1", interval_seconds=10, account_id="acc-test"
        )
        assert c.interval_seconds == 10

    def test_interval_max_valid(self):
        """최대 간격 3600초 허용."""
        c = BotConfig(
            bot_id="b1", strategy_id="s1", interval_seconds=3600, account_id="acc-test"
        )
        assert c.interval_seconds == 3600

    def test_interval_below_min_raises(self):
        """10초 미만이면 ValueError."""
        with pytest.raises(ValueError, match="10초 이상"):
            BotConfig(
                bot_id="b1", strategy_id="s1", interval_seconds=5, account_id="acc-test"
            )

    def test_interval_above_max_raises(self):
        """3600초 초과면 ValueError."""
        with pytest.raises(ValueError, match="3600초 이하"):
            BotConfig(
                bot_id="b1",
                strategy_id="s1",
                interval_seconds=7200,
                account_id="acc-test",
            )

    def test_interval_zero_raises(self):
        """0초면 ValueError."""
        with pytest.raises(ValueError):
            BotConfig(
                bot_id="b1", strategy_id="s1", interval_seconds=0, account_id="acc-test"
            )

    def test_bot_config_account_scoped_required(self):
        """Refs #1241 SPLIT-2: account_id fallback (`""`/`"default"`/None)
        은 ``InvalidAccountIdError`` 로 거부된다.

        ``"test"`` 는 bootstrap seed 계좌이므로 runtime valid 이다 (Refs
        #1239 / SPLIT-1 정책 — ``ACCOUNT_ID_PATTERN`` 만 거치면 통과).
        """
        from ante.account.errors import InvalidAccountIdError

        # default 값 (account_id 미지정) → 빈 문자열 → 거부
        with pytest.raises(InvalidAccountIdError, match="account_id"):
            BotConfig(bot_id="b1", strategy_id="s1")

        # 명시적 빈 문자열 → 거부
        with pytest.raises(InvalidAccountIdError):
            BotConfig(bot_id="b1", strategy_id="s1", account_id="")

        # ``"default"`` fallback 예약어 → 거부
        with pytest.raises(InvalidAccountIdError):
            BotConfig(bot_id="b1", strategy_id="s1", account_id="default")

        # 패턴 위반 (특수문자) → 거부
        with pytest.raises(InvalidAccountIdError):
            BotConfig(bot_id="b1", strategy_id="s1", account_id="bad acct!")

        # 정상 account_id 는 통과
        c = BotConfig(bot_id="b1", strategy_id="s1", account_id="acc-test")
        assert c.account_id == "acc-test"

        # bootstrap seed ``"test"`` 는 runtime valid
        c2 = BotConfig(bot_id="b1", strategy_id="s1", account_id="test")
        assert c2.account_id == "test"


# ── Bot 생명주기 ─────────────────────────────────


class TestBot:
    async def test_start_publishes_event(self, eventbus, ctx, simple_config):
        """봇 시작 시 BotStartedEvent 발행."""
        received = []
        eventbus.subscribe(BotStartedEvent, lambda e: received.append(e))

        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        assert bot.status == BotStatus.RUNNING
        assert len(received) == 1
        assert received[0].bot_id == "bot1"

        await bot.stop()

    async def test_stop_publishes_event(self, eventbus, ctx, simple_config):
        """봇 중지 시 BotStoppedEvent 발행."""
        received = []
        eventbus.subscribe(BotStoppedEvent, lambda e: received.append(e))

        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await bot.stop()

        assert bot.status == BotStatus.STOPPED
        assert len(received) == 1

    async def test_stop_idempotent(self, eventbus, ctx, simple_config):
        """이미 중지된 봇은 다시 중지해도 무시."""
        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await bot.stop()
        await bot.stop()  # 두 번째 호출은 무시
        assert bot.status == BotStatus.STOPPED

    async def test_stop_from_error_state(self, eventbus, ctx, simple_config):
        """ERROR 상태의 봇을 stop()으로 STOPPED 전이."""
        received = []
        eventbus.subscribe(BotStoppedEvent, lambda e: received.append(e))

        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        # ERROR 상태를 직접 설정 (run_loop 예외 시 발생하는 상태)
        bot.status = BotStatus.ERROR
        bot.error_message = "some error"
        bot.strategy = SimpleStrategy(ctx=ctx)

        await bot.stop()

        assert bot.status == BotStatus.STOPPED
        assert bot.stopped_at is not None
        assert len(received) == 1
        # on_stop()이 호출되어 리소스 정리가 수행되었는지 검증
        assert bot.strategy is not None  # strategy 참조는 유지

    async def test_stop_from_error_cleans_task(self, eventbus, ctx):
        """ERROR 상태 봇의 stop()이 실행 중인 태스크를 정리."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="error_v1.0.0",
            interval_seconds=10,
            account_id="acc-test",
        )
        bot = Bot(
            config=config,
            strategy_cls=ErrorStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        # ErrorStrategy가 즉시 예외를 던져 ERROR 상태로 전이될 때까지 대기
        await asyncio.sleep(0.1)
        assert bot.status == BotStatus.ERROR

        await bot.stop()

        assert bot.status == BotStatus.STOPPED
        assert bot.stopped_at is not None

    async def test_signal_to_order_event(self, eventbus, ctx):
        """전략 Signal → OrderRequestEvent 변환."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="buy_v1.0.0",
            interval_seconds=10,
            account_id="acc-test",
        )
        received = []
        eventbus.subscribe(OrderRequestEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=BuyStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        # 루프가 한 번 실행될 시간을 줌
        await asyncio.sleep(0.05)
        await bot.stop()

        assert len(received) >= 1
        assert received[0].symbol == "005930"
        assert received[0].side == "buy"
        assert received[0].quantity == 10.0
        assert received[0].bot_id == "bot1"

    async def test_error_isolation(self, eventbus, ctx):
        """전략 에러 시 봇만 ERROR 상태로 전환."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="error_v1.0.0",
            interval_seconds=10,
            account_id="acc-test",
        )
        received = []
        eventbus.subscribe(BotErrorEvent, lambda e: received.append(e))

        ErrorStrategy.call_count = 0
        bot = Bot(
            config=config,
            strategy_cls=ErrorStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await asyncio.sleep(0.05)

        assert bot.status == BotStatus.ERROR
        assert bot.error_message == "strategy error"
        assert len(received) >= 1

    async def test_on_order_filled(self, eventbus, ctx, simple_config):
        """체결 통보 → 전략 on_fill() 호출 → 후속 Signal 발행."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="fill_react_v1.0.0",
            interval_seconds=999,  # 루프 호출 방지
            account_id="acc-test",
        )
        received = []
        eventbus.subscribe(OrderRequestEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=FillReactStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        # 체결 이벤트 전달
        await bot.on_order_filled(
            OrderFilledEvent(
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="bot1",
                strategy_id="fill_react_v1.0.0",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50000.0,
                order_type="market",
                account_id="acc-test",
            )
        )

        assert len(received) == 1
        assert received[0].side == "sell"
        assert received[0].reason == "stop loss after fill"

        await bot.stop()

    async def test_on_order_filled_ignores_other_bot(
        self, eventbus, ctx, simple_config
    ):
        """다른 봇의 체결 이벤트는 무시."""
        received = []
        eventbus.subscribe(OrderRequestEvent, lambda e: received.append(e))

        bot = Bot(
            config=simple_config,
            strategy_cls=FillReactStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_filled(
            OrderFilledEvent(
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="other_bot",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50000.0,
                order_type="market",
                account_id="acc-test",
            )
        )

        assert len(received) == 0
        await bot.stop()

    async def test_on_order_filled_bounded_dedup_nonempty_key(self, eventbus, ctx):
        """#1957: 같은 비빈키 fill 재전달 → follow-up 1회만 발행."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="fill_react_v1.0.0",
            interval_seconds=999,
            account_id="acc-test",
        )
        received = []
        eventbus.subscribe(OrderRequestEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=FillReactStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        event = OrderFilledEvent(
            order_id="ord1",
            broker_order_id="bk1",
            bot_id="bot1",
            strategy_id="fill_react_v1.0.0",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=50000.0,
            order_type="market",
            account_id="acc-test",
            fill_dedup_key="ord1:10.0",
        )
        await bot.on_order_filled(event)
        await bot.on_order_filled(event)

        # 재전달은 억제 — follow-up 1회만.
        assert len(received) == 1
        await bot.stop()

    async def test_on_order_filled_empty_key_not_deduped(self, eventbus, ctx):
        """#1957: 빈키 fill 재전달 → follow-up 2회 (dedup 비대상)."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="fill_react_v1.0.0",
            interval_seconds=999,
            account_id="acc-test",
        )
        received = []
        eventbus.subscribe(OrderRequestEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=FillReactStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        event = OrderFilledEvent(
            order_id="ord1",
            broker_order_id="bk1",
            bot_id="bot1",
            strategy_id="fill_react_v1.0.0",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=50000.0,
            order_type="market",
            account_id="acc-test",
            fill_dedup_key="",
        )
        await bot.on_order_filled(event)
        await bot.on_order_filled(event)

        assert len(received) == 2
        await bot.stop()

    async def test_on_order_filled_passes_dedup_key_to_strategy(self, eventbus, ctx):
        """#1957: strategy.on_fill dict 에 fill_dedup_key 가 전달된다."""
        captured_fills: list[dict] = []

        class CaptureStrategy(Strategy):
            meta = StrategyMeta(name="cap", version="1.0.0", description="t")

            async def on_step(self, context):
                return []

            async def on_fill(self, fill):
                captured_fills.append(fill)
                return []

        config = BotConfig(
            bot_id="bot1",
            strategy_id="cap_v1.0.0",
            interval_seconds=999,
            account_id="acc-test",
        )
        bot = Bot(
            config=config,
            strategy_cls=CaptureStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_filled(
            OrderFilledEvent(
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="bot1",
                strategy_id="cap_v1.0.0",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50000.0,
                order_type="market",
                account_id="acc-test",
                fill_dedup_key="ord1:10.0",
            )
        )

        assert len(captured_fills) == 1
        assert captured_fills[0]["fill_dedup_key"] == "ord1:10.0"
        await bot.stop()

    async def test_on_order_update_rejected(self, eventbus, ctx, simple_config):
        """주문 거부 통보 → 전략 on_order_update() 호출."""
        updates = []

        class TrackStrategy(Strategy):
            meta = StrategyMeta(name="t", version="1.0.0", description="t")

            async def on_step(self, context):
                return []

            async def on_order_update(self, update):
                updates.append(update)

        bot = Bot(
            config=simple_config,
            strategy_cls=TrackStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_update(
            OrderRejectedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="market",
                reason="insufficient funds",
                account_id="acc-test",
            )
        )

        assert len(updates) == 1
        assert updates[0]["status"] == "rejected"
        assert updates[0]["reason"] == "insufficient funds"

        await bot.stop()

    async def test_on_order_update_cancel_failed_forwards_symbol_side(
        self, eventbus, ctx, simple_config
    ):
        """#2044: cancel_failed 통보가 event.symbol/side 를 전략에 forward.

        하드코딩 ``symbol=""``/``side=""`` 제거 회귀 잠금 — Gateway 가 채운
        OrderCancelFailedEvent.symbol/side 가 그대로 전략 update 로 전달돼야
        한다.
        """
        updates = []

        class TrackStrategy(Strategy):
            meta = StrategyMeta(name="t", version="1.0.0", description="t")

            async def on_step(self, context):
                return []

            async def on_order_update(self, update):
                updates.append(update)

        bot = Bot(
            config=simple_config,
            strategy_cls=TrackStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_update(
            OrderCancelFailedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                error_message="브로커가 취소 실패(False)를 반환함",
                account_id="acc-test",
            )
        )

        assert len(updates) == 1
        assert updates[0]["status"] == "cancel_failed"
        assert updates[0]["symbol"] == "005930"
        assert updates[0]["side"] == "buy"
        assert updates[0]["reason"] == "브로커가 취소 실패(False)를 반환함"

        await bot.stop()

    async def test_drain_actions_cancel(self, eventbus, ctx, simple_config):
        """전략이 cancel_order() → OrderCancelEvent 발행."""

        class CancelStrategy(Strategy):
            meta = StrategyMeta(name="c", version="1.0.0", description="c")

            async def on_step(self, context):
                self.ctx.cancel_order("ord1", reason="test cancel")
                return []

        received = []
        eventbus.subscribe(OrderCancelEvent, lambda e: received.append(e))

        bot = Bot(
            config=BotConfig(
                bot_id="bot1",
                strategy_id="c_v1.0.0",
                interval_seconds=10,
                account_id="acc-test",
            ),
            strategy_cls=CancelStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await asyncio.sleep(0.05)
        await bot.stop()

        assert len(received) >= 1
        assert received[0].order_id == "ord1"
        assert received[0].reason == "test cancel"

    def test_get_info(self, eventbus, ctx, simple_config):
        """봇 상태 정보 반환."""
        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        info = bot.get_info()
        assert info["bot_id"] == "bot1"
        assert info["name"] == ""
        assert info["status"] == "created"
        # 기본값: 빈 문자열
        assert info["trading_mode"] == ""
        assert info["exchange"] == ""
        assert info["currency"] == ""

    def test_get_info_with_name(self, eventbus, ctx):
        """이름이 설정된 봇의 정보 반환."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            name="모멘텀 봇",
            interval_seconds=10,
            account_id="acc-test",
        )
        bot = Bot(
            config=config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        info = bot.get_info()
        assert info["name"] == "모멘텀 봇"

    def test_get_info_includes_trading_mode_exchange_currency(self, eventbus, ctx):
        """get_info()에 trading_mode, exchange, currency 포함."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=10, account_id="acc-test"
        )
        bot = Bot(
            config=config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
            exchange="KRX",
            trading_mode="live",
            currency="KRW",
        )
        info = bot.get_info()
        assert info["trading_mode"] == "live"
        assert info["exchange"] == "KRX"
        assert info["currency"] == "KRW"

    def test_get_info_returns_runtime_controls_in_config(self, eventbus, ctx):
        """#1458: get_info()["config"]가 runtime control 6필드를 nested로 노출."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            interval_seconds=10,
            account_id="acc-test",
            auto_restart=True,
            max_restart_attempts=5,
            restart_cooldown_seconds=120,
            step_timeout_seconds=45,
            max_signals_per_step=100,
        )
        bot = Bot(
            config=config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        info = bot.get_info()
        assert "config" in info
        nested = info["config"]
        assert nested == {
            "interval_seconds": 10,
            "auto_restart": True,
            "max_restart_attempts": 5,
            "restart_cooldown_seconds": 120,
            "step_timeout_seconds": 45,
            "max_signals_per_step": 100,
        }

    def test_get_info_config_reflects_updated_runtime_controls(
        self, eventbus, ctx, simple_config
    ):
        """#1458: BotConfig 필드 변경 후 get_info()가 새 값을 반영."""
        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        # BotConfig dataclass 의 mutable 필드를 직접 갱신
        bot.config.auto_restart = False
        bot.config.max_restart_attempts = 7
        bot.config.restart_cooldown_seconds = 200
        bot.config.step_timeout_seconds = 90
        bot.config.max_signals_per_step = 150

        info = bot.get_info()
        assert info["config"]["auto_restart"] is False
        assert info["config"]["max_restart_attempts"] == 7
        assert info["config"]["restart_cooldown_seconds"] == 200
        assert info["config"]["step_timeout_seconds"] == 90
        assert info["config"]["max_signals_per_step"] == 150

    def test_get_info_keeps_flat_interval_seconds(self, eventbus, ctx, simple_config):
        """#1458: backward compat — top-level interval_seconds 유지."""
        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        info = bot.get_info()
        assert info["interval_seconds"] == simple_config.interval_seconds
        # config nested 값과 동일해야 함
        assert info["config"]["interval_seconds"] == info["interval_seconds"]

    def test_get_info_no_top_level_runtime_controls(self, eventbus, ctx, simple_config):
        """#1458: 계약 중복 방지 — top-level에는 flat 5필드를 추가하지 않는다."""
        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        info = bot.get_info()
        for key in (
            "auto_restart",
            "max_restart_attempts",
            "restart_cooldown_seconds",
            "step_timeout_seconds",
            "max_signals_per_step",
        ):
            assert key not in info, (
                f"top-level에 {key}가 추가됨 — config nested에만 노출해야 함"
            )


# ── on_step ↔ on_external_signal 직렬화 lock ─────────

_real_sleep = asyncio.sleep


async def _spin(times: int = 20) -> None:
    """이벤트 루프를 시간 경과 없이 ``times`` 번 양보한다."""
    for _ in range(times):
        await _real_sleep(0)


class _LockProbeStrategy(Strategy):
    """on_step/on_data 호출을 기록하고, on_data 는 gate 가 열릴 때까지 붙잡는다."""

    meta = StrategyMeta(
        name="lock_probe",
        version="1.0.0",
        description="test",
        accepts_external_signals=True,
    )
    steps: list[object] = []
    data_calls: list[object] = []
    stepped: asyncio.Event | None = None
    data_entered: asyncio.Event | None = None
    data_gate: asyncio.Event | None = None

    @classmethod
    def reset(cls) -> None:
        cls.steps = []
        cls.data_calls = []
        cls.stepped = asyncio.Event()
        cls.data_entered = asyncio.Event()
        cls.data_gate = asyncio.Event()
        cls.data_gate.set()

    async def on_step(self, context):
        type(self).steps.append(self)
        assert type(self).stepped is not None
        type(self).stepped.set()
        return []

    async def on_data(self, data):
        type(self).data_calls.append(self)
        assert type(self).data_entered is not None
        assert type(self).data_gate is not None
        type(self).data_entered.set()
        await type(self).data_gate.wait()
        return []


def _external_signal(bot_id: str = "bot1") -> object:
    from ante.eventbus.events import ExternalSignalEvent

    return ExternalSignalEvent(
        account_id="acc-test",
        bot_id=bot_id,
        signal_id="sig-1",
        symbol="005930",
        action="buy",
    )


def _lock_probe_config() -> BotConfig:
    return BotConfig(
        bot_id="bot1",
        strategy_id="lock_probe_v1.0.0",
        interval_seconds=10,
        account_id="acc-test",
    )


class TestBotSignalLock:
    async def test_external_signal_waits_for_injected_lock(self, eventbus, ctx):
        """주입된 signal_lock 이 잡혀 있으면 on_data 는 풀릴 때까지 기다린다."""
        _LockProbeStrategy.reset()
        shared = asyncio.Lock()
        bot = Bot(
            config=_lock_probe_config(),
            strategy_cls=_LockProbeStrategy,
            ctx=ctx,
            eventbus=eventbus,
            signal_lock=shared,
        )
        bot.strategy = _LockProbeStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        await shared.acquire()
        task = asyncio.create_task(bot.on_external_signal(_external_signal()))
        await _spin()
        assert _LockProbeStrategy.data_calls == []
        assert not task.done()

        shared.release()
        await asyncio.wait_for(task, timeout=5.0)
        assert len(_LockProbeStrategy.data_calls) == 1

    async def test_run_loop_step_waits_for_injected_lock(
        self, eventbus, ctx, monkeypatch
    ):
        """on_step 은 signal_lock 안에서만 호출된다(lock 보유 중엔 시작하지 않는다)."""
        _LockProbeStrategy.reset()

        async def fake_sleep(delay):
            if delay == 10:
                bot.status = BotStatus.STOPPED
            await _real_sleep(0)

        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", fake_sleep)
        shared = asyncio.Lock()
        bot = Bot(
            config=_lock_probe_config(),
            strategy_cls=_LockProbeStrategy,
            ctx=ctx,
            eventbus=eventbus,
            signal_lock=shared,
        )
        bot.strategy = _LockProbeStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        await shared.acquire()
        loop_task = asyncio.create_task(bot._run_loop())
        await _spin()
        assert _LockProbeStrategy.steps == []

        shared.release()
        await asyncio.wait_for(loop_task, timeout=5.0)
        assert len(_LockProbeStrategy.steps) == 1

    async def test_interval_sleep_does_not_hold_lock(self, eventbus, ctx, monkeypatch):
        """step 사이 interval 대기 중에는 lock 을 놓아 외부 시그널이 처리된다."""
        _LockProbeStrategy.reset()
        sleeping = asyncio.Event()
        wake = asyncio.Event()
        intervals: list[float] = []

        async def fake_sleep(delay):
            if delay == 10:
                intervals.append(delay)
                sleeping.set()
                await wake.wait()
                return
            await _real_sleep(delay)

        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", fake_sleep)
        bot = Bot(
            config=_lock_probe_config(),
            strategy_cls=_LockProbeStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        bot.strategy = _LockProbeStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        loop_task = asyncio.create_task(bot._run_loop())
        await asyncio.wait_for(sleeping.wait(), timeout=5.0)
        assert len(_LockProbeStrategy.steps) == 1
        assert intervals == [10]

        signal_task = asyncio.create_task(bot.on_external_signal(_external_signal()))
        await _spin()
        try:
            assert len(_LockProbeStrategy.data_calls) == 1
            assert signal_task.done()
        finally:
            bot.status = BotStatus.STOPPED
            wake.set()
            await asyncio.wait_for(loop_task, timeout=5.0)
            await asyncio.wait_for(signal_task, timeout=5.0)


# ── BotManager ───────────────────────────────────


class TestBotManager:
    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        try:
            await asyncio.wait_for(database.close(), timeout=5.0)
        except TimeoutError:
            pass

    @pytest.fixture
    async def manager(self, eventbus, db):
        m = BotManager(eventbus=eventbus, db=db)
        await m.initialize()
        yield m
        # 모든 봇 태스크 강제 취소
        for bot in list(m._bots.values()):
            if bot._task and not bot._task.done():
                bot._task.cancel()
        # stop_all에도 timeout 적용
        try:
            await asyncio.wait_for(m.stop_all(), timeout=5.0)
        except TimeoutError:
            pass

    async def test_create_bot(self, manager, eventbus, ctx):
        """봇 생성."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        bot = await manager.create_bot(config, SimpleStrategy, ctx)
        assert bot.status == BotStatus.CREATED
        assert manager.get_bot("bot1") is bot

    async def test_create_duplicate_raises(self, manager, eventbus, ctx):
        """중복 봇 생성 시 에러."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        with pytest.raises(BotError, match="already exists"):
            await manager.create_bot(config, SimpleStrategy, ctx)

    async def test_start_and_stop(self, manager, eventbus, ctx):
        """봇 시작/중지."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.RUNNING

        await manager.stop_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.STOPPED

    async def test_remove_bot(self, manager, eventbus, ctx):
        """봇 삭제 (하위 호환 — remove_bot은 delete_bot 별칭)."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.remove_bot("bot1")
        assert manager.get_bot("bot1") is None

    async def test_delete_bot_soft_delete(self, manager, eventbus, ctx, db):
        """delete_bot은 DB 레코드를 삭제하지 않고 status를 deleted로 변경."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.delete_bot("bot1")

        # 메모리에서는 제거
        assert manager.get_bot("bot1") is None

        # DB에는 레코드가 남아있고 status가 deleted
        row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = 'bot1'")
        assert row is not None
        assert row["status"] == "deleted"

    async def test_delete_bot_stops_running(self, manager, eventbus, ctx, db):
        """실행 중인 봇 삭제 시 먼저 중지 후 deleted 처리."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.RUNNING

        await manager.delete_bot("bot1")
        assert manager.get_bot("bot1") is None

        row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = 'bot1'")
        assert row["status"] == "deleted"

    async def test_stop_all(self, manager, eventbus):
        """전체 봇 중지."""
        for i in range(3):
            ctx = StrategyContext(
                bot_id=f"bot{i}",
                data_provider=FakeDataProvider(),
                portfolio=FakePortfolioView(),
                order_view=FakeOrderView(),
            )
            config = BotConfig(
                bot_id=f"bot{i}",
                strategy_id=f"s{i}",
                interval_seconds=999,
                account_id="acc-test",
            )
            await manager.create_bot(config, SimpleStrategy, ctx)
            await manager.start_bot(f"bot{i}")

        await manager.stop_all()
        for i in range(3):
            assert manager.get_bot(f"bot{i}").status == BotStatus.STOPPED

    async def test_list_bots(self, manager, eventbus, ctx):
        """봇 목록 조회."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        bots = manager.list_bots()
        assert len(bots) == 1
        assert bots[0]["bot_id"] == "bot1"

    async def test_bot_stop_event(self, manager, eventbus, ctx):
        """BotStopEvent 수신 시 봇 중지."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        await eventbus.publish(
            BotStopEvent(account_id="acc-test", bot_id="bot1", reason="rule violation")
        )

        assert manager.get_bot("bot1").status == BotStatus.STOPPED

    async def test_account_suspended_stops_bots(self, manager, eventbus, ctx):
        """AccountSuspendedEvent 시 해당 계좌의 봇만 중지."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        await eventbus.publish(
            AccountSuspendedEvent(
                account_id="acc-test",
                reason="critical",
                suspended_by="system",
            )
        )

        assert manager.get_bot("bot1").status == BotStatus.STOPPED

    async def test_not_found_raises(self, manager):
        """존재하지 않는 봇 시작 시 에러."""
        with pytest.raises(BotError, match="not found"):
            await manager.start_bot("nonexistent")

    async def test_single_bot_per_strategy_running(self, manager, eventbus):
        """실행 중인 봇의 전략으로 새 봇 생성 시 에러."""
        ctx1 = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        ctx2 = StrategyContext(
            bot_id="bot2",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        config1 = BotConfig(
            bot_id="bot1",
            strategy_id="same_stg",
            interval_seconds=999,
            account_id="acc-test",
        )
        config2 = BotConfig(
            bot_id="bot2",
            strategy_id="same_stg",
            interval_seconds=999,
            account_id="acc-test",
        )
        await manager.create_bot(config1, SimpleStrategy, ctx1)
        await manager.start_bot("bot1")

        with pytest.raises(BotError, match="이미 봇"):
            await manager.create_bot(config2, SimpleStrategy, ctx2)

        await manager.stop_bot("bot1")

    async def test_single_bot_per_strategy_stopped_reuse(self, manager, eventbus):
        """중지된 봇의 전략은 재사용 가능."""
        ctx1 = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        ctx2 = StrategyContext(
            bot_id="bot2",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        config1 = BotConfig(
            bot_id="bot1",
            strategy_id="same_stg",
            interval_seconds=999,
            account_id="acc-test",
        )
        config2 = BotConfig(
            bot_id="bot2",
            strategy_id="same_stg",
            interval_seconds=999,
            account_id="acc-test",
        )
        await manager.create_bot(config1, SimpleStrategy, ctx1)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1")

        # stopped 상태이므로 같은 전략으로 생성 가능
        bot2 = await manager.create_bot(config2, SimpleStrategy, ctx2)
        assert bot2.status == BotStatus.CREATED

    async def test_single_bot_per_strategy_different_strategy(self, manager, eventbus):
        """다른 전략이면 봇 생성 정상."""
        ctx1 = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        ctx2 = StrategyContext(
            bot_id="bot2",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        config1 = BotConfig(
            bot_id="bot1",
            strategy_id="stg_a",
            interval_seconds=999,
            account_id="acc-test",
        )
        config2 = BotConfig(
            bot_id="bot2",
            strategy_id="stg_b",
            interval_seconds=999,
            account_id="acc-test",
        )
        await manager.create_bot(config1, SimpleStrategy, ctx1)
        await manager.start_bot("bot1")

        bot2 = await manager.create_bot(config2, SimpleStrategy, ctx2)
        assert bot2.status == BotStatus.CREATED

        await manager.stop_bot("bot1")

    async def test_bot_config_persisted(self, manager, eventbus, ctx, db):
        """봇 설정이 DB에 저장됨."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = 'bot1'")
        assert row is not None
        assert row["strategy_id"] == "s1"

    async def test_bot_name_persisted(self, manager, eventbus, ctx, db):
        """봇 이름이 DB에 저장됨."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", name="모멘텀 봇", account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)

        row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = 'bot1'")
        assert row is not None
        assert row["name"] == "모멘텀 봇"

    async def test_bot_config_account_id(self, manager, eventbus, ctx, db):
        """account_id 필드 존재 및 기본값."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        assert config.account_id == "acc-test"

        config2 = BotConfig(bot_id="bot2", strategy_id="s2", account_id="domestic")
        assert config2.account_id == "domestic"

    async def test_bot_config_no_bot_type(self):
        """BotConfig에서 bot_type, exchange 필드가 제거되었음."""
        config = BotConfig(bot_id="b1", strategy_id="s1", account_id="acc-test")
        assert not hasattr(config, "bot_type")
        assert not hasattr(config, "exchange")

    async def test_create_bot_with_account(self, manager, eventbus, ctx, db):
        """BotManager.create_bot()에 account_id 전달 및 DB 저장."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="domestic")
        bot = await manager.create_bot(config, SimpleStrategy, ctx)
        assert bot.config.account_id == "domestic"

        row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = 'bot1'")
        assert row is not None
        assert row["account_id"] == "domestic"

    async def test_order_request_has_account(self, eventbus, ctx):
        """OrderRequestEvent에 account_id 포함."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="buy_v1.0.0",
            account_id="my-account",
            interval_seconds=10,
        )
        received = []
        eventbus.subscribe(OrderRequestEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=BuyStrategy,
            ctx=ctx,
            eventbus=eventbus,
            exchange="KRX",
        )
        await bot.start()
        await asyncio.sleep(0.05)
        await bot.stop()

        assert len(received) >= 1
        assert received[0].account_id == "my-account"
        assert received[0].exchange == "KRX"

    async def test_load_bot_from_db_with_account(self, manager, eventbus, ctx, db):
        """DB 복원 시 account_id 유지."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="domestic")
        await manager.create_bot(config, SimpleStrategy, ctx)

        # 새 매니저로 DB에서 로드
        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        count = await manager2.load_from_db()
        assert count == 1

        bot = manager2.get_bot("bot1")
        assert bot is not None
        assert bot.config.account_id == "domestic"

    async def test_load_bot_migration_old_format(self, manager, eventbus, db):
        """기존 bot_type/exchange 포함 config_json → account_id 마이그레이션."""
        import json

        # 기존 형식으로 직접 DB에 삽입
        old_config = json.dumps(
            {
                "bot_id": "old-bot",
                "strategy_id": "s1",
                "bot_type": "legacy",
                "exchange": "KRX",
                "interval_seconds": 60,
            }
        )
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("old-bot", "old", "s1", "test", old_config, "created"),
        )

        # 새 매니저로 로드 — bot_type/exchange 무시, account_id 사용
        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        count = await manager2.load_from_db()
        assert count >= 1

        bot = manager2.get_bot("old-bot")
        assert bot is not None
        assert bot.config.account_id == "test"
        # bot_type, exchange는 BotConfig에 없으므로 속성 자체가 존재하지 않음
        assert not hasattr(bot.config, "bot_type")
        assert not hasattr(bot.config, "exchange")

    async def test_bot_manager_load_bots_account_scoped_invalid_skip(
        self, manager, eventbus, ctx, db, caplog
    ):
        """Refs #1241 SPLIT-2: legacy invalid account_id row 는 skip + warning.

        SPLIT-1 패턴: ``BotConfig.__post_init__`` 가
        ``InvalidAccountIdError`` 를 raise 해도 read 경로는 실패하지 않고,
        해당 row 만 건너뛴다. 형식 위반 / ``"default"`` / ``""`` row 가
        전체 ``load_from_db`` 를 깨뜨리지 않도록 보장한다.
        """
        import json
        import logging

        # 정상 row 1건 + invalid row 2건 직접 삽입
        valid_config = json.dumps({"interval_seconds": 60})
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("good-bot", "good", "s1", "domestic", valid_config, "created"),
        )
        # invalid: 빈 문자열
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("blank-bot", "blank", "s1", "", valid_config, "created"),
        )
        # invalid: ``"default"``
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("legacy-default-bot", "legacy", "s1", "default", valid_config, "created"),
        )

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        with caplog.at_level(logging.WARNING):
            count = await manager2.load_from_db()

        # invalid 2건은 skip, valid 1건만 로드된다
        assert count == 1
        assert manager2.get_bot("good-bot") is not None
        assert manager2.get_bot("blank-bot") is None
        assert manager2.get_bot("legacy-default-bot") is None
        # warning log 가 invalid row 마다 남아있어야 한다 (legacy migration 가시화)
        warn_messages = [r.message for r in caplog.records if r.levelno >= 30]
        assert any("blank-bot" in m for m in warn_messages)
        assert any("legacy-default-bot" in m for m in warn_messages)

    async def test_bot_get_info_has_account(self, eventbus, ctx, simple_config):
        """get_info()에 account_id 포함, bot_type 없음."""
        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        info = bot.get_info()
        assert "account_id" in info
        assert info["account_id"] == "acc-test"
        assert "bot_type" not in info

    async def test_bot_started_event_has_account_id(self, eventbus, ctx):
        """봇 시작 시 BotStartedEvent에 account_id 포함."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            account_id="my-account",
            interval_seconds=999,
        )
        received = []
        eventbus.subscribe(BotStartedEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        assert len(received) == 1
        assert received[0].account_id == "my-account"
        await bot.stop()

    async def test_bot_stopped_event_has_account_id(self, eventbus, ctx):
        """봇 중지 시 BotStoppedEvent에 account_id 포함."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            account_id="my-account",
            interval_seconds=999,
        )
        received = []
        eventbus.subscribe(BotStoppedEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await bot.stop()
        assert len(received) == 1
        assert received[0].account_id == "my-account"

    async def test_cancel_event_has_account_id(self, eventbus, ctx):
        """OrderCancelEvent에 account_id 포함."""

        class CancelStrategy(Strategy):
            meta = StrategyMeta(name="c", version="1.0.0", description="c")

            async def on_step(self, context):
                self.ctx.cancel_order("ord1", reason="test cancel")
                return []

        config = BotConfig(
            bot_id="bot1",
            strategy_id="c_v1.0.0",
            account_id="acct-1",
            interval_seconds=10,
        )
        received = []
        eventbus.subscribe(OrderCancelEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=CancelStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await asyncio.sleep(0.05)
        await bot.stop()

        assert len(received) >= 1
        assert received[0].account_id == "acct-1"

    async def test_duplicate_bot_id_raises_bot_already_exists(
        self, manager, eventbus, ctx
    ):
        """같은 bot_id 로 다시 만들면 BotAlreadyExistsError(BOT_ALREADY_EXISTS)."""
        from ante.bot.exceptions import BotAlreadyExistsError

        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        again = BotConfig(bot_id="bot1", strategy_id="s2", account_id="acc-test")
        with pytest.raises(BotAlreadyExistsError) as exc_info:
            await manager.create_bot(again, SimpleStrategy, ctx)
        assert exc_info.value.code == "BOT_ALREADY_EXISTS"

    async def test_load_from_db_propagates_corrupt_config_json(
        self, manager, eventbus, db
    ):
        """config_json 파싱 실패는 행 건너뛰기로 삼키지 않고 그대로 전파된다."""
        import json

        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("corrupt-bot", "corrupt", "s1", "acc-test", "{not json", "created"),
        )
        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        with pytest.raises(json.JSONDecodeError):
            await manager2.load_from_db()

    async def test_recreated_bot_shares_signal_lock_with_previous_instance(
        self, manager, eventbus, ctx
    ):
        """같은 bot_id 로 다시 만든 봇은 이전 인스턴스와 같은 signal lock 을 쓴다.

        이전 봇의 외부 시그널 처리(on_data)가 끝나기 전에는 새 봇의 on_step 이
        시작하지 않는다.
        """
        _LockProbeStrategy.reset()
        config = BotConfig(
            bot_id="bot1",
            strategy_id="lock_probe",
            interval_seconds=999,
            account_id="acc-test",
        )
        old = await manager.create_bot(config, _LockProbeStrategy, ctx)
        await manager.start_bot("bot1")
        assert _LockProbeStrategy.stepped is not None
        await asyncio.wait_for(_LockProbeStrategy.stepped.wait(), timeout=5.0)
        old_strategy = old.strategy

        assert _LockProbeStrategy.data_gate is not None
        assert _LockProbeStrategy.data_entered is not None
        _LockProbeStrategy.data_gate.clear()
        signal_task = asyncio.create_task(old.on_external_signal(_external_signal()))
        await asyncio.wait_for(_LockProbeStrategy.data_entered.wait(), timeout=5.0)

        await manager.delete_bot("bot1")
        _LockProbeStrategy.stepped.clear()
        new_config = BotConfig(
            bot_id="bot1",
            strategy_id="lock_probe",
            interval_seconds=999,
            account_id="acc-test",
        )
        new = await manager.create_bot(new_config, _LockProbeStrategy, ctx)
        assert new is not old
        await manager.start_bot("bot1")
        await _spin()
        assert [s for s in _LockProbeStrategy.steps if s is not old_strategy] == []

        _LockProbeStrategy.data_gate.set()
        await asyncio.wait_for(signal_task, timeout=5.0)
        await asyncio.wait_for(_LockProbeStrategy.stepped.wait(), timeout=5.0)
        assert [s for s in _LockProbeStrategy.steps if s is new.strategy] != []


# ── Exchange 호환성 검증 (BotManager) ───────────────


class TestBotManagerExchangeValidation:
    """BotManager.create_bot() exchange 호환성 검증 테스트."""

    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        try:
            await asyncio.wait_for(database.close(), timeout=5.0)
        except TimeoutError:
            pass

    @pytest.fixture
    async def account_service(self, db, eventbus):
        from ante.account.service import AccountService

        svc = AccountService(db=db, eventbus=eventbus)
        await svc.initialize()
        return svc

    @pytest.fixture
    async def manager_with_account(self, eventbus, db, account_service):
        m = BotManager(eventbus=eventbus, db=db, account_service=account_service)
        await m.initialize()
        yield m
        for bot in list(m._bots.values()):
            if bot._task and not bot._task.done():
                bot._task.cancel()
        try:
            await asyncio.wait_for(m.stop_all(), timeout=5.0)
        except TimeoutError:
            pass

    async def test_compatible_exchange_allowed(
        self, manager_with_account, account_service, ctx
    ):
        """동일 exchange 조합은 봇 생성 허용."""
        from ante.account.models import Account

        account = Account(
            account_id="krx-acct",
            name="국내계좌",
            exchange="KRX",
            currency="KRW",
            broker_type="test",
            credentials={"app_key": "test", "app_secret": "test"},
        )
        await account_service.create(account)
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="krx-acct")
        # SimpleStrategy.meta.exchange는 기본값 "KRX"
        bot = await manager_with_account.create_bot(config, SimpleStrategy, ctx)
        assert bot.status == BotStatus.CREATED

    async def test_incompatible_exchange_rejected(
        self, manager_with_account, account_service, ctx
    ):
        """KRX 전략 + NYSE 계좌 → IncompatibleExchangeError."""
        from ante.account.models import Account
        from ante.strategy.exceptions import IncompatibleExchangeError

        account = Account(
            account_id="nyse-acct",
            name="미국계좌",
            exchange="NYSE",
            currency="USD",
            broker_type="test",
            credentials={"app_key": "test", "app_secret": "test"},
        )
        await account_service.create(account)
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="nyse-acct")
        with pytest.raises(IncompatibleExchangeError, match="simple"):
            await manager_with_account.create_bot(config, SimpleStrategy, ctx)

    async def test_wildcard_exchange_allowed(
        self, manager_with_account, account_service, ctx
    ):
        """전략 exchange='*'이면 어떤 계좌든 허용."""
        from ante.account.models import Account

        class WildcardStrategy(Strategy):
            meta = StrategyMeta(
                name="wildcard",
                version="1.0.0",
                description="test",
                exchange="*",
            )

            async def on_step(self, context):
                return []

        account = Account(
            account_id="nyse-acct",
            name="미국계좌",
            exchange="NYSE",
            currency="USD",
            broker_type="test",
            credentials={"app_key": "test", "app_secret": "test"},
        )
        await account_service.create(account)
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="nyse-acct")
        bot = await manager_with_account.create_bot(config, WildcardStrategy, ctx)
        assert bot.status == BotStatus.CREATED

    async def test_no_account_service_skips_validation(self, eventbus, db, ctx):
        """AccountService 미주입 시 exchange 검증 스킵."""
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="any-acct")
        # account_service가 없으므로 검증 스킵, 정상 생성
        bot = await manager.create_bot(config, SimpleStrategy, ctx)
        assert bot.status == BotStatus.CREATED


# ── 정지·재시작을 건넌 외부 시그널과 옛 실행 루프 ─────────


class _ProbeLock(asyncio.Lock):
    """``acquire`` 에 들어온 태스크를 차례로 기록하는 계측용 잠금."""

    def __init__(self) -> None:
        super().__init__()
        self.entered: list[object] = []
        self._entry = asyncio.Event()

    async def acquire(self) -> bool:
        self.entered.append(asyncio.current_task())
        self._entry.set()
        return await super().acquire()

    async def wait_entered(self, task: object) -> None:
        async def until() -> None:
            while task not in self.entered:
                self._entry.clear()
                await self._entry.wait()

        await asyncio.wait_for(until(), timeout=5.0)

    async def wait_entries(self, count: int) -> None:
        async def until() -> None:
            while len(self.entered) < count:
                self._entry.clear()
                await self._entry.wait()

        await asyncio.wait_for(until(), timeout=5.0)


class _IntervalGate:
    """``interval_seconds`` 대기를 태스크마다 ``asyncio.Event`` 로 여닫는 가짜 sleep.

    깨어난 뒤에도 반드시 한 번 양보하고, 호출 횟수에 상한을 둔다.
    """

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.sleeping: dict[object, asyncio.Event] = {}
        self.calls = 0
        self._changed = asyncio.Event()

    async def sleep(self, delay: float) -> None:
        if delay != self.interval:
            await _real_sleep(delay)
            return
        self.calls += 1
        if self.calls > 50:
            raise RuntimeError("interval sleep cap exceeded")
        task = asyncio.current_task()
        wake = asyncio.Event()
        self.sleeping[task] = wake
        self._changed.set()
        try:
            await wake.wait()
        finally:
            self.sleeping.pop(task, None)
        await _real_sleep(0)

    async def wait_sleeping(self, task: object) -> None:
        async def until() -> None:
            while task not in self.sleeping:
                self._changed.clear()
                await self._changed.wait()

        await asyncio.wait_for(until(), timeout=5.0)

    async def settle(self, task: object) -> None:
        """``task`` 가 끝나거나 간격 대기에 들어갈 때까지 기다린다(취소하지 않는다)."""
        assert isinstance(task, asyncio.Task)
        sleeper = asyncio.create_task(self.wait_sleeping(task))
        try:
            await asyncio.wait(
                {task, sleeper}, timeout=5.0, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            sleeper.cancel()
            await asyncio.gather(sleeper, return_exceptions=True)

    def wake(self, task: object) -> None:
        self.sleeping[task].set()


class _RecordingPortfolio(FakePortfolioView):
    """조회한 태스크를 기록하고, ``raise_for`` 태스크의 조회는 실패시킨다."""

    def __init__(self) -> None:
        self.calls: list[object] = []
        self.raise_for: object = None

    def get_positions(self, bot_id):
        task = asyncio.current_task()
        self.calls.append(task)
        if task is self.raise_for:
            raise RuntimeError("portfolio lookup failed")
        return {}


class _RecorderBase(Strategy):
    """호출한 인스턴스·태스크·signal_id 를 기록하고, 지정한 지점에서 붙잡힌다."""

    meta = StrategyMeta(
        name="gen_probe",
        version="1.0.0",
        description="test",
        accepts_external_signals=True,
    )
    steps: list[tuple[Strategy, object]]
    data_calls: list[tuple[Strategy, str]]
    stepped: asyncio.Event
    data_entered: asyncio.Event
    hold_step: asyncio.Event | None
    fail_held_step: bool
    hold_data: dict[str, asyncio.Event]
    data_signals: Any

    @staticmethod
    def step_signals(count: int) -> list:
        return []

    async def on_step(self, context):
        cls = type(self)
        cls.steps.append((self, asyncio.current_task()))
        cls.stepped.set()
        if cls.hold_step is not None and len(cls.steps) == 1:
            await cls.hold_step.wait()
            if cls.fail_held_step:
                raise RuntimeError("on_step failed")
        return cls.step_signals(len(cls.steps))

    async def on_data(self, data):
        cls = type(self)
        signal_id = data["signal_id"]
        cls.data_calls.append((self, signal_id))
        gate = cls.hold_data.get(signal_id)
        if gate is not None:
            cls.data_entered.set()
            await gate.wait()
        if cls.data_signals is not None:
            return cls.data_signals(signal_id)
        return [Signal(symbol="005930", side="buy", quantity=1.0, reason=signal_id)]

    @classmethod
    async def wait_steps(cls, count: int) -> None:
        async def until() -> None:
            while len(cls.steps) < count:
                cls.stepped.clear()
                await cls.stepped.wait()

        await asyncio.wait_for(until(), timeout=5.0)


def _recorder(**attrs: object) -> type[_RecorderBase]:
    namespace: dict[str, object] = {
        "steps": [],
        "data_calls": [],
        "stepped": asyncio.Event(),
        "data_entered": asyncio.Event(),
        "hold_step": None,
        "fail_held_step": False,
        "hold_data": {},
        "data_signals": None,
    }
    namespace.update(attrs)
    return type("_Recorder", (_RecorderBase,), namespace)


def _gen_signal(signal_id: str) -> object:
    from ante.eventbus.events import ExternalSignalEvent

    return ExternalSignalEvent(
        account_id="acc-test",
        bot_id="bot1",
        signal_id=signal_id,
        symbol="005930",
        action="buy",
    )


def _gen_config(**overrides: object) -> BotConfig:
    values: dict = {
        "bot_id": "bot1",
        "strategy_id": "gen_probe",
        "interval_seconds": 999,
        "account_id": "acc-test",
    }
    values.update(overrides)
    return BotConfig(**values)


def _collect(eventbus: EventBus, *event_types: type) -> list[tuple[object, object]]:
    seen: list[tuple[object, object]] = []
    for event_type in event_types:
        eventbus.subscribe(
            event_type,
            lambda e: seen.append((e, asyncio.current_task())),
            priority=1000,
        )
    return seen


def _rejections(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "ante.bot.bot" and r.getMessage().startswith("외부 시그널 거부")
    ]


class TestBotSignalAcrossStopAndRestart:
    """잠금을 기다리던 외부 시그널과 옛 실행 루프는 정지·재시작을 건너지 못한다."""

    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await asyncio.wait_for(database.close(), timeout=5.0)

    @pytest.fixture
    async def pending(self):
        tasks: list[asyncio.Task] = []
        yield tasks
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=5.0
        )

    @pytest.fixture
    async def manager(self, eventbus, db):
        m = BotManager(eventbus=eventbus, db=db)
        await m.initialize()
        m._bot_signal_locks["bot1"] = _ProbeLock()
        yield m
        loops = [b._task for b in m._bots.values() if b._task and not b._task.done()]
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
        for task in loops:
            task.cancel()
        await asyncio.wait_for(
            asyncio.gather(*loops, return_exceptions=True), timeout=5.0
        )

    @staticmethod
    def _probe(manager: BotManager) -> _ProbeLock:
        lock = manager._bot_signal_locks["bot1"]
        assert isinstance(lock, _ProbeLock)
        return lock

    async def test_waiting_signal_is_dropped_after_stop(
        self, manager, eventbus, ctx, pending, caplog
    ):
        """on_step 이 쥔 잠금을 기다리던 시그널은 stop_bot 뒤 실행되지 않는다."""
        strategy_cls = _recorder(hold_step=asyncio.Event())
        orders = _collect(eventbus, OrderRequestEvent)
        probe = self._probe(manager)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)
        assert probe.locked()

        publisher = asyncio.create_task(eventbus.publish(_gen_signal("sig-B")))
        pending.append(publisher)
        await probe.wait_entered(publisher)

        with caplog.at_level("WARNING", logger="ante.bot.bot"):
            await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)
            await asyncio.wait_for(publisher, timeout=5.0)

        assert bot.status == BotStatus.STOPPED
        assert strategy_cls.data_calls == []
        assert [e for e, _ in orders if e.reason == "sig-B"] == []
        assert any("bot1" in m and "signal_id=sig-B" in m for m in _rejections(caplog))

    @staticmethod
    async def _stop_then_resume(manager: BotManager) -> None:
        await manager.stop_bot("bot1")
        await manager.resume_bot("bot1")

    @staticmethod
    async def _assign_strategy(manager: BotManager) -> None:
        await manager.assign_strategy("bot1", "gen_probe_v2")

    @staticmethod
    async def _stop_then_resume_twice(manager: BotManager) -> None:
        for _ in range(2):
            await manager.stop_bot("bot1")
            await manager.resume_bot("bot1")

    @pytest.mark.parametrize(
        "restart",
        ["_stop_then_resume", "_assign_strategy", "_stop_then_resume_twice"],
    )
    async def test_waiting_signal_is_dropped_after_restart(
        self, manager, eventbus, ctx, pending, caplog, restart
    ):
        """다른 on_data 의 잠금을 기다리던 시그널은 재시작 뒤 새 전략에 닿지 않는다."""
        strategy_cls = _recorder(hold_data={"sig-A": asyncio.Event()})
        orders = _collect(eventbus, OrderRequestEvent)
        probe = self._probe(manager)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)
        first = bot.strategy

        publisher_a = asyncio.create_task(eventbus.publish(_gen_signal("sig-A")))
        pending.append(publisher_a)
        await asyncio.wait_for(strategy_cls.data_entered.wait(), timeout=5.0)
        assert probe.locked()
        publisher_b = asyncio.create_task(eventbus.publish(_gen_signal("sig-B")))
        pending.append(publisher_b)
        await probe.wait_entered(publisher_b)

        await asyncio.wait_for(getattr(self, restart)(manager), timeout=5.0)
        assert bot.status == BotStatus.RUNNING
        second = bot.strategy
        assert second is not first

        with caplog.at_level("WARNING", logger="ante.bot.bot"):
            strategy_cls.hold_data["sig-A"].set()
            await asyncio.wait_for(publisher_a, timeout=5.0)
            await asyncio.wait_for(publisher_b, timeout=5.0)

        assert [s for s, _ in strategy_cls.data_calls if s is second] == []
        assert [sid for _, sid in strategy_cls.data_calls if sid == "sig-B"] == []
        assert [e for e, _ in orders if e.reason == "sig-B"] == []
        assert any("bot1" in m and "signal_id=sig-B" in m for m in _rejections(caplog))
        assert bot.status == BotStatus.RUNNING

    async def test_signal_released_while_restart_publishes_is_dropped(
        self, manager, eventbus, ctx, pending
    ):
        """재개가 BotStartedEvent 를 발행하는 동안 잠금을 얻은 시그널도 버려진다."""
        strategy_cls = _recorder(hold_data={"sig-A": asyncio.Event()})
        orders = _collect(eventbus, OrderRequestEvent)
        probe = self._probe(manager)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)

        publisher_a = asyncio.create_task(eventbus.publish(_gen_signal("sig-A")))
        pending.append(publisher_a)
        await asyncio.wait_for(strategy_cls.data_entered.wait(), timeout=5.0)
        publisher_b = asyncio.create_task(eventbus.publish(_gen_signal("sig-B")))
        pending.append(publisher_b)
        await probe.wait_entered(publisher_b)

        async def release_while_starting(event: object) -> None:
            strategy_cls.hold_data["sig-A"].set()
            await asyncio.wait_for(publisher_a, timeout=5.0)
            await asyncio.wait_for(publisher_b, timeout=5.0)

        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)
        eventbus.subscribe(BotStartedEvent, release_while_starting, priority=1000)
        await asyncio.wait_for(manager.resume_bot("bot1"), timeout=5.0)

        assert publisher_b.done()
        assert bot.status == BotStatus.RUNNING
        assert [sid for _, sid in strategy_cls.data_calls if sid == "sig-B"] == []
        assert [e for e, _ in orders if e.reason == "sig-B"] == []

    async def test_old_loop_woken_while_restart_publishes_ends_without_step(
        self, manager, eventbus, monkeypatch, pending
    ):
        """재개가 BotStartedEvent 를 발행하는 동안 깨어난 옛 루프도 스텝 없이 끝난다."""
        (
            strategy_cls,
            gate,
            portfolio,
            bot,
        ) = await self._orphan_loop_after_in_chain_stop(manager, eventbus, monkeypatch)
        old_loop = strategy_cls.steps[0][1]
        assert isinstance(old_loop, asyncio.Task)
        pending.append(old_loop)
        lifecycle = _collect(eventbus, BotErrorEvent, BotStepCompletedEvent)
        lookups_before = portfolio.calls.count(old_loop)

        async def wake_while_starting(event: object) -> None:
            gate.wake(old_loop)
            await gate.settle(old_loop)

        eventbus.subscribe(BotStartedEvent, wake_while_starting, priority=1000)
        await asyncio.wait_for(manager.resume_bot("bot1"), timeout=5.0)

        assert [t for _, t in strategy_cls.steps if t is old_loop] == [old_loop]
        assert portfolio.calls.count(old_loop) == lookups_before
        assert [e for e, t in lifecycle if t is old_loop] == []
        assert old_loop.done()
        assert old_loop.result() is None
        assert bot.status == BotStatus.RUNNING

        await strategy_cls.wait_steps(2)
        new_loop = strategy_cls.steps[1][1]
        assert new_loop is not old_loop
        await gate.wait_sleeping(new_loop)
        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)

    async def test_waiting_signal_is_dropped_after_error(
        self, manager, eventbus, ctx, pending
    ):
        """on_step 예외로 ERROR 가 되는 동안 기다리던 시그널은 실행되지 않는다."""
        strategy_cls = _recorder(hold_step=asyncio.Event(), fail_held_step=True)
        orders = _collect(eventbus, OrderRequestEvent)
        probe = self._probe(manager)
        bot = await manager.create_bot(
            _gen_config(auto_restart=False), strategy_cls, ctx
        )
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)

        publisher = asyncio.create_task(eventbus.publish(_gen_signal("sig-B")))
        pending.append(publisher)
        await probe.wait_entered(publisher)

        assert strategy_cls.hold_step is not None
        strategy_cls.hold_step.set()
        await asyncio.wait_for(publisher, timeout=5.0)

        assert bot.status == BotStatus.ERROR
        assert strategy_cls.data_calls == []
        assert [e for e, _ in orders if e.reason == "sig-B"] == []

    async def test_waiting_signal_is_dropped_after_delete(
        self, manager, eventbus, ctx, pending
    ):
        """잠금을 쥔 on_data 를 기다리던 시그널은 delete_bot 뒤 실행되지 않는다."""
        strategy_cls = _recorder(hold_data={"sig-A": asyncio.Event()})
        orders = _collect(eventbus, OrderRequestEvent)
        probe = self._probe(manager)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)

        publisher_a = asyncio.create_task(eventbus.publish(_gen_signal("sig-A")))
        pending.append(publisher_a)
        await asyncio.wait_for(strategy_cls.data_entered.wait(), timeout=5.0)
        publisher_b = asyncio.create_task(eventbus.publish(_gen_signal("sig-B")))
        pending.append(publisher_b)
        await probe.wait_entered(publisher_b)

        await asyncio.wait_for(manager.delete_bot("bot1"), timeout=5.0)
        assert bot.status == BotStatus.DELETED

        strategy_cls.hold_data["sig-A"].set()
        await asyncio.wait_for(publisher_a, timeout=5.0)
        await asyncio.wait_for(publisher_b, timeout=5.0)

        assert [sid for _, sid in strategy_cls.data_calls if sid == "sig-B"] == []
        assert [e for e, _ in orders if e.reason == "sig-B"] == []

    async def test_waiting_signal_is_dropped_after_account_suspended(
        self, manager, eventbus, ctx, pending
    ):
        """잠금을 쥔 on_data 를 기다리던 시그널은 계좌 정지 뒤 실행되지 않는다."""
        strategy_cls = _recorder(hold_data={"sig-A": asyncio.Event()})
        orders = _collect(eventbus, OrderRequestEvent)
        probe = self._probe(manager)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)

        publisher_a = asyncio.create_task(eventbus.publish(_gen_signal("sig-A")))
        pending.append(publisher_a)
        await asyncio.wait_for(strategy_cls.data_entered.wait(), timeout=5.0)
        publisher_b = asyncio.create_task(eventbus.publish(_gen_signal("sig-B")))
        pending.append(publisher_b)
        await probe.wait_entered(publisher_b)

        await asyncio.wait_for(
            eventbus.publish(
                AccountSuspendedEvent(
                    account_id="acc-test", reason="test", suspended_by="test"
                )
            ),
            timeout=5.0,
        )
        assert bot.status == BotStatus.STOPPED

        strategy_cls.hold_data["sig-A"].set()
        await asyncio.wait_for(publisher_a, timeout=5.0)
        await asyncio.wait_for(publisher_b, timeout=5.0)

        assert [sid for _, sid in strategy_cls.data_calls if sid == "sig-B"] == []
        assert [e for e, _ in orders if e.reason == "sig-B"] == []

    @staticmethod
    async def _orphan_loop_after_in_chain_stop(
        manager: BotManager, eventbus: EventBus, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[type[_RecorderBase], _IntervalGate, _RecordingPortfolio, Bot]:
        """끝의 단언은 옛 루프가 남은 시나리오에 도달했는지 확인하는 장치다."""
        gate = _IntervalGate(999)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        portfolio = _RecordingPortfolio()
        ctx = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=portfolio,
            order_view=FakeOrderView(),
        )

        def first_step_stops(count: int) -> list:
            if count == 1:
                return [
                    Signal(symbol="005930", side="buy", quantity=1.0, reason="stop")
                ]
            return []

        strategy_cls = _recorder(step_signals=staticmethod(first_step_stops))

        async def stop_in_chain(event: object) -> None:
            if isinstance(event, OrderRequestEvent) and event.reason == "stop":
                await eventbus.publish(
                    BotStopEvent(account_id="acc-test", bot_id="bot1", reason="rule")
                )

        eventbus.subscribe(OrderRequestEvent, stop_in_chain)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)
        old_loop = strategy_cls.steps[0][1]
        await gate.wait_sleeping(old_loop)
        assert bot.status == BotStatus.STOPPED
        assert isinstance(old_loop, asyncio.Task)
        assert not old_loop.done()
        return strategy_cls, gate, portfolio, bot

    async def test_old_loop_after_in_chain_stop_ends_without_touching_new_generation(
        self, manager, eventbus, monkeypatch, pending
    ):
        """사슬 안 정지로 남은 옛 루프는 재개 뒤 깨어나도 아무것도 하지 않고 끝난다."""
        (
            strategy_cls,
            gate,
            portfolio,
            bot,
        ) = await self._orphan_loop_after_in_chain_stop(manager, eventbus, monkeypatch)
        old_loop = strategy_cls.steps[0][1]
        assert isinstance(old_loop, asyncio.Task)
        pending.append(old_loop)
        lifecycle = _collect(eventbus, BotErrorEvent, BotStepCompletedEvent)

        await asyncio.wait_for(manager.resume_bot("bot1"), timeout=5.0)
        await strategy_cls.wait_steps(2)
        new_loop = strategy_cls.steps[1][1]
        assert new_loop is not old_loop
        await gate.wait_sleeping(new_loop)
        lookups_before = portfolio.calls.count(old_loop)

        gate.wake(old_loop)
        await gate.settle(old_loop)

        assert [t for _, t in strategy_cls.steps if t is old_loop] == [old_loop]
        assert portfolio.calls.count(old_loop) == lookups_before
        assert [e for e, t in lifecycle if t is old_loop] == []
        assert old_loop.done()
        assert old_loop.result() is None
        assert bot.status == BotStatus.RUNNING
        assert set(gate.sleeping) == {new_loop}

        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)
        assert isinstance(new_loop, asyncio.Task)
        assert new_loop.done()

    async def test_old_loop_failing_before_lock_does_not_error_new_generation(
        self, manager, eventbus, monkeypatch, pending
    ):
        """옛 루프가 잠금 전에 실패해도 새 세대는 ERROR 가 되지 않는다."""
        (
            strategy_cls,
            gate,
            portfolio,
            bot,
        ) = await self._orphan_loop_after_in_chain_stop(manager, eventbus, monkeypatch)
        old_loop = strategy_cls.steps[0][1]
        assert isinstance(old_loop, asyncio.Task)
        pending.append(old_loop)
        errors = _collect(eventbus, BotErrorEvent)

        await asyncio.wait_for(manager.resume_bot("bot1"), timeout=5.0)
        await strategy_cls.wait_steps(2)
        new_loop = strategy_cls.steps[1][1]
        await gate.wait_sleeping(new_loop)

        portfolio.raise_for = old_loop
        gate.wake(old_loop)
        await gate.settle(old_loop)

        assert bot.status == BotStatus.RUNNING
        assert bot.error_message is None
        assert errors == []
        assert old_loop.done()
        assert old_loop.result() is None
        assert set(gate.sleeping) == {new_loop}
        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)

    async def test_old_loop_failing_after_mid_step_restart_keeps_new_generation(
        self, manager, eventbus, monkeypatch, pending, caplog
    ):
        """스텝 도중 정지·재개된 뒤 옛 루프가 예외로 끝나도 새 세대는 그대로다.

        발행 경로를 바꿔 끼워 그 상태를 직접 만드는 선제 검사다.
        """
        gate = _IntervalGate(999)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        strategy_cls = _recorder(step_signals=_first_step_signals("stop", "after"))
        lifecycle = _collect(eventbus, BotErrorEvent, BotStepCompletedEvent)
        ctx = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        original_publish = bot._publish_signals
        restarted: list[object] = []

        async def restart_then_fail(signals: list, **kwargs: object) -> None:
            if not restarted:
                restarted.append(asyncio.current_task())
                await manager.stop_bot("bot1")
                await manager.resume_bot("bot1")
                raise RuntimeError("publish failed")
            await original_publish(signals, **kwargs)

        monkeypatch.setattr(bot, "_publish_signals", restart_then_fail)
        with caplog.at_level("WARNING", logger="ante.bot.bot"):
            await manager.start_bot("bot1")
            await strategy_cls.wait_steps(1)
            old_loop = strategy_cls.steps[0][1]
            assert isinstance(old_loop, asyncio.Task)
            pending.append(old_loop)
            await gate.settle(old_loop)

        assert restarted == [old_loop]
        assert old_loop.done()
        assert old_loop.result() is None
        assert bot.status == BotStatus.RUNNING
        assert bot.error_message is None
        assert [e for e, t in lifecycle if t is old_loop] == []
        ignored = [
            r
            for r in caplog.records
            if r.name == "ante.bot.bot"
            and r.getMessage().startswith("옛 세대 루프 예외 무시")
        ]
        assert len(ignored) == 1
        assert "bot1" in ignored[0].getMessage()
        assert "1 → 2" in ignored[0].getMessage()
        assert ignored[0].exc_info is not None

        await strategy_cls.wait_steps(2)
        new_loop = strategy_cls.steps[1][1]
        assert new_loop is not old_loop
        await gate.wait_sleeping(new_loop)
        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)

    async def test_loop_waiting_on_lock_skips_step_when_not_running(
        self, eventbus, ctx, monkeypatch, pending
    ):
        """잠금을 기다리던 루프는 잠금을 얻은 뒤 RUNNING 이 아니면 on_step 없이 끝난다.

        정지가 잠금을 기다리는 구조(PR-2)를 위한 선제 검사다.
        """
        gate = _IntervalGate(10)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        strategy_cls = _recorder()
        lifecycle = _collect(eventbus, BotErrorEvent, BotStepCompletedEvent)
        probe = _ProbeLock()
        bot = Bot(
            config=_lock_probe_config(),
            strategy_cls=strategy_cls,
            ctx=ctx,
            eventbus=eventbus,
            signal_lock=probe,
        )
        await probe.acquire()
        await bot.start()
        await probe.wait_entries(2)
        old_loop = probe.entered[1]
        assert isinstance(old_loop, asyncio.Task)
        pending.append(old_loop)

        bot.status = BotStatus.STOPPED
        probe.release()
        await gate.settle(old_loop)

        assert strategy_cls.steps == []
        assert old_loop.done()
        assert old_loop.result() is None
        assert bot.status == BotStatus.STOPPED
        assert lifecycle == []

    async def test_loop_waiting_on_lock_skips_step_after_restart(
        self, eventbus, ctx, monkeypatch, pending
    ):
        """잠금을 기다리던 루프는 그 사이 봇이 다시 시작됐으면 on_step 없이 끝난다.

        정지가 잠금을 기다리는 구조(PR-2)를 위한 선제 검사다.
        """
        gate = _IntervalGate(10)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        strategy_cls = _recorder()
        lifecycle = _collect(eventbus, BotErrorEvent, BotStepCompletedEvent)
        probe = _ProbeLock()
        bot = Bot(
            config=_lock_probe_config(),
            strategy_cls=strategy_cls,
            ctx=ctx,
            eventbus=eventbus,
            signal_lock=probe,
        )
        await probe.acquire()
        await bot.start()
        await probe.wait_entries(2)
        old_loop = probe.entered[1]
        assert isinstance(old_loop, asyncio.Task)
        pending.append(old_loop)

        bot.status = BotStatus.STOPPED
        await bot.start()
        await probe.wait_entries(3)
        new_loop = probe.entered[2]
        assert new_loop is not old_loop

        probe.release()
        await gate.settle(old_loop)
        await gate.settle(new_loop)

        assert [t for _, t in strategy_cls.steps] == [new_loop]
        assert [e for e, t in lifecycle if t is old_loop] == []
        assert old_loop.done()
        assert old_loop.result() is None
        assert bot.status == BotStatus.RUNNING

        await asyncio.wait_for(bot.stop(), timeout=5.0)
        assert isinstance(new_loop, asyncio.Task)
        assert new_loop.done()

    async def test_waiting_signal_runs_while_bot_keeps_running(
        self, manager, eventbus, ctx, pending
    ):
        """실행 중인 봇에서 잠금을 기다리던 시그널은 잠금을 얻은 뒤 처리된다."""
        strategy_cls = _recorder(hold_step=asyncio.Event())
        orders = _collect(eventbus, OrderRequestEvent)
        probe = self._probe(manager)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)

        publisher = asyncio.create_task(eventbus.publish(_gen_signal("sig-B")))
        pending.append(publisher)
        await probe.wait_entered(publisher)

        assert strategy_cls.hold_step is not None
        strategy_cls.hold_step.set()
        await asyncio.wait_for(publisher, timeout=5.0)

        assert strategy_cls.data_calls == [(bot.strategy, "sig-B")]
        assert [e.reason for e, _ in orders] == ["sig-B"]
        assert bot.status == BotStatus.RUNNING

    async def test_signal_to_stopped_bot_is_rejected_with_log(
        self, manager, eventbus, ctx, caplog
    ):
        """정지된 봇에 온 시그널은 on_data 없이 「외부 시그널 거부」 로그를 남긴다."""
        strategy_cls = _recorder()
        await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)
        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)

        with caplog.at_level("WARNING", logger="ante.bot.bot"):
            await asyncio.wait_for(eventbus.publish(_gen_signal("sig-B")), timeout=5.0)

        assert strategy_cls.data_calls == []
        assert any("bot1" in m and "signal_id=sig-B" in m for m in _rejections(caplog))

    async def test_bot_without_start_still_runs_loop_and_signal(
        self, eventbus, ctx, monkeypatch
    ):
        """start() 없이 상태만 RUNNING 인 봇에서도 루프와 시그널이 동작한다."""
        gate = _IntervalGate(10)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        strategy_cls = _recorder()
        bot = Bot(
            config=_lock_probe_config(),
            strategy_cls=strategy_cls,
            ctx=ctx,
            eventbus=eventbus,
        )
        bot.strategy = strategy_cls(ctx=ctx)
        bot.status = BotStatus.RUNNING

        await asyncio.wait_for(
            bot.on_external_signal(_gen_signal("sig-B")), timeout=5.0
        )
        assert strategy_cls.data_calls == [(bot.strategy, "sig-B")]

        loop_task = asyncio.create_task(bot._run_loop())
        await strategy_cls.wait_steps(1)
        await gate.wait_sleeping(loop_task)
        assert [t for _, t in strategy_cls.steps] == [loop_task]

        bot.status = BotStatus.STOPPED
        gate.wake(loop_task)
        assert await asyncio.wait_for(loop_task, timeout=5.0) is None


# ── 정지가 시작된 봇의 주문 관문 ─────────


def _two_signals(first: str, second: str) -> Any:
    def build(*_: object) -> list:
        return [
            Signal(symbol="005930", side="buy", quantity=1.0, reason=first),
            Signal(symbol="000660", side="buy", quantity=1.0, reason=second),
        ]

    return staticmethod(build)


def _first_step_signals(first: str, second: str) -> Any:
    def build(count: int) -> list:
        if count != 1:
            return []
        return [
            Signal(symbol="005930", side="buy", quantity=1.0, reason=first),
            Signal(symbol="000660", side="buy", quantity=1.0, reason=second),
        ]

    return staticmethod(build)


def _dropped_logs(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "ante.bot.bot" and r.getMessage().startswith("주문 요청 버림")
    ]


class _ActionFailingContext(StrategyContext):
    """``fail`` 이 서 있으면 대기 액션을 꺼낼 때 예외를 낸다."""

    fail = False

    def _drain_actions(self):
        if self.fail:
            raise RuntimeError("drain failed")
        return super()._drain_actions()


class _PositionsTradeService:
    """청산 대상 포지션 하나를 돌려주는 TradeService 대역."""

    async def get_positions(self, bot_id, include_closed=False, *, account_id=None):
        class _Position:
            symbol = "005930"
            quantity = 3.0
            exchange = "KRX"

        position = _Position()
        position.account_id = account_id  # type: ignore[attr-defined]
        return [position]


class TestBotOrderGateAfterStop:
    """정지가 시작된 봇의 on_step·on_data 시그널은 주문 요청으로 발행되지 않는다."""

    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await asyncio.wait_for(database.close(), timeout=5.0)

    @pytest.fixture
    async def pending(self):
        tasks: list[asyncio.Task] = []
        yield tasks
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=5.0
        )

    @pytest.fixture
    async def manager(self, eventbus, db):
        m = BotManager(eventbus=eventbus, db=db)
        await m.initialize()
        m._bot_signal_locks["bot1"] = _ProbeLock()
        yield m
        loops = [b._task for b in m._bots.values() if b._task and not b._task.done()]
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
        for task in loops:
            task.cancel()
        await asyncio.wait_for(
            asyncio.gather(*loops, return_exceptions=True), timeout=5.0
        )

    @staticmethod
    async def _stop(manager: BotManager, eventbus: EventBus) -> None:
        await manager.stop_bot("bot1")

    @staticmethod
    async def _delete(manager: BotManager, eventbus: EventBus) -> None:
        await manager.delete_bot("bot1")

    @staticmethod
    async def _suspend(manager: BotManager, eventbus: EventBus) -> None:
        await eventbus.publish(
            AccountSuspendedEvent(
                account_id="acc-test", reason="test", suspended_by="test"
            )
        )

    @pytest.mark.parametrize("transition", ["_stop", "_delete", "_suspend"])
    async def test_running_on_data_orders_are_dropped_after_stop(
        self, manager, eventbus, ctx, pending, caplog, transition
    ):
        """실행 중인 on_data 가 정지·삭제·계좌 정지 뒤 돌려준 시그널은 버려진다."""
        strategy_cls = _recorder(
            hold_data={"sig-A": asyncio.Event()},
            data_signals=_two_signals("sig-A", "sig-A"),
        )
        orders = _collect(eventbus, OrderRequestEvent)
        await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)

        publisher = asyncio.create_task(eventbus.publish(_gen_signal("sig-A")))
        pending.append(publisher)
        await asyncio.wait_for(strategy_cls.data_entered.wait(), timeout=5.0)

        await asyncio.wait_for(getattr(self, transition)(manager, eventbus), 5.0)
        with caplog.at_level("WARNING", logger="ante.bot.bot"):
            strategy_cls.hold_data["sig-A"].set()
            await asyncio.wait_for(publisher, timeout=5.0)

        assert [e for e, _ in orders if e.reason == "sig-A"] == []
        dropped = _dropped_logs(caplog)
        assert len(dropped) == 1
        assert "bot1" in dropped[0] and "2건" in dropped[0]

    async def test_running_on_data_orders_are_dropped_after_stop_and_resume(
        self, manager, eventbus, ctx, pending
    ):
        """정지·재개를 건넌 실행 중 on_data 의 시그널은 새 세대에서도 버려진다."""
        strategy_cls = _recorder(hold_data={"sig-A": asyncio.Event()})
        orders = _collect(eventbus, OrderRequestEvent)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)

        publisher = asyncio.create_task(eventbus.publish(_gen_signal("sig-A")))
        pending.append(publisher)
        await asyncio.wait_for(strategy_cls.data_entered.wait(), timeout=5.0)

        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)
        await asyncio.wait_for(manager.resume_bot("bot1"), timeout=5.0)
        assert bot.status == BotStatus.RUNNING

        strategy_cls.hold_data["sig-A"].set()
        await asyncio.wait_for(publisher, timeout=5.0)

        assert [e for e, _ in orders if e.reason == "sig-A"] == []

    async def test_remaining_step_signals_are_dropped_after_in_chain_stop(
        self, manager, eventbus, ctx, monkeypatch, caplog
    ):
        """첫 주문 요청의 처리 중에 정지되면 같은 스텝의 남은 시그널은 버려진다."""
        gate = _IntervalGate(999)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        strategy_cls = _recorder(step_signals=_first_step_signals("stop", "after"))
        orders = _collect(eventbus, OrderRequestEvent)

        async def stop_in_chain(event: object) -> None:
            if isinstance(event, OrderRequestEvent) and event.reason == "stop":
                await eventbus.publish(
                    BotStopEvent(account_id="acc-test", bot_id="bot1", reason="rule")
                )

        eventbus.subscribe(OrderRequestEvent, stop_in_chain)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        with caplog.at_level("WARNING", logger="ante.bot.bot"):
            await manager.start_bot("bot1")
            await strategy_cls.wait_steps(1)
            await gate.settle(strategy_cls.steps[0][1])

        assert bot.status == BotStatus.STOPPED
        assert [e.reason for e, _ in orders] == ["stop"]
        dropped = _dropped_logs(caplog)
        assert len(dropped) == 1
        assert "bot1" in dropped[0] and "1건" in dropped[0]

    async def test_remaining_data_signals_are_dropped_after_in_chain_stop(
        self, manager, eventbus, ctx, caplog
    ):
        """on_data 의 첫 주문 요청 처리 중에 정지되면 남은 시그널은 발행되지 않는다."""
        strategy_cls = _recorder(data_signals=_two_signals("stop", "after"))
        orders = _collect(eventbus, OrderRequestEvent)

        async def stop_in_chain(event: object) -> None:
            if isinstance(event, OrderRequestEvent) and event.reason == "stop":
                await eventbus.publish(
                    BotStopEvent(account_id="acc-test", bot_id="bot1", reason="rule")
                )

        eventbus.subscribe(OrderRequestEvent, stop_in_chain)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)

        with caplog.at_level("WARNING", logger="ante.bot.bot"):
            await asyncio.wait_for(eventbus.publish(_gen_signal("sig-A")), timeout=5.0)

        assert bot.status == BotStatus.STOPPED
        assert [e.reason for e, _ in orders] == ["stop"]
        dropped = _dropped_logs(caplog)
        assert len(dropped) == 1
        assert "bot1" in dropped[0] and "1건" in dropped[0]

    async def test_old_loop_skips_step_tail_after_mid_step_restart(
        self, manager, eventbus, monkeypatch, pending
    ):
        """한 스텝 안에서 정지·재개되면 옛 루프는 스텝의 나머지를 내지 않는다.

        남은 시그널, 새 세대의 대기 액션, 스텝 완료 이벤트가 해당한다.
        """
        gate = _IntervalGate(999)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        ctx = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        strategy_cls = _recorder(step_signals=_first_step_signals("stop", "after"))
        orders = _collect(eventbus, OrderRequestEvent)
        cancels = _collect(eventbus, OrderCancelEvent)
        completed = _collect(eventbus, BotStepCompletedEvent)
        stopped = asyncio.Event()
        resumed = asyncio.Event()

        async def stop_and_wait_for_resume(event: object) -> None:
            if isinstance(event, OrderRequestEvent) and event.reason == "stop":
                await eventbus.publish(
                    BotStopEvent(account_id="acc-test", bot_id="bot1", reason="rule")
                )
                stopped.set()
                await resumed.wait()

        eventbus.subscribe(OrderRequestEvent, stop_and_wait_for_resume)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await asyncio.wait_for(stopped.wait(), timeout=5.0)
        old_loop = strategy_cls.steps[0][1]
        assert isinstance(old_loop, asyncio.Task)
        pending.append(old_loop)

        await asyncio.wait_for(manager.resume_bot("bot1"), timeout=5.0)
        ctx.cancel_order("ord-new", reason="new generation")
        resumed.set()
        await gate.settle(old_loop)

        assert [e.reason for e, _ in orders] == ["stop"]
        assert [e for e, t in completed if t is old_loop] == []
        assert [e for e, t in cancels if t is old_loop] == []
        assert old_loop.done()
        assert old_loop.result() is None

        await strategy_cls.wait_steps(2)
        new_loop = strategy_cls.steps[1][1]
        await gate.settle(new_loop)
        assert [e.order_id for e, t in cancels if t is new_loop] == ["ord-new"]
        assert bot.status == BotStatus.RUNNING
        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)

    async def test_in_chain_stop_is_not_overwritten_by_error(
        self, manager, eventbus, monkeypatch, caplog
    ):
        """사슬 안 정지 뒤 꼬리에서 예외가 나도 STOPPED 가 ERROR 로 덮이지 않는다."""
        gate = _IntervalGate(999)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        ctx = _ActionFailingContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        strategy_cls = _recorder(step_signals=_first_step_signals("stop", "after"))
        lifecycle = _collect(eventbus, BotErrorEvent, BotStepCompletedEvent)

        async def stop_in_chain(event: object) -> None:
            if isinstance(event, OrderRequestEvent) and event.reason == "stop":
                await eventbus.publish(
                    BotStopEvent(account_id="acc-test", bot_id="bot1", reason="rule")
                )
                ctx.fail = True

        eventbus.subscribe(OrderRequestEvent, stop_in_chain)
        bot = await manager.create_bot(_gen_config(), strategy_cls, ctx)
        with caplog.at_level("WARNING", logger="ante.bot.bot"):
            await manager.start_bot("bot1")
            await strategy_cls.wait_steps(1)
            loop = strategy_cls.steps[0][1]
            await gate.settle(loop)

        assert isinstance(loop, asyncio.Task)
        assert loop.done()
        assert loop.result() is None
        assert bot.status == BotStatus.STOPPED
        assert bot.error_message is None
        assert lifecycle == []
        assert manager.get_restart_count("bot1") == 0
        ignored = [
            r
            for r in caplog.records
            if r.name == "ante.bot.bot" and r.getMessage().startswith("루프 예외 무시")
        ]
        assert len(ignored) == 1
        assert "bot1" in ignored[0].getMessage()
        assert ignored[0].exc_info is not None

    async def test_orders_stay_closed_after_error_until_resume(
        self, manager, eventbus, monkeypatch, pending
    ):
        """on_data 실행 중 ERROR 가 되면 그 시그널은 버려지고, 재개 뒤에는 발행된다."""
        gate = _IntervalGate(999)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        portfolio = _RecordingPortfolio()
        ctx = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=portfolio,
            order_view=FakeOrderView(),
        )
        strategy_cls = _recorder(hold_data={"sig-A": asyncio.Event()})
        orders = _collect(eventbus, OrderRequestEvent)
        bot = await manager.create_bot(
            _gen_config(auto_restart=False), strategy_cls, ctx
        )
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)
        loop = strategy_cls.steps[0][1]
        await gate.wait_sleeping(loop)

        publisher = asyncio.create_task(eventbus.publish(_gen_signal("sig-A")))
        pending.append(publisher)
        await asyncio.wait_for(strategy_cls.data_entered.wait(), timeout=5.0)

        portfolio.raise_for = loop
        gate.wake(loop)
        await gate.settle(loop)
        assert bot.status == BotStatus.ERROR

        strategy_cls.hold_data["sig-A"].set()
        await asyncio.wait_for(publisher, timeout=5.0)
        assert [e for e, _ in orders if e.reason == "sig-A"] == []

        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)
        await asyncio.wait_for(manager.resume_bot("bot1"), timeout=5.0)
        await asyncio.wait_for(eventbus.publish(_gen_signal("sig-C")), timeout=5.0)
        assert [e.reason for e, _ in orders] == ["sig-C"]

    async def test_running_bot_publishes_step_and_data_signals(
        self, manager, eventbus, ctx, monkeypatch
    ):
        """실행 중인 봇의 on_step·on_data 시그널은 그대로 발행된다."""
        gate = _IntervalGate(999)
        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", gate.sleep)
        strategy_cls = _recorder(step_signals=_first_step_signals("step-1", "step-2"))
        orders = _collect(eventbus, OrderRequestEvent)
        await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)
        await gate.wait_sleeping(strategy_cls.steps[0][1])

        await asyncio.wait_for(eventbus.publish(_gen_signal("sig-B")), timeout=5.0)

        assert [e.reason for e, _ in orders] == ["step-1", "step-2", "sig-B"]

    async def test_resumed_bot_publishes_again(self, manager, eventbus, ctx):
        """정지 뒤 재개한 봇의 새 세대는 시그널을 발행한다."""
        strategy_cls = _recorder()
        orders = _collect(eventbus, OrderRequestEvent)
        await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)
        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)
        await asyncio.wait_for(manager.resume_bot("bot1"), timeout=5.0)

        await asyncio.wait_for(eventbus.publish(_gen_signal("sig-B")), timeout=5.0)

        assert [e.reason for e, _ in orders] == ["sig-B"]

    async def test_stopped_bot_fill_follow_up_is_still_published(
        self, manager, eventbus, ctx
    ):
        """정지된 봇의 on_fill 후속 주문은 지금처럼 발행된다."""
        orders = _collect(eventbus, OrderRequestEvent)
        config = BotConfig(
            bot_id="bot1",
            strategy_id="fill_react",
            interval_seconds=999,
            account_id="acc-test",
        )
        bot = await manager.create_bot(config, FillReactStrategy, ctx)
        await manager.start_bot("bot1")
        await asyncio.wait_for(manager.stop_bot("bot1"), timeout=5.0)
        assert bot.status == BotStatus.STOPPED

        await asyncio.wait_for(
            eventbus.publish(
                OrderFilledEvent(
                    order_id="ord1",
                    broker_order_id="bk1",
                    bot_id="bot1",
                    strategy_id="fill_react",
                    symbol="005930",
                    side="buy",
                    quantity=10.0,
                    price=50000.0,
                    order_type="market",
                    account_id="acc-test",
                )
            ),
            timeout=5.0,
        )

        assert [(e.side, e.reason) for e, _ in orders] == [
            ("sell", "stop loss after fill")
        ]

    async def test_delete_with_liquidation_still_publishes_after_start(
        self, eventbus, db, ctx
    ):
        """시작했던 봇을 청산과 함께 삭제해도 청산 주문은 발행된다."""
        manager = BotManager(
            eventbus=eventbus, db=db, trade_service=_PositionsTradeService()
        )
        await manager.initialize()
        orders = _collect(eventbus, OrderRequestEvent)
        strategy_cls = _recorder()
        await manager.create_bot(_gen_config(), strategy_cls, ctx)
        await manager.start_bot("bot1")
        await strategy_cls.wait_steps(1)

        await asyncio.wait_for(
            manager.delete_bot("bot1", handle_positions="liquidate"), timeout=5.0
        )

        assert [(e.side, e.symbol, e.quantity) for e, _ in orders] == [
            ("sell", "005930", 3.0)
        ]
