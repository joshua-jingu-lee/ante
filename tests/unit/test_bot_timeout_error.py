"""연속 타임아웃 시 ERROR 상태 전이 및 BotErrorEvent 발행 테스트 (#793)."""

import asyncio

import pytest

from ante.bot import Bot, BotConfig, BotStatus
from ante.eventbus import EventBus
from ante.eventbus.events import BotErrorEvent
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
        import polars as pl

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


class TimeoutStrategy(Strategy):
    """on_step에서 항상 타임아웃을 유발하는 전략."""

    meta = StrategyMeta(name="timeout", version="0.1.0", description="test")

    async def on_step(self, context) -> list[Signal]:
        await asyncio.sleep(9999)
        return []


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


def _make_bot(strategy_cls, eventbus, ctx, *, step_timeout=0.01):
    """테스트용 Bot 생성. interval 검증 통과 후 짧은 값으로 교체한다."""
    config = BotConfig(
        bot_id="bot1",
        strategy_id="test_stg",
        account_id="test",
        interval_seconds=60,
        step_timeout_seconds=step_timeout,
    )
    # 검증 통과 후 interval을 짧게 교체하여 테스트 속도 확보
    config.interval_seconds = 0.01
    bot = Bot(
        config=config,
        strategy_cls=strategy_cls,
        ctx=ctx,
        eventbus=eventbus,
    )
    bot._max_consecutive_failures = 3
    return bot


# ── Tests ─────────────────────────────────────


class TestConsecutiveTimeoutError:
    """연속 타임아웃 초과 시 ERROR 전이 테스트."""

    async def test_consecutive_timeout_transitions_to_error(self, eventbus, ctx):
        """연속 타임아웃이 한도를 초과하면 BotStatus.ERROR로 전이해야 한다."""
        bot = _make_bot(TimeoutStrategy, eventbus, ctx)

        bot.strategy = TimeoutStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        await bot._run_loop()

        assert bot.status == BotStatus.ERROR
        assert bot.error_message is not None
        assert "타임아웃" in bot.error_message

    async def test_consecutive_timeout_publishes_bot_error_event(self, eventbus, ctx):
        """연속 타임아웃 초과 시 BotErrorEvent가 발행되어야 한다."""
        bot = _make_bot(TimeoutStrategy, eventbus, ctx)
        bot.strategy = TimeoutStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        captured_events: list[BotErrorEvent] = []

        async def on_error(event: BotErrorEvent) -> None:
            captured_events.append(event)

        eventbus.subscribe(BotErrorEvent, on_error)

        await bot._run_loop()

        assert len(captured_events) == 1
        evt = captured_events[0]
        assert evt.bot_id == "bot1"
        assert evt.account_id == "test"
        assert "타임아웃" in evt.error_message

    async def test_timeout_below_limit_keeps_running(self, eventbus, ctx):
        """타임아웃 횟수가 한도 미만이면 RUNNING 상태를 유지하고 카운터가 리셋된다."""
        call_count = 0
        stop_after = 4  # 4번째 호출 후 루프 탈출

        class PartialTimeoutStrategy(Strategy):
            """처음 2회는 타임아웃, 이후 정상 반환 후 루프 탈출."""

            meta = StrategyMeta(
                name="partial_timeout", version="0.1.0", description="test"
            )

            async def on_step(self, context) -> list[Signal]:
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    await asyncio.sleep(9999)
                if call_count >= stop_after:
                    bot.status = BotStatus.STOPPED
                return []

        bot = _make_bot(PartialTimeoutStrategy, eventbus, ctx)
        bot.strategy = PartialTimeoutStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        await bot._run_loop()

        # STOPPED로 정상 탈출 (ERROR가 아님)
        assert bot.status == BotStatus.STOPPED
        # 정상 실행 후 연속 실패 카운터가 리셋
        assert bot._consecutive_failures == 0
        assert call_count >= 3
