"""ante trade — 거래 내역 조회 커맨드."""

from __future__ import annotations

import asyncio
from datetime import datetime

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def trade() -> None:
    """거래 내역 조회."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_trade_service():  # noqa: ANN202
    from ante.core.database import Database
    from ante.trade.performance import PerformanceTracker
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder
    from ante.trade.service import TradeService

    db = Database("db/ante.db")
    await db.connect()
    position_history = PositionHistory(db=db)
    await position_history.initialize()
    recorder = TradeRecorder(db=db, position_history=position_history)
    await recorder.initialize()
    performance = PerformanceTracker(db=db)
    service = TradeService(recorder, position_history, performance)
    return service, db


@trade.command("list")
@click.option("--bot", "bot_id", default=None, help="봇 ID 필터")
@click.option("--from", "from_date", default=None, help="시작일 (YYYY-MM-DD)")
@click.option("--to", "to_date", default=None, help="종료일 (YYYY-MM-DD)")
@click.option("--limit", default=50, help="최대 조회 수")
@format_option
@click.pass_context
@require_auth
@require_scope("trade:read")
def trade_list(
    ctx: click.Context,
    bot_id: str | None,
    from_date: str | None,
    to_date: str | None,
    limit: int,
) -> None:
    """거래 목록 조회."""
    fmt = get_formatter(ctx)

    async def _run_list() -> list[dict]:
        service, db = await _create_trade_service()
        try:
            fd = datetime.fromisoformat(from_date) if from_date else None
            td = datetime.fromisoformat(to_date) if to_date else None
            trades = await service.get_trades(
                bot_id=bot_id, from_date=fd, to_date=td, limit=limit
            )
            return [
                {
                    "trade_id": str(t.trade_id),
                    "bot_id": t.bot_id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": t.price,
                    "status": t.status,
                    "timestamp": str(t.timestamp) if t.timestamp else "",
                }
                for t in trades
            ]
        finally:
            await db.close()

    result = _run(_run_list())

    if not result:
        fmt.output({"message": "거래 내역 없음", "trades": []})
        return

    if fmt.is_json:
        fmt.output({"trades": result})
    else:
        fmt.table(
            result,
            ["trade_id", "bot_id", "symbol", "side", "quantity", "price", "status"],
        )


@trade.command("info")
@click.argument("trade_id")
@format_option
@click.pass_context
@require_auth
@require_scope("trade:read")
def trade_info(ctx: click.Context, trade_id: str) -> None:
    """거래 상세 정보 조회."""
    fmt = get_formatter(ctx)

    async def _run_info() -> dict | None:
        from ante.core.database import Database

        db = Database("db/ante.db")
        await db.connect()
        try:
            row = await db.fetch_one(
                "SELECT * FROM trades WHERE trade_id = ?", (trade_id,)
            )
            return dict(row) if row else None
        finally:
            await db.close()

    result = _run(_run_info())

    if not result:
        fmt.error(f"거래를 찾을 수 없습니다: {trade_id}")
        return

    if fmt.is_json:
        fmt.output(result)
    else:
        for key, value in result.items():
            click.echo(f"  {key:15s}: {value}")
