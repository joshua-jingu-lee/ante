"""ante bot — 봇 생명주기 관리 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def bot() -> None:
    """봇 생성·시작·중지·조회."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_services():  # noqa: ANN202
    from ante.bot.manager import BotManager
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    manager = BotManager(eventbus=eventbus, db=db)
    await manager.initialize()
    return db, eventbus, manager


@bot.command("list")
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_list(ctx: click.Context) -> None:
    """봇 목록 조회."""
    fmt = get_formatter(ctx)

    async def _run_list() -> list[dict]:
        db, _, _ = await _create_services()
        try:
            rows = await db.fetch_all(
                "SELECT bot_id, strategy_id, bot_type, status, created_at FROM bots"
            )
            return [dict(r) for r in rows]
        finally:
            await db.close()

    result = _run(_run_list())

    if not result:
        fmt.output({"message": "등록된 봇이 없습니다.", "bots": []})
        return

    if fmt.is_json:
        fmt.output({"bots": result})
    else:
        fmt.table(
            result,
            ["bot_id", "strategy_id", "bot_type", "status", "created_at"],
        )


@bot.command("info")
@click.argument("bot_id")
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_info(ctx: click.Context, bot_id: str) -> None:
    """봇 상세 정보 조회."""
    fmt = get_formatter(ctx)

    async def _run_info() -> dict | None:
        db, _, _ = await _create_services()
        try:
            row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = ?", (bot_id,))
            return dict(row) if row else None
        finally:
            await db.close()

    result = _run(_run_info())

    if not result:
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}")
        return

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  Bot ID    : {result['bot_id']}")
        click.echo(f"  전략      : {result['strategy_id']}")
        click.echo(f"  타입      : {result['bot_type']}")
        click.echo(f"  상태      : {result['status']}")
        click.echo(f"  생성일    : {result['created_at']}")


@bot.command("create")
@click.option("--strategy", required=True, help="전략 ID")
@click.option(
    "--type",
    "bot_type",
    type=click.Choice(["live", "paper"]),
    default="live",
    help="봇 타입",
)
@click.option("--interval", default=60, help="실행 주기 (초)")
@click.option("--symbols", default="", help="대상 종목 (쉼표 구분)")
@click.option("--id", "bot_id", default="", help="봇 ID (미지정 시 자동 생성)")
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_create(
    ctx: click.Context,
    strategy: str,
    bot_type: str,
    interval: int,
    symbols: str,
    bot_id: str,
) -> None:
    """봇 생성."""
    fmt = get_formatter(ctx)

    async def _run_create() -> dict:
        import json
        from uuid import uuid4

        db, _, _ = await _create_services()
        try:
            bid = bot_id or f"bot-{uuid4().hex[:8]}"
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] or None
            config_dict = {
                "bot_id": bid,
                "strategy_id": strategy,
                "bot_type": bot_type,
                "interval_seconds": interval,
                "symbols": symbol_list,
            }
            await db.execute(
                """INSERT INTO bots (bot_id, strategy_id, bot_type, config_json)
                   VALUES (?, ?, ?, ?)""",
                (bid, strategy, bot_type, json.dumps(config_dict)),
            )
            return config_dict
        finally:
            await db.close()

    try:
        result = _run(_run_create())
    except Exception as e:
        fmt.error(str(e))
        return

    fmt.success(f"봇 생성 완료: {result['bot_id']}", result)


@bot.command("remove")
@click.argument("bot_id")
@click.confirmation_option(prompt="봇을 삭제합니다. 계속하시겠습니까?")
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_remove(ctx: click.Context, bot_id: str) -> None:
    """봇 삭제."""
    fmt = get_formatter(ctx)

    async def _run_remove() -> bool:
        db, _, _ = await _create_services()
        try:
            row = await db.fetch_one(
                "SELECT bot_id FROM bots WHERE bot_id = ?", (bot_id,)
            )
            if not row:
                return False
            await db.execute("DELETE FROM bots WHERE bot_id = ?", (bot_id,))
            return True
        finally:
            await db.close()

    if not _run(_run_remove()):
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}")
        return

    fmt.success(f"봇 삭제 완료: {bot_id}")


@bot.command("positions")
@click.argument("bot_id")
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_positions(ctx: click.Context, bot_id: str) -> None:
    """봇 보유 포지션 조회."""
    fmt = get_formatter(ctx)

    async def _run_positions() -> list[dict]:
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus
        from ante.trade.performance import PerformanceTracker
        from ante.trade.position import PositionHistory
        from ante.trade.recorder import TradeRecorder
        from ante.trade.service import TradeService

        db = Database("db/ante.db")
        await db.connect()
        try:
            eventbus = EventBus()
            recorder = TradeRecorder(db, eventbus)
            await recorder.initialize()
            position_history = PositionHistory(db, eventbus)
            await position_history.initialize()
            performance = PerformanceTracker(db)
            await performance.initialize()
            service = TradeService(recorder, position_history, performance)
            positions = await service.get_positions(bot_id)
            return [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_entry_price": p.avg_entry_price,
                    "realized_pnl": p.realized_pnl,
                }
                for p in positions
            ]
        finally:
            await db.close()

    result = _run(_run_positions())

    if not result:
        fmt.output({"message": "보유 포지션 없음", "positions": []})
        return

    if fmt.is_json:
        fmt.output({"positions": result})
    else:
        fmt.table(result, ["symbol", "quantity", "avg_entry_price", "realized_pnl"])
