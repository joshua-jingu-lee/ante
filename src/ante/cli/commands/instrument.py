"""ante instrument — 종목 마스터 데이터 관리 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


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
@require_auth
@require_scope("data:read")
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
@click.option("--exchange", default="KRX", help="거래소 (기본: KRX)")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
@require_auth
@require_scope("data:write")
def sync(
    ctx: click.Context,
    exchange: str,
    db_path: str,
) -> None:
    """KIS API에서 종목 마스터 데이터를 동기화."""
    from ante.broker.kis import KISAdapter
    from ante.config import Config
    from ante.core.database import Database
    from ante.instrument.models import Instrument
    from ante.instrument.service import InstrumentService

    fmt = get_formatter(ctx)

    async def _run() -> dict:
        config = Config.load()
        broker_config = config.get("broker", {})
        if not broker_config.get("app_key"):
            return {"error": "브로커 설정이 없습니다."}

        db = Database(db_path)
        await db.connect()
        try:
            svc = InstrumentService(db)
            await svc.initialize()

            # 동기화 전 기존 종목 수
            old_rows = await db.fetch_all(
                "SELECT symbol, listed FROM instruments WHERE exchange = ?",
                (exchange,),
            )
            old_symbols = {r["symbol"] for r in old_rows}
            old_listed = {r["symbol"] for r in old_rows if r["listed"]}

            adapter = KISAdapter(config=broker_config)
            await adapter.connect()
            try:
                raw = await adapter.get_instruments(exchange=exchange)
            finally:
                await adapter.disconnect()

            if not raw:
                return {"error": "종목 데이터를 가져오지 못했습니다."}

            new_symbols = {item["symbol"] for item in raw}

            instruments = [
                Instrument(
                    symbol=item["symbol"],
                    exchange=exchange,
                    name=item.get("name", ""),
                    name_en=item.get("name_en", ""),
                    instrument_type=item.get("instrument_type", ""),
                    listed=item.get("listed", True),
                )
                for item in raw
            ]

            # 상폐 처리: 기존에 listed였지만 새 목록에 없는 종목
            delisted = old_listed - new_symbols
            for sym in delisted:
                await db.execute(
                    "UPDATE instruments SET listed = 0, "
                    "updated_at = datetime('now') "
                    "WHERE symbol = ? AND exchange = ?",
                    (sym, exchange),
                )

            count = await svc.bulk_upsert(instruments)

            new_count = len(new_symbols - old_symbols)
            updated_count = count - new_count
            return {
                "total": count,
                "new": new_count,
                "updated": updated_count,
                "delisted": len(delisted),
            }
        finally:
            await db.close()

    result = asyncio.run(_run())

    if "error" in result:
        click.echo(f"오류: {result['error']}", err=True)
        raise SystemExit(1)

    fmt.output(
        {
            "sync_result": result,
            "message": (
                f"동기화 완료: "
                f"신규 {result['new']}건, "
                f"갱신 {result['updated']}건, "
                f"상폐 {result['delisted']}건"
            ),
        }
    )


@instrument.command()
@click.argument("keyword")
@click.option("--limit", default=20, help="최대 결과 수")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
@require_auth
@require_scope("data:read")
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
