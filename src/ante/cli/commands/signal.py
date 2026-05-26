"""ante signal — 외부 시그널 채널 관리 커맨드."""

from __future__ import annotations

import asyncio
import sys
from typing import NoReturn

import click

from ante.bot.exceptions import BOT_NOT_FOUND_CODE
from ante.cli.formatter import OutputFormatter, format_option
from ante.cli.middleware import require_auth


@click.group()
def signal() -> None:
    """외부 시그널 채널 관리."""


@signal.command("connect")
@click.option("--key", required=True, help="시그널 키 (sk_...)")
@format_option
@click.pass_context
@require_auth
def signal_connect(ctx: click.Context, key: str) -> None:
    """양방향 JSON Lines 시그널 채널 수립."""
    asyncio.run(_run_connect(ctx, key))


async def _run_connect(ctx: click.Context, key: str) -> None:
    """시그널 채널 연결 및 실행.

    #1857: 본 명령은 ``SignalChannel`` 을 통해 외부 시그널 소스 (HTTP/WS 등)
    와 long-lived loop 를 형성한다. ``Database`` lifecycle 이 external process
    runtime 과 엮여 있어 단순 ``open_cli_db`` async-context wrap 으로 동치
    변환이 불가능하다 — 별도 spec 정렬 PR (#1818 follow-up) 에서 다룬다.
    """
    from ante.bot.config import BotStatus
    from ante.bot.manager import BotManager
    from ante.bot.signal_channel import SignalChannel
    from ante.bot.signal_key import SignalKeyManager
    from ante.cli.main import get_db_path, get_formatter
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    fmt = get_formatter(ctx)
    db = Database(get_db_path())
    await db.connect()

    try:
        skm = SignalKeyManager(db)
        await skm.initialize()

        # 1. 키 검증
        bot_id = await skm.validate_key(key)
        if not bot_id:
            _fail(fmt, "Invalid signal key", "INVALID_SIGNAL_KEY")

        # 2. 봇 존재 및 상태 확인
        eventbus = EventBus()
        manager = BotManager(eventbus=eventbus, db=db, signal_key_manager=skm)
        await manager.initialize()

        bot = manager.get_bot(bot_id)
        if not bot:
            _fail(fmt, f"Bot not found: {bot_id}", BOT_NOT_FOUND_CODE)

        if bot.status != BotStatus.RUNNING:
            _fail(
                fmt,
                f"Bot is not running: {bot_id} (status: {bot.status.value})",
                "BOT_NOT_RUNNING",
            )

        # 3. accepts_external_signals 확인
        if not bot.strategy or not bot.strategy.meta.accepts_external_signals:
            _fail(
                fmt,
                f"Bot {bot_id} does not accept external signals",
                "BOT_NOT_ACCEPTING_SIGNALS",
            )

        # 4. 채널 수립 (informational stderr 유지)
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


def _fail(fmt: OutputFormatter, msg: str, code: str) -> NoReturn:
    """validation 오류 종료.

    JSON 모드는 stdout envelope (``{status,code,message}``),
    text 모드는 기존 ``_err()`` raw stderr 동작을 그대로 보존한다
    (no ``Error: `` prefix).
    """
    if fmt.is_json:
        fmt.error(msg, code=code)
    else:
        _err(msg)
    raise SystemExit(1)


def _err(msg: str) -> None:
    """stderr에 메시지 출력."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
