"""알림 메시지 템플릿 테스트."""

from ante.notification.templates import (
    BOT_ERROR,
    CIRCUIT_BREAKER,
    ORDER_CANCEL_FAILED,
    ORDER_FILLED,
    POSITION_MISMATCH,
    RESTART_EXHAUSTED,
    TRADING_STATE_CHANGED,
)


class TestTemplateFormat:
    """각 템플릿이 올바른 변수로 포맷되는지 확인."""

    def test_trading_state_changed(self):
        result = TRADING_STATE_CHANGED.format(
            old_state="active",
            new_state="halted",
            reason="일일 손실 한도",
        )
        assert "active" in result
        assert "halted" in result
        assert "일일 손실 한도" in result

    def test_position_mismatch(self):
        result = POSITION_MISMATCH.format(
            bot_id="bot1",
            symbol="005930",
            internal_qty=100,
            broker_qty=50,
            reason="외부 일부 매도",
        )
        assert "bot1" in result
        assert "005930" in result
        assert "100" in result
        assert "50" in result

    def test_bot_error(self):
        result = BOT_ERROR.format(
            bot_id="bot1",
            error_message="Connection timeout",
        )
        assert "bot1" in result
        assert "Connection timeout" in result

    def test_restart_exhausted(self):
        result = RESTART_EXHAUSTED.format(
            bot_id="bot1",
            restart_attempts=3,
            last_error="timeout",
        )
        assert "bot1" in result
        assert "3" in result

    def test_order_cancel_failed(self):
        result = ORDER_CANCEL_FAILED.format(
            bot_id="bot1",
            order_id="ord-123",
            error_message="시장 마감",
        )
        assert "bot1" in result
        assert "ord-123" in result

    def test_circuit_breaker(self):
        result = CIRCUIT_BREAKER.format(
            broker="KIS",
            old_state="closed",
            new_state="open",
            reason="연속 오류",
        )
        assert "KIS" in result
        assert "open" in result

    def test_order_filled(self):
        result = ORDER_FILLED.format(
            bot_id="bot1",
            display="005930(삼성전자)",
            side="buy",
            quantity=100,
            price=72000,
        )
        assert "bot1" in result
        assert "005930(삼성전자)" in result
        assert "72,000" in result
