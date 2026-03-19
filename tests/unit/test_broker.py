"""Broker Adapter 모듈 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.broker import (
    APIError,
    AuthenticationError,
    BrokerAdapter,
    BrokerError,
    KISAdapter,
    OrderNotFoundError,
    OrderRegistry,
    RateLimitError,
)
from ante.core import Database

# ── 예외 계층 ──────────────────────────────────────


class TestExceptions:
    def test_hierarchy(self):
        """예외 계층 구조."""
        assert issubclass(AuthenticationError, BrokerError)
        assert issubclass(APIError, BrokerError)
        assert issubclass(OrderNotFoundError, BrokerError)
        assert issubclass(RateLimitError, BrokerError)

    def test_api_error_fields(self):
        """APIError 필드."""
        e = APIError("test", status_code=400, error_code="ERR001")
        assert str(e) == "test"
        assert e.status_code == 400
        assert e.error_code == "ERR001"


# ── BrokerAdapter ABC ──────────────────────────────


class TestBrokerAdapterABC:
    def test_cannot_instantiate(self):
        """ABC 직접 인스턴스화 불가."""
        with pytest.raises(TypeError):
            BrokerAdapter({})  # type: ignore[abstract]

    def test_normalize_symbol(self):
        """종목코드 표준화."""

        class DummyBroker(BrokerAdapter):
            async def connect(self) -> None: ...
            async def disconnect(self) -> None: ...
            async def get_account_balance(self) -> dict[str, float]: ...
            async def get_positions(self) -> list[dict[str, Any]]: ...
            async def get_current_price(self, symbol: str) -> float: ...
            async def place_order(
                self,
                symbol: str,
                side: str,
                quantity: float,
                order_type: str = "market",
                price: float | None = None,
                stop_price: float | None = None,
            ) -> str: ...
            async def cancel_order(self, order_id: str) -> bool: ...
            async def get_order_status(self, order_id: str) -> dict[str, Any]: ...
            async def get_pending_orders(self) -> list[dict[str, Any]]: ...
            async def get_account_positions(self) -> list[dict[str, Any]]: ...
            async def get_order_history(
                self, from_date: str | None = None, to_date: str | None = None
            ) -> list[dict[str, Any]]: ...
            async def get_instruments(
                self, exchange: str = "KRX"
            ) -> list[dict[str, Any]]: ...
            def get_commission_info(self) -> Any: ...

        broker = DummyBroker({})
        assert broker.normalize_symbol("5930") == "005930"
        assert broker.normalize_symbol("005930") == "005930"
        assert broker.normalize_symbol("AAPL") == "AAPL"

    def test_config_stored(self):
        """config 저장."""

        class MinBroker(BrokerAdapter):
            async def connect(self) -> None: ...
            async def disconnect(self) -> None: ...
            async def get_account_balance(self) -> dict[str, float]: ...
            async def get_positions(self) -> list[dict[str, Any]]: ...
            async def get_current_price(self, symbol: str) -> float: ...
            async def place_order(
                self,
                symbol: str,
                side: str,
                quantity: float,
                order_type: str = "market",
                price: float | None = None,
                stop_price: float | None = None,
            ) -> str: ...
            async def cancel_order(self, order_id: str) -> bool: ...
            async def get_order_status(self, order_id: str) -> dict[str, Any]: ...
            async def get_pending_orders(self) -> list[dict[str, Any]]: ...
            async def get_account_positions(self) -> list[dict[str, Any]]: ...
            async def get_order_history(
                self, from_date: str | None = None, to_date: str | None = None
            ) -> list[dict[str, Any]]: ...
            async def get_instruments(
                self, exchange: str = "KRX"
            ) -> list[dict[str, Any]]: ...
            def get_commission_info(self) -> Any: ...

        cfg = {"key": "value"}
        broker = MinBroker(cfg)
        assert broker.config == cfg
        assert broker.is_connected is False


# ── KISAdapter ─────────────────────────────────────


KIS_CONFIG = {
    "app_key": "test_key",
    "app_secret": "test_secret",
    "account_no": "1234567801",
    "is_paper": True,
}


class TestKISAdapterInit:
    def test_paper_mode(self):
        """모의투자 모드 초기화."""
        adapter = KISAdapter(KIS_CONFIG)
        assert adapter.is_paper is True
        assert "openapivts" in adapter.base_url
        assert adapter._rate_limit_per_minute == 5
        assert adapter.is_connected is False

    def test_live_mode(self):
        """실전투자 모드 초기화."""
        config = {**KIS_CONFIG, "is_paper": False}
        adapter = KISAdapter(config)
        assert adapter.is_paper is False
        assert "openapi.koreainvestment" in adapter.base_url
        assert adapter._rate_limit_per_minute == 20


class TestKISAdapterMapping:
    def test_map_order_type(self):
        """주문 유형 매핑."""
        adapter = KISAdapter(KIS_CONFIG)
        assert adapter._map_order_type("market") == "01"
        assert adapter._map_order_type("limit") == "00"
        assert adapter._map_order_type("unknown") == "01"

    def test_map_order_status(self):
        """주문 상태 코드 매핑."""
        adapter = KISAdapter(KIS_CONFIG)
        assert adapter._map_order_status("10") == "pending"
        assert adapter._map_order_status("30") == "filled"
        assert adapter._map_order_status("40") == "cancelled"
        assert adapter._map_order_status("99") == "unknown"

    def test_build_order_data_market(self):
        """시장가 주문 데이터 구성."""
        adapter = KISAdapter(KIS_CONFIG)
        data = adapter._build_order_data("005930", "buy", 10.0, "market", None)
        assert data["PDNO"] == "005930"
        assert data["ORD_DVSN"] == "01"
        assert data["ORD_QTY"] == "10"
        assert data["ORD_UNPR"] == "0"

    def test_build_order_data_limit(self):
        """지정가 주문 데이터 구성."""
        adapter = KISAdapter(KIS_CONFIG)
        data = adapter._build_order_data("005930", "buy", 5.0, "limit", 70000.0)
        assert data["ORD_DVSN"] == "00"
        assert data["ORD_UNPR"] == "70000"

    async def test_stop_order_raises(self):
        """stop 주문은 ValueError."""
        adapter = KISAdapter(KIS_CONFIG)
        with pytest.raises(ValueError, match="stop"):
            await adapter.place_order("005930", "buy", 10, order_type="stop")

    def test_normalize_symbol(self):
        """종목코드 표준화."""
        adapter = KISAdapter(KIS_CONFIG)
        assert adapter.normalize_symbol("5930") == "005930"
        assert adapter.normalize_symbol("005930") == "005930"

    def test_balance_params(self):
        """잔고 조회 파라미터."""
        adapter = KISAdapter(KIS_CONFIG)
        params = adapter._balance_params()
        assert params["CANO"] == "12345678"
        assert params["ACNT_PRDT_CD"] == "01"


class TestKISAdapterAPI:
    """KIS API 호출 테스트 (aiohttp mock)."""

    @pytest.fixture
    def adapter(self):
        a = KISAdapter(KIS_CONFIG)
        a.access_token = "test_token"
        a.token_expires_at = datetime.now(UTC) + timedelta(hours=23)
        a.is_connected = True
        return a

    def _mock_response(self, json_data: dict, status: int = 200) -> AsyncMock:
        """Mock aiohttp response."""
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(return_value=json_data)
        resp.text = AsyncMock(return_value="error text")
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    async def test_get_account_balance(self, adapter):
        """계좌 잔고 조회."""
        mock_resp = self._mock_response(
            {
                "rt_cd": "0",
                "output2": [
                    {
                        "dnca_tot_amt": "5000000",
                        "tot_evlu_amt": "10000000",
                        "pchs_amt_smtl_amt": "4500000",
                        "evlu_amt_smtl_amt": "5500000",
                        "evlu_pfls_smtl_amt": "1000000",
                    }
                ],
            }
        )
        session = MagicMock()
        session.get = MagicMock(return_value=mock_resp)
        adapter._session = session

        balance = await adapter.get_account_balance()
        assert balance["cash"] == 5_000_000.0
        assert balance["total_assets"] == 10_000_000.0

    async def test_get_positions(self, adapter):
        """포지션 조회."""
        mock_resp = self._mock_response(
            {
                "rt_cd": "0",
                "output1": [
                    {
                        "pdno": "005930",
                        "prdt_name": "삼성전자",
                        "hldg_qty": "100",
                        "pchs_avg_pric": "70000",
                        "prpr": "75000",
                        "evlu_amt": "7500000",
                        "evlu_pfls_amt": "500000",
                        "evlu_erng_rt": "7.14",
                    },
                    {
                        "pdno": "000660",
                        "prdt_name": "SK하이닉스",
                        "hldg_qty": "0",
                        "pchs_avg_pric": "0",
                        "prpr": "0",
                        "evlu_amt": "0",
                        "evlu_pfls_amt": "0",
                        "evlu_erng_rt": "0",
                    },
                ],
                "output2": [],
            }
        )
        session = MagicMock()
        session.get = MagicMock(return_value=mock_resp)
        adapter._session = session

        positions = await adapter.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "005930"
        assert positions[0]["quantity"] == 100.0

    async def test_place_order(self, adapter):
        """주문 접수."""
        mock_resp = self._mock_response(
            {"rt_cd": "0", "output": {"ODNO": "0001234567"}}
        )
        session = MagicMock()
        session.post = MagicMock(return_value=mock_resp)
        adapter._session = session

        order_id = await adapter.place_order("005930", "buy", 10.0)
        assert order_id == "0001234567"

    async def test_place_order_stop_raises(self, adapter):
        """stop 주문 시 ValueError."""
        with pytest.raises(ValueError, match="stop"):
            await adapter.place_order("005930", "buy", 10, order_type="stop")

    async def test_cancel_order(self, adapter):
        """주문 취소."""
        mock_resp = self._mock_response({"rt_cd": "0"})
        session = MagicMock()
        session.post = MagicMock(return_value=mock_resp)
        adapter._session = session

        result = await adapter.cancel_order("0001234567")
        assert result is True

    async def test_get_order_status(self, adapter):
        """주문 상태 조회."""
        mock_resp = self._mock_response(
            {
                "rt_cd": "0",
                "output": [
                    {
                        "odno": "0001234567",
                        "pdno": "005930",
                        "sll_buy_dvsn_cd": "02",
                        "ord_qty": "10",
                        "tot_ccld_qty": "10",
                        "rmn_qty": "0",
                        "ord_stat_cd": "30",
                        "ord_unpr": "70000",
                        "avg_prvs": "70000",
                    }
                ],
            }
        )
        session = MagicMock()
        session.get = MagicMock(return_value=mock_resp)
        adapter._session = session

        status = await adapter.get_order_status("0001234567")
        assert status["order_id"] == "0001234567"
        assert status["side"] == "buy"
        assert status["status"] == "filled"
        assert status["filled_quantity"] == 10.0

    async def test_get_order_status_not_found(self, adapter):
        """존재하지 않는 주문 조회 시 OrderNotFoundError."""
        mock_resp = self._mock_response({"rt_cd": "0", "output": []})
        session = MagicMock()
        session.get = MagicMock(return_value=mock_resp)
        adapter._session = session

        with pytest.raises(OrderNotFoundError):
            await adapter.get_order_status("nonexistent")

    async def test_api_error_handling(self, adapter):
        """API 에러 응답 처리."""
        mock_resp = self._mock_response({"rt_cd": "1", "msg1": "잘못된 요청"})
        session = MagicMock()
        session.get = MagicMock(return_value=mock_resp)
        adapter._session = session

        with pytest.raises(APIError, match="잘못된 요청"):
            await adapter.get_account_balance()

    async def test_http_error_handling(self, adapter):
        """HTTP 에러 응답 처리."""
        mock_resp = self._mock_response({}, status=500)
        session = MagicMock()
        session.get = MagicMock(return_value=mock_resp)
        adapter._session = session

        with pytest.raises(APIError, match="HTTP 500"):
            await adapter.get_account_balance()

    async def test_get_pending_orders(self, adapter):
        """미체결 주문 목록 조회."""
        mock_resp = self._mock_response(
            {
                "rt_cd": "0",
                "output": [
                    {
                        "odno": "001",
                        "pdno": "005930",
                        "sll_buy_dvsn_cd": "02",
                        "ord_qty": "10",
                        "tot_ccld_qty": "0",
                        "rmn_qty": "10",
                        "ord_stat_cd": "10",
                    }
                ],
            }
        )
        session = MagicMock()
        session.get = MagicMock(return_value=mock_resp)
        adapter._session = session

        orders = await adapter.get_pending_orders()
        assert len(orders) == 1
        assert orders[0]["status"] == "pending"

    async def test_get_account_positions_for_reconcile(self, adapter):
        """대사용 포지션 조회."""
        mock_resp = self._mock_response(
            {
                "rt_cd": "0",
                "output1": [
                    {
                        "pdno": "005930",
                        "prdt_name": "삼성전자",
                        "hldg_qty": "50",
                        "pchs_avg_pric": "65000",
                        "prpr": "70000",
                        "evlu_amt": "3500000",
                        "evlu_pfls_amt": "250000",
                        "evlu_erng_rt": "7.69",
                    }
                ],
                "output2": [],
            }
        )
        session = MagicMock()
        session.get = MagicMock(return_value=mock_resp)
        adapter._session = session

        positions = await adapter.get_account_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "005930"
        assert positions[0]["quantity"] == 50.0
        assert "name" not in positions[0]


# ── OrderRegistry ──────────────────────────────────


class TestOrderRegistry:
    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await database.close()

    @pytest.fixture
    async def registry(self, db):
        r = OrderRegistry(db)
        await r.initialize()
        return r

    async def test_register_and_get(self, registry):
        """주문 등록 및 조회."""
        await registry.register("ord1", "bot1", "005930")
        bot_id = await registry.get_bot_id("ord1")
        assert bot_id == "bot1"

    async def test_get_nonexistent(self, registry):
        """존재하지 않는 주문 조회."""
        bot_id = await registry.get_bot_id("nonexistent")
        assert bot_id is None

    async def test_register_upsert(self, registry):
        """중복 등록 시 업데이트."""
        await registry.register("ord1", "bot1", "005930")
        await registry.register("ord1", "bot2", "005930")
        bot_id = await registry.get_bot_id("ord1")
        assert bot_id == "bot2"

    async def test_get_orders_by_bot(self, registry):
        """봇별 주문 조회."""
        await registry.register("ord1", "bot1", "005930")
        await registry.register("ord2", "bot1", "000660")
        await registry.register("ord3", "bot2", "005930")

        orders = await registry.get_orders_by_bot("bot1")
        assert len(orders) == 2

    async def test_remove(self, registry):
        """매핑 삭제."""
        await registry.register("ord1", "bot1", "005930")
        await registry.remove("ord1")
        bot_id = await registry.get_bot_id("ord1")
        assert bot_id is None

    async def test_remove_nonexistent(self, registry):
        """존재하지 않는 주문 삭제 (무시)."""
        await registry.remove("nonexistent")  # should not raise
