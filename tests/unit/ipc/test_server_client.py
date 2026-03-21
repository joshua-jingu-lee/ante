"""IPCServer + IPCClient 통합 테스트."""

from __future__ import annotations

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
