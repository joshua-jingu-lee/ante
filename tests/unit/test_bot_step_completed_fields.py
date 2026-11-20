"""BotStepCompletedEvent 의 signal_count/duration_ms 발행 검증 (#2155).

spec(`docs/specs/bot/04-eventbus-integration.md:14,27-34`)이 계약한
`signal_count`/`duration_ms` 가 4 result(success/timeout/signal_overflow/
error) 발행 경로 모두에서 채워지는지 검증한다.

`duration_ms > 0` 은 wall-clock 에 의존하면 flaky 하므로
``ante.bot.bot.monotonic`` (모듈 로컬 alias) 를 patch 하여 결정적으로
검증한다 (전역 ``time.monotonic`` 이 아니라 모듈 로컬 alias).
"""

import asyncio

import polars as pl
import pytest

from ante.bot import Bot, BotConfig, BotStatus
from ante.eventbus import EventBus
from ante.eventbus.events import BotStepCompletedEvent
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


def _signal(symbol="005930"):
    return Signal(symbol=symbol, side="buy", quantity=10.0, reason="test")


class TwoSignalStrategy(Strategy):
    """매 step 2개 시그널을 반환 후 루프 탈출."""

    meta = StrategyMeta(name="two_signal", version="1.0.0", description="test")

    def __init__(self, ctx, stop_bot):
        super().__init__(ctx=ctx)
        self._stop_bot = stop_bot

    async def on_step(self, context) -> list[Signal]:
        self._stop_bot()
        return [_signal(), _signal()]


class EmptyStrategy(Strategy):
    """시그널 없이 정상 반환 후 루프 탈출."""

    meta = StrategyMeta(name="empty", version="1.0.0", description="test")

    def __init__(self, ctx, stop_bot):
        super().__init__(ctx=ctx)
        self._stop_bot = stop_bot

    async def on_step(self, context) -> list[Signal]:
        self._stop_bot()
        return []


class OverflowStrategy(Strategy):
    """max_signals_per_step 를 초과하는 시그널을 반환."""

    meta = StrategyMeta(name="overflow", version="1.0.0", description="test")

    def __init__(self, ctx, count):
        super().__init__(ctx=ctx)
        self._count = count

    async def on_step(self, context) -> list[Signal]:
        return [_signal() for _ in range(self._count)]


class TimeoutStrategy(Strategy):
    """on_step 에서 타임아웃을 유발."""

    meta = StrategyMeta(name="timeout", version="1.0.0", description="test")

    async def on_step(self, context) -> list[Signal]:
        await asyncio.sleep(9999)
        return []


class RaiseStrategy(Strategy):
    """on_step 에서 예외를 발생시켜 outer except(error) 경로 진입."""

    meta = StrategyMeta(name="raise", version="1.0.0", description="test")

    async def on_step(self, context) -> list[Signal]:
        raise RuntimeError("boom")


# ── Fixtures ──────────────────────────────────


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


def _make_config(**overrides):
    """spec 범위 통과값으로 만든 뒤 인스턴스 attr 를 짧게 swap.

    (`test_bot_timeout_error._make_bot` 와 동일 패턴 — invariant
    validation 은 통과시키고 실제 timeout/interval 비교만 짧게.)
    """
    config = BotConfig(
        bot_id="bot1",
        strategy_id="test_stg",
        account_id="test",
        interval_seconds=60,
        step_timeout_seconds=5,
    )
    config.interval_seconds = 0.01
    config.step_timeout_seconds = 0.01
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _make_bot(strategy, eventbus, ctx, config=None):
    bot = Bot(
        config=config or _make_config(),
        strategy_cls=type(strategy),
        ctx=ctx,
        eventbus=eventbus,
    )
    bot.strategy = strategy
    bot.status = BotStatus.RUNNING
    return bot


