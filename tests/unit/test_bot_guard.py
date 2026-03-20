"""Bot Runtime Guard 테스트 — on_step 타임아웃 및 Signal 수 상한."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from ante.bot.bot import Bot
from ante.bot.config import BotConfig, BotStatus
from ante.strategy.base import Signal, Strategy, StrategyMeta

# ── 테스트 전략 ──────────────────────────────────


class _NormalStrategy(Strategy):
    """정상 전략."""

    meta = StrategyMeta(name="normal", version="1.0.0", description="normal")

    async def on_step(self, context: dict) -> list[Signal]:
        return [Signal(symbol="005930", side="buy", quantity=1.0)]


class _SlowStrategy(Strategy):
    """타임아웃 유발 전략."""

    meta = StrategyMeta(name="slow", version="1.0.0", description="slow")

    async def on_step(self, context: dict) -> list[Signal]:
        await asyncio.sleep(100)  # 매우 오래 걸림
        return []


class _MassSignalStrategy(Strategy):
    """대량 Signal 반환 전략."""

    meta = StrategyMeta(name="mass", version="1.0.0", description="mass signals")

    async def on_step(self, context: dict) -> list[Signal]:
        return [
            Signal(symbol=f"0{i:05d}", side="buy", quantity=1.0) for i in range(100)
        ]


# ── Fixtures ─────────────────────────────────────


def _make_bot(
    strategy_cls: type[Strategy],
    step_timeout: int = 30,
    max_signals: int = 50,
    interval: int = 10,
) -> Bot:
    config = BotConfig(
        bot_id="bot-test",
        strategy_id="stg-test",
        interval_seconds=interval,
        step_timeout_seconds=step_timeout,
        max_signals_per_step=max_signals,
    )
    ctx = MagicMock()
    ctx.get_positions.return_value = {}
    ctx.get_balance.return_value = {"available": 1000000.0}
    ctx._drain_actions.return_value = []

    eventbus = MagicMock()
    eventbus.publish = AsyncMock()

    bot = Bot(config=config, strategy_cls=strategy_cls, ctx=ctx, eventbus=eventbus)
    return bot


# ── US-1: on_step 타임아웃 ──────────────────────


class TestStepTimeout:
    """on_step 타임아웃 테스트."""

    async def test_timeout_skips_step(self) -> None:
        """타임아웃 발생 시 해당 주기 스킵 + 카운터 증가."""
        bot = _make_bot(_SlowStrategy, step_timeout=1, interval=10)
        bot.strategy = _SlowStrategy(ctx=MagicMock())
        bot.status = BotStatus.RUNNING

        call_count = 0

        async def _slow_then_stop(context: dict) -> list[Signal]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(100)  # 타임아웃 유발
            # 2회차: 봇 중지 (카운터 확인 전)
            bot.status = BotStatus.STOPPED
            return []

        bot.strategy.on_step = _slow_then_stop  # type: ignore[assignment]

        await bot._run_loop()

        # 1회 타임아웃 → continue → 2회차 on_step 호출 → STOPPED 설정
        assert call_count == 2
        # OrderRequestEvent 발행 없음 (타임아웃으로 Signal 미수집)
        order_calls = [
            c
            for c in bot._eventbus.publish.call_args_list
            if "OrderRequestEvent" in str(type(c[0][0]))
        ]
        assert len(order_calls) == 0

    async def test_consecutive_timeout_stops_bot(self) -> None:
        """연속 3회 타임아웃 시 봇 중지."""
        bot = _make_bot(_SlowStrategy, step_timeout=1, interval=10)
        bot.strategy = _SlowStrategy(ctx=MagicMock())
        bot.status = BotStatus.RUNNING

        # stop()이 호출되는지 확인
        with patch.object(bot, "stop", new_callable=AsyncMock) as mock_stop:
            await bot._run_loop()
            mock_stop.assert_called_once()

        assert bot._consecutive_failures >= 3

    async def test_normal_execution_resets_counter(self) -> None:
        """정상 실행 시 카운터 리셋."""
        bot = _make_bot(_NormalStrategy, step_timeout=30, interval=10)
        bot.strategy = _NormalStrategy(ctx=MagicMock())
        bot.status = BotStatus.RUNNING
        bot._consecutive_failures = 2  # 이전에 2회 실패 상태

        step_count = 0

        original_on_step = bot.strategy.on_step

        async def _on_step_counted(context: dict) -> list[Signal]:
            nonlocal step_count
            step_count += 1
            if step_count >= 1:
                bot.status = BotStatus.STOPPED
            return await original_on_step(context)

        bot.strategy.on_step = _on_step_counted  # type: ignore[assignment]

        await bot._run_loop()

        # 정상 실행 후 카운터 리셋
        assert bot._consecutive_failures == 0


# ── US-2: Signal 수 상한 ──────────────────────


class TestSignalLimit:
    """Signal 수 상한 테스트."""

    async def test_excess_signals_discarded(self) -> None:
        """Signal 수 초과 시 전체 폐기 + BotErrorEvent 발행."""
        bot = _make_bot(_MassSignalStrategy, max_signals=10, interval=10)
        bot.strategy = _MassSignalStrategy(ctx=MagicMock())
        bot.status = BotStatus.RUNNING

        call_count = 0
        original_on_step = bot.strategy.on_step

        async def _mass_then_stop(context: dict) -> list[Signal]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return await original_on_step(context)  # 100개 Signal
            bot.status = BotStatus.STOPPED
            return []

        bot.strategy.on_step = _mass_then_stop  # type: ignore[assignment]

        await bot._run_loop()

        # BotErrorEvent 발행됨 (Signal count exceeded)
        error_calls = [
            c
            for c in bot._eventbus.publish.call_args_list
            if "Signal count exceeded" in str(c)
        ]
        assert len(error_calls) >= 1

        # OrderRequestEvent는 발행되지 않음 (전체 폐기)
        order_calls = [
            c
            for c in bot._eventbus.publish.call_args_list
            if "OrderRequestEvent" in str(type(c[0][0]))
        ]
        assert len(order_calls) == 0

    async def test_consecutive_excess_stops_bot(self) -> None:
        """연속 3회 Signal 초과 시 봇 중지."""
        bot = _make_bot(_MassSignalStrategy, max_signals=10, interval=10)
        bot.strategy = _MassSignalStrategy(ctx=MagicMock())
        bot.status = BotStatus.RUNNING

        with patch.object(bot, "stop", new_callable=AsyncMock) as mock_stop:
            await bot._run_loop()
            mock_stop.assert_called_once()

        assert bot._consecutive_failures >= 3

    async def test_within_limit_passes(self) -> None:
        """Signal 수 상한 이내면 정상 처리."""
        bot = _make_bot(_NormalStrategy, max_signals=50, interval=10)
        bot.strategy = _NormalStrategy(ctx=MagicMock())
        bot.status = BotStatus.RUNNING

        step_count = 0

        original_on_step = bot.strategy.on_step

        async def _on_step_once(context: dict) -> list[Signal]:
            nonlocal step_count
            step_count += 1
            if step_count >= 1:
                bot.status = BotStatus.STOPPED
            return await original_on_step(context)

        bot.strategy.on_step = _on_step_once  # type: ignore[assignment]

        await bot._run_loop()

        # OrderRequestEvent가 발행됨 (1개 Signal)
        order_calls = [
            c
            for c in bot._eventbus.publish.call_args_list
            if "OrderRequestEvent" in str(type(c[0][0]))
        ]
        assert len(order_calls) >= 1
        assert bot._consecutive_failures == 0


# ── BotConfig 필드 테스트 ──────────────────────


class TestBotConfigGuardFields:
    """BotConfig guard 필드 기본값 테스트."""

    def test_default_step_timeout(self) -> None:
        """step_timeout_seconds 기본값 30."""
        config = BotConfig(bot_id="t", strategy_id="s")
        assert config.step_timeout_seconds == 30

    def test_default_max_signals(self) -> None:
        """max_signals_per_step 기본값 50."""
        config = BotConfig(bot_id="t", strategy_id="s")
        assert config.max_signals_per_step == 50

    def test_custom_values(self) -> None:
        """커스텀 값 설정."""
        config = BotConfig(
            bot_id="t",
            strategy_id="s",
            step_timeout_seconds=60,
            max_signals_per_step=100,
        )
        assert config.step_timeout_seconds == 60
        assert config.max_signals_per_step == 100
