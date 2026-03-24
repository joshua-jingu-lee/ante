"""SignalChannel 단위 테스트."""

from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.signal_channel import SignalChannel
from ante.eventbus.events import (
    ExternalSignalEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
)


@pytest.fixture
def bot() -> MagicMock:
    """Bot mock."""
    b = MagicMock()
    b.bot_id = "bot-001"
    return b


@pytest.fixture
def eventbus() -> MagicMock:
    """EventBus mock."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.subscribe = MagicMock()
    bus.unsubscribe = MagicMock()
    return bus


@pytest.fixture
def ctx() -> MagicMock:
    """StrategyContext mock."""
    c = MagicMock()
    c.get_positions.return_value = {"005930": {"quantity": 10, "avg_price": 58200}}
    c.get_balance.return_value = {"available": 5000000.0}
    c.get_open_orders.return_value = []
    c.get_current_price = AsyncMock(return_value=58500.0)
    import polars as pl

    c.get_ohlcv = AsyncMock(return_value=pl.DataFrame({"close": [58200]}))
    return c


@pytest.fixture
def output() -> io.StringIO:
    """출력 스트림."""
    return io.StringIO()


@pytest.fixture
def channel(
    bot: MagicMock,
    eventbus: MagicMock,
    ctx: MagicMock,
    output: io.StringIO,
) -> SignalChannel:
    """SignalChannel 인스턴스."""
    return SignalChannel(
        bot=bot,
        eventbus=eventbus,
        ctx=ctx,
        output_stream=output,
    )


class TestHandleSignal:
    """외부 시그널 처리 테스트."""

    async def test_signal_publishes_event(
        self, channel: SignalChannel, eventbus: MagicMock, output: io.StringIO
    ) -> None:
        """signal 메시지 → ExternalSignalEvent 발행 + ack 응답."""
        msg = json.dumps(
            {"type": "signal", "symbol": "005930", "side": "buy", "quantity": 10}
        )
        await channel._handle_line(msg)

        # ExternalSignalEvent 발행
        eventbus.publish.assert_called_once()
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, ExternalSignalEvent)
        assert event.symbol == "005930"
        assert event.action == "buy"
        assert event.bot_id == "bot-001"

        # ack 응답
        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "ack"
        assert resp["signal_id"].startswith("sig-")

    async def test_signal_with_confidence(
        self, channel: SignalChannel, eventbus: MagicMock
    ) -> None:
        """confidence 포함 시그널."""
        msg = json.dumps(
            {
                "type": "signal",
                "symbol": "005930",
                "action": "sell",
                "confidence": 0.95,
                "reason": "AI prediction",
            }
        )
        await channel._handle_line(msg)

        event = eventbus.publish.call_args[0][0]
        assert event.confidence == 0.95
        assert event.action == "sell"


class TestHandleQuery:
    """데이터 조회 테스트."""

    async def test_query_positions(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """positions 조회."""
        msg = json.dumps({"type": "query", "method": "positions"})
        await channel._handle_line(msg)

        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "result"
        assert resp["method"] == "positions"
        assert "005930" in resp["data"]

    async def test_query_balance(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """balance 조회."""
        msg = json.dumps({"type": "query", "method": "balance"})
        await channel._handle_line(msg)

        resp = json.loads(output.getvalue().strip())
        assert resp["data"]["available"] == 5000000.0

    async def test_query_current_price(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """current_price 조회."""
        msg = json.dumps(
            {
                "type": "query",
                "method": "current_price",
                "params": {"symbol": "005930"},
            }
        )
        await channel._handle_line(msg)

        resp = json.loads(output.getvalue().strip())
        assert resp["data"] == 58500.0

    async def test_query_ohlcv(
        self, channel: SignalChannel, ctx: MagicMock, output: io.StringIO
    ) -> None:
        """ohlcv 조회 + params 전달."""
        msg = json.dumps(
            {
                "type": "query",
                "method": "ohlcv",
                "params": {"symbol": "005930", "timeframe": "1h", "limit": 50},
            }
        )
        await channel._handle_line(msg)

        ctx.get_ohlcv.assert_called_once_with(symbol="005930", timeframe="1h", limit=50)

    async def test_query_unknown_method(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """알 수 없는 method → 에러."""
        msg = json.dumps({"type": "query", "method": "unknown_method"})
        await channel._handle_line(msg)

        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "error"


class TestHandleErrors:
    """에러 처리 테스트."""

    async def test_invalid_json(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """잘못된 JSON → 에러 응답 (채널 끊김 없이)."""
        await channel._handle_line("not valid json {{{")

        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "error"
        assert "Invalid JSON" in resp["message"]

    async def test_unknown_type(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """알 수 없는 type → 에러."""
        msg = json.dumps({"type": "unknown_type"})
        await channel._handle_line(msg)

        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "error"

    async def test_ping_pong(self, channel: SignalChannel, output: io.StringIO) -> None:
        """ping → pong."""
        msg = json.dumps({"type": "ping"})
        await channel._handle_line(msg)

        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "pong"

    async def test_empty_line_ignored(self, channel: SignalChannel) -> None:
        """빈 줄 무시."""
        await channel._handle_line("")
        await channel._handle_line("  ")


class TestEventForwarding:
    """Ante → 외부 이벤트 전달 테스트."""

    async def test_fill_forwarded(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """체결 이벤트 → 외부 전달."""
        event = OrderFilledEvent(
            order_id="ORD-001",
            bot_id="bot-001",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=58200.0,
            commission=87.3,
        )

        await channel._on_fill(event)

        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "fill"
        assert resp["order_id"] == "ORD-001"
        assert resp["price"] == 58200.0

    async def test_fill_other_bot_ignored(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """다른 봇의 체결은 무시."""
        event = OrderFilledEvent(order_id="ORD-002", bot_id="bot-999")
        await channel._on_fill(event)
        assert output.getvalue() == ""

    async def test_order_rejected_forwarded(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """주문 거부 → 외부 전달."""
        event = OrderRejectedEvent(
            order_id="ORD-003",
            bot_id="bot-001",
            reason="insufficient funds",
        )

        await channel._on_order_update(event)

        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "order_update"
        assert resp["status"] == "rejected"
        assert resp["reason"] == "insufficient funds"

    async def test_order_cancelled_forwarded(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """주문 취소 → 외부 전달."""
        event = OrderCancelledEvent(
            order_id="ORD-004",
            bot_id="bot-001",
            reason="user_cancel",
        )

        await channel._on_order_update(event)

        resp = json.loads(output.getvalue().strip())
        assert resp["status"] == "cancelled"

    async def test_order_cancel_failed_forwarded(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """주문 취소 실패 → 외부 전달."""
        from ante.eventbus.events import OrderCancelFailedEvent

        event = OrderCancelFailedEvent(
            order_id="ORD-005",
            bot_id="bot-001",
            error_message="cancel_rejected",
        )

        await channel._on_order_update(event)

        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "order_update"
        assert resp["status"] == "cancel_failed"
        assert resp["reason"] == "cancel_rejected"
