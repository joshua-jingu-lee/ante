"""ante data — 데이터 관리 커맨드."""

from __future__ import annotations

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def data() -> None:
    """데이터 관리."""


@data.command("list")
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("data:read")
def data_list(ctx: click.Context, data_path: str, db_path: str | None) -> None:
    """보유 데이터셋 목록."""
    import asyncio

    from ante.cli.main import get_db_path
    from ante.data.schemas import TIMEFRAMES
    from ante.data.store import ParquetStore

    fmt = get_formatter(ctx)
    store = ParquetStore(base_path=data_path)
    resolved_db_path = db_path or get_db_path(ctx)

    datasets = []
    for tf in TIMEFRAMES:
        symbols = store.list_symbols(tf)
        for symbol in symbols:
            date_range = store.get_date_range(symbol, tf)
            datasets.append(
                {
                    "symbol": symbol,
                    "timeframe": tf,
                    "start": date_range[0] if date_range else None,
                    "end": date_range[1] if date_range else None,
                }
            )

    if not datasets:
        fmt.output({"datasets": [], "count": 0})
        return

    async def _enrich(items: list[dict]) -> list[dict]:
        from ante.core.database import Database
        from ante.instrument.service import InstrumentService

        db = Database(resolved_db_path)
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
    """데이터 스키마 조회."""
    from ante.data.schemas import OHLCV_SCHEMA

    fmt = get_formatter(ctx)
    fmt.output({k: str(v) for k, v in OHLCV_SCHEMA.items()})


@data.command()
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.pass_context
@require_auth
@require_scope("data:read")
def storage(ctx: click.Context, data_path: str) -> None:
    """저장 용량 현황."""
    from ante.data.store import ParquetStore

    fmt = get_formatter(ctx)
    store = ParquetStore(base_path=data_path)
    usage = store.get_storage_usage()
    total = sum(usage.values())
    summary = {
        "total_bytes": total,
        "total_mb": round(total / 1024 / 1024, 1),
        "by_timeframe": {
            tf: round(size / 1024 / 1024, 1) for tf, size in usage.items()
        },
    }

    fmt.output(
        summary,
        "Total: {total_mb} MB",
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

    from ante.core.market_data_vocab import (
        CANONICAL_TIMEFRAMES,
        is_krx_symbol,
        is_valid_timeframe,
    )
    from ante.data.store import ParquetStore

    fmt = get_formatter(ctx)

    # 타임프레임/심볼 검증 (CLI 경계 단일 지점, #1613 SSOT helper 위임).
    # precedence: ① timeframe → ② KRX symbol shape. ParquetStore 생성·
    # store.list_symbols·store.validate·`if not symbols:` exit-0 이전이어야
    # invalid 입력이 "검증할 데이터 없음" fake-success(#1591 oracle 증상)로
    # 처리되지 않는다. `data validate`는 --exchange 옵션 없는 KRX-domain
    # local store 대상이라 symbol에 is_krx_symbol을 직접 적용한다
    # (core.md `### KRX symbol shape` 정합 — 비-KRX 경로 부재).
    # `--symbol` 미지정(symbol is None)은 기존 전체 validate 동작을
    # 유지하며 거부하지 않는다.
    if not is_valid_timeframe(timeframe):
        fmt.error(
            f"유효하지 않은 타임프레임: {timeframe!r}. "
            f"허용 값: {', '.join(CANONICAL_TIMEFRAMES)}",
            code="DATA_VALIDATE_INVALID_TIMEFRAME",
        )
        raise SystemExit(1)

    if symbol is not None and not is_krx_symbol(symbol):
        fmt.error(
            f"유효하지 않은 종목 코드: {symbol!r} (KRX 6자리 숫자)",
            code="DATA_VALIDATE_INVALID_SYMBOL",
        )
        raise SystemExit(1)

    store = ParquetStore(base_path=data_path)

    if symbol:
        symbols = [symbol]
    else:
        symbols = store.list_symbols(timeframe)

    if not symbols:
        fmt.output({"message": "검증할 데이터가 없습니다.", "results": []})
        return

    results = []
    for sym in symbols:
        result = store.validate(sym, timeframe, fix=fix)
        results.append(result)

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
