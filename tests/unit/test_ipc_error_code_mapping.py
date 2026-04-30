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

    cmd_registry.register("test.cold_path", cold_path_handler)

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

    cmd_registry.register("test.fail", value_error_handler)

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

    cmd_registry.register("test.already_suspended", already_suspended_handler)

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
