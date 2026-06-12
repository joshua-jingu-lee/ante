"""InstrumentService — 종목 마스터 데이터 관리 서비스."""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

from ante.instrument.models import Instrument

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

INSTRUMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    symbol           TEXT NOT NULL,
    exchange         TEXT NOT NULL,
    name             TEXT DEFAULT '',
    name_en          TEXT DEFAULT '',
    instrument_type  TEXT DEFAULT '',
    logo_url         TEXT DEFAULT '',
    listed           INTEGER DEFAULT 1,
    updated_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, exchange)
);
CREATE INDEX IF NOT EXISTS idx_instruments_name ON instruments(name);
"""


class InstrumentService:
    """종목 마스터 데이터 조회·관리 서비스.

    전체 종목을 메모리 캐시에 적재하여 동기 조회를 지원한다.
    한국 상장 종목 ~2,500개 수준이므로 전체 메모리 적재가 합리적.
    """

    def __init__(self, db: Database, cache_ttl_seconds: float = 3600.0) -> None:
        self._db = db
        self._cache: dict[tuple[str, str], Instrument] = {}
        self._cache_ttl = cache_ttl_seconds
        self._cache_loaded_at: float = 0.0

    async def initialize(self) -> None:
        """스키마 생성 + 캐시 워밍."""
        await self._db.execute_script(INSTRUMENT_SCHEMA)
        await self._warm_cache()
        logger.info("InstrumentService 초기화 완료 (캐시: %d건)", len(self._cache))

    async def load_readonly(self) -> None:
        """read-only DB 에서 schema DDL 없이 캐시만 워밍한다 (#1984).

        ``initialize()`` 와 달리 ``CREATE TABLE IF NOT EXISTS instruments`` DDL
        (writer 경로) 을 발화하지 않는다. read-only DB artifact (``data list
        --db-path``) 에서 ``initialize()`` 를 호출하면 ``read_only=True``
        ``Database`` 가 writer 연결을 열지 않아(또는 실제 read-only fs 에서 WAL
        PRAGMA 가) 실패하므로, offline read 경로는 본 메서드로 캐시를 워밍한다
        (``backtest history`` 의 ``BacktestRunStore.initialize()`` skip 와 동형
        — offline-factory.md §2 옵션 A).

        ``instruments`` 테이블이 부재한 (부트스트랩 안 된) DB 는 정의상 종목
        마스터 부재와 동치이므로 빈 캐시로 graceful 정규화한다 — 이후
        ``get_name(symbol)`` 은 symbol fallback 을 반환한다. malformed/locked DB
        같은 다른 ``OperationalError`` 까지 삼키지 않도록 ``"no such table"``
        메시지로만 좁혀 그 외는 호출 표면으로 재전파한다 (``backtest history``
        의 ``list_by_strategy`` 가드 동형).
        """
        try:
            await self._warm_cache()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                self._cache = {}
                logger.info("instruments 테이블 부재 — 빈 캐시로 정규화 (read-only DB)")
                return
            raise
        logger.info(
            "InstrumentService read-only 로드 완료 (캐시: %d건)", len(self._cache)
        )

    async def _warm_cache(self) -> None:
        """DB 전체 로드 → 메모리 캐시."""
        import time as time_mod

        rows = await self._db.fetch_all("SELECT * FROM instruments")
        self._cache = {
            (row["symbol"], row["exchange"]): self._row_to_instrument(row)
            for row in rows
        }
        self._cache_loaded_at = time_mod.monotonic()

    def _is_cache_expired(self) -> bool:
        """캐시 TTL 초과 여부."""
        import math
        import time as time_mod

        if math.isclose(self._cache_loaded_at, 0.0, abs_tol=1e-9):
            return True
        return (time_mod.monotonic() - self._cache_loaded_at) > self._cache_ttl

    async def _ensure_cache(self) -> None:
        """캐시 TTL 초과 시 재로드."""
        if self._is_cache_expired():
            logger.info("캐시 TTL 만료, 재로드 시작")
            await self._warm_cache()
            logger.info("캐시 재로드 완료 (%d건)", len(self._cache))

    async def get(self, symbol: str, exchange: str = "KRX") -> Instrument | None:
        """(symbol, exchange) 조회. 캐시 TTL 체크."""
        await self._ensure_cache()
        return self._cache.get((symbol, exchange))

    def get_name(self, symbol: str, exchange: str = "KRX") -> str:
        """종목명 동기 조회. 캐시 미스 시 symbol 반환."""
        inst = self._cache.get((symbol, exchange))
        return inst.name if inst and inst.name else symbol

    def format_label(
        self, symbol: str, exchange: str = "KRX", *, markdown: bool = False
    ) -> str:
        """알림용 ``{symbol} (종목명)`` 병기 라벨을 동기 반환한다 (#2377).

        텔레그램 알림에서 종목코드만 노출되는 지점들이 각자 ``get_name`` 을
        조합하지 않고 이 헬퍼만 사용해 표기를 SSOT 로 단일화한다. 발행자가
        완성된 label 을 받아 백틱/괄호 조립 실수를 차단한다.

        반환 계약:

        - ``markdown=False`` (plain): 조회 성공 시 ``069500 (KODEX 200)``,
          실패 시 ``069500``.
        - ``markdown=True``: 조회 성공 시 ``` `069500` (KODEX 200) ```,
          실패 시 ``` `069500` ``` (백틱 안에 종목명을 넣으면 텔레그램
          monospace 로 가독성이 떨어지므로 종목명은 백틱 밖 괄호에 둔다).

        sync·무예외·무IO — ``get_name`` 과 동일하게 메모리 캐시 dict 만 동기
        조회한다(``get()``/``_ensure_cache()`` 의 async DB fetch 를 경유하지
        않는다). 백그라운드 태스크(reconciler·fill_scheduler)에서 ``await``
        없이 호출되므로 알림 경로에 IO·지연을 추가하지 않는다. 캐시
        미스·테이블 부재(빈 캐시)·빈 name·``name == symbol`` 은 모두 종목명
        병기 없이 symbol-only 로 폴백한다.

        반환 라벨은 발행자→NotificationService 를 거쳐 텔레그램
        ``parse_mode="Markdown"`` (legacy) 로 전송된다. name 에 legacy Markdown
        특수문자(``_`` ``*`` ```` ` ```` ``[``)가 있으면 텔레그램 parse 가 실패해
        해당 알림 발송 자체가 실패할 수 있으므로(불변식: 발송 실패 금지),
        name 부분을 백슬래시로 escape 한다(markdown=True/plain 양 모드 — 두 모드
        다 최종적으로 Markdown parse 메시지에 삽입되기 때문). symbol 은
        영숫자(종목코드)라 escape 비대상이다.
        """
        base = f"`{symbol}`" if markdown else symbol
        inst = self._cache.get((symbol, exchange))
        name = inst.name if inst else ""
        if not name or name == symbol:
            return base
        return f"{base} ({self._escape_markdown(name)})"

    @staticmethod
    def _escape_markdown(text: str) -> str:
        """텔레그램 legacy Markdown parse 실패 방지(불변식: 발송 실패 금지).

        legacy Markdown 특수문자(``_`` ``*`` ```` ` ```` ``[``)를 백슬래시로 escape
        한다. 종목명에 이 문자가 들어가면(예: ``FOO_BAR``, ``ACME [ADR]``)
        텔레그램 ``parse_mode="Markdown"`` 가 entity parse 에 실패해 알림 발송이
        실패하므로 라벨 삽입 전 무력화한다.
        """
        for ch in ("_", "*", "`", "["):
            text = text.replace(ch, f"\\{ch}")
        return text

    async def search(
        self,
        keyword: str,
        limit: int = 20,
        listed_only: bool = False,
    ) -> list[Instrument]:
        """키워드로 종목 검색 (name, name_en, symbol LIKE)."""
        pattern = f"%{keyword}%"
        query = (
            "SELECT * FROM instruments "
            "WHERE (name LIKE ? OR name_en LIKE ? OR symbol LIKE ?)"
        )
        params: list[object] = [pattern, pattern, pattern]

        if listed_only:
            query += " AND listed = 1"

        query += " LIMIT ?"
        params.append(limit)

        rows = await self._db.fetch_all(query, tuple(params))
        return [self._row_to_instrument(row) for row in rows]

    async def bulk_upsert(self, instruments: list[Instrument]) -> int:
        """대량 등록/갱신. 캐시도 갱신."""
        count = 0
        for inst in instruments:
            await self._db.execute(
                "INSERT INTO instruments "
                "(symbol, exchange, name, name_en, "
                "instrument_type, logo_url, listed, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(symbol, exchange) DO UPDATE SET "
                "name=excluded.name, name_en=excluded.name_en, "
                "instrument_type=excluded.instrument_type, "
                "logo_url=excluded.logo_url, listed=excluded.listed, "
                "updated_at=datetime('now')",
                (
                    inst.symbol,
                    inst.exchange,
                    inst.name,
                    inst.name_en,
                    inst.instrument_type,
                    inst.logo_url,
                    1 if inst.listed else 0,
                ),
            )
            self._cache[(inst.symbol, inst.exchange)] = inst
            count += 1
        logger.info("종목 bulk_upsert 완료: %d건", count)
        return count

    @staticmethod
    def _row_to_instrument(row: dict) -> Instrument:  # type: ignore[type-arg]
        """DB row → Instrument 변환."""
        return Instrument(
            symbol=row["symbol"],
            exchange=row["exchange"],
            name=row["name"] or "",
            name_en=row["name_en"] or "",
            instrument_type=row["instrument_type"] or "",
            logo_url=row["logo_url"] or "",
            listed=bool(row["listed"]),
            updated_at=row["updated_at"] or "",
        )
