"""broker.type 설정 기반 KIS <-> Test 브로커 전환 통합 테스트.

main.py의 브로커 초기화 분기가 설정에 따라 올바른 어댑터를 생성하는지 검증한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ante.broker.base import BrokerAdapter
from ante.broker.mock import MockBrokerAdapter
from ante.broker.test import TestBrokerAdapter


def _make_config(broker_type: str, **extra: object) -> MagicMock:
    """테스트용 Config 객체를 생성한다."""
    broker_section: dict = {
        "type": broker_type,
        "is_paper": True,
        "commission_rate": 0.00015,
        "sell_tax_rate": 0.0023,
        **extra,
    }

    config = MagicMock()
    config.get.side_effect = lambda key, default=None: (
        broker_section if key == "broker" else default
    )
    config.secret.return_value = None
    config.validate.return_value = None
    return config


async def _create_broker_from_config(
    broker_config: dict,
) -> BrokerAdapter | None:
    """main.py의 브로커 초기화 분기 로직을 재현한다.

    main.py에서 발췌한 핵심 분기만 격리 테스트한다.
    """
    broker_type = (
        broker_config.get("type", "kis") if isinstance(broker_config, dict) else "kis"
    )

    if broker_type == "mock":
        broker = MockBrokerAdapter(
            broker_config if isinstance(broker_config, dict) else {}
        )
        await broker.connect()
        return broker
    elif broker_type == "test":
        test_config = (
            broker_config.get("test", {}) if isinstance(broker_config, dict) else {}
        )
        merged = {
            **(broker_config if isinstance(broker_config, dict) else {}),
            **test_config,
        }
        broker = TestBrokerAdapter(merged)
        await broker.connect()
        return broker
    else:
        # KIS 분기 — 시크릿 없으면 None
        return None


# ── 전환 분기 검증 ──────────────────────────────────────────────


class TestBrokerTypeSwitch:
    """broker.type 설정에 따른 브로커 인스턴스 생성 검증."""

    @pytest.mark.asyncio
    async def test_type_test_creates_test_broker(self) -> None:
        """type = 'test'이면 TestBrokerAdapter가 생성된다."""
        broker_config = {
            "type": "test",
            "commission_rate": 0.00015,
            "sell_tax_rate": 0.0023,
            "test": {"seed": 42, "initial_cash": 50_000_000},
        }
        broker = await _create_broker_from_config(broker_config)
        assert isinstance(broker, TestBrokerAdapter)
        assert broker.is_connected is True
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_type_mock_creates_mock_broker(self) -> None:
        """type = 'mock'이면 MockBrokerAdapter가 생성된다."""
        broker_config = {"type": "mock"}
        broker = await _create_broker_from_config(broker_config)
        assert isinstance(broker, MockBrokerAdapter)
        assert broker.is_connected is True
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_type_kis_without_secrets_returns_none(self) -> None:
        """type = 'kis'이고 시크릿이 없으면 None."""
        broker_config = {"type": "kis"}
        broker = await _create_broker_from_config(broker_config)
        assert broker is None

    @pytest.mark.asyncio
    async def test_default_type_is_kis(self) -> None:
        """type 미지정 시 기본값 'kis'로 동작한다."""
        broker_config = {}
        broker = await _create_broker_from_config(broker_config)
        assert broker is None  # KIS 시크릿 없으면 None


class TestTestBrokerConfigMerge:
    """[broker.test] 섹션이 브로커 설정에 올바르게 병합되는지 검증."""

    @pytest.mark.asyncio
    async def test_test_section_overrides_defaults(self) -> None:
        """[broker.test] 설정이 기본 seed/initial_cash를 오버라이드한다."""
        broker_config = {
            "type": "test",
            "commission_rate": 0.00015,
            "sell_tax_rate": 0.0023,
            "test": {
                "seed": 99,
                "initial_cash": 50_000_000,
                "tick_interval": 0.5,
            },
        }
        broker = await _create_broker_from_config(broker_config)
        assert isinstance(broker, TestBrokerAdapter)
        assert broker._seed == 99
        assert broker._initial_cash == 50_000_000
        assert broker._tick_interval == 0.5
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_commission_rates_propagated(self) -> None:
        """broker 섹션의 수수료율이 TestBrokerAdapter에 전달된다."""
        broker_config = {
            "type": "test",
            "buy_commission_rate": 0.0002,
            "sell_commission_rate": 0.003,
            "test": {"seed": 42},
        }
        broker = await _create_broker_from_config(broker_config)
        assert isinstance(broker, TestBrokerAdapter)
        info = broker.get_commission_info()
        assert info.buy_commission_rate == 0.0002
        assert info.sell_commission_rate == 0.003
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_empty_test_section_uses_defaults(self) -> None:
        """[broker.test] 미지정 시 기본값으로 동작한다."""
        broker_config = {"type": "test"}
        broker = await _create_broker_from_config(broker_config)
        assert isinstance(broker, TestBrokerAdapter)
        assert broker._seed == 42
        assert broker._initial_cash == 100_000_000.0
        await broker.disconnect()


class TestBrokerAdapterInterfaceConsistency:
    """KIS <-> Test 전환 시 인터페이스 일관성 검증."""

    @pytest.mark.asyncio
    async def test_test_broker_is_broker_adapter(self) -> None:
        """TestBrokerAdapter가 BrokerAdapter 인터페이스를 구현한다."""
        broker = TestBrokerAdapter({"seed": 1})
        assert isinstance(broker, BrokerAdapter)

    @pytest.mark.asyncio
    async def test_test_broker_full_cycle(self) -> None:
        """Test 브로커로 조회/매수/매도/이력 전체 흐름이 동작한다."""
        broker_config = {
            "type": "test",
            "test": {"seed": 42, "initial_cash": 100_000_000},
        }
        broker = await _create_broker_from_config(broker_config)
        assert isinstance(broker, TestBrokerAdapter)

        # 잔고 조회
        balance = await broker.get_account_balance()
        assert balance["cash"] == 100_000_000

        # 시세 조회
        price = await broker.get_current_price("000001")
        assert price > 0

        # 매수
        order_id = await broker.place_order("000001", "buy", 10)
        assert order_id

        # 포지션 확인
        positions = await broker.get_positions()
        assert len(positions) == 1

        # 매도
        sell_id = await broker.place_order("000001", "sell", 5)
        assert sell_id

        # 이력
        history = await broker.get_order_history()
        assert len(history) == 2

        # 종목 마스터
        instruments = await broker.get_instruments()
        assert len(instruments) == 6

        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_switch_test_to_test_independent(self) -> None:
        """서로 다른 Test 브로커 인스턴스가 독립적이다."""
        b1 = await _create_broker_from_config(
            {"type": "test", "test": {"seed": 1, "initial_cash": 10_000_000}}
        )
        b2 = await _create_broker_from_config(
            {"type": "test", "test": {"seed": 2, "initial_cash": 50_000_000}}
        )

        assert isinstance(b1, TestBrokerAdapter)
        assert isinstance(b2, TestBrokerAdapter)

        bal1 = await b1.get_account_balance()
        bal2 = await b2.get_account_balance()
        assert bal1["cash"] == 10_000_000
        assert bal2["cash"] == 50_000_000

        # b1에서 매수해도 b2에 영향 없음
        await b1.place_order("000001", "buy", 5)
        assert len(await b1.get_positions()) == 1
        assert len(await b2.get_positions()) == 0

        await b1.disconnect()
        await b2.disconnect()
