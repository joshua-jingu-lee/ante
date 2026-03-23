"""Broker 어댑터 분리 테스트 (KISBase + KISDomestic + Registry).

이슈 #561: KISAdapter → KISBaseAdapter + KISDomesticAdapter 분리,
CommissionInfo buy/sell 분리, BROKER_REGISTRY 신규 생성.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from ante.broker.base import BrokerAdapter
from ante.broker.kis import KISAdapter, KISBaseAdapter, KISDomesticAdapter
from ante.broker.mock import MockBrokerAdapter
from ante.broker.models import CommissionInfo
from ante.broker.registry import (
    BROKER_REGISTRY,
    InvalidBrokerTypeError,
    get_broker_class,
)
from ante.broker.test import TestBrokerAdapter

# ── CommissionInfo buy/sell 분리 ────────────────────────


class TestCommissionInfoBuySell:
    """CommissionInfo가 buy_commission_rate / sell_commission_rate로 분리되었다."""

    def test_defaults(self):
        """기본값: buy=0.015%, sell=0.195%."""
        info = CommissionInfo()
        assert info.buy_commission_rate == 0.00015
        assert info.sell_commission_rate == 0.00195

    def test_custom_rates(self):
        """커스텀 수수료율."""
        info = CommissionInfo(buy_commission_rate=0.001, sell_commission_rate=0.002)
        assert info.buy_commission_rate == 0.001
        assert info.sell_commission_rate == 0.002

    def test_frozen(self):
        """불변 객체."""
        info = CommissionInfo()
        with pytest.raises(AttributeError):
            info.buy_commission_rate = 0.001  # type: ignore[misc]

    def test_buy_calculation(self):
        """매수 수수료: filled_value * buy_commission_rate."""
        info = CommissionInfo(buy_commission_rate=0.00015, sell_commission_rate=0.00195)
        commission = info.calculate("buy", 1_000_000.0)
        assert commission == pytest.approx(150.0)

    def test_sell_calculation(self):
        """매도 수수료: filled_value * sell_commission_rate."""
        info = CommissionInfo(buy_commission_rate=0.00015, sell_commission_rate=0.00195)
        commission = info.calculate("sell", 1_000_000.0)
        assert commission == pytest.approx(1_950.0)

    def test_sell_higher_than_buy(self):
        """기본 설정에서 매도 수수료가 매수보다 높다."""
        info = CommissionInfo()
        buy_fee = info.calculate("buy", 1_000_000.0)
        sell_fee = info.calculate("sell", 1_000_000.0)
        assert sell_fee > buy_fee

    def test_zero_amount(self):
        """0원 체결 → 수수료 0."""
        info = CommissionInfo()
        assert info.calculate("buy", 0.0) == 0.0
        assert info.calculate("sell", 0.0) == 0.0

    def test_equal_buy_sell_rates(self):
        """해외주식처럼 buy/sell 동일 수수료."""
        info = CommissionInfo(buy_commission_rate=0.001, sell_commission_rate=0.001)
        buy_fee = info.calculate("buy", 1_000_000.0)
        sell_fee = info.calculate("sell", 1_000_000.0)
        assert buy_fee == pytest.approx(sell_fee)


# ── BrokerAdapter ABC currency 속성 ──────────────────


class TestBrokerAdapterCurrency:
    """BrokerAdapter ABC에 currency 속성이 추가되었다."""

    def test_default_currency(self):
        """기본 currency는 KRW."""
        adapter = MockBrokerAdapter({"exchange": "KRX"})
        assert adapter.currency == "KRW"

    def test_custom_currency(self):
        """config에서 currency 지정."""
        adapter = MockBrokerAdapter({"exchange": "NYSE", "currency": "USD"})
        assert adapter.currency == "USD"


# ── KISBaseAdapter + KISDomesticAdapter 계층 ─────────


class TestKISAdapterHierarchy:
    """KISBaseAdapter → KISDomesticAdapter 계층 구조."""

    def test_kis_base_is_abstract(self):
        """KISBaseAdapter는 직접 인스턴스화 불가 (ABC)."""
        with pytest.raises(TypeError):
            KISBaseAdapter(  # type: ignore[abstract]
                {"app_key": "k", "app_secret": "s", "account_no": "1234567801"}
            )

    def test_kis_domestic_inherits_base(self):
        """KISDomesticAdapter는 KISBaseAdapter를 상속한다."""
        assert issubclass(KISDomesticAdapter, KISBaseAdapter)
        assert issubclass(KISDomesticAdapter, BrokerAdapter)

    def test_kis_adapter_alias(self):
        """KISAdapter는 KISDomesticAdapter의 별칭이다."""
        assert KISAdapter is KISDomesticAdapter


class TestKISDomesticAdapterMeta:
    """KISDomesticAdapter 메타정보."""

    def test_broker_id(self):
        assert KISDomesticAdapter.broker_id == "kis-domestic"

    def test_broker_name(self):
        assert KISDomesticAdapter.broker_name == "한국투자증권 국내"

    def test_broker_short_name(self):
        assert KISDomesticAdapter.broker_short_name == "KIS"


KIS_CONFIG = {
    "app_key": "test_key",
    "app_secret": "test_secret",
    "account_no": "1234567801",
    "is_paper": True,
}


class TestKISDomesticAdapterInit:
    """KISDomesticAdapter 초기화."""

    def test_paper_mode(self):
        """모의투자 모드."""
        adapter = KISDomesticAdapter(KIS_CONFIG)
        assert adapter.is_paper is True
        assert "openapivts" in adapter.base_url
        assert adapter._rate_limit_per_minute == 5
        assert adapter.currency == "KRW"
        assert adapter.exchange == "KRX"

    def test_live_mode(self):
        """실전투자 모드."""
        config = {**KIS_CONFIG, "is_paper": False}
        adapter = KISDomesticAdapter(config)
        assert adapter.is_paper is False
        assert "openapi.koreainvestment" in adapter.base_url
        assert adapter._rate_limit_per_minute == 20

    def test_commission_info_buy_sell(self):
        """수수료율이 buy/sell로 분리된다."""
        adapter = KISDomesticAdapter(KIS_CONFIG)
        info = adapter.get_commission_info()
        assert isinstance(info, CommissionInfo)
        assert info.buy_commission_rate == 0.00015
        # 기본: commission_rate(0.00015) + sell_tax_rate(0.0018)
        assert info.sell_commission_rate == pytest.approx(0.00195)

    def test_custom_buy_sell_commission(self):
        """config에서 buy/sell 수수료율 직접 지정."""
        config = {
            **KIS_CONFIG,
            "buy_commission_rate": 0.001,
            "sell_commission_rate": 0.002,
        }
        adapter = KISDomesticAdapter(config)
        info = adapter.get_commission_info()
        assert info.buy_commission_rate == 0.001
        assert info.sell_commission_rate == 0.002

    def test_backward_compat_commission_rate(self):
        """기존 commission_rate + sell_tax_rate 방식도 하위호환 지원."""
        config = {
            **KIS_CONFIG,
            "commission_rate": 0.0001,
            "sell_tax_rate": 0.002,
        }
        adapter = KISDomesticAdapter(config)
        info = adapter.get_commission_info()
        assert info.buy_commission_rate == 0.0001
        assert info.sell_commission_rate == pytest.approx(0.0021)


class TestKISDomesticAdapterMapping:
    """KISDomesticAdapter 매핑 메서드."""

    def test_map_order_type(self):
        adapter = KISDomesticAdapter(KIS_CONFIG)
        assert adapter._map_order_type("market") == "01"
        assert adapter._map_order_type("limit") == "00"
        assert adapter._map_order_type("unknown") == "01"

    def test_map_order_status(self):
        adapter = KISDomesticAdapter(KIS_CONFIG)
        assert adapter._map_order_status("10") == "pending"
        assert adapter._map_order_status("30") == "filled"
        assert adapter._map_order_status("40") == "cancelled"
        assert adapter._map_order_status("99") == "unknown"

    def test_build_order_data_market(self):
        adapter = KISDomesticAdapter(KIS_CONFIG)
        data = adapter._build_order_data("005930", "buy", 10.0, "market", None)
        assert data["PDNO"] == "005930"
        assert data["ORD_DVSN"] == "01"
        assert data["ORD_QTY"] == "10"
        assert data["ORD_UNPR"] == "0"

    def test_build_order_data_limit(self):
        adapter = KISDomesticAdapter(KIS_CONFIG)
        data = adapter._build_order_data("005930", "buy", 5.0, "limit", 70000.0)
        assert data["ORD_DVSN"] == "00"
        assert data["ORD_UNPR"] == "70000"

    def test_balance_params(self):
        adapter = KISDomesticAdapter(KIS_CONFIG)
        params = adapter._balance_params()
        assert params["CANO"] == "12345678"
        assert params["ACNT_PRDT_CD"] == "01"


class TestKISDomesticAdapterAPI:
    """KISDomesticAdapter API 호출 테스트."""

    @pytest.fixture
    def adapter(self):
        a = KISDomesticAdapter(KIS_CONFIG)
        a.access_token = "test_token"
        a.token_expires_at = datetime.now(UTC) + timedelta(hours=23)
        a.is_connected = True
        return a

    def _mock_response(self, json_data: dict, status: int = 200) -> AsyncMock:
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(return_value=json_data)
        resp.text = AsyncMock(return_value="error text")
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    async def test_place_order_stop_raises(self, adapter):
        """stop 주문 시 ValueError."""
        with pytest.raises(ValueError, match="stop"):
            await adapter.place_order("005930", "buy", 10, order_type="stop")


# ── TestBrokerAdapter 정비 ────────────────────────────


class TestTestBrokerAdapterUpdate:
    """TestBrokerAdapter가 새 CommissionInfo를 사용한다."""

    def test_default_exchange_test(self):
        """기본 exchange는 TEST."""
        adapter = TestBrokerAdapter({})
        assert adapter.exchange == "TEST"

    def test_default_currency_krw(self):
        """기본 currency는 KRW."""
        adapter = TestBrokerAdapter({})
        assert adapter.currency == "KRW"

    def test_zero_commission(self):
        """test 브로커는 기본 수수료 0."""
        adapter = TestBrokerAdapter({})
        info = adapter.get_commission_info()
        assert info.buy_commission_rate == 0.0
        assert info.sell_commission_rate == 0.0

    def test_custom_commission(self):
        """config에서 수수료율 지정."""
        adapter = TestBrokerAdapter(
            {
                "buy_commission_rate": 0.001,
                "sell_commission_rate": 0.002,
            }
        )
        info = adapter.get_commission_info()
        assert info.buy_commission_rate == 0.001
        assert info.sell_commission_rate == 0.002


# ── MockBrokerAdapter 정비 ────────────────────────────


class TestMockBrokerAdapterUpdate:
    """MockBrokerAdapter가 새 CommissionInfo를 사용한다."""

    def test_commission_buy_sell(self):
        """MockBrokerAdapter 수수료율 확인."""
        adapter = MockBrokerAdapter({"exchange": "KRX"})
        info = adapter.get_commission_info()
        assert info.buy_commission_rate == 0.00015
        assert info.sell_commission_rate == 0.00195


# ── BROKER_REGISTRY ──────────────────────────────────


class TestBrokerRegistry:
    """BROKER_REGISTRY에 test, kis-domestic만 등록되어 있다."""

    def test_registry_contains_test(self):
        """test 타입이 등록되어 있다."""
        assert "test" in BROKER_REGISTRY
        assert BROKER_REGISTRY["test"] is TestBrokerAdapter

    def test_registry_contains_kis_domestic(self):
        """kis-domestic 타입이 등록되어 있다."""
        assert "kis-domestic" in BROKER_REGISTRY
        assert BROKER_REGISTRY["kis-domestic"] is KISDomesticAdapter

    def test_registry_size(self):
        """현재 2개만 등록."""
        assert len(BROKER_REGISTRY) == 2

    def test_get_broker_class_test(self):
        """get_broker_class로 test 어댑터 조회."""
        cls = get_broker_class("test")
        assert cls is TestBrokerAdapter

    def test_get_broker_class_kis_domestic(self):
        """get_broker_class로 kis-domestic 어댑터 조회."""
        cls = get_broker_class("kis-domestic")
        assert cls is KISDomesticAdapter

    def test_get_broker_class_unknown_raises(self):
        """미등록 타입 요청 시 InvalidBrokerTypeError."""
        with pytest.raises(InvalidBrokerTypeError) as exc_info:
            get_broker_class("unknown-broker")
        assert "unknown-broker" in str(exc_info.value)
        assert exc_info.value.broker_type == "unknown-broker"

    def test_invalid_broker_type_error_message(self):
        """에러 메시지에 등록된 타입 목록이 포함된다."""
        with pytest.raises(InvalidBrokerTypeError) as exc_info:
            get_broker_class("nonexistent")
        msg = str(exc_info.value)
        assert "kis-domestic" in msg
        assert "test" in msg
