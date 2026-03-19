"""InstrumentService — 종목 마스터 데이터 관리 서비스."""

from __future__ import annotations

import logging
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
