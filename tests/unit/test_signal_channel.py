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
    # #2146: _handle_signal 이 bot.config.account_id 를 ExternalSignalEvent 에
    # 싣는다. MagicMock default account_id 는 invalid 라 검증기에서 거부되므로
    # valid 값을 명시 설정한다.
    b.config.account_id = "acc-test"
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
        # #2146: 봇 계좌(bot.config.account_id)가 이벤트에 실려야 한다.
        assert event.account_id == "acc-test"

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

    async def test_signal_carries_bot_account_id(
        self, channel: SignalChannel, eventbus: MagicMock
    ) -> None:
        """#2146: _handle_signal 이 봇 계좌(account_id)를 실은 이벤트를 발행한다."""
        msg = json.dumps({"type": "signal", "symbol": "005930", "side": "buy"})
        await channel._handle_line(msg)

        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, ExternalSignalEvent)
        # bot fixture 의 config.account_id 가 그대로 이벤트에 전파되어야 한다.
        assert event.account_id == "acc-test"


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

    async def test_signal_handler_unrelated_exception_becomes_error_frame(
        self, channel: SignalChannel, eventbus: MagicMock, output: io.StringIO
    ) -> None:
        """시그널 처리 중 어떤 예외도 error 프레임으로 끝나고 전파되지 않는다."""

        class _UnrelatedError(Exception):
            pass

        eventbus.publish = AsyncMock(side_effect=_UnrelatedError("bus down"))
        msg = json.dumps({"type": "signal", "symbol": "005930", "side": "buy"})

        await channel._handle_line(msg)

        eventbus.publish.assert_awaited_once()
        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "error"

        await channel._handle_line(json.dumps({"type": "ping"}))
        last = json.loads(output.getvalue().strip().splitlines()[-1])
        assert last["type"] == "pong"


def _signal_with_metadata(metadata: dict) -> dict:
    return {"type": "signal", "symbol": "005930", "side": "buy", **metadata}


class TestSignalMetadataBound:
    """외부 시그널 metadata 의 키 수(64)·크기(16KB) 상한."""

    async def test_64_keys_accepted_65_rejected(
        self, channel: SignalChannel, eventbus: MagicMock, output: io.StringIO
    ) -> None:
        at_limit = {f"k{i}": i for i in range(64)}
        await channel._handle_message(_signal_with_metadata(at_limit))
        eventbus.publish.assert_awaited_once()
        assert eventbus.publish.call_args[0][0].metadata == at_limit

        over = {f"k{i}": i for i in range(65)}
        await channel._handle_message(_signal_with_metadata(over))
        eventbus.publish.assert_awaited_once()
        frames = [json.loads(line) for line in output.getvalue().splitlines()]
        assert [f["type"] for f in frames] == ["ack", "error"]
        assert frames[1]["message"] == "signal metadata too large"

    async def test_16384_bytes_accepted_16385_rejected(
        self, channel: SignalChannel, eventbus: MagicMock, output: io.StringIO
    ) -> None:
        overhead = len(json.dumps({"blob": ""}).encode("utf-8"))
        at_limit = {"blob": "x" * (16_384 - overhead)}
        assert len(json.dumps(at_limit).encode("utf-8")) == 16_384
        await channel._handle_message(_signal_with_metadata(at_limit))
        eventbus.publish.assert_awaited_once()

        over = {"blob": "x" * (16_385 - overhead)}
        await channel._handle_message(_signal_with_metadata(over))
        eventbus.publish.assert_awaited_once()
        frames = [json.loads(line) for line in output.getvalue().splitlines()]
        assert [f["type"] for f in frames] == ["ack", "error"]
        assert frames[1]["message"] == "signal metadata too large"


class TestConstructorPositionalOrder:
    async def test_fifth_positional_argument_is_output_stream(
        self, bot: MagicMock, eventbus: MagicMock, ctx: MagicMock
    ) -> None:
        """위치 인자 순서는 (bot, eventbus, ctx, input_stream, output_stream)이다."""
        input_stream = io.StringIO()
        output_stream = io.StringIO()
        ch = SignalChannel(bot, eventbus, ctx, input_stream, output_stream)

        await ch._handle_message({"type": "query", "method": "balance"})

        assert input_stream.getvalue() == ""
        resp = json.loads(output_stream.getvalue().strip())
        assert resp == {
            "type": "result",
            "method": "balance",
            "data": {"available": 5000000.0},
        }