def _capture(eventbus) -> list[BotStepCompletedEvent]:
    captured: list[BotStepCompletedEvent] = []

    async def _on(event: BotStepCompletedEvent) -> None:
        captured.append(event)

    eventbus.subscribe(BotStepCompletedEvent, _on)
    return captured


def _patch_monotonic(monkeypatch, values):
    """``ante.bot.bot.monotonic`` 모듈 로컬 alias 를 결정적 시퀀스로 patch.

    전역 ``time.monotonic`` 이 아니라 bot 모듈이 import 한 alias 를
    교체하여 duration 계산을 flake 없이 검증한다.
    """
    seq = iter(values)
    last = [values[-1]]

    def _fake() -> float:
        try:
            last[0] = next(seq)
        except StopIteration:
            pass
        return last[0]

    monkeypatch.setattr("ante.bot.bot.monotonic", _fake)


# ── Tests ─────────────────────────────────────


class TestBotStepCompletedFields:
    async def test_success_with_signals(self, eventbus, ctx, monkeypatch):
        """success: signal_count == 발행 signal 수, duration_ms > 0."""
        # on_step 직전(t0), wait_for 정상 반환 직후(t0+0.5)
        _patch_monotonic(monkeypatch, [10.0, 10.5])
        captured = _capture(eventbus)

        bot = _make_bot(None, eventbus, ctx)
        bot.strategy = TwoSignalStrategy(
            ctx, stop_bot=lambda: setattr(bot, "status", BotStatus.STOPPED)
        )

        await bot._run_loop()

        success = [e for e in captured if e.result == "success"]
        assert len(success) == 1
        evt = success[0]
        assert evt.signal_count == 2
        assert evt.duration_ms == 500
        assert evt.duration_ms > 0

    async def test_success_no_signals(self, eventbus, ctx, monkeypatch):
        """success(시그널 없음): signal_count == 0, duration_ms > 0."""
        _patch_monotonic(monkeypatch, [1.0, 1.25])
        captured = _capture(eventbus)

        bot = _make_bot(None, eventbus, ctx)
        bot.strategy = EmptyStrategy(
            ctx, stop_bot=lambda: setattr(bot, "status", BotStatus.STOPPED)
        )

        await bot._run_loop()

        success = [e for e in captured if e.result == "success"]
        assert len(success) == 1
        assert success[0].signal_count == 0
        assert success[0].duration_ms == 250
        assert success[0].duration_ms > 0

    async def test_signal_overflow(self, eventbus, ctx, monkeypatch):
        """signal_overflow: signal_count == 실제 시그널 수, duration_ms > 0."""
        # delta=0.125 → 이진수로 정확히 표현 가능(부동소수점 floor 안전)
        _patch_monotonic(monkeypatch, [100.0, 100.125])
        captured = _capture(eventbus)

        config = _make_config(max_signals_per_step=2)
        bot = _make_bot(OverflowStrategy(ctx, count=5), eventbus, ctx, config=config)
        # 첫 overflow 후 즉시 중지하도록 max_consecutive_failures=1
        bot._max_consecutive_failures = 1

        await bot._run_loop()

        overflow = [e for e in captured if e.result == "signal_overflow"]
        assert len(overflow) == 1
        evt = overflow[0]
        assert evt.signal_count == 5
        assert evt.duration_ms == 125
        assert evt.duration_ms > 0

    async def test_timeout(self, eventbus, ctx, monkeypatch):
        """timeout: signal_count == 0, duration_ms > 0."""
        # step_start(t0), timeout emit 시점(t0+0.0625 — 이진수 정확값)
        _patch_monotonic(monkeypatch, [50.0, 50.0625])
        captured = _capture(eventbus)

        bot = _make_bot(TimeoutStrategy(ctx=ctx), eventbus, ctx)
        # 첫 timeout 후 ERROR 전이로 루프 탈출
        bot._max_consecutive_failures = 1

        await bot._run_loop()

        timeout = [e for e in captured if e.result == "timeout"]
        assert len(timeout) == 1
        evt = timeout[0]
        assert evt.signal_count == 0
        assert evt.duration_ms == 62
        assert evt.duration_ms > 0

    async def test_error(self, eventbus, ctx, monkeypatch):
        """error(outer except): signal_count == 0, duration_ms > 0."""
        # step_start(t0), error emit 시점(t0+0.75)
        _patch_monotonic(monkeypatch, [200.0, 200.75])
        captured = _capture(eventbus)

        bot = _make_bot(RaiseStrategy(ctx=ctx), eventbus, ctx)

        await bot._run_loop()

        assert bot.status == BotStatus.ERROR
        error = [e for e in captured if e.result == "error"]
        assert len(error) == 1
        evt = error[0]
        assert evt.signal_count == 0
        assert evt.duration_ms == 750
        assert evt.duration_ms > 0


