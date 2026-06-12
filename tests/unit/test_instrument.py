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


class TestInstrumentServiceFormatLabel:
    """#2377: 텔레그램 알림용 ``{symbol} (종목명)`` 병기 라벨 헬퍼.

    sync·무예외·무IO — 알림 핸들러(백그라운드 태스크 포함)에서 await 없이 호출한다.
    조회 실패(미적재·테이블 부재·빈 name·name==symbol) 시 symbol-only 폴백한다.
    """

    @pytest.mark.asyncio
    async def test_format_label_plain_loaded(self, service):
        """적재 성공 — plain: ``069500 (KODEX 200)``."""
        inst = Instrument(symbol="069500", exchange="KRX", name="KODEX 200")
        await service.bulk_upsert([inst])

        assert service.format_label("069500") == "069500 (KODEX 200)"

    @pytest.mark.asyncio
    async def test_format_label_markdown_loaded(self, service):
        """적재 성공 — markdown: backtick symbol + 괄호 종목명."""
        inst = Instrument(symbol="069500", exchange="KRX", name="KODEX 200")
        await service.bulk_upsert([inst])

        assert service.format_label("069500", markdown=True) == "`069500` (KODEX 200)"

    @pytest.mark.asyncio
    async def test_format_label_explicit_exchange(self, service):
        """exchange 명시 전달 경로(체결 이벤트 등)."""
        inst = Instrument(symbol="005930", exchange="KRX", name="삼성전자")
        await service.bulk_upsert([inst])

        assert service.format_label("005930", "KRX") == "005930 (삼성전자)"
        assert (
            service.format_label("005930", "KRX", markdown=True)
            == "`005930` (삼성전자)"
        )

    def test_format_label_cold_empty_cache_plain(self, service):
        """fresh service / cold 빈 캐시 — symbol-only 폴백 (plain)."""
        # service fixture 는 initialize 만 호출(빈 instruments 테이블) → 빈 캐시.
        assert service.format_label("069500") == "069500"

    def test_format_label_cold_empty_cache_markdown(self, service):
        """cold 빈 캐시 — markdown 폴백은 backtick symbol 만."""
        assert service.format_label("069500", markdown=True) == "`069500`"

    def test_format_label_missing_table_normalized_cache(self, db):
        """missing-table 정규화(빈 캐시) — symbol-only 폴백."""
        # load_readonly 가 'no such table' 를 빈 캐시로 정규화한 상태와 동치.
        svc = InstrumentService(db=db)
        svc._cache = {}
        assert svc.format_label("069500") == "069500"
        assert svc.format_label("069500", markdown=True) == "`069500`"

    @pytest.mark.asyncio
    async def test_format_label_empty_name(self, service):
        """빈 name — symbol-only 폴백."""
        inst = Instrument(symbol="005930", exchange="KRX", name="")
        await service.bulk_upsert([inst])

        assert service.format_label("005930") == "005930"
        assert service.format_label("005930", markdown=True) == "`005930`"

    def test_format_label_name_equals_symbol(self, db):
        """name == symbol — 병기하지 않고 symbol-only."""
        svc = InstrumentService(db=db)
        svc._cache = {
            ("069500", "KRX"): Instrument(
                symbol="069500", exchange="KRX", name="069500"
            )
        }
        assert svc.format_label("069500") == "069500"
        assert svc.format_label("069500", markdown=True) == "`069500`"

    def test_format_label_no_db_io(self, db):
        """no-IO 회귀 고정 — format_label 은 DB fetch / await 를 일으키지 않는다.

        _warm_cache / _ensure_cache / get 을 호출하면 RuntimeError 로 즉시 실패하게
        막아, format_label 이 캐시 dict 만 동기 조회함을 강제한다(알림 경로 IO 금지).
        """

        async def _explode(*_a, **_k):  # pragma: no cover - 호출되면 실패
            raise RuntimeError("format_label 은 DB IO / await 를 호출해서는 안 된다")

        svc = InstrumentService(db=db)
        svc._cache = {
            ("069500", "KRX"): Instrument(
                symbol="069500", exchange="KRX", name="KODEX 200"
            )
        }
        # async 경로를 전부 폭발시켜 동기-캐시-only 조회임을 고정.
        svc._warm_cache = _explode  # type: ignore[method-assign]
        svc._ensure_cache = _explode  # type: ignore[method-assign]
        svc.get = _explode  # type: ignore[method-assign]
        # DB 도 직접 건드리지 않음을 보장.
        svc._db.fetch_all = _explode  # type: ignore[method-assign]
        svc._db.fetch_one = _explode  # type: ignore[method-assign]

        assert svc.format_label("069500") == "069500 (KODEX 200)"
        assert svc.format_label("069500", markdown=True) == "`069500` (KODEX 200)"
        # 미적재 symbol 도 동기 폴백(여전히 DB 비접근).
        assert svc.format_label("999999") == "999999"


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

        req = OrderRequestEvent(symbol="005930", account_id="acc-test")
        assert req.exchange == "KRX"

        filled = OrderFilledEvent(symbol="005930", account_id="acc-test")
        assert filled.exchange == "KRX"

    def test_bot_config_default_account_id(self):
        """BotConfig account_id는 명시값으로 보존된다 (exchange는 Account에서 관리)."""
        from ante.bot.config import BotConfig

        config = BotConfig(bot_id="bot-1", strategy_id="strat-1", account_id="acc-test")
        assert config.account_id == "acc-test"

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
            account_id="acc-test",
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
            account_id="acc-test",
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
            account_id="acc-test",
        )
        assert ctx.exchange == "KRX"
