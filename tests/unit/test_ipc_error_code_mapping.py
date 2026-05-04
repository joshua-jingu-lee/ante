"""IPCServer가 예외의 ``code`` 속성을 안정 코드로 노출하는지 검증한다 (#1144 S5).

기존 ``account.delete`` IPC handler는 #1139에서 제거되어 직접 회귀 테스트가
불가능하므로, server-level 매핑 동작을 generic dummy handler로 검증한다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ante.account.errors import AccountStructuralChangeRequiresStoppedServerError
from ante.core.registry import ServiceRegistry
from ante.ipc.client import IPCClient
from ante.ipc.registry import CommandRegistry
from ante.ipc.server import IPCServer


def _make_service_registry() -> ServiceRegistry:
    """테스트용 ServiceRegistry — 모든 서비스 mock."""
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
    """Unix 소켓 경로(길이 제한 104바이트 → /tmp 직접 사용)."""
    td = tempfile.mkdtemp(prefix="ipc_code", dir="/tmp")
    return str(Path(td) / "t.sock")


@pytest.fixture
def service_registry() -> ServiceRegistry:
    return _make_service_registry()


# ── S5: 예외 자체의 code 속성 검증 ────────────────────


def test_account_structural_change_error_carries_stable_code() -> None:
    """``AccountStructuralChangeRequiresStoppedServerError`` 인스턴스의 ``code``
    클래스 속성이 안정 코드를 노출한다 (#1144 S5).

    IPCServer가 ``getattr(e, "code", "EXECUTION_ERROR")``로 읽기 위한 사전 조건.
    """
    exc = AccountStructuralChangeRequiresStoppedServerError("test")
    assert exc.code == "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"
    # 클래스 레벨 속성으로 직접 접근도 가능
    assert (
        AccountStructuralChangeRequiresStoppedServerError.code
        == "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"
    )


# ── IPC server-level 매핑 ────────────────────────────


@pytest.mark.asyncio
async def test_ipc_server_uses_exception_code_attribute_when_present(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """핸들러가 ``code`` 속성을 가진 예외를 raise하면 응답 ``error.code``가 그 값."""
    cmd_registry = CommandRegistry()

    async def cold_path_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        raise AccountStructuralChangeRequiresStoppedServerError(
            "테스트: 런타임 cold-path 차단"
        )

    cmd_registry.register("test.cold_path", cold_path_handler, is_mutating=True)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send("test.cold_path", {}, actor="tester")
        assert response["status"] == "error"
        assert (
            response["error"]["code"]
            == "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"
        )
        assert "런타임 cold-path 차단" in response["error"]["message"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ipc_server_falls_back_to_execution_error_when_no_code(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """``code`` 속성이 없는 예외는 ``EXECUTION_ERROR``로 폴백된다 (회귀 보호)."""
    cmd_registry = CommandRegistry()

    async def value_error_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        raise ValueError("no code attribute")

    cmd_registry.register("test.fail", value_error_handler, is_mutating=True)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send("test.fail", {})
        assert response["status"] == "error"
        assert response["error"]["code"] == "EXECUTION_ERROR"
        assert "no code attribute" in response["error"]["message"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ipc_server_falls_back_for_account_error_without_code(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """기존 AccountError 계층(``AccountAlreadySuspendedError`` 등)은 ``code`` 속성이
    없으므로 ``EXECUTION_ERROR``로 폴백 — ``account.suspend`` 등 IPC 핸들러
    응답 코드가 변경되지 않음을 보장 (회귀 보호).
    """
    from ante.account.errors import AccountAlreadySuspendedError

    cmd_registry = CommandRegistry()

    async def already_suspended_handler(svc, args, actor):
        raise AccountAlreadySuspendedError("이미 정지됨")

    cmd_registry.register(
        "test.already_suspended",
        already_suspended_handler,
        is_mutating=True,
    )

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send("test.already_suspended", {})
        assert response["status"] == "error"
        # 기존 동작 그대로
        assert response["error"]["code"] == "EXECUTION_ERROR"
        assert "이미 정지됨" in response["error"]["message"]
    finally:
        await server.stop()


# ── #1241 SPLIT-2 attempt 2: InvalidAccountIdError → VALIDATION_ERROR ──


def test_invalid_account_id_error_carries_validation_error_code() -> None:
    """``InvalidAccountIdError`` 인스턴스의 ``code`` 클래스 속성이
    ``"VALIDATION_ERROR"``를 노출한다.

    IPCServer가 ``getattr(e, "code", "EXECUTION_ERROR")`` 폴백으로 읽어
    ``VALIDATION_ERROR`` 응답을 만들기 위한 사전 조건. ``require_account_id``
    가 이 예외를 raise하는 모든 IPC 경로(bot.create, broker.* 등)는 자동으로
    ``VALIDATION_ERROR``로 매핑된다.
    """
    from ante.account.errors import InvalidAccountIdError

    exc = InvalidAccountIdError("test")
    assert exc.code == "VALIDATION_ERROR"
    # 클래스 레벨 속성으로 직접 접근도 가능
    assert InvalidAccountIdError.code == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_ipc_dispatch_bot_create_account_scoped_returns_validation_error_code(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """``bot.create`` IPC dispatch 경로에서 ``account_id`` 누락/빈 문자열은
    ``InvalidAccountIdError`` 로 raise되고, IPC server가 ``getattr(e, "code", ...)``
    폴백을 통해 응답 ``error.code == "VALIDATION_ERROR"`` 로 노출한다.

    Codex branch review (#1241 SPLIT-2 attempt 1) 회귀 가드:
    이전에는 ``InvalidAccountIdError`` 에 ``code`` 속성이 없어 응답이
    ``EXECUTION_ERROR`` 로 잘못 노출되었다. ``_handle_bot_create`` 단위 테스트가
    예외 raise 자체는 잡았지만 IPC dispatch 매핑 회귀는 잡지 못했다.

    실제 ``register_all_handlers`` 등록 경로를 사용해 `bot.create`가 mutating
    으로 등록되는지, dispatch가 fallback 코드 매핑을 거치는지 함께 검증한다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)

        # Case 1: account_id 누락 → VALIDATION_ERROR
        # strategy_registry.get은 None을 반환해 require_account_id 도달 전에
        # ValueError가 raise되므로, strategy_registry를 명시 mock한다.
        from dataclasses import dataclass
        from unittest.mock import AsyncMock

        @dataclass
        class FakeRecord:
            filepath: str = "/tmp/strategy.py"

        # strategy_registry.get은 dispatch 시점에 호출되므로 fixture mock 위에
        # 명시적으로 AsyncMock을 덮어쓴다. StrategyLoader.load는 dispatch 시
        # 호출되지만, account_id 검증이 그 다음 줄에서 실행되므로 monkeypatch가
        # 없어도 InvalidAccountIdError가 먼저 raise된다... 실제로는 load가 먼저
        # 호출되어 파일 경로 IO 실패가 발생할 수 있어 patch가 필요하다.
        import ante.strategy.loader

        fake_strategy_registry = AsyncMock()
        fake_strategy_registry.get.return_value = FakeRecord()
        service_registry.strategy_registry = fake_strategy_registry  # type: ignore[misc]

        original_load = ante.strategy.loader.StrategyLoader.load
        ante.strategy.loader.StrategyLoader.load = lambda _path: type(  # type: ignore[assignment]
            "FakeStrategy", (), {}
        )
        try:
            response = await client.send(
                "bot.create",
                {"strategy_id": "strat-1"},
                actor="tester",
            )
            assert response["status"] == "error"
            assert response["error"]["code"] == "VALIDATION_ERROR"
            assert "ipc.bot.create" in response["error"]["message"]

            # Case 2: 빈 문자열 account_id → VALIDATION_ERROR
            response = await client.send(
                "bot.create",
                {"strategy_id": "strat-1", "account_id": ""},
                actor="tester",
            )
            assert response["status"] == "error"
            assert response["error"]["code"] == "VALIDATION_ERROR"
        finally:
            ante.strategy.loader.StrategyLoader.load = original_load
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ipc_dispatch_broker_status_account_scoped_returns_validation_error_code(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """다른 account-scoped IPC 핸들러(``broker.status``, read-only)도 같은
    ``VALIDATION_ERROR`` 매핑이 동작하는지 검증.

    ``bot.create`` 외의 모든 ``require_account_id`` 호출 경로가 ``code`` 속성
    추가로 자동 정렬되었는지 회귀 가드. ``treasury.allocate``는
    ``require_account_id`` 를 호출하지 않으므로 (KeyError 직접 raise) 본 회귀
    보호 대상이 아니다 — read-only side에서 동등한 매핑이 작동하는지를
    ``broker.status`` 로 대신 검증한다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)

        # account_id 누락 → VALIDATION_ERROR
        response = await client.send("broker.status", {}, actor="tester")
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR"
        assert "ipc.broker.status" in response["error"]["message"]

        # 'default' 예약어 → VALIDATION_ERROR
        response = await client.send(
            "broker.status",
            {"account_id": "default"},
            actor="tester",
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR"
    finally:
        await server.stop()
