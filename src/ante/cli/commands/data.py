"""ante data — 데이터 관리 커맨드."""

from __future__ import annotations

from pathlib import Path

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def data() -> None:
    """데이터 관리."""


@data.command("list")
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
@require_auth
@require_scope("data:read")
def data_list(ctx: click.Context, data_path: str, db_path: str) -> None:
    """보유 데이터셋 목록."""
    import asyncio

    from ante.data.catalog import DataCatalog
    from ante.data.store import ParquetStore

    fmt = get_formatter(ctx)
    store = ParquetStore(base_path=data_path)
    catalog = DataCatalog(store)
    datasets = catalog.list_datasets()

    if not datasets:
        fmt.output({"datasets": [], "count": 0})
        return

    async def _enrich(items: list[dict]) -> list[dict]:
        from ante.core.database import Database
        from ante.instrument.service import InstrumentService

        db = Database(db_path)
        await db.connect()
        try:
            svc = InstrumentService(db)
            await svc.initialize()
            for item in items:
                item["name"] = svc.get_name(item["symbol"])
            return items
        finally:
            await db.close()

    datasets = asyncio.run(_enrich(datasets))
    fmt.table(datasets, ["symbol", "name", "timeframe", "start", "end"])


@data.command()
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.pass_context
@require_auth
@require_scope("data:read")
def schema(ctx: click.Context, data_path: str) -> None:
    """OHLCV 데이터 스키마 조회."""
    from ante.data.catalog import DataCatalog
    from ante.data.store import ParquetStore

    fmt = get_formatter(ctx)
    store = ParquetStore(base_path=data_path)
    catalog = DataCatalog(store)
    fmt.output(catalog.get_schema())


@data.command()
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.pass_context
@require_auth
@require_scope("data:read")
def storage(ctx: click.Context, data_path: str) -> None:
    """저장 용량 현황."""
    from ante.data.catalog import DataCatalog
    from ante.data.store import ParquetStore

    fmt = get_formatter(ctx)
    store = ParquetStore(base_path=data_path)
    catalog = DataCatalog(store)
    summary = catalog.get_storage_summary()

    fmt.output(
        summary,
        "Total: {total_mb} MB",
    )


@data.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--symbol", required=True, help="종목 코드")
@click.option("--timeframe", default="1d", help="타임프레임")
@click.option("--source", default="external", help="데이터 소스")
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.pass_context
@require_auth
@require_scope("data:write")
def inject(
    ctx: click.Context,
    path: str,
    symbol: str,
    timeframe: str,
    source: str,
    data_path: str,
) -> None:
    """CSV 파일에서 데이터 주입."""
    import asyncio

    from ante.data.injector import DataInjector
    from ante.data.normalizer import DataNormalizer
    from ante.data.store import ParquetStore

    fmt = get_formatter(ctx)
    store = ParquetStore(base_path=data_path)
    normalizer = DataNormalizer()
    injector = DataInjector(store=store, normalizer=normalizer)

    count = asyncio.run(
        injector.inject_csv(Path(path), symbol, timeframe, source=source)
    )

    fmt.success(
        f"Injected {count} rows for {symbol}/{timeframe}",
        {"count": count, "symbol": symbol, "timeframe": timeframe},
    )


@data.command("validate")
@click.option("--symbol", default=None, help="검증할 종목 코드 (미지정 시 전체)")
@click.option("--timeframe", default="1d", help="타임프레임")
@click.option(
    "--fix", is_flag=True, default=False, help="손상 파일을 .corrupted로 이동"
)
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.pass_context
@require_auth
@require_scope("data:read")
def validate(
    ctx: click.Context,
    symbol: str | None,
    timeframe: str,
    fix: bool,
    data_path: str,
) -> None:
    """Parquet 파일 무결성 검증."""
    import asyncio

    from ante.data.store import ParquetStore

    fmt = get_formatter(ctx)
    store = ParquetStore(base_path=data_path)

    if symbol:
        symbols = [symbol]
    else:
        symbols = store.list_symbols(timeframe)

    if not symbols:
        fmt.output({"message": "검증할 데이터가 없습니다.", "results": []})
        return

    async def _validate() -> list[dict]:
        results = []
        for sym in symbols:
            result = await store.validate(sym, timeframe, fix=fix)
            results.append(result)
        return results

    results = asyncio.run(_validate())

    total_files = sum(r["total"] for r in results)
    total_valid = sum(r["valid"] for r in results)
    total_corrupted = sum(r["corrupted"] for r in results)

    if fmt.is_json:
        fmt.output(
            {
                "results": results,
                "summary": {
                    "total_files": total_files,
                    "valid": total_valid,
                    "corrupted": total_corrupted,
                    "fixed": fix and total_corrupted > 0,
                },
            }
        )
    else:
        for r in results:
            if r["corrupted"] > 0:
                click.echo(
                    f"  {r['symbol']}/{r['timeframe']}: "
                    f"{r['total']}개 중 {r['corrupted']}개 손상"
                )
                for cf in r["corrupted_files"]:
                    click.echo(f"    → {cf}")
        click.echo()
        click.echo(
            f"  검증 완료: 전체 {total_files}개 / "
            f"정상 {total_valid}개 / 손상 {total_corrupted}개"
        )
        if fix and total_corrupted > 0:
            click.echo("  손상 파일을 .corrupted로 이동 완료")
