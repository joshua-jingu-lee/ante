"""Instrument 모듈 단위 테스트."""

from __future__ import annotations

import pytest
import pytest_asyncio

from ante.instrument.models import Instrument
from ante.instrument.service import InstrumentService

# ── Instrument 모델 ──────────────────────────────


class TestInstrumentModel:
    def test_create(self):
        """Instrument 생성."""
        inst = Instrument(symbol="005930", exchange="KRX", name="삼성전자")
        assert inst.symbol == "005930"
        assert inst.exchange == "KRX"
        assert inst.name == "삼성전자"

    def test_frozen(self):
        """frozen dataclass — 불변."""
        inst = Instrument(symbol="005930", exchange="KRX")
        with pytest.raises(AttributeError):
            inst.name = "변경"  # type: ignore[misc]

    def test_defaults(self):
        """기본값 확인."""
        inst = Instrument(symbol="000660", exchange="KRX")
        assert inst.name == ""
        assert inst.name_en == ""
        assert inst.instrument_type == ""
        assert inst.logo_url == ""
        assert inst.listed is True
        assert inst.updated_at == ""


# ── InstrumentService ────────────────────────────


@pytest_asyncio.fixture
async def db(tmp_path):
    """테스트용 DB."""
    from ante.core.database import Database

    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield db
    await db.close()


@pytest_asyncio.fixture
async def service(db):
    """InstrumentService 인스턴스."""
    svc = InstrumentService(db=db)
    await svc.initialize()
    return svc


class TestInstrumentServiceInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_table(self, db):
        """initialize()가 instruments 테이블을 생성한다."""
        svc = InstrumentService(db=db)
        await svc.initialize()

        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instruments'"
        )
        assert row is not None

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, db):
        """중복 호출해도 에러 없음."""
        svc = InstrumentService(db=db)
        await svc.initialize()
        await svc.initialize()


class TestInstrumentServiceGet:
    @pytest.mark.asyncio
    async def test_get_cached(self, service):
        """캐시에서 조회."""
        inst = Instrument(symbol="005930", exchange="KRX", name="삼성전자")
        await service.bulk_upsert([inst])

        result = await service.get("005930", "KRX")
        assert result is not None
        assert result.name == "삼성전자"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, service):
        """없는 종목은 None 반환."""
        result = await service.get("999999", "KRX")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_default_exchange(self, service):
        """exchange 기본값 KRX."""
        inst = Instrument(symbol="005930", exchange="KRX", name="삼성전자")
        await service.bulk_upsert([inst])

        result = await service.get("005930")
        assert result is not None
        assert result.name == "삼성전자"


class TestInstrumentServiceGetName:
    @pytest.mark.asyncio
    async def test_get_name(self, service):
        """종목명 반환."""
        inst = Instrument(symbol="005930", exchange="KRX", name="삼성전자")
        await service.bulk_upsert([inst])

        assert service.get_name("005930") == "삼성전자"

    @pytest.mark.asyncio
    async def test_get_name_fallback(self, service):
        """캐시 미스 시 symbol 반환."""
        assert service.get_name("999999") == "999999"

    @pytest.mark.asyncio
    async def test_get_name_empty_name(self, service):
        """name이 빈 문자열이면 symbol 반환."""
        inst = Instrument(symbol="005930", exchange="KRX", name="")
        await service.bulk_upsert([inst])

        assert service.get_name("005930") == "005930"


class TestInstrumentServiceSearch:
    @pytest.mark.asyncio
    async def test_search_by_name(self, service):
        """한글명 검색."""
        instruments = [
            Instrument(symbol="005930", exchange="KRX", name="삼성전자"),
            Instrument(symbol="000660", exchange="KRX", name="SK하이닉스"),
            Instrument(symbol="035420", exchange="KRX", name="NAVER"),
        ]
        await service.bulk_upsert(instruments)

        results = await service.search("삼성")
        assert len(results) == 1
        assert results[0].symbol == "005930"

    @pytest.mark.asyncio
    async def test_search_by_symbol(self, service):
        """종목코드 검색."""
        instruments = [
            Instrument(symbol="005930", exchange="KRX", name="삼성전자"),
        ]
        await service.bulk_upsert(instruments)

        results = await service.search("0059")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_no_results(self, service):
        """결과 없음."""
        results = await service.search("없는종목")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_limit(self, service):
        """limit 적용."""
        instruments = [
            Instrument(symbol=f"00{i:04d}", exchange="KRX", name=f"종목{i}")
            for i in range(10)
        ]
        await service.bulk_upsert(instruments)

        results = await service.search("종목", limit=3)
        assert len(results) == 3


