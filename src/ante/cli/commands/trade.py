"""ante trade — 거래 내역 조회 커맨드."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime

import click

from ante.cli._validators import reject_inverted_date_range, validate_iso_date
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def trade() -> None:
    """거래 내역 조회."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_trade_service():  # noqa: ANN202
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.trade.performance import PerformanceTracker
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder
    from ante.trade.service import TradeService

    db = Database(get_db_path())
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
) -> None:
    """거래 목록 조회."""
    fmt = get_formatter(ctx)

    # inverted date range(시작일 > 종료일) 거부: _create_trade_service/DB
    # 생성 및 _run_list 내부 datetime.fromisoformat 이전에 차단한다
    # (backtest.py:72-77 동형, INVALID_DATE_RANGE + exit 1).
    reject_inverted_date_range(
        from_date,
        to_date,
        fmt,
        from_label="시작일",
        to_label="종료일",
    )

    async def _run_list() -> list[dict]:
        service, db = await _create_trade_service()
        try:
            fd = datetime.fromisoformat(from_date) if from_date else None
            td = datetime.fromisoformat(to_date) if to_date else None
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
            [
                "trade_id",
                "bot_id",
                "strategy_id",
                "symbol",
                "side",
                "quantity",
                "price",
                "status",
            ],
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
        from ante.cli.main import get_db_path
        from ante.core.database import Database

        db = Database(get_db_path())
        await db.connect()
        try:
            # fresh DB 에서는 `trades` 테이블이 아직 생성되지 않은 상태일 수
            # 있다. (`_create_trade_service` 경로와 달리 `trade info` 는
            # raw db 핸들만 쓰고 `TradeRecorder.initialize` 를 거치지 않는다.)
            # 정의상 테이블 부재는 해당 trade 미존재와 동치이므로 not-found 로
            # 정규화한다. malformed DB 같은 다른 OperationalError 까지
            # 삼키지 않도록 "no such table" 메시지로만 좁힌다 (#1753).
            try:
                row = await db.fetch_one(
                    "SELECT * FROM trades WHERE trade_id = ?", (trade_id,)
                )
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    return None
                raise
            return dict(row) if row else None
        finally:
            await db.close()

    # 호출 표면 try/except: 위 _run_info 에서 흡수하지 못한 비정상 예외는
    # TRADE_ERROR 로 분류해 raw traceback 노출을 차단한다 (#1753).
    try:
        result = _run(_run_info())
    except Exception as e:
        fmt.error(str(e), code="TRADE_ERROR")
        raise SystemExit(1) from e

    if not result:
        fmt.error(f"거래를 찾을 수 없습니다: {trade_id}", code="TRADE_NOT_FOUND")
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(result)
    else:
        for key, value in result.items():
            click.echo(f"  {key:15s}: {value}")