def _modify_and_stop_events() -> list[tuple[object, str]]:
    from ante.eventbus.events import (
        OrderModifyExecutedEvent,
        OrderModifyRejectedEvent,
        StopOrderExpiredEvent,
        StopOrderRegisteredEvent,
        StopOrderTriggeredEvent,
    )

    common = {"account_id": "acc-test", "bot_id": "bot-001", "strategy_id": "s1"}
    return [
        (
            OrderModifyExecutedEvent(
                **common,
                order_id="ord-mod-exec",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=45000.0,
                reason="adjust",
            ),
            "modified",
        ),
        (
            OrderModifyRejectedEvent(
                **common,
                order_id="ord-mod-rej",
                symbol="005930",
                side="sell",
                quantity=2.0,
                price=51000.0,
                reason="modify_not_implemented",
            ),
            "modify_rejected",
        ),
        (
            StopOrderRegisteredEvent(
                **common,
                stop_order_id="stop-reg",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
            ),
            "stop_registered",
        ),
        (
            StopOrderTriggeredEvent(
                **common,
                stop_order_id="stop-trig",
                symbol="005930",
                side="sell",
                quantity=10.0,
                trigger_price=48500.0,
                converted_order_type="market",
            ),
            "stop_triggered",
        ),
        (
            StopOrderExpiredEvent(
                **common,
                stop_order_id="stop-exp",
                symbol="005930",
                reason="session_ended",
            ),
            "stop_expired",
        ),
    ]


class TestModifyAndStopEventSubscription:
    async def test_published_modify_and_stop_events_reach_channel(
        self, bot: MagicMock, ctx: MagicMock
    ) -> None:
        """정정 완료·거부와 stop 등록·발동·만료가 order_update 로 나간다."""
        from ante.eventbus import EventBus

        bus = EventBus()
        frames: list[dict] = []
        ch = SignalChannel(bot, bus, ctx, sink=frames.append)
        ch._subscribe_events()

        expected = []
        for event, status in _modify_and_stop_events():
            await bus.publish(event)
            expected.append(status)

        assert [f["type"] for f in frames] == ["order_update"] * len(expected)
        assert [f["status"] for f in frames] == expected


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
            account_id="acc-test",
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
        event = OrderFilledEvent(
            order_id="ORD-002", bot_id="bot-999", account_id="acc-test"
        )
        await channel._on_fill(event)
        assert output.getvalue() == ""


class TestFillBoundedDedup:
    """SignalChannel 체결 bounded dedup (#1957)."""

    async def test_fill_includes_dedup_key(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """JSON payload 에 fill_dedup_key 가 포함된다."""
        event = OrderFilledEvent(
            order_id="ORD-001",
            bot_id="bot-001",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=58200.0,
            commission=87.3,
            account_id="acc-test",
            fill_dedup_key="ORD-001:10.0",
        )
        await channel._on_fill(event)
        resp = json.loads(output.getvalue().strip())
        assert resp["fill_dedup_key"] == "ORD-001:10.0"

    async def test_nonempty_key_redelivery_writes_once(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """같은 비빈키 fill 2회 → write 1회 (stdout 1줄)."""
        event = OrderFilledEvent(
            order_id="ORD-001",
            bot_id="bot-001",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=58200.0,
            account_id="acc-test",
            fill_dedup_key="ORD-001:10.0",
        )
        await channel._on_fill(event)
        await channel._on_fill(event)

        lines = [ln for ln in output.getvalue().splitlines() if ln]
        assert len(lines) == 1

    async def test_empty_key_redelivery_writes_twice(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """빈키 fill 2회 → write 2회 (dedup 비대상)."""
        event = OrderFilledEvent(
            order_id="ORD-001",
            bot_id="bot-001",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=58200.0,
            account_id="acc-test",
            fill_dedup_key="",
        )
        await channel._on_fill(event)
        await channel._on_fill(event)

        lines = [ln for ln in output.getvalue().splitlines() if ln]
        assert len(lines) == 2

    async def test_order_rejected_forwarded(
        self, channel: SignalChannel, output: io.StringIO
    ) -> None:
        """주문 거부 → 외부 전달."""
        event = OrderRejectedEvent(
            order_id="ORD-003",
            bot_id="bot-001",
            reason="insufficient funds",
            account_id="acc-test",
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
            account_id="acc-test",
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
            account_id="test-account",
            order_id="ORD-005",
            bot_id="bot-001",
            error_message="cancel_rejected",
        )

        await channel._on_order_update(event)

        resp = json.loads(output.getvalue().strip())
        assert resp["type"] == "order_update"
        assert resp["status"] == "cancel_failed"
        assert resp["reason"] == "cancel_rejected"
