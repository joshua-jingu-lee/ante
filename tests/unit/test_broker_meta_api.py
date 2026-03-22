"""브로커 메타정보 API 테스트."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from ante.broker.base import BrokerAdapter
from ante.broker.mock import MockBrokerAdapter
from ante.web.app import create_app


class FakeTreasury:
    """Treasury stub."""

    commission_rate: float = 0.00015
    sell_tax_rate: float = 0.0023
    last_synced_at = None

    def get_summary(self) -> dict:
        return {
            "account_balance": 10_000_000,
            "purchasable_amount": 10_000_000,
            "total_evaluation": 10_000_000,
            "total_profit_loss": 0,
            "total_allocated": 0,
            "total_reserved": 0,
            "total_available": 10_000_000,
            "unallocated": 10_000_000,
            "bot_count": 0,
        }

    async def get_latest_snapshot(self) -> None:
        return None


class TestBrokerMetaInTreasury:
    """GET /api/treasury 응답에 브로커 메타정보가 포함된다."""

    @pytest.fixture
    def client_with_broker(self) -> TestClient:
        broker = MockBrokerAdapter({"exchange": "KRX"})
        app = create_app(treasury=FakeTreasury(), broker=broker)
        return TestClient(app)

    @pytest.fixture
    def client_without_broker(self) -> TestClient:
        app = create_app(treasury=FakeTreasury())
        return TestClient(app)

    def test_broker_meta_fields_present(self, client_with_broker: TestClient) -> None:
        """브로커가 있으면 메타정보 4개 필드가 응답에 포함된다."""
        resp = client_with_broker.get("/api/treasury")
        assert resp.status_code == 200
        body = resp.json()
        assert body["broker_id"] == "mock"
        assert body["broker_name"] == "모의 브로커"
        assert body["broker_short_name"] == "MOCK"
        assert body["exchange"] == "KRX"

    def test_no_broker_no_meta(self, client_without_broker: TestClient) -> None:
        """브로커가 없으면 메타정보 필드가 응답에 없다."""
        resp = client_without_broker.get("/api/treasury")
        assert resp.status_code == 200
        body = resp.json()
        assert "broker_id" not in body
        assert "broker_name" not in body


class TestBrokerAdapterMetaDefaults:
    """BrokerAdapter 클래스 레벨 메타정보 기본값."""

    def test_base_defaults(self) -> None:
        """BrokerAdapter 기본 메타정보 값이 정의되어 있다."""
        assert BrokerAdapter.broker_id == "unknown"
        assert BrokerAdapter.broker_name == "Unknown Broker"
        assert BrokerAdapter.broker_short_name == "UNK"

    def test_mock_broker_meta(self) -> None:
        """MockBrokerAdapter 메타정보가 올바르다."""
        adapter = MockBrokerAdapter({"exchange": "KRX"})
        assert adapter.broker_id == "mock"
        assert adapter.broker_name == "모의 브로커"
        assert adapter.broker_short_name == "MOCK"

    def test_kis_adapter_meta(self) -> None:
        """KISDomesticAdapter 메타정보가 올바르다 (클래스 속성)."""
        from ante.broker.kis import KISDomesticAdapter

        assert KISDomesticAdapter.broker_id == "kis-domestic"
        assert KISDomesticAdapter.broker_name == "한국투자증권 국내"
        assert KISDomesticAdapter.broker_short_name == "KIS"