# ── duration_ms 의 측정 구간 ──────────────────────

_real_sleep = asyncio.sleep


class _Clock:
    """``ante.bot.bot.monotonic`` 자리에 넣는 수동 시계."""

    def __init__(self, start: float) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class _FailOnSecondPositions(FakePortfolioView):
    def __init__(self) -> None:
        self.calls = 0

    def get_positions(self, bot_id):
        self.calls += 1
        if self.calls >= 2:
            raise RuntimeError("positions down")
        return {}


class TestBotStepDurationWindow:
    async def test_success_duration_excludes_signal_publish_time(
        self, eventbus, ctx, monkeypatch
    ):
        """success 의 duration_ms 는 on_step 실행 시간만 잰다(시그널 발행 시간 제외)."""
        from ante.eventbus.events import OrderRequestEvent

        clock = _Clock(100.0)
        monkeypatch.setattr("ante.bot.bot.monotonic", clock)

        async def fake_sleep(delay):
            await _real_sleep(0)

        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", fake_sleep)
        captured = _capture(eventbus)
        published: list[OrderRequestEvent] = []

        async def _slow_order_handler(event: OrderRequestEvent) -> None:
            published.append(event)
            clock.now += 2.0

        eventbus.subscribe(OrderRequestEvent, _slow_order_handler)

        class _TimedStrategy(Strategy):
            meta = StrategyMeta(name="timed", version="1.0.0", description="test")

            async def on_step(self, context) -> list[Signal]:
                clock.now += 0.5
                bot.status = BotStatus.STOPPED
                return [_signal()]

        bot = _make_bot(_TimedStrategy(ctx=ctx), eventbus, ctx)

        await bot._run_loop()

        assert len(published) == 1
        success = [e for e in captured if e.result == "success"]
        assert len(success) == 1
        assert success[0].duration_ms == 500

    async def test_error_before_on_step_reports_zero_duration(
        self, eventbus, monkeypatch
    ):
        """앞 반복의 step 시작 시각이 다음 반복의 error duration_ms 에 새지 않는다."""
        clock = _Clock(10.0)
        monkeypatch.setattr("ante.bot.bot.monotonic", clock)

        async def fake_sleep(delay):
            clock.now += 30.0
            await _real_sleep(0)

        monkeypatch.setattr("ante.bot.bot.asyncio.sleep", fake_sleep)
        portfolio = _FailOnSecondPositions()
        flaky_ctx = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=portfolio,
            order_view=FakeOrderView(),
        )
        captured = _capture(eventbus)

        class _QuickStrategy(Strategy):
            meta = StrategyMeta(name="quick", version="1.0.0", description="test")

            async def on_step(self, context) -> list[Signal]:
                clock.now += 0.5
                return []

        bot = _make_bot(_QuickStrategy(ctx=flaky_ctx), eventbus, flaky_ctx)

        await bot._run_loop()

        assert portfolio.calls == 2
        assert bot.status == BotStatus.ERROR
        assert [e.result for e in captured] == ["success", "error"]
        error = captured[1]
        assert error.message == "positions down"
        assert error.duration_ms == 0
