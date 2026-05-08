"""StopOrder 이벤트 ``account_id`` 필드 검증 (#1336).

본 모듈은 ``StopOrderRegisteredEvent``, ``StopOrderTriggeredEvent``,
``StopOrderExpiredEvent`` 가 다른 account-scoped 이벤트와 동일한
컨벤션 ( ``account_id`` 가 첫 데이터 필드 + ``_requires_account_id``
마커) 을 지키는지를 회귀로 보호한다.
"""

from __future__ import annotations

import pytest

from ante.account.errors import InvalidAccountIdError
from ante.eventbus.events import (
    StopOrderExpiredEvent,
    StopOrderRegisteredEvent,
    StopOrderTriggeredEvent,
)


class TestStopOrderRegisteredEvent:
    def test_has_account_id_field(self) -> None:
        event = StopOrderRegisteredEvent(
            account_id="acc-test",
            stop_order_id="stop-001",
            bot_id="bot-1",
            strategy_id="stg-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
        )
        assert event.account_id == "acc-test"
        assert event.stop_order_id == "stop-001"
        assert event.bot_id == "bot-1"

    def test_invalid_account_id_rejected(self) -> None:
        with pytest.raises(InvalidAccountIdError):
            StopOrderRegisteredEvent(
                account_id="",
                stop_order_id="stop-001",
                bot_id="bot-1",
                strategy_id="stg-1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
            )

    def test_invalid_account_id_default_rejected(self) -> None:
        with pytest.raises(InvalidAccountIdError):
            StopOrderRegisteredEvent(
                account_id="default",
                stop_order_id="stop-001",
                bot_id="bot-1",
                strategy_id="stg-1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
            )


class TestStopOrderTriggeredEvent:
    def test_has_account_id_field(self) -> None:
        event = StopOrderTriggeredEvent(
            account_id="acc-test",
            stop_order_id="stop-001",
            bot_id="bot-1",
            strategy_id="stg-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            trigger_price=48500.0,
            converted_order_type="market",
        )
        assert event.account_id == "acc-test"
        assert event.trigger_price == 48500.0
        assert event.converted_order_type == "market"

    def test_invalid_account_id_rejected(self) -> None:
        with pytest.raises(InvalidAccountIdError):
            StopOrderTriggeredEvent(
                account_id="",
                stop_order_id="stop-001",
                bot_id="bot-1",
                strategy_id="stg-1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                trigger_price=48500.0,
                converted_order_type="market",
            )


class TestStopOrderExpiredEvent:
    def test_has_account_id_field(self) -> None:
        event = StopOrderExpiredEvent(
            account_id="acc-test",
            stop_order_id="stop-001",
            bot_id="bot-1",
            strategy_id="stg-1",
            symbol="005930",
            reason="session_ended",
        )
        assert event.account_id == "acc-test"
        assert event.reason == "session_ended"

    def test_manager_stopped_reason(self) -> None:
        event = StopOrderExpiredEvent(
            account_id="acc-test",
            stop_order_id="stop-001",
            bot_id="bot-1",
            strategy_id="stg-1",
            symbol="005930",
            reason="manager_stopped",
        )
        assert event.reason == "manager_stopped"

    def test_invalid_account_id_rejected(self) -> None:
        with pytest.raises(InvalidAccountIdError):
            StopOrderExpiredEvent(
                account_id="",
                stop_order_id="stop-001",
                bot_id="bot-1",
                strategy_id="stg-1",
                symbol="005930",
                reason="session_ended",
            )
