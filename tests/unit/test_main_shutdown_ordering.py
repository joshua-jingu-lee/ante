"""_shutdown 종료 순서 회귀 테스트 (Refs #1159).

cold-path guard(`PID alive AND socket exists`)가 shutdown 전 구간에서
'active runtime'으로 판정해야 한다. 본 테스트는 IPCServer.stop_accepting()이
초기에, IPCServer.unlink_socket()이 BotManager/DB 종료 후 마지막에
호출되도록 ordering이 보존되는지 검증한다.

모든 테스트는 **실제 Unix 소켓 파일**을 사용한다 — 모킹 없이 race window
회귀를 직접 노출시키는 것이 목적이다.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry
from ante.ipc.server import IPCServer, IPCServerState
from ante.main import Services, _shutdown


def _make_service_registry() -> ServiceRegistry:
    return ServiceRegistry(
        account=MagicMock(),
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
    )


@pytest.fixture
def socket_path() -> str:
    """Unix 소켓 경로 길이 제한(104바이트)을 위해 /tmp 직접 사용."""
    td = tempfile.mkdtemp(prefix="ipc1159", dir="/tmp")
    return str(Path(td) / "ante.sock")


@pytest.mark.asyncio
async def test_shutdown_keeps_ipc_socket_alive_until_db_closed(
    socket_path: str,
) -> None:
    """_shutdown은 IPC unlink를 BotManager/DB 종료 후로 미룬다.

    호출 순서: stop_accepting < bot_stop_all < db_close < drain <= unlink_socket.
    cold-path guard가 'PID alive AND socket exists'를 active 기준으로 사용하므로,
    socket 파일은 BotManager/DB 종료 완료 시점까지 남아 있어야 한다.
    """
    cmd_registry = CommandRegistry()
    service_registry = _make_service_registry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    events: list[str] = []

    # IPCServer 호출 추적 wrapper
    original_stop_accepting = server.stop_accepting
    original_drain = server.drain_connections
    original_unlink = server.unlink_socket

    async def tracked_stop_accepting() -> None:
        events.append("ipc_stop_accepting")
        await original_stop_accepting()

    async def tracked_drain(timeout: float = 5.0) -> None:
        events.append("ipc_drain")
        await original_drain(timeout)

    def tracked_unlink() -> None:
        events.append("ipc_unlink_socket")
        original_unlink()

    server.stop_accepting = tracked_stop_accepting  # type: ignore[method-assign]
    server.drain_connections = tracked_drain  # type: ignore[method-assign]
    server.unlink_socket = tracked_unlink  # type: ignore[method-assign]

    # BotManager stub
    class _StubBotManager:
        async def stop_all(self) -> None:
            events.append("bot_stop_all")

    # Database stub (close만 사용)
    class _StubDatabase:
        async def close(self) -> None:
            events.append("db_close")

    s = Services(
        ipc_server=server,
        bot_manager=_StubBotManager(),
        db=_StubDatabase(),
    )

    try:
        await _shutdown(s)
    finally:
        # 정리: 만약 unlink_socket이 호출되지 않았다면 강제 정리
        if Path(socket_path).exists():
            Path(socket_path).unlink()

    # ordering 검증
    assert "ipc_stop_accepting" in events, f"events: {events}"
    assert "bot_stop_all" in events, f"events: {events}"
    assert "db_close" in events, f"events: {events}"
    assert "ipc_drain" in events, f"events: {events}"
    assert "ipc_unlink_socket" in events, f"events: {events}"

    idx_stop_accepting = events.index("ipc_stop_accepting")
    idx_bot = events.index("bot_stop_all")
    idx_db = events.index("db_close")
    idx_drain = events.index("ipc_drain")
    idx_unlink = events.index("ipc_unlink_socket")

    assert idx_stop_accepting < idx_bot, (
        f"stop_accepting must happen before bot_stop_all; events={events}"
    )
    assert idx_bot < idx_db, (
        f"bot_stop_all must happen before db_close; events={events}"
    )
    assert idx_db < idx_drain, f"db_close must happen before ipc_drain; events={events}"
    assert idx_drain <= idx_unlink, (
        f"ipc_drain must happen before/at ipc_unlink_socket; events={events}"
    )


@pytest.mark.asyncio
async def test_shutdown_socket_file_present_during_bot_and_db_phase(
    socket_path: str,
) -> None:
    """BotManager.stop_all와 Database.close 실행 시점에 socket 파일이 존재해야 한다.

    cold-path guard가 active로 판정해야 하는 구간이다.
    """
    cmd_registry = CommandRegistry()
    service_registry = _make_service_registry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    bot_stop_socket_present: list[bool] = []
    db_close_socket_present: list[bool] = []

    class _StubBotManager:
        async def stop_all(self) -> None:
            bot_stop_socket_present.append(Path(socket_path).exists())

    class _StubDatabase:
        async def close(self) -> None:
            db_close_socket_present.append(Path(socket_path).exists())

    s = Services(
        ipc_server=server,
        bot_manager=_StubBotManager(),
        db=_StubDatabase(),
    )

    try:
        await _shutdown(s)
    finally:
        if Path(socket_path).exists():
            Path(socket_path).unlink()

    assert bot_stop_socket_present == [True], (
        "BotManager.stop_all 시점에 socket 파일이 존재해야 한다 "
        f"(actual: {bot_stop_socket_present})"
    )
    assert db_close_socket_present == [True], (
        "Database.close 시점에 socket 파일이 존재해야 한다 "
        f"(actual: {db_close_socket_present})"
    )
    assert not Path(socket_path).exists(), (
        "_shutdown 완료 후에는 socket 파일이 제거되어야 한다"
    )


@pytest.mark.asyncio
async def test_shutdown_sets_shutting_down_before_bot_stop(
    socket_path: str,
) -> None:
    """_shutdown은 BotManager 정지 전에 IPC state를 SHUTTING_DOWN으로 전환한다."""
    cmd_registry = CommandRegistry()
    service_registry = _make_service_registry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    state_at_bot_stop: list[IPCServerState] = []

    class _StubBotManager:
        async def stop_all(self) -> None:
            state_at_bot_stop.append(server.state)

    class _StubDatabase:
        async def close(self) -> None:
            pass

    s = Services(
        ipc_server=server,
        bot_manager=_StubBotManager(),
        db=_StubDatabase(),
    )

    try:
        await _shutdown(s)
    finally:
        if Path(socket_path).exists():
            Path(socket_path).unlink()

    assert state_at_bot_stop == [IPCServerState.SHUTTING_DOWN]
    assert server.state is IPCServerState.STOPPED


@pytest.mark.asyncio
async def test_active_connection_mutating_command_rejected_during_shutdown(
    socket_path: str,
) -> None:
    """stop_accepting 이후 active connection의 mutating dispatch는 503으로 거부된다."""
    cmd_registry = CommandRegistry()
    service_registry = _make_service_registry()
    server = IPCServer(socket_path, service_registry, cmd_registry)

    mutation_calls: list[str] = []

    async def mutate_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        mutation_calls.append(actor)
        return {"mutated": True}

    cmd_registry.register("test.mutate", mutate_handler, is_mutating=True)
    await server.start()

    response_before_shutdown = await server._dispatch(
        {"id": "before", "command": "test.mutate", "args": {}, "actor": "pre"}
    )
    assert response_before_shutdown["status"] == "ok"

    class _StubBotManager:
        async def stop_all(self) -> None:
            response = await server._dispatch(
                {
                    "id": "during",
                    "command": "test.mutate",
                    "args": {},
                    "actor": "active-client",
                }
            )
            assert response["status"] == "error"
            assert response["error"]["code"] == "SERVICE_UNAVAILABLE"

    class _StubDatabase:
        async def close(self) -> None:
            pass

    s = Services(
        ipc_server=server,
        bot_manager=_StubBotManager(),
        db=_StubDatabase(),
    )

    try:
        await _shutdown(s)
    finally:
        if Path(socket_path).exists():
            Path(socket_path).unlink()

    assert mutation_calls == ["pre"]


@pytest.mark.asyncio
async def test_active_connection_read_only_command_allowed_during_shutdown(
    socket_path: str,
) -> None:
    """SHUTTING_DOWN 중 active connection의 read-only dispatch는 통과한다."""
    cmd_registry = CommandRegistry()
    service_registry = _make_service_registry()
    server = IPCServer(socket_path, service_registry, cmd_registry)

    async def read_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"state": server.state.value, "actor": actor}

    cmd_registry.register("test.read", read_handler, is_mutating=False)
    await server.start()

    responses: list[dict] = []

    class _StubBotManager:
        async def stop_all(self) -> None:
            responses.append(
                await server._dispatch(
                    {
                        "id": "during",
                        "command": "test.read",
                        "args": {},
                        "actor": "active-client",
                    }
                )
            )

    class _StubDatabase:
        async def close(self) -> None:
            pass

    s = Services(
        ipc_server=server,
        bot_manager=_StubBotManager(),
        db=_StubDatabase(),
    )

    try:
        await _shutdown(s)
    finally:
        if Path(socket_path).exists():
            Path(socket_path).unlink()

    assert responses == [
        {
            "id": "during",
            "status": "ok",
            "result": {
                "state": IPCServerState.SHUTTING_DOWN.value,
                "actor": "active-client",
            },
        }
    ]


@pytest.mark.asyncio
async def test_post_stopped_dispatch_rejected(
    socket_path: str,
) -> None:
    """unlink_socket 이후 이론적 잔여 dispatch는 read-only도 503으로 거부된다."""
    cmd_registry = CommandRegistry()
    service_registry = _make_service_registry()
    server = IPCServer(socket_path, service_registry, cmd_registry)

    async def read_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"read": True}

    cmd_registry.register("test.read", read_handler, is_mutating=False)
    await server.start()

    class _StubBotManager:
        async def stop_all(self) -> None:
            pass

    class _StubDatabase:
        async def close(self) -> None:
            pass

    s = Services(
        ipc_server=server,
        bot_manager=_StubBotManager(),
        db=_StubDatabase(),
    )

    try:
        await _shutdown(s)
        response = await server._dispatch(
            {"id": "after", "command": "test.read", "args": {}, "actor": "client"}
        )
    finally:
        if Path(socket_path).exists():
            Path(socket_path).unlink()

    assert response["status"] == "error"
    assert response["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "종료되었습니다" in response["error"]["message"]


@pytest.mark.asyncio
async def test_cold_path_guard_blocks_until_socket_unlinked(
    socket_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop_accepting 후에는 cold-path guard가 차단, unlink_socket 후에는 통과.

    Real IPCServer + non-patched `_assert_no_active_runtime` 결합 검증.
    """
    cmd_registry = CommandRegistry()
    service_registry = _make_service_registry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    # cold-path guard가 보는 PID/socket을 우리 server로 가리키게 한다
    monkeypatch.setattr("ante.main.read_pid_file", lambda config=None: os.getpid())
    monkeypatch.setattr(
        "ante.cli.commands.ipc_helpers.get_socket_path",
        lambda config_dir=None: str(socket_path),
    )

    from ante.cli.commands.account import _assert_no_active_runtime
    from ante.cli.formatter import OutputFormatter

    fmt = OutputFormatter(fmt="text")

    # === stop_accepting 호출 후, unlink_socket 전: guard가 차단해야 한다 ===
    await server.stop_accepting()
    assert Path(socket_path).exists(), (
        "stop_accepting 후에도 socket 파일은 유지되어야 한다 (cold-path guard용)"
    )

    with pytest.raises(SystemExit):
        _assert_no_active_runtime(fmt)

    # === drain_connections + unlink_socket 후: guard가 통과해야 한다 ===
    await server.drain_connections(timeout=0.5)
    server.unlink_socket()
    assert not Path(socket_path).exists()

    # socket missing → stale PID 판정 → SystemExit 발생 안 함
    _assert_no_active_runtime(fmt)


@pytest.mark.asyncio
async def test_signal_handler_uses_same_shutdown_path() -> None:
    """SIGTERM/SIGINT 경로가 동일 _shutdown(s) 진입점을 사용함을 source 레벨에서 확인.

    `test_shutdown_has_timeout_in_run`이 wait_for 패턴을 검증하지만, 본 테스트는
    ordering 회귀가 SIGTERM/SIGINT 모두에서 보존됨을 명시한다.
    """
    import inspect

    from ante import main as main_module

    source = inspect.getsource(main_module._run)
    # 시그널 핸들러가 SIGTERM/SIGINT 모두에 동일 shutdown_event를 set
    assert "signal.SIGTERM" in source
    assert "signal.SIGINT" in source
    # 단일 진입점 _shutdown(s)
    assert "_shutdown(s)" in source
    # asyncio.wait_for로 timeout 감싸기
    assert "asyncio.wait_for(_shutdown(s)" in source
