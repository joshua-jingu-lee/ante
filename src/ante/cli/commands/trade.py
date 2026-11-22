"""ante trade — 거래 내역 조회 커맨드."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING, Any

import click

from ante.cli._validators import reject_inverted_date_range, validate_iso_date
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, format_option, table_lines
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope
from ante.contracts.cli_errors import TradeError, TradeNotFoundError
from ante.core.database import OperationalError

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.trade.service import TradeService


@click.group()
def trade() -> None:
    """거래 내역 조회."""


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@asynccontextmanager
async def _create_trade_service(
    ctx: click.Context | None = None,
) -> AsyncIterator[tuple[TradeService, Database]]:
    """CLI 에서 ``TradeService`` async context manager."""
    from ante.trade.performance import PerformanceTracker
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder
    from ante.trade.service import TradeService

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_create_trade_service requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
        position_history = PositionHistory(db=db)
        await position_history.initialize()
        recorder = TradeRecorder(db=db, position_history=position_history)
        await recorder.initialize()
        performance = PerformanceTracker(db=db)
        service = TradeService(recorder, position_history, performance)
        yield service, db


@trade.command("list")
@click.option("--bot", "bot_id", default=None, help="봇 ID 필터")
@click.option("--strategy", "strategy_id", default=None, help="전략 ID 필터")
@click.option(
    "--from",
    "from_date",
    default=None,
    callback=validate_iso_date,
    help="시작일 (YYYY-MM-DD)",
)
@click.option(
    "--to",
    "to_date",
    default=None,
    callback=validate_iso_date,
    help="종료일 (YYYY-MM-DD)",
)
@click.option("--limit", default=50, type=click.IntRange(min=1), help="최대 조회 수")
@format_option
@click.pass_context
@require_auth
@require_scope("trade:read")
def trade_list(
    ctx: click.Context,
    bot_id: str | None,
    strategy_id: str | None,
    from_date: str | None,
    to_date: str | None,
    limit: int,
) -> CommandResult:
    """거래 목록 조회."""
    fmt = get_formatter(ctx)

    reject_inverted_date_range(
        from_date,
        to_date,
        fmt,
        from_label="시작일",
        to_label="종료일",
    )

    async def _run_list() -> list[dict[str, Any]]:
        async with _create_trade_service(ctx=ctx) as (service, _):
            fd = datetime.fromisoformat(from_date) if from_date else None
            td = (
                datetime.combine(date.fromisoformat(to_date), time.max, tzinfo=UTC)
                if to_date
                else None
            )
            trades = await service.get_trades(
                bot_id=bot_id,
                strategy_id=strategy_id,
                from_date=fd,
                to_date=td,
                limit=limit,
            )
            return [
                {
                    "trade_id": str(t.trade_id),
                    "bot_id": t.bot_id,
                    "strategy_id": t.strategy_id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": t.price,
                    "status": t.status,
                    "timestamp": str(t.timestamp) if t.timestamp else "",
                }
                for t in trades
            ]

    result = _run(_run_list())

    if not result:
        empty: dict[str, Any] = {"message": "거래 내역 없음", "trades": []}
        return CommandResult(data=empty, text=(str(empty),))

    columns = [
        "trade_id",
        "bot_id",
        "strategy_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "status",
    ]
    return CommandResult(
        data={"trades": result}, text=tuple(table_lines(result, columns))
    )


@trade.command("info")
@click.argument("trade_id")
@format_option
@click.pass_context
@require_auth
@require_scope("trade:read")
def trade_info(ctx: click.Context, trade_id: str) -> CommandResult:
    """거래 상세 정보 조회."""

    async def _run_info() -> dict[str, Any] | None:
        async with open_cli_db(ctx) as db:
            try:
                row = await db.fetch_one(
                    "SELECT * FROM trades WHERE trade_id = ?", (trade_id,)
                )
            except OperationalError as e:
                if "no such table" in str(e).lower():
                    return None
                raise
            return dict(row) if row else None

    try:
        result = _run(_run_info())
    except Exception as e:
        raise TradeError(str(e)) from e

    if not result:
        raise TradeNotFoundError(f"거래를 찾을 수 없습니다: {trade_id}")

    return CommandResult(
        data=result,
        text=tuple(f"  {key:15s}: {value}" for key, value in result.items()),
    )
