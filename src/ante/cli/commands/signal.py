"""ante signal — 외부 시그널 채널 관리 커맨드."""

from __future__ import annotations

import asyncio
import sys

import click

from ante.cli.middleware import require_auth


@click.group()
def signal() -> None:
    """외부 시그널 채널 관리."""


@signal.command("connect")
@click.option("--key", required=True, help="시그널 키 (sk_...)")
@click.pass_context
@require_auth
def signal_connect(ctx: click.Context, key: str) -> None:
    """양방향 JSON Lines 시그널 채널 수립."""
    asyncio.run(_run_connect(key))


async def _run_connect(key: str) -> None:
    """시그널 채널 연결 및 실행."""
    from ante.bot.config import BotStatus
    from ante.bot.manager import BotManager
    from ante.bot.signal_channel import SignalChannel
    from ante.bot.signal_key import SignalKeyManager
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database("db/ante.db")
    await db.connect()

    try:
        skm = SignalKeyManager(db)
        await skm.initialize()

        # 1. 키 검증
        bot_id = await skm.validate_key(key)
        if not bot_id:
            _err("Invalid signal key")
            return

        # 2. 봇 존재 및 상태 확인
        eventbus = EventBus()
        manager = BotManager(eventbus=eventbus, db=db, signal_key_manager=skm)
        await manager.initialize()

        bot = manager.get_bot(bot_id)
        if not bot:
            _err(f"Bot not found: {bot_id}")
            return

        if bot.status != BotStatus.RUNNING:
            _err(f"Bot is not running: {bot_id} (status: {bot.status.value})")
            return

        # 3. accepts_external_signals 확인
        if not bot.strategy or not bot.strategy.meta.accepts_external_signals:
            _err(f"Bot {bot_id} does not accept external signals")
            return

        # 4. 채널 수립
        _err(f"Connected to bot {bot_id}")
        _err("Ready for JSON Lines communication on stdin/stdout")

        channel = SignalChannel(
            bot=bot,
            eventbus=eventbus,
            ctx=bot._ctx,
        )
        await channel.run()

    finally:
        await db.close()


def _err(msg: str) -> None:
    """stderr에 메시지 출력."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