class TestInstrumentServiceBulkUpsert:
    @pytest.mark.asyncio
    async def test_bulk_upsert_insert(self, service):
        """신규 종목 등록."""
        instruments = [
            Instrument(symbol="005930", exchange="KRX", name="삼성전자"),
            Instrument(symbol="000660", exchange="KRX", name="SK하이닉스"),
        ]
        count = await service.bulk_upsert(instruments)

        assert count == 2
        assert await service.get("005930") is not None
        assert await service.get("000660") is not None

    @pytest.mark.asyncio
    async def test_bulk_upsert_update(self, service):
        """기존 종목 갱신."""
        inst1 = Instrument(symbol="005930", exchange="KRX", name="삼성전자(구)")
        await service.bulk_upsert([inst1])

        inst2 = Instrument(symbol="005930", exchange="KRX", name="삼성전자")
        await service.bulk_upsert([inst2])

        result = await service.get("005930")
        assert result is not None
        assert result.name == "삼성전자"

    @pytest.mark.asyncio
    async def test_bulk_upsert_updates_cache(self, service):
        """upsert 후 캐시가 즉시 갱신된다."""
        inst = Instrument(symbol="005930", exchange="KRX", name="삼성전자")
        await service.bulk_upsert([inst])

        assert service.get_name("005930") == "삼성전자"


# ── exchange 필드 기본값 ──────────────────────────


class TestExchangeDefaults:
    def test_event_default_exchange(self):
        """이벤트 exchange 기본값 KRX."""
        from ante.eventbus.events import (
            OrderFilledEvent,
            OrderRequestEvent,
        )

        req = OrderRequestEvent(symbol="005930")
        assert req.exchange == "KRX"

        filled = OrderFilledEvent(symbol="005930")
        assert filled.exchange == "KRX"

    def test_bot_config_default_account_id(self):
        """BotConfig account_id 기본값 test (exchange는 Account에서 관리)."""
        from ante.bot.config import BotConfig

        config = BotConfig(bot_id="bot-1", strategy_id="strat-1")
        assert config.account_id == "test"

    def test_strategy_meta_default_exchange(self):
        """StrategyMeta exchange 기본값 KRX."""
        from ante.strategy.base import StrategyMeta

        meta = StrategyMeta(name="test", version="1.0", description="test")
        assert meta.exchange == "KRX"

    def test_trade_record_default_exchange(self):
        """TradeRecord exchange 기본값 KRX."""
        from uuid import uuid4

        from ante.trade.models import TradeRecord, TradeStatus

        record = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot-1",
            strategy_id="strat-1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=70000,
            status=TradeStatus.FILLED,
        )
        assert record.exchange == "KRX"

    def test_position_snapshot_default_exchange(self):
        """PositionSnapshot exchange 기본값 KRX."""
        from ante.trade.models import PositionSnapshot

        pos = PositionSnapshot(
            bot_id="bot-1",
            symbol="005930",
            quantity=10,
            avg_entry_price=70000,
        )
        assert pos.exchange == "KRX"

    def test_backtest_trade_default_exchange(self):
        """BacktestTrade exchange 기본값 KRX."""
        from datetime import datetime

        from ante.backtest.result import BacktestTrade

        trade = BacktestTrade(
            timestamp=datetime.now(),
            symbol="005930",
            side="buy",
            quantity=10,
            price=70000,
            commission=100,
            slippage=0,
        )
        assert trade.exchange == "KRX"

    def test_rule_context_default_exchange(self):
        """RuleContext exchange 기본값 KRX."""
        from ante.rule.base import RuleContext

        ctx = RuleContext(
            bot_id="bot-1",
            strategy_id="strat-1",
            symbol="005930",
            side="buy",
            quantity=10,
            order_type="market",
        )
        assert ctx.exchange == "KRX"
