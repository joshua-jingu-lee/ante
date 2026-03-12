"""ante data — 데이터 관리 커맨드."""

from __future__ import annotations

from pathlib import Path

import click

from ante.cli.main import get_formatter


@click.group()
def data() -> None:
    """데이터 관리."""


@data.command("list")
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.pass_context
def data_list(ctx: click.Context, data_path: str) -> None:
    """보유 데이터셋 목록."""
    from ante.data.catalog import DataCatalog
    from ante.data.store import ParquetStore

    fmt = get_formatter(ctx)
    store = ParquetStore(base_path=data_path)
    catalog = DataCatalog(store)
    datasets = catalog.list_datasets()

    if not datasets:
        fmt.output({"datasets": [], "count": 0})
        return

    fmt.table(datasets, ["symbol", "timeframe", "start", "end"])


@data.command()
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.pass_context
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
