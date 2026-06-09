"""#2333 daemon-side repro (#2334/#2337 T5).

RUNNING + accepts_external_signals=True 봇을 ``BotManager.create_bot`` 로 만들고,
``_run_signal_stream`` 에 in-memory reader 로 signal 프레임 1개를 흘려 (1) ack
반환, (2) ``strategy.on_data`` 호출됨, (3) **OrderRequestEvent 정확히 1건이 daemon
EventBus history**(manager 의 기존 ExternalSignalEvent→on_external_signal→
_publish_signals 경유)를 검증한다. CLP의 import-removal 절반(CLI 자체 EventBus/
BotManager 미구성 단언)은 #2338 PR#3 소관 — 본 PR 은 daemon-side repro 만.
"""

from __future__ import annotations

import asyncio
import json
import struct
from unittest.mock import MagicMock

import pytest

from ante.bot.config import BotConfig, BotStatus
from ante.bot.manager import BotManager
from ante.bot.signal_channel_registry import ChannelHandle, SignalChannelRegistry
from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.eventbus.bus import EventBus
from ante.eventbus.events import OrderRequestEvent
from ante.ipc.server import IPCServer
from ante.strategy.base import Signal, Strategy, StrategyMeta

pytestmark = pytest.mark.asyncio


class _AcceptingStrategy(Strategy):
    """on_data → 1 Signal(OrderRequestEvent 1건 유발) 전략."""

    on_data_calls: list[dict] = []

    meta = StrategyMeta(
        name="accepting-repro",
        version="1.0.0",
        description="accepts external signals",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict) -> list[Signal]:
        return []

    async def on_data(self, data: dict) -> list[Signal]:
        type(self).on_data_calls.append(data)
        return [
            Signal(
                symbol=data["symbol"],
                side=data["action"],
                quantity=1.0,
                reason="external_repro",
            )
        ]


def _frame_bytes(obj: dict) -> bytes:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


class _FakeWriter:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None

    def frames(self) -> list[dict]:
        out: list[dict] = []
        view = memoryview(self.buffer)
        i = 0
        while i + 4 <= len(view):
            (length,) = struct.unpack("!I", view[i : i + 4])
            i += 4
            if i + length > len(view):
                break
            out.append(json.loads(bytes(view[i : i + length]).decode("utf-8")))
            i += length
        return out


async def test_daemon_side_signal_to_order_request_repro_2333() -> None:
    _AcceptingStrategy.on_data_calls = []

    db = Database(":memory:")
    await db.connect()
    try:
        bus = EventBus()
        reg = SignalChannelRegistry()
        manager = BotManager(
            eventbus=bus,
            db=db,
            signal_channel_registry=reg,
        )
        await manager.initialize()

        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {"available": 1_000_000.0}

        await manager.create_bot(
            config=BotConfig(
                bot_id="bot-1",
                strategy_id="stg-1",
                interval_seconds=60,
                account_id="acc-test",
            ),
            strategy_cls=_AcceptingStrategy,
            ctx=ctx,
        )
        bot = manager.get_bot("bot-1")
        bot.strategy = _AcceptingStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        svc = ServiceRegistry(
            account=MagicMock(),
            bot_manager=manager,
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=bus,
            signal_channel_registry=reg,
            audit_logger=None,
        )
        server = IPCServer("/tmp/unused.sock", svc, MagicMock())

        reg.register(ChannelHandle(session_id="s1", bot_id="bot-1", generation=0))

        reader = asyncio.StreamReader()
        writer = _FakeWriter()
        reader.feed_data(
            _frame_bytes(
                {"type": "signal", "symbol": "005930", "side": "buy", "confidence": 0.9}
            )
        )

        task = asyncio.ensure_future(
            server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
        )
        # ack + on_data + OrderRequestEvent 가 나타날 때까지 yield(sleep 동기화 금지).
        for _ in range(200):
            await asyncio.sleep(0)
            if any(f.get("type") == "ack" for f in writer.frames()):
                break

        reader.feed_eof()
        await asyncio.wait_for(task, timeout=3.0)

        # (1) ack 반환.
        frames = writer.frames()
        assert any(f.get("type") == "ack" for f in frames)
        # (2) strategy.on_data 호출됨.
        assert len(_AcceptingStrategy.on_data_calls) == 1
        assert _AcceptingStrategy.on_data_calls[0]["symbol"] == "005930"
        # (3) OrderRequestEvent 정확히 1건 daemon EventBus history.
        history = bus.get_history(OrderRequestEvent)
        assert len(history) == 1
        assert history[0].bot_id == "bot-1"
        assert history[0].symbol == "005930"
        assert history[0].side == "buy"
    finally:
        await db.close()
