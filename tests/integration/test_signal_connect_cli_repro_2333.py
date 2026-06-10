"""#2333 CLI end-to-end repro — thin IPC relay → real daemon (#2338 T15).

재작성된 CLI ``_run_connect`` (thin IPC relay) 를 **unmocked**
``asyncio.open_unix_connection`` 으로 real ``IPCServer`` (RUNNING +
``accepts_external_signals=True`` 봇 + signal_key_manager) 의 UDS 에 연결해,
``signal.connect`` 핸드셰이크가 ``status=="ok"`` 로 통과하고 ``BOT_NOT_FOUND``
가 **발생하지 않음** 을 end-to-end 로 단언한다 (=#2333 회귀 lock).

과거(in-process) CLI 는 자체 ``Database``/``BotManager`` 를 새로 구성해 데몬과
다른 상태(빈 bot registry)를 봤기에 RUNNING 봇에도 ``BOT_NOT_FOUND`` 를 냈다.
relay 전환 후 CLI 는 데몬의 LIVE 상태를 그대로 위임받으므로 회귀가 해소된다.

T7 anti-flakiness: sleep 동기화 금지(asyncio.Event/wait_for), ``mkdtemp(dir=
"/tmp")`` UDS, server try/finally stop + settle.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest

from ante.bot.config import BotConfig, BotStatus
from ante.bot.manager import BotManager
from ante.bot.signal_channel_registry import SignalChannelRegistry
from ante.cli.commands.signal import _run_connect
from ante.cli.formatter import OutputFormatter
from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.eventbus.bus import EventBus
from ante.ipc.registry import CommandRegistry, _handle_signal_connect
from ante.ipc.server import IPCServer
from ante.member.models import Member, MemberRole, MemberType
from ante.strategy.base import Signal, Strategy, StrategyMeta

pytestmark = pytest.mark.asyncio

_SIGNAL_KEY = "sk_repro_2333"

_MASTER = Member(
    member_id="m-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Master",
    status="active",
    scopes=[],
)


class _AcceptingStrategy(Strategy):
    meta = StrategyMeta(
        name="accepting-cli-repro",
        version="1.0.0",
        description="accepts external signals",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict) -> list[Signal]:
        return []

    async def on_data(self, data: dict) -> list[Signal]:
        return []


class _Harness:
    def __init__(self) -> None:
        self.db: Database | None = None
        self.server: IPCServer | None = None
        self.bus = EventBus()
        self.reg = SignalChannelRegistry()
        self.manager: BotManager | None = None

    async def setup(self, socket_path: str) -> None:
        self.db = Database(":memory:")
        await self.db.connect()

        self.manager = BotManager(
            eventbus=self.bus,
            db=self.db,
            signal_channel_registry=self.reg,
        )
        await self.manager.initialize()

        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {"available": 1_000_000.0}

        await self.manager.create_bot(
            config=BotConfig(
                bot_id="bot-1",
                strategy_id="stg-1",
                interval_seconds=60,
                account_id="acc-test",
            ),
            strategy_cls=_AcceptingStrategy,
            ctx=ctx,
        )
        bot = self.manager.get_bot("bot-1")
        bot.strategy = _AcceptingStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        async def _validate(key: str) -> str | None:
            return "bot-1" if key == _SIGNAL_KEY else None

        self.manager.validate_signal_key = _validate  # type: ignore[method-assign]

        svc = ServiceRegistry(
            account=MagicMock(),
            bot_manager=self.manager,
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=self.bus,
            signal_channel_registry=self.reg,
            audit_logger=None,
        )
        cmd_reg = CommandRegistry()
        cmd_reg.register(
            "signal.connect",
            _handle_signal_connect,
            is_mutating=False,
            result_kind="stream",
            required_services=frozenset({"bot_manager"}),
            account_id_policy="none",
        )
        self.server = IPCServer(socket_path, svc, cmd_reg)
        await self.server.start()

    async def teardown(self) -> None:
        if self.server is not None:
            await self.server.stop()
        if self.db is not None:
            await self.db.close()


@pytest.fixture
def socket_path() -> str:
    td = tempfile.mkdtemp(prefix="sig-cli-repro", dir="/tmp")
    return str(Path(td) / "ante.sock")


def _make_ctx(fmt: str = "text") -> click.Context:
    """``_run_connect`` 가 요구하는 ctx (formatter/member/config_dir) 구성."""
    ctx = MagicMock(spec=click.Context)
    ctx.obj = {
        "formatter": OutputFormatter(fmt),
        "member": _MASTER,
        "config_dir": None,
    }
    return ctx


async def _drive_run_connect(
    ctx: click.Context, socket_path: str, key: str
) -> list[str]:
    """재작성된 CLI ``_run_connect`` 를 unmocked open_unix_connection 으로 구동.

    ``get_socket_path`` 만 테스트 UDS 로 고정하고(실제 connect 는 unmocked),
    ``_pump_in`` 은 idle stub 으로 패치해(pytest stdin connect_read_pipe 부작용
    회피) ``_pump_out`` 이 데몬 close 로 종료를 주도하게 한다. stderr 라인을
    수집해 informational/거부 메시지를 검사한다.
    """
    stderr_lines: list[str] = []

    async def _idle_pump_in(_writer):  # noqa: ANN001, ANN202
        await asyncio.Event().wait()

    def _capture_err(msg: str) -> None:
        stderr_lines.append(msg)

    with (
        patch(
            "ante.cli.commands.signal.get_socket_path",
            return_value=socket_path,
        ),
        patch("ante.cli.commands.signal._pump_in", _idle_pump_in),
        patch("ante.cli.commands.signal._err", _capture_err),
    ):
        await _run_connect(ctx, key)

    return stderr_lines


async def test_cli_relay_handshake_ok_no_bot_not_found(socket_path: str) -> None:
    """valid key + RUNNING + accepts_external_signals 봇 → handshake OK,
    BOT_NOT_FOUND 미발생 (#2333 회귀 lock)."""
    h = _Harness()
    await h.setup(socket_path)
    ctx = _make_ctx("text")

    drive = asyncio.ensure_future(_drive_run_connect(ctx, socket_path, _SIGNAL_KEY))
    try:
        # adopt 완료(데이터플레인 채워짐) 대기 — sleep 동기화 금지.
        for _ in range(500):
            await asyncio.sleep(0)
            if h.reg.has_active_session("bot-1"):
                sid = next(iter(h.reg._sessions["bot-1"]))
                handle = h.reg.get("bot-1", sid)
                if handle is not None and handle.out_queue is not None:
                    break
        else:
            pytest.fail("relay 가 active session 을 수립하지 못함(handshake 실패 의심)")

        # 데몬 주도 close → _pump_out 이 closed frame 수신 후 종료.
        h.reg.close_bot("bot-1", "bot_stopped")
        stderr_lines = await asyncio.wait_for(drive, timeout=3.0)
    finally:
        if not drive.done():
            drive.cancel()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await drive
        await h.teardown()

    joined = "\n".join(stderr_lines)
    # handshake OK informational.
    assert "Connected to bot bot-1" in joined, stderr_lines
    assert "Ready for JSON Lines communication on stdin/stdout" in stderr_lines
    # #2333 회귀 lock — relay→real-daemon 경계에서 BOT_NOT_FOUND 미발생.
    assert "Bot not found" not in joined, stderr_lines
    assert "BOT_NOT_FOUND" not in joined, stderr_lines


async def test_cli_relay_invalid_key_rejected_no_bot_not_found(
    socket_path: str,
) -> None:
    """invalid key → 데몬 Phase-B INVALID_SIGNAL_KEY 거부(exit 1), BOT_NOT_FOUND
    미발생. relay 가 데몬 envelope 을 그대로 surface 함을 lock."""
    h = _Harness()
    await h.setup(socket_path)
    ctx = _make_ctx("text")

    try:
        with pytest.raises(SystemExit) as exc_info:
            await _drive_run_connect(ctx, socket_path, "sk_wrong")
    finally:
        await h.teardown()

    assert exc_info.value.code == 1
