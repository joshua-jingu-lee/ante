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
from ante.ipc.server import IPCServer, IPCServerState


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


def _capture_server_side_transports(
    underlying: asyncio.AbstractServer,
) -> list:
    """``underlying`` asyncio.Server 의 accepted-connection transport 목록 캡처.

    Refs #2304: ``asyncio.Server._clients`` 는 ``connection_made`` 시점에 등록되는
    server-side accepted transport 의 set 이다. active 연결을 일부러 열어 둔
    테스트(``stop_accepting``/``drain_connections`` 부분 경로만 호출)에서는
    server-side ``_handle_connection`` 의 transport 가 같은 테스트 경계 안에서
    결정적으로 닫히지 않는다. 이 transport 가 ``_sock`` LIVE + ``_server`` SET
    상태로 GC 되면 ``_SelectorTransport.__del__`` → ``Server._detach`` →
    ``Server._wakeup`` 에서 ``self._waiters`` 가 이미 ``None`` (앞선 ``wait_closed``
    완료로 소진) 이라 ``for waiter in waiters: TypeError: 'NoneType' object is not
    iterable`` 가 unraisable 로 새고, 후속 sync 테스트의 ``asyncio.run`` cleanup
    에서 ``RuntimeError: Event loop is closed`` 로 표출돼 원래 에러를 마스킹한다.

    이를 차단하기 위해 transport reference 를 ``stop_accepting`` (= ``_server`` 를
    ``None`` 으로 비움) **전에** 캡처해 두고, fixture 종료 시
    ``_settle_server_side_transports`` 로 명시 close 한다. 단일 underlying private
    attribute (``_clients``) 만 읽으며, production IPCServer 동작은 변경하지
    않는다 (테스트 격리 전용).
    """
    clients = getattr(underlying, "_clients", None)
    return list(clients) if clients else []


async def _settle_server_side_transports(
    transports: list, *, max_iters: int = 50
) -> None:
    """캡처된 server-side transport 들을 명시적으로 close 하고 teardown 을 정착.

    Refs #2304: 각 transport 에 ``close()`` 를 호출하면 ``_call_connection_lost``
    가 ``loop.call_soon`` 으로 스케줄된다. ``_call_connection_lost`` 는 ``_sock``/
    ``_server`` 를 정리하고 ``server._detach`` 를 (``_waiters`` 가 아직 일관된
    상태에서) **단 한 번** 호출하므로, 이후 GC 시 ``__del__`` 이
    ``_sock is None`` 가드에 걸려 안전하게 무시된다. 콜백이 실제 실행될 때까지
    ``asyncio.sleep(0)`` 으로 양보한다.
    """
    for transport in transports:
        transport.close()
    for _ in range(max_iters):
        if all(getattr(t, "_sock", None) is None for t in transports):
            return
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_roundtrip(socket_path: str, service_registry: ServiceRegistry) -> None:
    """요청 -> 응답 라운드트립."""
    cmd_registry = CommandRegistry()

    async def echo_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"echo": args, "actor": actor}

    cmd_registry.register("test.echo", echo_handler, is_mutating=False)

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

    cmd_registry.register("test.fail", failing_handler, is_mutating=True)

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

    cmd_registry.register("test.count", counter_handler, is_mutating=False)

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
async def test_lifecycle_state_transitions(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """IPCServer lifecycle state는 start/stop 3-phase와 동기화된다."""
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)

    assert server.state is IPCServerState.STOPPED

    await server.start()
    assert server.state is IPCServerState.RUNNING

    await server.stop_accepting()
    assert server.state is IPCServerState.SHUTTING_DOWN

    await server.drain_connections(timeout=0.1)
    assert server.state is IPCServerState.SHUTTING_DOWN

    server.stop_dispatching()
    assert server.state is IPCServerState.DRAINING

    server.unlink_socket()
    assert server.state is IPCServerState.STOPPED


