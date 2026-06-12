"""ante trade — 거래 내역 조회 커맨드."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

import click

from ante.cli._validators import reject_inverted_date_range, validate_iso_date
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.trade.service import TradeService


@click.group()
def trade() -> None:
    """거래 내역 조회."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


@asynccontextmanager
async def _create_trade_service(
    ctx: click.Context | None = None,
) -> AsyncIterator[tuple[TradeService, Database]]:
    """CLI 에서 ``TradeService`` async context manager.

    ``open_cli_db`` 기반 lifecycle (factory composition, account.py 패턴
    1:1 미러). 호출 패턴:

        async with _create_trade_service(ctx=ctx) as (service, db):
            ...

    ``PositionHistory``/``TradeRecorder`` ``initialize()`` 는 표 생성용으로
    그대로 보존한다 (read-only 명시 예외는 AuditLogger/DynamicConfigService
    만; 본 helper 는 안전성을 위해 호출 유지).
    """
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
        # ``_create_trade_service`` async context manager lifecycle.
        async with _create_trade_service(ctx=ctx) as (service, _):
            # ``--from`` 은 naive ``T00:00:00`` 하한을 그대로 유지한다(비변경).
            #   - aware fd 로 바꾸면, 자정 정각에 저장된 naive isoformat 행
            #     (``'D'`` prefix-shorter)이 lexical 비교에서 의도치 않게
            #     제외되는 반례가 생긴다.
            #   - 공백 구분 포맷(``save_adjustment`` 의 ``'D HH:MM:SS'``)의 당일
            #     ``--from`` 경계 제외(``' '(0x20) < 'T'(0x54)``)는 main 기존재
            #     known-limitation 이며 본 수정은 도입·악화하지 않는다
            #     (#2367 Non-Goals — 저장 포맷 정규화 follow-up).
            fd = datetime.fromisoformat(from_date) if from_date else None
            # ``--to D`` 는 date-only 일 때 당일 end-of-day(``23:59:59.999999``)
            # UTC-aware 상한으로 변환한다. date-only 를 ``fromisoformat`` 으로
            # 그대로 넘기면 ``T00:00:00`` 이 되어 당일 장중 거래가
            # ``timestamp <= ?`` 에서 전부 제외된다(#2367). ``bot.py:941``
            # (``_parse_log_datetime`` end-of-day)의 ``time.max, tzinfo=UTC``
            # 선례를 1:1 미러한다. isoformat aware 저장(당일 마지막 microsecond
            # equal 포함, 다음날 제외) / 공백 포맷 저장(``' ' < 'T'`` 포함, 다음날
            # 날짜 prefix 제외) 두 포맷 모두 lexical 상한이 정확하다.
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
        # ``open_cli_db`` 헬퍼 lifecycle (cleanup invariant — 예외/cancellation
        # 시에도 ``Database.close()`` 1회 보장).
        async with open_cli_db(ctx) as db:
            # fresh DB 에서는 `trades` 테이블이 아직 생성되지 않은 상태일 수
            # 있다. (`_create_trade_service` 경로와 달리 `trade info` 는
            # raw db 핸들만 쓰고 `TradeRecorder.initialize` 를 거치지 않는다.)
            # 정의상 테이블 부재는 해당 trade 미존재와 동치이므로 not-found 로
            # 정규화한다. malformed DB 같은 다른 OperationalError 까지
            # 삼키지 않도록 "no such table" 메시지로만 좁힌다.
            try:
                row = await db.fetch_one(
                    "SELECT * FROM trades WHERE trade_id = ?", (trade_id,)
                )
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    return None
                raise
            return dict(row) if row else None

    # 호출 표면 try/except: 위 _run_info 에서 흡수하지 못한 비정상 예외는
    # TRADE_ERROR 로 분류해 raw traceback 노출을 차단한다.
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
