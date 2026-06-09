"""signal.connect manual connect-audit + redaction (#2334 §8 / #2337).

핸드셰이크-OK 시 정확히 1회 ``log(member_id='ipc', action='signal.connect',
resource='bot:<id>')``, 게이트 실패 시 0회, headless 무크래시, invalid-key
caplog 에 ``sk_`` 미등장 + expected-exc ERROR traceback 부재를 lock 한다.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.config import BotStatus
from ante.bot.exceptions import InvalidSignalKey
from ante.bot.signal_channel_registry import SignalChannelRegistry
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import _handle_signal_connect

pytestmark = pytest.mark.asyncio


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.config.account_id = "acc-live"
    bot.status = BotStatus.RUNNING
    bot.strategy.meta.accepts_external_signals = True
    return bot


def _svc(*, audit_logger: object | None, valid_key: bool = True) -> ServiceRegistry:
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(return_value="bot-1" if valid_key else None)
    bm.get_bot = MagicMock(return_value=_make_bot())
    return ServiceRegistry(
        account=MagicMock(),
        bot_manager=bm,
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
        signal_channel_registry=SignalChannelRegistry(),
        audit_logger=audit_logger,
    )


async def test_handshake_ok_logs_connect_audit_once() -> None:
    audit = MagicMock()
    audit.log = AsyncMock()
    svc = _svc(audit_logger=audit)

    await _handle_signal_connect(svc, {"key": "sk_secret"}, "ipc")

    audit.log.assert_awaited_once()
    kwargs = audit.log.await_args.kwargs
    assert kwargs["member_id"] == "ipc"
    assert kwargs["action"] == "signal.connect"
    assert kwargs["resource"] == "bot:bot-1"
    # detail 에 키 비노출.
    assert "sk_" not in str(kwargs)


async def test_gate_failure_does_not_log_audit() -> None:
    audit = MagicMock()
    audit.log = AsyncMock()
    svc = _svc(audit_logger=audit, valid_key=False)

    with pytest.raises(InvalidSignalKey):
        await _handle_signal_connect(svc, {"key": "sk_bad"}, "ipc")

    audit.log.assert_not_awaited()


async def test_headless_no_audit_logger_no_crash() -> None:
    svc = _svc(audit_logger=None)
    result = await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
    assert result["bot_id"] == "bot-1"


async def test_invalid_key_dispatch_warns_without_sk_or_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """invalid-key 거부는 구조화 WARNING — caplog 에 sk_ 미등장·ERROR traceback 부재."""
    from ante.ipc.registry import CommandRegistry
    from ante.ipc.server import IPCServer, IPCServerState

    svc = _svc(audit_logger=None, valid_key=False)
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
    server._state = IPCServerState.RUNNING

    with caplog.at_level(logging.WARNING, logger="ante.ipc.server"):
        resp = await server._dispatch(
            {"id": "h1", "command": "signal.connect", "args": {"key": "sk_bad"}}
        )

    assert resp["error"]["code"] == "INVALID_SIGNAL_KEY"
    # expected-exc 는 WARNING 1줄(traceback 없는 구조화). ERROR/exception 부재.
    assert any(
        rec.levelno == logging.WARNING and "handshake rejected" in rec.message
        for rec in caplog.records
    )
    assert not any(rec.levelno >= logging.ERROR for rec in caplog.records)
    # caplog 전체에 sk_ 미등장(키 비노출).
    assert "sk_" not in caplog.text
    # expected-exc 는 exc_info(traceback) 미부착.
    assert all(rec.exc_info is None for rec in caplog.records)
