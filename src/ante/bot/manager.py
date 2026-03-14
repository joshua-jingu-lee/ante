"""BotManager — 봇 생명주기 중앙 관리."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from ante.bot.bot import Bot
from ante.bot.config import BotConfig, BotStatus
from ante.bot.exceptions import BotError

if TYPE_CHECKING:
    from ante.bot.context_factory import StrategyContextFactory
    from ante.bot.signal_key import SignalKeyManager  # noqa: F811
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.strategy.base import Strategy
    from ante.strategy.context import StrategyContext

logger = logging.getLogger(__name__)

BOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS bots (
    bot_id       TEXT PRIMARY KEY,
    strategy_id  TEXT NOT NULL,
    bot_type     TEXT NOT NULL DEFAULT 'live',
    config_json  TEXT NOT NULL,
    auto_start   BOOLEAN DEFAULT 0,
    status       TEXT DEFAULT 'created',
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);
"""


class BotManager:
    """봇들의 생명주기를 중앙 관리."""

    def __init__(
        self,
        eventbus: EventBus,
        db: Database,
        context_factory: StrategyContextFactory | None = None,
        signal_key_manager: SignalKeyManager | None = None,
    ) -> None:
        self._eventbus = eventbus
        self._db = db
        self._context_factory = context_factory
        self._signal_key_manager = signal_key_manager
        self._bots: dict[str, Bot] = {}
        self._restart_counts: dict[str, int] = {}
        self._restart_tasks: dict[str, asyncio.Task[None]] = {}
        self._restart_reset_tasks: dict[str, asyncio.Task[None]] = {}

    async def initialize(self) -> None:
        """스키마 생성 + EventBus 구독."""
        await self._db.execute_script(BOT_SCHEMA)
        self._subscribe_events()
        logger.info("BotManager 초기화 완료")

    def _subscribe_events(self) -> None:
        """시스템 이벤트 구독."""
        from ante.eventbus.events import (
            BotErrorEvent,
            BotStopEvent,
            TradingStateChangedEvent,
        )

        self._eventbus.subscribe(BotStopEvent, self._on_bot_stop_request)
        self._eventbus.subscribe(
            TradingStateChangedEvent, self._on_trading_state_changed
        )
        self._eventbus.subscribe(BotErrorEvent, self._on_bot_error)

    async def create_bot(
        self,
        config: BotConfig,
        strategy_cls: type[Strategy],
        ctx: StrategyContext | None = None,
    ) -> Bot:
        """봇 생성.

        ctx가 주입되면 그대로 사용하고, None이면 context_factory로 자동 생성한다.
        """
        if config.bot_id in self._bots:
            raise BotError(f"Bot already exists: {config.bot_id}")

        # 1전략 1봇 정책: 실행 중인 봇이 사용 중인 전략 중복 차단
        active_statuses = {BotStatus.RUNNING, BotStatus.STOPPING}
        for existing_bot in self._bots.values():
            if (
                existing_bot.config.strategy_id == config.strategy_id
                and existing_bot.status in active_statuses
            ):
                raise BotError(
                    f"전략 '{config.strategy_id}'은(는) 이미 봇 "
                    f"'{existing_bot.bot_id}'에서 사용 중입니다. "
                    f"파라미터가 다른 전략은 별도 파일로 작성하세요."
                )

        if ctx is None:
            if self._context_factory is None:
                msg = "ctx 또는 context_factory 중 하나는 필수입니다"
                raise BotError(msg)
            ctx = self._context_factory.create(config)

        bot = Bot(
            config=config,
            strategy_cls=strategy_cls,
            ctx=ctx,
            eventbus=self._eventbus,
        )

        self._register_bot_events(bot)
        self._bots[config.bot_id] = bot
        await self._save_bot_config(config)

        # accepts_external_signals=True이면 시그널 키 자동 발급
        if (
            self._signal_key_manager
            and hasattr(strategy_cls, "meta")
            and getattr(strategy_cls.meta, "accepts_external_signals", False)
        ):
            signal_key = await self._signal_key_manager.generate(config.bot_id)
            logger.info(
                "시그널 키 자동 발급: bot=%s key=%s...",
                config.bot_id,
                signal_key[:8],
            )

        logger.info("봇 생성: %s (전략: %s)", config.bot_id, config.strategy_id)
        return bot

    async def start_bot(self, bot_id: str) -> None:
        """봇 시작."""
        bot = self._get_bot(bot_id)
        await bot.start()

    async def stop_bot(self, bot_id: str) -> None:
        """봇 중지."""
        bot = self._get_bot(bot_id)
        await bot.stop()

    async def remove_bot(self, bot_id: str) -> None:
        """봇 삭제. 실행 중이면 먼저 중지."""
        bot = self._get_bot(bot_id)
        if bot.status == BotStatus.RUNNING:
            await bot.stop()

        self._unregister_bot_events(bot)

        # Paper 봇 PaperExecutor 등록 해제
        if (
            self._context_factory
            and self._context_factory._paper_executor
            and bot.config.bot_type == "paper"
        ):
            self._context_factory._paper_executor.unregister_bot(bot_id)

        # 시그널 키 폐기
        if self._signal_key_manager:
            await self._signal_key_manager.revoke(bot_id)

        del self._bots[bot_id]
        await self._db.execute("DELETE FROM bots WHERE bot_id = ?", (bot_id,))
        logger.info("봇 삭제: %s", bot_id)

    async def stop_all(self) -> None:
        """모든 봇 중지."""
        # 재시작 태스크 취소
        for task in list(self._restart_tasks.values()):
            task.cancel()
        for task in list(self._restart_reset_tasks.values()):
            task.cancel()
        self._restart_tasks.clear()
        self._restart_reset_tasks.clear()

        tasks = [
            bot.stop() for bot in self._bots.values() if bot.status == BotStatus.RUNNING
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("전체 봇 중지 완료")

    def list_bots(self) -> list[dict[str, Any]]:
        """봇 목록 조회."""
        return [bot.get_info() for bot in self._bots.values()]

    def get_bot(self, bot_id: str) -> Bot | None:
        """봇 조회. 없으면 None."""
        return self._bots.get(bot_id)

    def _get_bot(self, bot_id: str) -> Bot:
        """봇 조회. 없으면 예외."""
        bot = self._bots.get(bot_id)
        if bot is None:
            raise BotError(f"Bot not found: {bot_id}")
        return bot

    # ── EventBus 핸들러 ──────────────────────────────

    async def _on_bot_stop_request(self, event: object) -> None:
        """BotStopEvent 수신 시 해당 봇 중지."""
        from ante.eventbus.events import BotStopEvent

        if not isinstance(event, BotStopEvent):
            return
        if event.bot_id in self._bots:
            await self.stop_bot(event.bot_id)

    async def _on_trading_state_changed(self, event: object) -> None:
        """킬 스위치 HALTED 시 전체 봇 중지."""
        from ante.eventbus.events import TradingStateChangedEvent

        if not isinstance(event, TradingStateChangedEvent):
            return
        if event.new_state == "halted":
            logger.warning("시스템 HALTED — 전체 봇 중지")
            await self.stop_all()

    async def _on_bot_error(self, event: object) -> None:
        """봇 에러 시 재시작 정책에 따라 자동 재시작."""
        from ante.eventbus.events import BotErrorEvent

        if not isinstance(event, BotErrorEvent):
            return

        bot = self._bots.get(event.bot_id)
        if not bot or not bot.config.auto_restart:
            return

        config = bot.config
        count = self._restart_counts.get(event.bot_id, 0)

        if count >= config.max_restart_attempts:
            await self._on_restart_exhausted(event.bot_id, count, event.error_message)
            return

        self._restart_counts[event.bot_id] = count + 1
        logger.warning(
            "봇 재시작 예약: %s (시도 %d/%d, %d초 후)",
            event.bot_id,
            count + 1,
            config.max_restart_attempts,
            config.restart_cooldown_seconds,
        )

        task = asyncio.create_task(
            self._restart_after_cooldown(event.bot_id),
            name=f"restart-{event.bot_id}",
        )
        self._restart_tasks[event.bot_id] = task

    async def _restart_after_cooldown(self, bot_id: str) -> None:
        """쿨다운 대기 후 봇 재시작."""
        bot = self._bots.get(bot_id)
        if not bot:
            return

        try:
            await asyncio.sleep(bot.config.restart_cooldown_seconds)
        except asyncio.CancelledError:
            return

        if bot.status != BotStatus.ERROR:
            return

        try:
            await bot.start()
            logger.info("봇 재시작 성공: %s", bot_id)
            self._schedule_restart_reset(bot_id)
        except Exception as e:
            logger.error("봇 재시작 실패: %s — %s", bot_id, e)
        finally:
            self._restart_tasks.pop(bot_id, None)

    def _schedule_restart_reset(self, bot_id: str) -> None:
        """정상 실행 유지 시 재시작 카운터 리셋 스케줄링."""
        old_task = self._restart_reset_tasks.pop(bot_id, None)
        if old_task and not old_task.done():
            old_task.cancel()

        bot = self._bots.get(bot_id)
        if not bot:
            return

        config = bot.config
        reset_after = config.restart_cooldown_seconds * config.max_restart_attempts

        task = asyncio.create_task(
            self._reset_restart_count_after(bot_id, reset_after),
            name=f"restart-reset-{bot_id}",
        )
        self._restart_reset_tasks[bot_id] = task

    async def _reset_restart_count_after(self, bot_id: str, seconds: float) -> None:
        """일정 시간 정상 실행 후 재시작 카운터 초기화."""
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return

        bot = self._bots.get(bot_id)
        if bot and bot.status == BotStatus.RUNNING:
            old_count = self._restart_counts.pop(bot_id, 0)
            if old_count > 0:
                logger.info(
                    "봇 재시작 카운터 리셋: %s (정상 %d초 유지)",
                    bot_id,
                    seconds,
                )
        self._restart_reset_tasks.pop(bot_id, None)

    async def _on_restart_exhausted(
        self, bot_id: str, attempts: int, last_error: str
    ) -> None:
        """재시작 한도 소진 시 이벤트 발행."""
        from ante.eventbus.events import BotRestartExhaustedEvent

        logger.error(
            "봇 재시작 한도 소진: %s (%d회 시도)",
            bot_id,
            attempts,
        )
        await self._eventbus.publish(
            BotRestartExhaustedEvent(
                bot_id=bot_id,
                restart_attempts=attempts,
                last_error=last_error,
            )
        )

    async def get_signal_key(self, bot_id: str) -> str | None:
        """봇의 시그널 키 조회."""
        if not self._signal_key_manager:
            return None
        return await self._signal_key_manager.get_key(bot_id)

    async def rotate_signal_key(self, bot_id: str) -> str:
        """시그널 키 재발급."""
        if not self._signal_key_manager:
            raise BotError("SignalKeyManager가 설정되지 않았습니다")
        self._get_bot(bot_id)  # 존재 확인
        return await self._signal_key_manager.rotate(bot_id)

    def get_restart_count(self, bot_id: str) -> int:
        """봇의 현재 재시작 시도 횟수."""
        return self._restart_counts.get(bot_id, 0)

    # ── 봇 이벤트 구독 관리 ──────────────────────────

    def _register_bot_events(self, bot: Bot) -> None:
        """봇의 이벤트 핸들러 등록."""
        from ante.eventbus.events import (
            ExternalSignalEvent,
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        self._eventbus.subscribe(OrderFilledEvent, bot.on_order_filled)
        self._eventbus.subscribe(ExternalSignalEvent, bot.on_external_signal)
        for event_type in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
        ):
            self._eventbus.subscribe(event_type, bot.on_order_update)

    def _unregister_bot_events(self, bot: Bot) -> None:
        """봇의 이벤트 핸들러 해제."""
        from ante.eventbus.events import (
            ExternalSignalEvent,
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        self._eventbus.unsubscribe(OrderFilledEvent, bot.on_order_filled)
        self._eventbus.unsubscribe(ExternalSignalEvent, bot.on_external_signal)
        for event_type in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
        ):
            self._eventbus.unsubscribe(event_type, bot.on_order_update)

    # ── DB ───────────────────────────────────────────

    async def _save_bot_config(self, config: BotConfig) -> None:
        """봇 설정 DB 저장."""
        config_dict = {
            "bot_id": config.bot_id,
            "strategy_id": config.strategy_id,
            "bot_type": config.bot_type,
            "interval_seconds": config.interval_seconds,
            "symbols": config.symbols,
            "paper_initial_balance": config.paper_initial_balance,
        }
        await self._db.execute(
            """INSERT INTO bots
               (bot_id, strategy_id, bot_type, config_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(bot_id) DO UPDATE SET
                 config_json = excluded.config_json,
                 updated_at = datetime('now')""",
            (
                config.bot_id,
                config.strategy_id,
                config.bot_type,
                json.dumps(config_dict),
            ),
        )
