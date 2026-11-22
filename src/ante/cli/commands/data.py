"""ante data — 데이터 관리 커맨드."""

from __future__ import annotations

from typing import Any

import click

from ante.cli._data_path import resolve_data_path
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, format_option, table_lines
from ante.cli.middleware import enforce_scope, require_auth, require_scope
from ante.contracts.cli_errors import (
    CliConfirmationRequiredError,
    DataError,
    DataInvalidDatasetIdError,
    DataInvalidFilterError,
    DatasetNotFoundError,
    DataValidateInvalidSymbolError,
    DataValidateInvalidTimeframeError,
)


@click.group()
def data() -> None:
    """데이터 관리."""


@data.command("list")
@click.option("--symbol", default=None, help="종목 코드 exact-match 필터")
@click.option("--timeframe", default=None, help="타임프레임 필터")
@click.option(
    "--type",
    "data_type",
    type=click.Choice(["ohlcv", "fundamental"]),
    default=None,
    help="데이터 유형 필터",
)
@click.option("--offset", default=0, type=click.IntRange(min=0), help="조회 offset")
@click.option("--limit", default=50, type=click.IntRange(min=1), help="조회 개수")
@click.option(
    "--data-path",
    default=None,
    help="데이터 디렉토리 경로 (미지정 시 config_dir 기반)",
)
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@format_option
@click.pass_context
@require_auth
@require_scope("data:read")
def data_list(
    ctx: click.Context,
    symbol: str | None,
    timeframe: str | None,
    data_type: str | None,
    offset: int,
    limit: int,
    data_path: str | None,
    db_path: str | None,
) -> CommandResult:
    """보유 데이터셋 목록."""
    import asyncio

    from ante.data.datasets import list_datasets, validate_dataset_filters
    from ante.data.store import ParquetStore

    data_path = resolve_data_path(ctx, data_path)
    store = ParquetStore(base_path=data_path)

    try:
        normalized_type = validate_dataset_filters(
            timeframe=timeframe,
            data_type=data_type,
        )
        result = list_datasets(
            store,
            symbol=symbol,
            timeframe=timeframe,
            data_type=normalized_type,
            offset=offset,
            limit=limit,
        )
    except ValueError as e:
        raise DataInvalidFilterError(str(e)) from e

    datasets = result["items"]
    if not datasets:
        empty: dict[str, Any] = {"datasets": [], "count": result["total"]}
        return CommandResult(data=empty, text=(str(empty),))

    async def _enrich(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from ante.instrument.service import InstrumentService

        async with open_cli_db(ctx, read_only=True, db_path_override=db_path) as db:
            svc = InstrumentService(db)
            await svc.load_readonly()
            for item in items:
                item["name"] = svc.get_name(item["symbol"])
            return items

    try:
        datasets = asyncio.run(_enrich(datasets))
    except Exception as e:
        raise DataError(str(e)) from e

    columns = [
        "id",
        "symbol",
        "name",
        "timeframe",
        "data_type",
        "start_date",
        "end_date",
    ]
    return CommandResult(
        data={"datasets": datasets, "count": result["total"]},
        text=tuple(table_lines(datasets, columns)),
    )


@data.command("info")
@click.argument("dataset_id")
@click.option(
    "--data-path",
    default=None,
    help="데이터 디렉토리 경로 (미지정 시 config_dir 기반)",
)
@format_option
@click.pass_context
@require_auth
@require_scope("data:read")
def data_info(
    ctx: click.Context, dataset_id: str, data_path: str | None
) -> CommandResult:
    """데이터셋 상세 조회."""
    from ante.data.datasets import get_dataset_detail
    from ante.data.store import ParquetStore

    data_path = resolve_data_path(ctx, data_path)
    store = ParquetStore(base_path=data_path)
    try:
        result = get_dataset_detail(store, dataset_id)
    except ValueError as e:
        raise DataInvalidDatasetIdError(str(e)) from e
    except FileNotFoundError as e:
        raise DatasetNotFoundError(str(e)) from e

    dataset = result["dataset"]
    lines = [
        f"  {key:12s}: {dataset.get(key)}"
        for key in (
            "id",
            "symbol",
            "timeframe",
            "data_type",
            "start_date",
            "end_date",
            "row_count",
            "file_size",
        )
    ]
    if result["preview"]:
        lines += ["", "  preview:", *(f"    {row}" for row in result["preview"])]
    return CommandResult(data=result, text=tuple(lines))


@data.command("delete")
@click.argument("dataset_id")
@click.option(
    "--type",
    "data_type",
    type=click.Choice(["ohlcv", "fundamental"]),
    default=None,
    help="dataset_id 파생 유형과 일치해야 하는 데이터 유형",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="삭제를 확인 (위험 명령). 누락 시 prompt 없이 에러로 실패",
)
@click.option(
    "--data-path",
    default=None,
    help="데이터 디렉토리 경로 (미지정 시 config_dir 기반)",
)
@format_option
@click.pass_context
@require_auth
@require_scope("data:write")
def data_delete(
    ctx: click.Context,
    dataset_id: str,
    data_type: str | None,
    yes: bool,
    data_path: str | None,
) -> CommandResult:
    """데이터셋 삭제."""
    from ante.data.datasets import delete_dataset, validate_dataset_filters
    from ante.data.store import ParquetStore

    data_path = resolve_data_path(ctx, data_path)
    if not yes:
        raise CliConfirmationRequiredError(
            "위험 명령입니다. --yes를 명시해야 데이터셋을 삭제합니다."
        )

    store = ParquetStore(base_path=data_path)
    try:
        normalized_type = validate_dataset_filters(data_type=data_type)
        result = delete_dataset(store, dataset_id, data_type=normalized_type)
    except ValueError as e:
        raise DataInvalidDatasetIdError(str(e)) from e
    except FileNotFoundError as e:
        raise DatasetNotFoundError(str(e)) from e

    return CommandResult(data=result, text=(f"데이터셋 삭제 완료: {dataset_id}",))


@data.command()
@click.option(
    "--data-path",
    default=None,
    help="데이터 디렉토리 경로 (미지정 시 config_dir 기반)",
)
@click.pass_context
@require_auth
@require_scope("data:read")
def schema(ctx: click.Context, data_path: str | None) -> CommandResult:
    """데이터 스키마 조회."""
    from ante.data.schemas import OHLCV_SCHEMA

    data_path = resolve_data_path(ctx, data_path)
    columns = {k: str(v) for k, v in OHLCV_SCHEMA.items()}
    return CommandResult(data=columns, text=(str(columns),))


@data.command()
@click.option(
    "--data-path",
    default=None,
    help="데이터 디렉토리 경로 (미지정 시 config_dir 기반)",
)
@click.pass_context
@require_auth
@require_scope("data:read")
def storage(ctx: click.Context, data_path: str | None) -> CommandResult:
    """저장 용량 현황."""
    from ante.data.store import ParquetStore

    data_path = resolve_data_path(ctx, data_path)
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

    return CommandResult(data=summary, text=(f"Total: {summary['total_mb']} MB",))


@data.command("validate")
@click.option("--symbol", default=None, help="검증할 종목 코드 (미지정 시 전체)")
@click.option("--timeframe", default="1d", help="타임프레임")
@click.option(
    "--fix", is_flag=True, default=False, help="손상 파일을 .corrupted로 이동"
)
@click.option(
    "--data-path",
    default=None,
    help="데이터 디렉토리 경로 (미지정 시 config_dir 기반)",
)
@click.pass_context
@require_auth
@require_scope("data:read")
def validate(
    ctx: click.Context,
    symbol: str | None,
    timeframe: str,
    fix: bool,
    data_path: str | None,
) -> CommandResult:
    """Parquet 파일 무결성 검증."""

    from ante.core.market_data_vocab import (
        CANONICAL_TIMEFRAMES,
        is_krx_symbol,
        is_valid_timeframe,
    )
    from ante.data.store import ParquetStore

    if fix:
        enforce_scope(ctx, "data:write")

    data_path = resolve_data_path(ctx, data_path)

    if not is_valid_timeframe(timeframe):
        raise DataValidateInvalidTimeframeError(
            f"유효하지 않은 타임프레임: {timeframe!r}. "
            f"허용 값: {', '.join(CANONICAL_TIMEFRAMES)}"
        )

    if symbol is not None and not is_krx_symbol(symbol):
        raise DataValidateInvalidSymbolError(
            f"유효하지 않은 종목 코드: {symbol!r} (KRX 6자리 숫자)"
        )

    store = ParquetStore(base_path=data_path)

    if symbol:
        symbols = [symbol]
    else:
        symbols = store.list_symbols(timeframe)

    if not symbols:
        empty: dict[str, Any] = {"message": "검증할 데이터가 없습니다.", "results": []}
        return CommandResult(data=empty, text=(str(empty),))

    results = []
    for sym in symbols:
        result = store.validate(sym, timeframe, fix=fix)
        results.append(result)

    total_files = sum(r["total"] for r in results)
    total_valid = sum(r["valid"] for r in results)
    total_corrupted = sum(r["corrupted"] for r in results)

    lines: list[str] = []
    for r in results:
        if r["corrupted"] > 0:
            lines.append(
                f"  {r['symbol']}/{r['timeframe']}: "
                f"{r['total']}개 중 {r['corrupted']}개 손상"
            )
            lines += [f"    → {cf}" for cf in r["corrupted_files"]]
    lines += [
        "",
        f"  검증 완료: 전체 {total_files}개 / "
        f"정상 {total_valid}개 / 손상 {total_corrupted}개",
    ]
    if fix and total_corrupted > 0:
        lines.append("  손상 파일을 .corrupted로 이동 완료")
    return CommandResult(
        data={
            "results": results,
            "summary": {
                "total_files": total_files,
                "valid": total_valid,
                "corrupted": total_corrupted,
                "fixed": fix and total_corrupted > 0,
            },
        },
        text=tuple(lines),
    )
