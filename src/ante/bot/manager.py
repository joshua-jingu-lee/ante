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
    ) -> None:
        self._eventbus = eventbus
        self._db = db
        self._context_factory = context_factory
        self._bots: dict[str, Bot] = {}

    async def initialize(self) -> None:
        """스키마 생성 + EventBus 구독."""
        await self._db.execute_script(BOT_SCHEMA)
        self._subscribe_events()
        logger.info("BotManager 초기화 완료")

    def _subscribe_events(self) -> None:
        """시스템 이벤트 구독."""
        from ante.eventbus.events import BotStopEvent, TradingStateChangedEvent

        self._eventbus.subscribe(BotStopEvent, self._on_bot_stop_request)
        self._eventbus.subscribe(
            TradingStateChangedEvent, self._on_trading_state_changed
        )

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

        del self._bots[bot_id]
        await self._db.execute("DELETE FROM bots WHERE bot_id = ?", (bot_id,))
        logger.info("봇 삭제: %s", bot_id)

    async def stop_all(self) -> None:
        """모든 봇 중지."""
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

    # ── 봇 이벤트 구독 관리 ──────────────────────────

    def _register_bot_events(self, bot: Bot) -> None:
        """봇의 이벤트 핸들러 등록."""
        from ante.eventbus.events import (
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        self._eventbus.subscribe(OrderFilledEvent, bot.on_order_filled)
        for event_type in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
        ):
            self._eventbus.subscribe(event_type, bot.on_order_update)

    def _unregister_bot_events(self, bot: Bot) -> None:
        """봇의 이벤트 핸들러 해제."""
        from ante.eventbus.events import (
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        self._eventbus.unsubscribe(OrderFilledEvent, bot.on_order_filled)
        for event_type in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
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
