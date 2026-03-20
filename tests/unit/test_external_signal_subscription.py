"""외부 시그널 EventBus 구독 등록 및 채널 이벤트 전달 테스트 (#102)."""

from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.bot import Bot
from ante.bot.config import BotConfig
from ante.bot.manager import BotManager
from ante.bot.signal_channel import SignalChannel
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import (
    ExternalSignalEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
)
from ante.strategy.base import Signal, Strategy, StrategyMeta

# ── 테스트 전략 ──────────────────────────────────


class _AcceptingStrategy(Strategy):
    """accepts_external_signals=True 전략."""

    meta = StrategyMeta(
        name="accepting",
        version="1.0.0",
        description="accepts external signals",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict) -> list[Signal]:
        return []

    async def on_data(self, data: dict) -> list[Signal]:
        return [
            Signal(
                symbol=data["symbol"],
                side=data["action"],
                quantity=1.0,
                reason="external",
            )
        ]


class _RejectingStrategy(Strategy):
    """accepts_external_signals=False 전략."""

    meta = StrategyMeta(
        name="rejecting",
        version="1.0.0",
        description="rejects external signals",
    )

    async def on_step(self, context: dict) -> list[Signal]:
        return []


# ── Fixtures ─────────────────────────────────────


@pytest.fixture
def eventbus() -> EventBus:
    """실제 EventBus 인스턴스."""
    return EventBus()