@pytest.mark.asyncio
async def test_stop_facade_ends_in_stopped_state(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """stop() facade도 최종 STOPPED 상태로 끝난다."""
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    await server.stop()

    assert server.state is IPCServerState.STOPPED
    assert not Path(socket_path).exists()


@pytest.mark.asyncio
async def test_dispatch_rejects_mutating_only_while_shutting_down(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """SHUTTING_DOWN에서는 mutating만 503으로 거부하고 read-only는 통과한다."""
    cmd_registry = CommandRegistry()

    async def mutating_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"mutated": True}

    async def read_only_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"read": True}

    cmd_registry.register("test.mutate", mutating_handler, is_mutating=True)
    cmd_registry.register("test.read", read_only_handler, is_mutating=False)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        mutating_running = await server._dispatch(
            {"id": "m1", "command": "test.mutate", "args": {}, "actor": "tester"}
        )
        read_running = await server._dispatch(
            {"id": "r1", "command": "test.read", "args": {}, "actor": "tester"}
        )

        assert mutating_running["status"] == "ok"
        assert read_running["status"] == "ok"

        await server.stop_accepting()

        mutating_stopping = await server._dispatch(
            {"id": "m2", "command": "test.mutate", "args": {}, "actor": "tester"}
        )
        read_stopping = await server._dispatch(
            {"id": "r2", "command": "test.read", "args": {}, "actor": "tester"}
        )

        assert mutating_stopping["status"] == "error"
        assert mutating_stopping["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "종료 중" in mutating_stopping["error"]["message"]
        assert read_stopping["status"] == "ok"
        assert read_stopping["result"] == {"read": True}
    finally:
        await server.drain_connections(timeout=0.1)
        if Path(socket_path).exists():
            server.unlink_socket()


@pytest.mark.asyncio
async def test_dispatch_rejects_everything_when_stopped(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """STOPPED에서는 read-only 포함 모든 dispatch를 503으로 거부한다."""
    cmd_registry = CommandRegistry()

    async def mutating_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"mutated": True}

    async def read_only_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"read": True}

    cmd_registry.register("test.mutate", mutating_handler, is_mutating=True)
    cmd_registry.register("test.read", read_only_handler, is_mutating=False)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    await server.stop_accepting()
    server.stop_dispatching()
    await server.drain_connections(timeout=0.1)
    server.unlink_socket()

    mutating_response = await server._dispatch(
        {"id": "m1", "command": "test.mutate", "args": {}, "actor": "tester"}
    )
    read_response = await server._dispatch(
        {"id": "r1", "command": "test.read", "args": {}, "actor": "tester"}
    )

    for response in (mutating_response, read_response):
        assert response["status"] == "error"
        assert response["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "종료되었습니다" in response["error"]["message"]


@pytest.mark.asyncio
async def test_dispatch_rejects_everything_while_draining(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """DRAINING에서는 read-only 포함 모든 dispatch를 503으로 거부한다."""
    cmd_registry = CommandRegistry()

    async def read_only_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"read": True}

    cmd_registry.register("test.read", read_only_handler, is_mutating=False)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        await server.stop_accepting()
        server.stop_dispatching()

        response = await server._dispatch(
            {"id": "r1", "command": "test.read", "args": {}, "actor": "tester"}
        )

        assert response["status"] == "error"
        assert response["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "리소스 종료 중" in response["error"]["message"]
    finally:
        await server.drain_connections(timeout=0.1)
        if Path(socket_path).exists():
            server.unlink_socket()


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
    # Refs #2304: stop_accepting() 이 ``server._server`` 를 None 으로 비우기
    # 전에 underlying asyncio.Server 를 잡아, accepted 된 server-side transport
    # 를 캡처한다. ``connection_made`` 가 ``_clients`` 에 등록될 시간을 yield 로
    # 보장한 뒤 캡처한다.
    underlying = server._server
    assert underlying is not None
    server_side_transports: list = []
    for _ in range(50):
        server_side_transports = _capture_server_side_transports(underlying)
        if server_side_transports:
            break
        await asyncio.sleep(0)
    # Refs #2304 (Codex 브랜치 리뷰 attempt 1): 캡처가 비어 있으면 fixture
    # 종료 시 ``_settle_server_side_transports`` 가 no-op 이 되어 누수 차단을
    # 검증하지 못한다(회귀 시 silent pass). active 연결이 결정적으로
    # ``asyncio.Server._clients`` 에 등록돼 server-side transport 가 캡처됐음을
    # 단언해, (a) cleanup 이 실제로 수행됨을 보장하고 (b) 향후 캡처 로직이
    # 깨지면(빈 결과) 이 테스트가 FAIL 해 회귀를 잡는다.
    assert server_side_transports, (
        "server-side accepted transport 캡처가 비어 있다 — active 연결이 "
        "asyncio.Server._clients 에 등록되지 않아 teardown cleanup 이 "
        "no-op 이 된다 (Refs #2304)."
    )
    try:
        # 1초 안에 stop_accepting이 완료되어야 한다 — wait_closed 미사용 검증.
        await asyncio.wait_for(server.stop_accepting(), timeout=1.0)
        assert server._server is None
        # active 연결은 socket 닫기 전까지 살아 있어도 OK — 소켓 파일도 유지.
        assert Path(socket_path).exists()
    finally:
        # Refs #1897: ``Server._wakeup`` 의 ``_waiters = None`` race 회피
        # (자세한 설명은 ``test_drain_connections_with_timeout`` 참고). client
        # 를 먼저 닫고 server _handle_connection 이 detach 를 완료할 시간을
        # 양보한 뒤 drain.
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        for _ in range(20):
            await asyncio.sleep(0)
        # 후속 정리 (남은 연결 drain + socket 제거).
        await server.drain_connections(timeout=0.5)
        # Refs #2304: 캡처한 server-side transport 를 명시 close 해 teardown 을
        # 같은 테스트 경계 안에서 정착 — LIVE transport 가 닫힌 loop 에 바인딩된
        # 채 후속(특히 sync) 테스트로 전이되어 ``__del__`` 에서 unraisable 로
        # 새는 것을 차단한다.
        await _settle_server_side_transports(server_side_transports)
        server.unlink_socket()


@pytest.mark.asyncio
async def test_drain_connections_with_timeout(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """drain_connections는 timeout 안에 active 연결이 닫히지 않으면 경고 후 통과한다.

    asyncio.TimeoutError를 raise하지 않고 삼키며, lifecycle은 계속 진행된다.

    Refs #1897: 종료 순서는 ``client writer 먼저 close → 서버 _handle_connection
    의 finally 가 transport 를 정리할 시간 확보 → server cleanup``. 이래야
    ``_SelectorTransport.__del__`` race(`self._server._detach(self)` 호출 시점에
    이미 ``_server.close()`` 후 attribute 들이 비어 ``'NoneType' object is not
    iterable``) 가 unraisable warning 으로 새지 않는다.
    """
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()

    # 클라이언트 연결을 잡아 둠 (요청 미전송)
    reader, writer = await asyncio.open_unix_connection(socket_path)
    # Refs #2304: stop_accepting() 전에 underlying asyncio.Server 를 잡아
    # server-side accepted transport 를 캡처한다 (등록 시간 yield 보장).
    underlying = server._server
    assert underlying is not None
    server_side_transports: list = []
    for _ in range(50):
        server_side_transports = _capture_server_side_transports(underlying)
        if server_side_transports:
            break
        await asyncio.sleep(0)
    # Refs #2304 (Codex 브랜치 리뷰 attempt 1): 캡처가 비어 있으면 fixture
    # 종료 시 ``_settle_server_side_transports`` 가 no-op 이 되어 drain timeout
    # 경로의 누수 차단을 검증하지 못한다(회귀 시 silent pass). server-side
    # transport 가 결정적으로 캡처됐음을 단언해 cleanup 수행을 보장하고, 캡처
    # 로직이 깨지면 이 테스트가 FAIL 하도록 한다.
    assert server_side_transports, (
        "server-side accepted transport 캡처가 비어 있다 — active 연결이 "
        "asyncio.Server._clients 에 등록되지 않아 teardown cleanup 이 "
        "no-op 이 된다 (Refs #2304)."
    )
    try:
        await server.stop_accepting()
        # 짧은 timeout으로 drain — TimeoutError가 외부로 전파되면 안 된다.
        await server.drain_connections(timeout=0.2)
        # 호출 자체가 정상 종료됐다는 사실을 검증
    finally:
        # Refs #1897: 누수 cleanup — production drain 이 timeout 으로 끝났을
        # 경우에도, fixture 종료 시점에는 server-side transport 까지 결정적으로
        # 닫혀야 한다. client 측 writer 를 먼저 닫고 server-side
        # _handle_connection 의 finally 가 transport detach 를 완료할 시간을
        # 양보한다.
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        for _ in range(20):
            await asyncio.sleep(0)
        # Refs #2304: drain 이 timeout 으로 끝나 server-side transport 가
        # ``_sock`` LIVE 로 남는 경로에서도, 캡처한 transport 를 명시 close 해
        # ``_call_connection_lost`` 를 같은 loop 에서 실행시켜 teardown 을
        # 정착한다. ``_SelectorTransport.__del__`` → ``Server._wakeup``
        # (``_waiters=None``) 재진입으로 unraisable 이 새는 것을 차단한다.
        await _settle_server_side_transports(server_side_transports)
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
async def test_stop_facade_runs_all_phases(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """기존 stop() 호출자 호환 facade — listener close → reject → drain → unlink."""
    cmd_registry = CommandRegistry()
    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    assert Path(socket_path).exists()

    # 호출 추적 wrapper로 3단계가 모두 실행되는지 검증
    calls: list[str] = []
    original_stop_accepting = server.stop_accepting
    original_stop_dispatching = server.stop_dispatching
    original_drain = server.drain_connections
    original_unlink = server.unlink_socket

    async def tracked_stop_accepting() -> None:
        calls.append("stop_accepting")
        await original_stop_accepting()

    async def tracked_drain(timeout: float = 5.0) -> None:
        calls.append("drain_connections")
        await original_drain(timeout)

    def tracked_stop_dispatching() -> None:
        calls.append("stop_dispatching")
        original_stop_dispatching()

    def tracked_unlink() -> None:
        calls.append("unlink_socket")
        original_unlink()

    server.stop_accepting = tracked_stop_accepting  # type: ignore[method-assign]
    server.stop_dispatching = tracked_stop_dispatching  # type: ignore[method-assign]
    server.drain_connections = tracked_drain  # type: ignore[method-assign]
    server.unlink_socket = tracked_unlink  # type: ignore[method-assign]

    await server.stop()

    assert calls == [
        "stop_accepting",
        "stop_dispatching",
        "drain_connections",
        "unlink_socket",
    ]
    assert not Path(socket_path).exists()
