"""ante instrument — 종목 마스터 데이터 관리 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter


@click.group()
def instrument() -> None:
    """종목 마스터 데이터 관리."""


@instrument.command("list")
@click.option("--exchange", default="KRX", help="거래소 (기본: KRX)")
@click.option(
    "--type", "inst_type", default=None, help="종목 유형 필터 (stock, etf, etn 등)"
)
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
def instrument_list(
    ctx: click.Context,
    exchange: str,
    inst_type: str | None,
    db_path: str,
) -> None:
    """등록된 종목 목록 조회."""
    from ante.core.database import Database
    from ante.instrument.service import InstrumentService

    fmt = get_formatter(ctx)

    async def _run() -> list[dict]:
        db = Database(db_path)
        await db.connect()
        try:
            svc = InstrumentService(db)
            await svc.initialize()

            query = "SELECT * FROM instruments WHERE exchange = ?"
            params: list[object] = [exchange]

            if inst_type:
                query += " AND instrument_type = ?"
                params.append(inst_type)

            query += " ORDER BY symbol"
            rows = await db.fetch_all(query, tuple(params))
            return [
                {
                    "symbol": r["symbol"],
                    "name": r["name"] or "",
                    "name_en": r["name_en"] or "",
                    "type": r["instrument_type"] or "",
                    "listed": "Y" if r["listed"] else "N",
                }
                for r in rows
            ]
        finally:
            await db.close()

    results = asyncio.run(_run())

    if not results:
        fmt.output({"instruments": [], "count": 0})
        return

    fmt.table(results, ["symbol", "name", "name_en", "type", "listed"])


@instrument.command()
@click.argument("keyword")
@click.option("--limit", default=20, help="최대 결과 수")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
def search(
    ctx: click.Context,
    keyword: str,
    limit: int,
    db_path: str,
) -> None:
    """키워드로 종목 검색 (종목코드, 한글명, 영문명)."""
    from ante.core.database import Database
    from ante.instrument.service import InstrumentService

    fmt = get_formatter(ctx)

    async def _run() -> list[dict]:
        db = Database(db_path)
        await db.connect()
        try:
            svc = InstrumentService(db)
            await svc.initialize()
            instruments = await svc.search(keyword, limit=limit)
            return [
                {
                    "symbol": inst.symbol,
                    "exchange": inst.exchange,
                    "name": inst.name,
                    "name_en": inst.name_en,
                    "type": inst.instrument_type,
                }
                for inst in instruments
            ]
        finally:
            await db.close()

    results = asyncio.run(_run())

    if not results:
        fmt.output({"results": [], "count": 0})
        return

    fmt.table(results, ["symbol", "exchange", "name", "name_en", "type"])
