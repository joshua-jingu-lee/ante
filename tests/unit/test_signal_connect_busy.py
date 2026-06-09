"""signal.connect 단일-connect Phase-B BUSY envelope (#2334/#2337).

핸드셰이크 핸들러가 register atomic check-and-insert 로 같은 bot 의 두 번째
핸드셰이크를 ``BotSignalChannelBusy`` 로 거부하고, IPC ``_dispatch`` 가
``BOT_SIGNAL_CHANNEL_BUSY`` envelope(stable code, 키/식별자 비노출)으로 변환함을
lock 한다. frozen 거부도 검증한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.exceptions import BotSignalChannelBusy, SignalChannelRegistryFrozen
from ante.bot.signal_channel_registry import SignalChannelRegistry
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import _handle_signal_connect

pytestmark = pytest.mark.asyncio


def _make_bot(*, account_id: str = "acc-live") -> MagicMock:
    bot = MagicMock()
    bot.config.account_id = account_id
    from ante.bot.config import BotStatus

    bot.status = BotStatus.RUNNING
    bot.strategy.meta.accepts_external_signals = True
    return bot


def _svc(reg: SignalChannelRegistry | None) -> ServiceRegistry:
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(return_value="bot-1")
    bm.get_bot = MagicMock(return_value=_make_bot())
    return ServiceRegistry(
        account=MagicMock(),
        bot_manager=bm,
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
        signal_channel_registry=reg,
        audit_logger=None,
    )


async def test_first_connect_registers_and_returns_session() -> None:
    reg = SignalChannelRegistry()
    svc = _svc(reg)
    result = await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
    assert result["bot_id"] == "bot-1"
    assert result["_stream"] == "signal.connect"
    assert "session_id" in result
    assert reg.has_active_session("bot-1") is True


async def test_second_connect_raises_busy() -> None:
    reg = SignalChannelRegistry()
    svc = _svc(reg)
    await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
    with pytest.raises(BotSignalChannelBusy) as ei:
        await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
    assert ei.value.code == "BOT_SIGNAL_CHANNEL_BUSY"


async def test_busy_envelope_via_dispatch_redacts_identifiers() -> None:
    """server _dispatch 가 BUSY → BOT_SIGNAL_CHANNEL_BUSY envelope(키 비노출)."""
    import json

    from ante.ipc.registry import CommandRegistry
    from ante.ipc.server import IPCServer

    reg = SignalChannelRegistry()
    svc = _svc(reg)
    cmd_reg = CommandRegistry()
    cmd_reg.register(
        "signal.connect",
        _handle_signal_connect,
        is_mutating=False,
        result_kind="stream",
        required_services=frozenset({"bot_manager"}),
        account_id_policy="none",
    )
    server = IPCServer("/tmp/unused.sock", svc, cmd_reg)
    # _dispatch lifecycle gate 통과를 위해 RUNNING 으로 둔다(start() 없이 단위).
    from ante.ipc.server import IPCServerState

    server._state = IPCServerState.RUNNING

    # 1st OK.
    ok = await server._dispatch(
        {"id": "h1", "command": "signal.connect", "args": {"key": "sk_x"}}
    )
    assert ok["status"] == "ok"
    # 2nd → BUSY envelope.
    busy = await server._dispatch(
        {"id": "h2", "command": "signal.connect", "args": {"key": "sk_x"}}
    )
    assert busy["status"] == "error"
    assert busy["error"]["code"] == "BOT_SIGNAL_CHANNEL_BUSY"
    # 키/식별자 비노출.
    assert "sk_" not in json.dumps(busy)
    assert "bot-1" not in busy["error"]["message"]


async def test_frozen_registry_rejects_connect() -> None:
    reg = SignalChannelRegistry()
    reg.freeze()
    svc = _svc(reg)
    with pytest.raises(SignalChannelRegistryFrozen):
        await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
    assert reg.has_active_session("bot-1") is False


async def test_headless_no_registry_returns_session_no_register() -> None:
    """reg=None → register 스킵, session_id 만 전달(crash 없음)."""
    svc = _svc(None)
    result = await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
    assert "session_id" in result
    assert result["_stream"] == "signal.connect"
