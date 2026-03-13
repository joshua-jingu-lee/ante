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

    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[tuple[str, str], Instrument] = {}

    async def initialize(self) -> None:
        """스키마 생성 + 캐시 워밍."""
        await self._db.execute_script(INSTRUMENT_SCHEMA)
        await self._warm_cache()
        logger.info("InstrumentService 초기화 완료 (캐시: %d건)", len(self._cache))

    async def _warm_cache(self) -> None:
        """DB 전체 로드 → 메모리 캐시."""
        rows = await self._db.fetch_all("SELECT * FROM instruments")
        self._cache = {
            (row["symbol"], row["exchange"]): self._row_to_instrument(row)
            for row in rows
        }

    async def get(self, symbol: str, exchange: str = "KRX") -> Instrument | None:
        """(symbol, exchange) 조회. 캐시 우선."""
        return self._cache.get((symbol, exchange))

    def get_name(self, symbol: str, exchange: str = "KRX") -> str:
        """종목명 동기 조회. 캐시 미스 시 symbol 반환."""
        inst = self._cache.get((symbol, exchange))
        return inst.name if inst and inst.name else symbol

    async def search(self, keyword: str, limit: int = 20) -> list[Instrument]:
        """키워드로 종목 검색 (name, name_en, symbol LIKE)."""
        pattern = f"%{keyword}%"
        rows = await self._db.fetch_all(
            "SELECT * FROM instruments "
            "WHERE name LIKE ? OR name_en LIKE ? OR symbol LIKE ? "
            "LIMIT ?",
            (pattern, pattern, pattern, limit),
        )
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
