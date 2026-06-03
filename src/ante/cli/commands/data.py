"""ante data — 데이터 관리 커맨드."""

from __future__ import annotations

import click

from ante.cli._data_path import resolve_data_path
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import enforce_scope, require_auth, require_scope


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
) -> None:
    """보유 데이터셋 목록."""
    import asyncio

    from ante.data.datasets import list_datasets, validate_dataset_filters
    from ante.data.store import ParquetStore

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
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
        fmt.error(str(e), code="DATA_INVALID_FILTER")
        raise SystemExit(1) from e

    datasets = result["items"]
    if not datasets:
        fmt.output({"datasets": [], "count": result["total"]})
        return

    async def _enrich(items: list[dict]) -> list[dict]:
        from ante.instrument.service import InstrumentService

        # ``data list`` 는 ParquetStore (파일) 에서 datasets 를 읽는 offline read
        # 명령이며, DB 는 종목명 보강 (``get_name``) 에만 쓰인다. read-only DB
        # artifact (``--db-path`` 로 지정된 0444 파일 / 0555 부모 디렉터리) 에서
        # ``InstrumentService.initialize()`` (CREATE TABLE instruments DDL) 나
        # ``Database(read_only=False)`` (WAL PRAGMA writer 연결) 를 발화하면
        # read-only fs 에서 실패한다. 따라서 ``backtest history`` (#1974) 와 동형
        # 으로 ``open_cli_db(read_only=True)`` + ``svc.load_readonly()`` (DDL 없는
        # 캐시 워밍) 를 사용한다 (offline-factory.md §2 옵션 A). ``--db-path``
        # 원시 값 (None 가능) 을 그대로 ``db_path_override`` 로 전달하면
        # ``open_cli_db`` 가 None 일 때 ``get_db_path(ctx)`` 로 해석하므로 기존
        # ``--db-path`` 동작과 동치다 (approval.py / backtest.py 패턴).
        async with open_cli_db(ctx, read_only=True, db_path_override=db_path) as db:
            svc = InstrumentService(db)
            # initialize() 대신 load_readonly(): schema DDL 없이 캐시만 워밍한다.
            # instruments 테이블이 부재하면 빈 캐시로 정규화되어 ``get_name`` 이
            # symbol fallback 을 반환한다 (malformed/locked 등 다른
            # OperationalError 는 재전파 → 아래 DATA_ERROR 로 변환).
            await svc.load_readonly()
            for item in items:
                item["name"] = svc.get_name(item["symbol"])
            return items

    try:
        datasets = asyncio.run(_enrich(datasets))
    except Exception as e:
        # malformed/locked DB 등 종목명 보강 단계의 DB 에러는 traceback 을
        # JSON 으로 노출하지 않고 public error code 로 변환한다 (#1984 —
        # ``backtest history`` 의 BACKTEST_ERROR 분류 동형). read-only 성공
        # 경로 (테이블 존재/부재 graceful) 는 본 분기에 들어오지 않는다.
        fmt.error(str(e), code="DATA_ERROR")
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output({"datasets": datasets, "count": result["total"]})
    else:
        fmt.table(
            datasets,
            [
                "id",
                "symbol",
                "name",
                "timeframe",
                "data_type",
                "start_date",
                "end_date",
            ],
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
def data_info(ctx: click.Context, dataset_id: str, data_path: str | None) -> None:
    """데이터셋 상세 조회."""
    from ante.data.datasets import get_dataset_detail
    from ante.data.store import ParquetStore

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    store = ParquetStore(base_path=data_path)
    try:
        result = get_dataset_detail(store, dataset_id)
    except ValueError as e:
        fmt.error(str(e), code="DATA_INVALID_DATASET_ID")
        raise SystemExit(1) from e
    except FileNotFoundError as e:
        fmt.error(str(e), code="DATASET_NOT_FOUND")
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(result)
        return

    dataset = result["dataset"]
    for key in (
        "id",
        "symbol",
        "timeframe",
        "data_type",
        "start_date",
        "end_date",
        "row_count",
        "file_size",
    ):
        click.echo(f"  {key:12s}: {dataset.get(key)}")
    if result["preview"]:
        click.echo("")
        click.echo("  preview:")
        for row in result["preview"]:
            click.echo(f"    {row}")


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
) -> None:
    """데이터셋 삭제."""
    from ante.data.datasets import delete_dataset, validate_dataset_filters
    from ante.data.store import ParquetStore

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    if not yes:
        fmt.error(
            "위험 명령입니다. --yes를 명시해야 데이터셋을 삭제합니다.",
            code="CLI_CONFIRMATION_REQUIRED",
        )
        raise SystemExit(1)

    store = ParquetStore(base_path=data_path)
    try:
        normalized_type = validate_dataset_filters(data_type=data_type)
        result = delete_dataset(store, dataset_id, data_type=normalized_type)
    except ValueError as e:
        fmt.error(str(e), code="DATA_INVALID_DATASET_ID")
        raise SystemExit(1) from e
    except FileNotFoundError as e:
        fmt.error(str(e), code="DATASET_NOT_FOUND")
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(result)
    else:
        fmt.success(f"데이터셋 삭제 완료: {dataset_id}", result)


