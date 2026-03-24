"""trade_id UUID 파싱 방어 코드 단위 테스트.

_row_to_record()가 유효한 UUID뿐 아니라 비-UUID 문자열도
에러 없이 처리하는지 검증한다. (Refs #865)
"""

from __future__ import annotations

from uuid import UUID, uuid4

from ante.trade.models import TradeStatus
from ante.trade.recorder import TradeRecorder


class TestRowToRecordUUIDParsing:
    """TradeRecorder._row_to_record의 trade_id 파싱 테스트."""

    @staticmethod
    def _make_row(trade_id: str = "", **overrides: object) -> dict:
        base = {
            "trade_id": trade_id or str(uuid4()),
            "bot_id": "test-bot",
            "strategy_id": "test-strategy",
            "symbol": "005930",
            "side": "buy",
            "quantity": 10,
            "price": 70000,
            "status": "filled",
            "order_type": "market",
            "reason": "",
            "commission": 0.0,
            "timestamp": "2026-03-20 10:00:00",
            "order_id": None,
            "account_id": "default",
            "currency": "KRW",
        }
        base.update(overrides)
        return base

    def test_valid_uuid_parsed(self) -> None:
        """유효한 UUID4 문자열은 UUID 객체로 변환된다."""
        uid = uuid4()
        row = self._make_row(trade_id=str(uid))
        record = TradeRecorder._row_to_record(row)
        assert isinstance(record.trade_id, UUID)
        assert record.trade_id == uid

    def test_invalid_uuid_falls_back_to_string(self) -> None:
        """비-UUID 문자열은 에러 없이 문자열 그대로 반환된다."""
        row = self._make_row(trade_id="qa-trade-001")
        record = TradeRecorder._row_to_record(row)
        assert record.trade_id == "qa-trade-001"

    def test_uuid5_string_parsed(self) -> None:
        """UUID5 형식 문자열도 정상 파싱된다."""
        from uuid import UUID as _UUID
        from uuid import uuid5

        ns = _UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        uid = uuid5(ns, "qa-trade-001")
        row = self._make_row(trade_id=str(uid))
        record = TradeRecorder._row_to_record(row)
        assert isinstance(record.trade_id, UUID)
        assert record.trade_id == uid

    def test_record_fields_correct(self) -> None:
        """trade_id 외 다른 필드도 정상 매핑된다."""
        row = self._make_row(
            trade_id=str(uuid4()),
            bot_id="my-bot",
            symbol="000660",
            side="sell",
            quantity=5,
            price=190000,
            status="filled",
        )
        record = TradeRecorder._row_to_record(row)
        assert record.bot_id == "my-bot"
        assert record.symbol == "000660"
        assert record.side == "sell"
        assert record.quantity == 5.0
        assert record.price == 190000.0
        assert record.status == TradeStatus.FILLED
