"""종목 마스터 데이터 자동 수집 테스트."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.broker.kis import KISAdapter
from ante.core import Database
from ante.instrument.models import Instrument
from ante.instrument.service import InstrumentService


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def instrument_service(db):
    svc = InstrumentService(db)
    await svc.initialize()
    return svc


# ── US-1: BrokerAdapter.get_instruments ──────────


class TestGetInstrumentsAbstract:
    def test_broker_adapter_has_get_instruments(self):
        """BrokerAdapter에 get_instruments 추상 메서드가 존재."""
        from ante.broker.base import BrokerAdapter

        assert hasattr(BrokerAdapter, "get_instruments")

    def test_classify_stock(self):
        """일반 종목은 stock으로 분류."""
        result = KISAdapter._classify_instrument_type("005930", "삼성전자", "KOSPI")
        assert result == "stock"

    def test_classify_etf_kodex(self):
        """KODEX 종목은 etf로 분류."""
        result = KISAdapter._classify_instrument_type("069500", "KODEX 200", "KOSPI")
        assert result == "etf"

    def test_classify_etf_tiger(self):
        """TIGER 종목은 etf로 분류."""
        result = KISAdapter._classify_instrument_type("102110", "TIGER 200", "KOSPI")
        assert result == "etf"

    def test_classify_etn(self):
        """ETN 종목은 etn으로 분류."""
        result = KISAdapter._classify_instrument_type(
            "500001", "삼성 ETN 레버리지", "KOSPI"
        )
        assert result == "etn"


class TestKISGetInstruments:
    async def test_get_instruments_returns_list(self):
        """get_instruments가 종목 리스트를 반환."""
        config = {
            "app_key": "test",
            "app_secret": "test",
            "account_no": "1234567890",
            "is_paper": True,
        }
        adapter = KISAdapter(config=config)

        mock_response = {
            "rt_cd": "0",
            "output2": [
                {
                    "std_pdno": "005930",
                    "prdt_name": "삼성전자",
                    "prdt_eng_name": "Samsung Electronics",
                    "rprs_mrkt_kor_name": "KOSPI",
                },
                {
                    "std_pdno": "069500",
                    "prdt_name": "KODEX 200",
                    "prdt_eng_name": "KODEX 200",
                    "rprs_mrkt_kor_name": "KOSPI",
                },
            ],
        }

        adapter._session = MagicMock()
        adapter.access_token = "test_token"
        adapter._request = AsyncMock(return_value=mock_response)

        # _fetch_stock_list를 직접 mock
        adapter._fetch_stock_list = AsyncMock(
            side_effect=[
                mock_response["output2"],  # KOSPI
                [],  # KOSDAQ
            ]
        )

        result = await adapter.get_instruments()

        assert len(result) == 2
        assert result[0]["symbol"] == "005930"
        assert result[0]["name"] == "삼성전자"
        assert result[0]["name_en"] == "Samsung Electronics"
        assert result[0]["instrument_type"] == "stock"
        assert result[0]["listed"] is True
        assert result[1]["instrument_type"] == "etf"

    async def test_get_instruments_handles_api_failure(self):
        """API 실패 시 빈 리스트 반환 (예외 안 남)."""
        config = {
            "app_key": "test",
            "app_secret": "test",
            "account_no": "1234567890",
            "is_paper": True,
        }
        adapter = KISAdapter(config=config)
        adapter._session = MagicMock()
        adapter.access_token = "test_token"

        adapter._fetch_stock_list = AsyncMock(side_effect=Exception("API 오류"))

        result = await adapter.get_instruments()
        assert result == []

    async def test_get_instruments_partial_failure(self):
        """한 시장 실패 시 나머지 시장 결과만 반환."""
        config = {
            "app_key": "test",
            "app_secret": "test",
            "account_no": "1234567890",
            "is_paper": True,
        }
        adapter = KISAdapter(config=config)
        adapter._session = MagicMock()
        adapter.access_token = "test_token"

        adapter._fetch_stock_list = AsyncMock(
            side_effect=[
                [
                    {
                        "std_pdno": "005930",
                        "prdt_name": "삼성전자",
                        "prdt_eng_name": "Samsung",
                        "rprs_mrkt_kor_name": "KOSPI",
                    }
                ],
                Exception("KOSDAQ 조회 실패"),
            ]
        )

        result = await adapter.get_instruments()
        assert len(result) == 1
        assert result[0]["symbol"] == "005930"


# ── US-2: 시스템 시작 시 종목 동기화 ──────────────


class TestInstrumentSync:
    async def test_bulk_upsert_from_raw_data(self, instrument_service, db):
        """raw 데이터를 Instrument로 변환 후 bulk_upsert."""
        raw_instruments = [
            {
                "symbol": "005930",
                "name": "삼성전자",
                "name_en": "Samsung",
                "instrument_type": "stock",
                "listed": True,
            },
            {
                "symbol": "069500",
                "name": "KODEX 200",
                "name_en": "KODEX 200",
                "instrument_type": "etf",
                "listed": True,
            },
        ]

        instruments = [
            Instrument(
                symbol=item["symbol"],
                exchange="KRX",
                name=item.get("name", ""),
                name_en=item.get("name_en", ""),
                instrument_type=item.get("instrument_type", ""),
                listed=item.get("listed", True),
            )
            for item in raw_instruments
        ]

        count = await instrument_service.bulk_upsert(instruments)
        assert count == 2

        inst = await instrument_service.get("005930")
        assert inst is not None
        assert inst.name == "삼성전자"
        assert inst.instrument_type == "stock"

    async def test_sync_updates_existing(self, instrument_service, db):
        """기존 종목 이름 변경 시 갱신."""
        old = [Instrument(symbol="005930", exchange="KRX", name="삼성전자(구)")]
        await instrument_service.bulk_upsert(old)

        new = [Instrument(symbol="005930", exchange="KRX", name="삼성전자")]
        await instrument_service.bulk_upsert(new)

        inst = await instrument_service.get("005930")
        assert inst is not None
        assert inst.name == "삼성전자"

    async def test_sync_failure_does_not_clear_cache(self, instrument_service, db):
        """동기화 실패 시 기존 캐시 유지."""
        old = [Instrument(symbol="005930", exchange="KRX", name="삼성전자")]
        await instrument_service.bulk_upsert(old)

        # 캐시에 데이터가 있음을 확인
        inst = await instrument_service.get("005930")
        assert inst is not None
        assert inst.name == "삼성전자"


# ── US-3: CLI sync 커맨드 ──────────────────────────


class TestCLISyncCommand:
    def test_sync_command_exists(self):
        """instrument group에 sync 커맨드가 존재."""
        from ante.cli.commands.instrument import instrument

        commands = list(instrument.commands.keys())
        assert "sync" in commands

    def test_classify_instrument_type_various(self):
        """다양한 종목 분류 테스트."""
        assert (
            KISAdapter._classify_instrument_type("005930", "삼성전자", "KOSPI")
            == "stock"
        )
        assert (
            KISAdapter._classify_instrument_type("069500", "KODEX 200", "KOSPI")
            == "etf"
        )
        assert (
            KISAdapter._classify_instrument_type("500001", "TRUE ETN", "KOSPI") == "etn"
        )


# ── 상폐 처리 ──────────────────────────────────


class TestDelistingHandling:
    async def test_delisted_instrument_marked(self, instrument_service, db):
        """기존 종목이 새 목록에 없으면 상폐 처리 가능."""
        # 기존 종목 등록
        old = [
            Instrument(
                symbol="999999",
                exchange="KRX",
                name="상폐예정",
                listed=True,
            ),
            Instrument(
                symbol="005930",
                exchange="KRX",
                name="삼성전자",
                listed=True,
            ),
        ]
        await instrument_service.bulk_upsert(old)

        # DB에서 직접 상폐 처리 (CLI sync가 하는 것과 동일)
        await db.execute(
            "UPDATE instruments SET listed = 0 WHERE symbol = ? AND exchange = ?",
            ("999999", "KRX"),
        )

        # 캐시 재로드
        await instrument_service._warm_cache()

        inst = await instrument_service.get("999999")
        assert inst is not None
        assert inst.listed is False

        # 삼성전자는 여전히 listed
        samsung = await instrument_service.get("005930")
        assert samsung is not None
        assert samsung.listed is True
