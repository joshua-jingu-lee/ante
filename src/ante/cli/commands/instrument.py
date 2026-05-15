"""ante instrument — 종목 마스터 데이터 관리 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope
from ante.core.exchange import CANONICAL_EXCHANGES, is_canonical

# 비-canonical exchange 공통 거부 (list/sync/import 3 ingress).
_INVALID_EXCHANGE_CODE = "INSTRUMENT_INVALID_EXCHANGE"
# canonical이나 현재 sync source(KIS domestic/KRX)가 미지원 (sync 전용, 축 B).
_SYNC_SOURCE_UNSUPPORTED_CODE = "INSTRUMENT_SYNC_SOURCE_UNSUPPORTED"
# KIS sync source(KISDomesticAdapter=domestic-stock/KOSPI/KOSDAQ master)가
# 지원하는 canonical exchange. KRX 도메인 전용 계약 근거 (broker/kis.py
# ``KISAdapter = KISDomesticAdapter``). 나머지 canonical은 source 미지원.
_SYNC_SUPPORTED_EXCHANGES: frozenset[str] = frozenset({"KRX"})


def _allowed_exchanges_hint() -> str:
    """에러 메시지용 canonical 허용값 — 정렬 고정 (error-code SSOT)."""
    return ", ".join(sorted(CANONICAL_EXCHANGES))


@click.group()
def instrument() -> None:
    """종목 마스터 데이터 관리."""


@instrument.command("list")
@click.option("--exchange", default="KRX", help="거래소 (기본: KRX)")
@click.option(
    "--type", "inst_type", default=None, help="종목 유형 필터 (stock, etf, etn 등)"
)
@click.option("--listed-only", is_flag=True, help="상장 종목만 표시")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("data:read")
def instrument_list(
    ctx: click.Context,
    exchange: str,
    inst_type: str | None,
    listed_only: bool,
    db_path: str | None,
) -> None:
    """등록된 종목 목록 조회."""
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.instrument.service import InstrumentService

    fmt = get_formatter(ctx)
    resolved_db_path = db_path or get_db_path(ctx)

    # Axis 1 — ingress 옵션 검증: exchange 사용 전 canonical 검증.
    # `*` 도 비-canonical이라 거부됨 (StrategyMeta 전용 wildcard).
    if not is_canonical(exchange):
        fmt.error(
            f"유효하지 않은 거래소: {exchange!r}. 허용 값: {_allowed_exchanges_hint()}",
            code=_INVALID_EXCHANGE_CODE,
        )
        ctx.exit(1)

    async def _run() -> list[dict]:
        db = Database(resolved_db_path)
        await db.connect()
        try:
            svc = InstrumentService(db)
            await svc.initialize()

            query = "SELECT * FROM instruments WHERE exchange = ?"
            params: list[object] = [exchange]

            if inst_type:
                query += " AND instrument_type = ?"
                params.append(inst_type)

            if listed_only:
                query += " AND listed = 1"

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
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("data:write")
def sync(
    ctx: click.Context,
    exchange: str,
    db_path: str | None,
) -> None:
    """KIS API에서 종목 마스터 데이터를 동기화."""
    from ante.broker.kis import KISAdapter
    from ante.cli.main import get_config_dir, get_db_path
    from ante.config import Config
    from ante.core.database import Database
    from ante.instrument.models import Instrument
    from ante.instrument.service import InstrumentService

    fmt = get_formatter(ctx)
    resolved_db_path = db_path or get_db_path(ctx)
    resolved_config_dir = get_config_dir(ctx)

    # Axis 1 — ingress 옵션 검증: 비-canonical exchange 거부 (KISAdapter
    # 호출 전). `*` 도 비-canonical이라 거부됨.
    if not is_canonical(exchange):
        fmt.error(
            f"유효하지 않은 거래소: {exchange!r}. 허용 값: {_allowed_exchanges_hint()}",
            code=_INVALID_EXCHANGE_CODE,
        )
        ctx.exit(1)

    # Axis 3 — sync source-binding (축 B): canonical 검증 통과 후,
    # 현재 sync source(KIS domestic/KRX)가 미지원하는 canonical
    # exchange (= CANONICAL_EXCHANGES - {"KRX"}, 즉 NYSE/NASDAQ/AMEX/TEST)
    # 이면 invalid과 구분되는 별도 에러로 거부한다. canonical을 invalid로
    # 거부하지 않는다 (축 A/B 불변식).
    if exchange not in _SYNC_SUPPORTED_EXCHANGES:
        supported = ", ".join(sorted(_SYNC_SUPPORTED_EXCHANGES))
        fmt.error(
            f"거래소 {exchange!r}는 canonical이나 현재 sync source"
            f"(KIS domestic/KRX)가 미지원합니다 — invalid exchange 아님. "
            f"sync 지원 거래소: {supported}",
            code=_SYNC_SOURCE_UNSUPPORTED_CODE,
        )
        ctx.exit(1)

    async def _run() -> dict:
        config = Config.load(config_dir=resolved_config_dir)
        broker_config = config.get("broker", {})
        if not broker_config.get("app_key"):
            return {"error": "브로커 설정이 없습니다."}

        db = Database(resolved_db_path)
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
@click.option("--limit", default=20, type=click.IntRange(min=1), help="최대 결과 수")
@click.option("--listed-only", is_flag=True, help="상장 종목만 검색")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("data:read")
def search(
    ctx: click.Context,
    keyword: str,
    limit: int,
    listed_only: bool,
    db_path: str | None,
) -> None:
    """키워드로 종목 검색 (종목코드, 한글명, 영문명)."""
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.instrument.service import InstrumentService

    fmt = get_formatter(ctx)
    resolved_db_path = db_path or get_db_path(ctx)

    async def _run() -> list[dict]:
        db = Database(resolved_db_path)
        await db.connect()
        try:
            svc = InstrumentService(db)
            await svc.initialize()
            instruments = await svc.search(
                keyword,
                limit=limit,
                listed_only=listed_only,
            )
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


@instrument.command("import")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="실제 저장 없이 미리보기")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("data:write")
def instrument_import(
    ctx: click.Context,
    file_path: str,
    dry_run: bool,
    db_path: str | None,
) -> None:
    """CSV/JSON 파일에서 종목 데이터 import."""
    import json
    from pathlib import Path

    from ante.cli.main import get_db_path
    from ante.instrument.models import Instrument

    fmt = get_formatter(ctx)
    path = Path(file_path)
    ext = path.suffix.lower()
    resolved_db_path = db_path or get_db_path(ctx)

    # 파일 형식 확인 (try 블록 밖에서 분기 — ctx.exit(1)이 같은 try의
    # except Exception에 잡혀 swallow되는 것을 방지)
    if ext not in (".csv", ".json"):
        fmt.error(f"지원하지 않는 파일 형식: {ext} (csv 또는 json만 지원)")
        ctx.exit(1)

    # 파일 읽기
    try:
        if ext == ".csv":
            import csv

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                records = list(reader)
        else:  # ".json"
            with open(path, encoding="utf-8") as f:
                records = json.load(f)
    except Exception as e:
        fmt.error(f"파일 읽기 실패: {e}")
        ctx.exit(1)

    if ext == ".json" and not isinstance(records, list):
        fmt.error("JSON 파일은 배열 형태여야 합니다.")
        ctx.exit(1)

    if not records:
        fmt.error("파일에 데이터가 없습니다.")
        ctx.exit(1)

    # 필수 컬럼 확인
    first = records[0]
    if "symbol" not in first or "exchange" not in first:
        fmt.error("필수 컬럼 누락: symbol, exchange가 필요합니다.")
        ctx.exit(1)

    # Axis 2 — import 행별 검증: dry-run preview/실저장 전, 각 행
    # exchange를 canonical 검증한다. 하나라도 비-canonical이면 해당 행
    # (symbol/exchange) 식별 포함 에러로 거부한다. 유효 입력의 --dry-run은
    # 이 검증을 통과하므로 exit 0이 회귀 보존된다.
    for idx, r in enumerate(records):
        row_exchange = r.get("exchange", "")
        # JSON import 행은 비문자열 exchange(list/dict/number/None 등)를
        # 가질 수 있다. is_canonical()의 frozenset membership은 unhashable
        # 값에 TypeError를 던지므로, 호출 전 isinstance(str) 가드로 차단해
        # 비-canonical과 동일한 구조화 invalid-exchange 경로로 보낸다
        # (CSV는 항상 str, CLI --exchange는 click이 str 보장 — import
        # 행 경로만 해당).
        if not isinstance(row_exchange, str) or not is_canonical(row_exchange):
            row_symbol = r.get("symbol", "")
            fmt.error(
                f"유효하지 않은 거래소: {row_exchange!r} "
                f"(행 {idx + 1}, symbol={row_symbol!r}). "
                f"허용 값: {_allowed_exchanges_hint()}",
                code=_INVALID_EXCHANGE_CODE,
            )
            ctx.exit(1)

    instruments = [
        Instrument(
            symbol=r["symbol"],
            exchange=r["exchange"],
            name=r.get("name", ""),
            name_en=r.get("name_en", ""),
            instrument_type=r.get("instrument_type", ""),
            listed=str(r.get("listed", "true")).lower() in ("true", "1", "yes", "y"),
        )
        for r in records
    ]

    if dry_run:
        preview = [
            {
                "symbol": inst.symbol,
                "exchange": inst.exchange,
                "name": inst.name,
                "type": inst.instrument_type,
            }
            for inst in instruments[:10]
        ]
        if fmt.is_json:
            fmt.output(
                {
                    "dry_run": True,
                    "total": len(instruments),
                    "preview": preview,
                }
            )
        else:
            click.echo(f"  미리보기 ({len(instruments)}건 중 상위 {len(preview)}건):")
            fmt.table(
                preview,
                ["symbol", "exchange", "name", "type"],
            )
        return

    async def _import() -> int:
        from ante.core.database import Database
        from ante.instrument.service import InstrumentService

        db = Database(resolved_db_path)
        await db.connect()
        try:
            svc = InstrumentService(db)
            await svc.initialize()
            return await svc.bulk_upsert(instruments)
        finally:
            await db.close()

    count = asyncio.run(_import())
    fmt.success(
        f"종목 import 완료: {count}건",
        {"count": count, "file": str(path)},
    )