@data.command()
@click.option(
    "--data-path",
    default=None,
    help="데이터 디렉토리 경로 (미지정 시 config_dir 기반)",
)
@click.pass_context
@require_auth
@require_scope("data:read")
def schema(ctx: click.Context, data_path: str | None) -> None:
    """데이터 스키마 조회."""
    from ante.data.schemas import OHLCV_SCHEMA

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    fmt.output({k: str(v) for k, v in OHLCV_SCHEMA.items()})


@data.command()
@click.option(
    "--data-path",
    default=None,
    help="데이터 디렉토리 경로 (미지정 시 config_dir 기반)",
)
@click.pass_context
@require_auth
@require_scope("data:read")
def storage(ctx: click.Context, data_path: str | None) -> None:
    """저장 용량 현황."""
    from ante.data.store import ParquetStore

    data_path = resolve_data_path(ctx, data_path)
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
) -> None:
    """Parquet 파일 무결성 검증."""

    from ante.core.market_data_vocab import (
        CANONICAL_TIMEFRAMES,
        is_krx_symbol,
        is_valid_timeframe,
    )
    from ante.data.store import ParquetStore

    # 조건부 권한 경계: `--fix` 는 손상 파일을 `.corrupted` 로 격리(rename)하는
    # mutating 경로다. flat scope 모델(`member/scopes.py` SSOT — 계층 없음)에서
    # `data:write` 는 `data:read` 를 함의하지 않으므로, `@require_scope("data:read")`
    # 데코레이터에 더해 write 권한을 조건부로 검증한다. 어떤 입력검증·경로
    # resolution·파일 mutation(store.validate(..., fix=True) 의 rename)보다
    # **먼저** 발화한다. 미인가(read-only) 토큰은 입력 유효성·경로 resolution과
    # 무관하게 즉시 permission_denied 여야 하므로(정보 노출 순서 정리 + 어떤
    # side effect보다 우선) 함수 본문 최상단에서 fail-fast 한다. enforce_scope 는
    # ctx 만 필요하고 _emit_auth_error 는 get_formatter 선행이 불필요하다
    # (require_scope 데코레이터도 본문 진입 전 발화한다).
    if fix:
        enforce_scope(ctx, "data:write")

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)

    # 타임프레임/심볼 검증 (CLI 경계 단일 지점, SSOT helper 위임).
    # precedence: ① timeframe → ② KRX symbol shape. ParquetStore 생성·
    # store.list_symbols·store.validate·`if not symbols:` exit-0 이전이어야
    # invalid 입력이 "검증할 데이터 없음" fake-success 로 처리되지 않는다.
    # `data validate`는 --exchange 옵션 없는 KRX-domain local store 대상이라
    # symbol에 is_krx_symbol을 직접 적용한다 (core.md `### KRX symbol shape`
    # 정합 — 비-KRX 경로 부재). `--symbol` 미지정(symbol is None)은 기존 전체
    # validate 동작을 유지하며 거부하지 않는다.
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