@pytest.fixture
async def db(tmp_path) -> Database:  # noqa: ANN001
    """테스트용 임시 DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield db  # type: ignore[misc]
    await db.close()


def _make_config(bot_id: str = "bot-001") -> BotConfig:
    return BotConfig(
        bot_id=bot_id,
        strategy_id="stg-001",
        interval_seconds=60,
    )


# ── US-2: BotManager ExternalSignalEvent 구독 등록 ──────


class TestBotManagerSignalSubscription:
    """BotManager가 ExternalSignalEvent 구독을 등록/해제하는지 테스트."""

    async def test_register_subscribes_external_signal(
        self, eventbus: EventBus, db: Database
    ) -> None:
        """봇 생성 시 ExternalSignalEvent 구독 등록."""
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()

        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {"available": 1000000.0}

        bot = await manager.create_bot(
            config=_make_config(),
            strategy_cls=_AcceptingStrategy,
            ctx=ctx,
        )

        # ExternalSignalEvent 핸들러가 등록되었는지 확인
        handlers = eventbus.get_handlers(ExternalSignalEvent)
        handler_funcs = [h for _, h in handlers]
        assert bot.on_external_signal in handler_funcs

    async def test_unregister_on_remove(self, eventbus: EventBus, db: Database) -> None:
        """봇 삭제 시 ExternalSignalEvent 구독 해제."""
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()

        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {"available": 1000000.0}

        bot = await manager.create_bot(
            config=_make_config(),
            strategy_cls=_AcceptingStrategy,
            ctx=ctx,
        )

        await manager.remove_bot("bot-001")

        # ExternalSignalEvent 핸들러가 해제되었는지 확인
        handlers = eventbus.get_handlers(ExternalSignalEvent)
        handler_funcs = [h for _, h in handlers]
        assert bot.on_external_signal not in handler_funcs

    async def test_signal_delivered_via_eventbus(
        self, eventbus: EventBus, db: Database
    ) -> None:
        """EventBus에 ExternalSignalEvent 발행 → 봇의 on_external_signal() 호출."""
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()

        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {"available": 1000000.0}

        bot = await manager.create_bot(
            config=_make_config(),
            strategy_cls=_AcceptingStrategy,
            ctx=ctx,
        )
        # 전략 인스턴스 설정 (start() 없이도 on_external_signal 테스트 가능)
        bot.strategy = _AcceptingStrategy(ctx=ctx)

        event = ExternalSignalEvent(
            bot_id="bot-001",
            signal_id="sig-001",
            symbol="005930",
            action="buy",
            confidence=0.9,
        )

        await eventbus.publish(event)

        # EventBus를 통한 publish 확인 (history에서)
        history = eventbus.get_history(OrderRequestEvent)
        assert len(history) == 1
        assert history[0].symbol == "005930"
        assert history[0].side == "buy"

    async def test_signal_not_delivered_after_remove(
        self, eventbus: EventBus, db: Database
    ) -> None:
        """봇 삭제 후 ExternalSignalEvent 발행 → 호출되지 않음."""
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()

        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {"available": 1000000.0}

        bot = await manager.create_bot(
            config=_make_config(),
            strategy_cls=_AcceptingStrategy,
            ctx=ctx,
        )
        bot.strategy = _AcceptingStrategy(ctx=ctx)

        await manager.remove_bot("bot-001")

        event = ExternalSignalEvent(
            bot_id="bot-001",
            signal_id="sig-002",
            symbol="005930",
            action="sell",
        )

        await eventbus.publish(event)

        # OrderRequestEvent가 발행되지 않아야 함
        history = eventbus.get_history(OrderRequestEvent)
        assert len(history) == 0


# ── US-3: 시그널 채널 이벤트 전달 ─────────────────────


class TestChannelEventForwarding:
    """시그널 채널 연결/미연결 시 이벤트 전달 테스트."""

    async def test_fill_forwarded_to_channel(self) -> None:
        """시그널 채널 연결 상태에서 체결 시 채널에 fill 메시지 전달."""
        bot_mock = MagicMock()
        bot_mock.bot_id = "bot-001"
        eventbus = EventBus()
        ctx = MagicMock()
        output = io.StringIO()

        channel = SignalChannel(
            bot=bot_mock,
            eventbus=eventbus,
            ctx=ctx,
            output_stream=output,
        )

        # 채널이 이벤트 구독 시작
        channel._subscribe_events()

        try:
            # 체결 이벤트 발행
            fill_event = OrderFilledEvent(
                order_id="ORD-001",
                bot_id="bot-001",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=58200.0,
                commission=87.3,
            )
            await eventbus.publish(fill_event)

            # 채널 출력에 fill 메시지가 있어야 함
            resp = json.loads(output.getvalue().strip())
            assert resp["type"] == "fill"
            assert resp["order_id"] == "ORD-001"
            assert resp["price"] == 58200.0
        finally:
            channel._unsubscribe_events()

    async def test_bot_on_fill_works_without_channel(self) -> None:
        """시그널 채널 미연결 시 기존 on_fill() 동작에 영향 없음."""
        eventbus = EventBus()

        config = _make_config()
        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {"available": 1000000.0}

        bot = Bot(
            config=config,
            strategy_cls=_AcceptingStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        bot.strategy = _AcceptingStrategy(ctx=ctx)
        bot.strategy.on_fill = AsyncMock(return_value=[])

        # 채널 없이 EventBus에 구독
        eventbus.subscribe(OrderFilledEvent, bot.on_order_filled)

        fill_event = OrderFilledEvent(
            order_id="ORD-001",
            bot_id="bot-001",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=58200.0,
        )

        await eventbus.publish(fill_event)

        # 전략의 on_fill이 호출됨
        bot.strategy.on_fill.assert_called_once()

    async def test_rejected_forwarded_to_channel(self) -> None:
        """시그널 채널에 주문 거부 이벤트 전달."""
        bot_mock = MagicMock()
        bot_mock.bot_id = "bot-001"
        eventbus = EventBus()
        ctx = MagicMock()
        output = io.StringIO()

        channel = SignalChannel(
            bot=bot_mock,
            eventbus=eventbus,
            ctx=ctx,
            output_stream=output,
        )

        channel._subscribe_events()

        try:
            event = OrderRejectedEvent(
                order_id="ORD-002",
                bot_id="bot-001",
                reason="insufficient funds",
            )
            await eventbus.publish(event)

            resp = json.loads(output.getvalue().strip())
            assert resp["type"] == "order_update"
            assert resp["status"] == "rejected"
            assert resp["reason"] == "insufficient funds"
        finally:
            channel._unsubscribe_events()

    async def test_channel_and_bot_both_receive_fill(self) -> None:
        """채널과 봇 모두 체결 이벤트를 수신."""
        eventbus = EventBus()

        config = _make_config()
        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {"available": 1000000.0}

        bot = Bot(
            config=config,
            strategy_cls=_AcceptingStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        bot.strategy = _AcceptingStrategy(ctx=ctx)
        bot.strategy.on_fill = AsyncMock(return_value=[])

        # 봇 이벤트 구독
        eventbus.subscribe(OrderFilledEvent, bot.on_order_filled)

        # 채널 구독
        output = io.StringIO()
        bot_mock = MagicMock()
        bot_mock.bot_id = "bot-001"
        channel = SignalChannel(
            bot=bot_mock,
            eventbus=eventbus,
            ctx=ctx,
            output_stream=output,
        )
        channel._subscribe_events()

        try:
            fill_event = OrderFilledEvent(
                order_id="ORD-003",
                bot_id="bot-001",
                symbol="005930",
                side="buy",
                quantity=5.0,
                price=59000.0,
            )

            await eventbus.publish(fill_event)

            # 봇의 on_fill 호출됨
            bot.strategy.on_fill.assert_called_once()

            # 채널에도 전달됨
            resp = json.loads(output.getvalue().strip())
            assert resp["type"] == "fill"
            assert resp["order_id"] == "ORD-003"
        finally:
            channel._unsubscribe_events()
