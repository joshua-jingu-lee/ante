"""InstrumentService 캐시 TTL 단위 테스트."""

from __future__ import annotations

import time as time_mod
from unittest.mock import AsyncMock

import pytest

from ante.instrument.service import InstrumentService


def _make_row(symbol: str = "005930", exchange: str = "KRX") -> dict:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "name": "삼성전자",
        "name_en": "Samsung",
        "instrument_type": "stock",
        "logo_url": "",
        "listed": 1,
        "updated_at": "",
    }


class TestCacheTTL:
    @pytest.mark.asyncio
    async def test_default_ttl(self):
        """기본 TTL은 3600초."""
        db = AsyncMock()
        svc = InstrumentService(db)
        assert svc._cache_ttl == 3600.0

    @pytest.mark.asyncio
    async def test_custom_ttl(self):
        """커스텀 TTL 설정."""
        db = AsyncMock()
        svc = InstrumentService(db, cache_ttl_seconds=120.0)
        assert svc._cache_ttl == 120.0

    @pytest.mark.asyncio
    async def test_cache_not_expired_within_ttl(self):
        """TTL 내에서는 캐시 재로드하지 않음."""
        db = AsyncMock()
        db.execute_script = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[_make_row()])

        svc = InstrumentService(db, cache_ttl_seconds=3600.0)
        await svc.initialize()

        # initialize에서 1회 fetch
        assert db.fetch_all.call_count == 1

        # get() 호출 — TTL 내이므로 재로드 안 함
        result = await svc.get("005930")
        assert result is not None
        assert result.symbol == "005930"
        assert db.fetch_all.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_expired_triggers_reload(self):
        """TTL 초과 시 캐시 재로드."""
        db = AsyncMock()
        db.execute_script = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[_make_row()])

        svc = InstrumentService(db, cache_ttl_seconds=0.1)
        await svc.initialize()

        assert db.fetch_all.call_count == 1

        # TTL 초과 대기
        time_mod.sleep(0.15)

        # get() 호출 — TTL 만료로 재로드
        await svc.get("005930")
        assert db.fetch_all.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_reload_updates_data(self):
        """캐시 재로드 시 새 데이터 반영."""
        db = AsyncMock()
        db.execute_script = AsyncMock()

        row_v1 = _make_row()
        row_v1["name"] = "삼성전자(구)"
        row_v2 = _make_row()
        row_v2["name"] = "삼성전자(신)"

        db.fetch_all = AsyncMock(side_effect=[[row_v1], [row_v2]])

        svc = InstrumentService(db, cache_ttl_seconds=0.1)
        await svc.initialize()

        result = await svc.get("005930")
        assert result is not None
        assert result.name == "삼성전자(구)"

        time_mod.sleep(0.15)

        result = await svc.get("005930")
        assert result is not None
        assert result.name == "삼성전자(신)"

    @pytest.mark.asyncio
    async def test_bulk_upsert_resets_cache_timestamp(self):
        """bulk_upsert 후에도 캐시 타임스탬프 유지 (upsert는 개별 갱신)."""
        db = AsyncMock()
        db.execute_script = AsyncMock()
        db.execute = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        svc = InstrumentService(db, cache_ttl_seconds=3600.0)
        await svc.initialize()

        from ante.instrument.models import Instrument

        inst = Instrument(
            symbol="005930",
            exchange="KRX",
            name="삼성전자",
        )
        await svc.bulk_upsert([inst])

        # 캐시에 직접 추가됨
        result = await svc.get("005930")
        assert result is not None
        assert result.symbol == "005930"
