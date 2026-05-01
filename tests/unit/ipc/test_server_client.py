"""IPCServer + IPCClient 통합 테스트."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.client import IPCClient
from ante.ipc.exceptions import ServerNotRunningError
from ante.ipc.registry import CommandRegistry
from ante.ipc.server import IPCServer


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
    td = tempfile.mkdtemp(prefix="ipc", dir="/tmp")
    return str(Path(td) / "t.sock")


@pytest.fixture
def service_registry() -> ServiceRegistry:
    return _make_service_registry()


@pytest.mark.asyncio
async def test_roundtrip(socket_path: str, service_registry: ServiceRegistry) -> None:
    """요청 -> 응답 라운드트립."""
    cmd_registry = CommandRegistry()

    async def echo_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"echo": args, "actor": actor}

    cmd_registry.register("test.echo", echo_handler)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send("test.echo", {"msg": "hello"}, actor="tester")
        assert response["status"] == "ok"
        assert response["result"]["echo"] == {"msg": "hello"}
        assert response["result"]["actor"] == "tester"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_unknown_command(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """미등록 커맨드 에러 응답."""
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send("nonexistent.command")
        assert response["status"] == "error"
        assert response["error"]["code"] == "UNKNOWN_COMMAND"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_handler_exception(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """핸들러 예외 발생 시 에러 응답."""
    cmd_registry = CommandRegistry()

    async def failing_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        raise ValueError("의도적 예외")

    cmd_registry.register("test.fail", failing_handler)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send("test.fail")
        assert response["status"] == "error"
        assert response["error"]["code"] == "EXECUTION_ERROR"
        assert "의도적 예외" in response["error"]["message"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_server_not_running() -> None:
    """서버 미기동 시 ServerNotRunningError."""
    with tempfile.TemporaryDirectory() as tmp:
        sock = str(Path(tmp) / "nonexistent.sock")
        client = IPCClient(sock, timeout=2.0)
        with pytest.raises(ServerNotRunningError):
            await client.send("test.command")


@pytest.mark.asyncio
async def test_socket_permissions(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """소켓 파일 권한이 0o600으로 설정되는지 확인."""
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    try:
        import os
        import stat

        mode = os.stat(socket_path).st_mode
        file_perm = stat.S_IMODE(mode)
        assert file_perm == 0o600
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_socket_cleanup_on_stop(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """서버 종료 시 소켓 파일 삭제."""
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    assert Path(socket_path).exists()

    await server.stop()
    assert not Path(socket_path).exists()


@pytest.mark.asyncio
async def test_multiple_requests(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """여러 요청을 순차적으로 처리."""
    cmd_registry = CommandRegistry()
    call_count = 0

    async def counter_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        nonlocal call_count
        call_count += 1
        return {"count": call_count}

    cmd_registry.register("test.count", counter_handler)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    try:
        for i in range(3):
            client = IPCClient(socket_path, timeout=5.0)
            response = await client.send("test.count")
            assert response["status"] == "ok"
            assert response["result"]["count"] == i + 1
    finally:
        await server.stop()


# ── #1159: IPCServer.stop 3-phase 분리 (lifecycle race window 차단) ──


@pytest.mark.asyncio
async def test_stop_accepting_keeps_socket_file(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """stop_accepting()은 listener만 close하고 소켓 파일은 그대로 둔다.

    cold-path guard(`PID alive AND socket exists`)가 shutdown 동안에도
    'active runtime'으로 판정하도록, 소켓 파일은 BotManager/DB가
    완전히 종료될 때까지 유지되어야 한다 (Refs #1159).
    """
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    assert Path(socket_path).exists()

    await server.stop_accepting()

    # 소켓 파일은 유지 (cold-path guard가 active로 판정해야 함)
    assert Path(socket_path).exists()
    # 새 연결은 더 이상 받지 않음
    assert server._server is None

    # 정리 — 후속 단계 호출 호환 검증도 겸함
    await server.drain_connections(timeout=0.1)
    server.unlink_socket()
    assert not Path(socket_path).exists()


@pytest.mark.asyncio
async def test_stop_accepting_does_not_block_on_active_connection(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """active 연결이 있어도 stop_accepting()은 hang하지 않는다.

    wait_closed를 호출하지 않아야 한다.
    `_handle_connection`이 `while True` 루프이므로 `wait_closed`를
    호출하면 TCP/UDS detach된 연결까지 모두 기다리며 영원히 hang될 수
    있다. stop_accepting은 listener close만 수행하고, drain은 별도
    `drain_connections(timeout)`로 수행한다 (Refs #1159 Codex Plan v1 [high]).
    """
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    # 클라이언트 연결만 열고 요청은 보내지 않음 — 서버 측 _handle_connection이
    # 첫 decode에서 대기 상태로 머문다 (active 연결).
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        # 1초 안에 stop_accepting이 완료되어야 한다 — wait_closed 미사용 검증.
        await asyncio.wait_for(server.stop_accepting(), timeout=1.0)
        assert server._server is None
        # active 연결은 socket 닫기 전까지 살아 있어도 OK — 소켓 파일도 유지.
        assert Path(socket_path).exists()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        # 후속 정리 (남은 연결 drain + socket 제거)
        await server.drain_connections(timeout=0.5)
        server.unlink_socket()


@pytest.mark.asyncio
async def test_drain_connections_with_timeout(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """drain_connections는 timeout 안에 active 연결이 닫히지 않으면 경고 후 통과한다.

    asyncio.TimeoutError를 raise하지 않고 삼키며, lifecycle은 계속 진행된다.
    """
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    # 클라이언트 연결을 잡아 둠 (요청 미전송)
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        await server.stop_accepting()
        # 짧은 timeout으로 drain — TimeoutError가 외부로 전파되면 안 된다.
        await server.drain_connections(timeout=0.2)
        # 호출 자체가 정상 종료됐다는 사실을 검증
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        server.unlink_socket()


@pytest.mark.asyncio
async def test_unlink_socket_removes_file(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """unlink_socket()은 소켓 파일을 제거한다."""
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    assert Path(socket_path).exists()

    await server.stop_accepting()
    assert Path(socket_path).exists()  # stop_accepting 후에도 유지

    server.unlink_socket()
    assert not Path(socket_path).exists()


@pytest.mark.asyncio
async def test_stop_facade_runs_all_three_phases(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """기존 stop() 호출자 호환 facade — listener close → drain → unlink."""
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    assert Path(socket_path).exists()

    # 호출 추적 wrapper로 3단계가 모두 실행되는지 검증
    calls: list[str] = []
    original_stop_accepting = server.stop_accepting
    original_drain = server.drain_connections
    original_unlink = server.unlink_socket

    async def tracked_stop_accepting() -> None:
        calls.append("stop_accepting")
        await original_stop_accepting()

    async def tracked_drain(timeout: float = 5.0) -> None:
        calls.append("drain_connections")
        await original_drain(timeout)

    def tracked_unlink() -> None:
        calls.append("unlink_socket")
        original_unlink()

    server.stop_accepting = tracked_stop_accepting  # type: ignore[method-assign]
    server.drain_connections = tracked_drain  # type: ignore[method-assign]
    server.unlink_socket = tracked_unlink  # type: ignore[method-assign]

    await server.stop()

    assert calls == ["stop_accepting", "drain_connections", "unlink_socket"]
    assert not Path(socket_path).exists()
