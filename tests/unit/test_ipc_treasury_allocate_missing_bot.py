"""``treasury.allocate``/``treasury.deallocate`` IPC missing-bot 회귀 (#1792).

oracle A7 probe ``cli_treasury_allocate_missing_bot_error_code_contract`` /
``cli_treasury_deallocate_missing_bot_error_code_contract`` 가 발견한
회귀 모델: 두 표면이 missing bot id 로 호출되어도 ``Treasury.allocate``/
``deallocate`` 가 cash 만 검증하고 bot 존재 여부를 검사하지 않아 exit 0
+ status="ok" 가 반환되어 budget automation 이 nonexistent bot 에 예산을
할당/회수할 수 있었다.

#1792 fix: IPC handler ``_handle_treasury_allocate``/``_handle_treasury_deallocate``
(src/ante/ipc/registry.py:348/372) 에 ``bot.start``/``bot.stop``/``bot.status``/
``bot.update`` (registry.py:212/256/297/326) 와 동형의 ``svc.bot_manager.get_bot``
+ ``BotNotFoundError`` (code="BOT_NOT_FOUND") 가드를 ``Treasury`` 호출 이전에
배치한다.

검증축:

1. missing bot id → ``error.code == "BOT_NOT_FOUND"`` envelope
2. account_id 검증과 bot 존재 검증이 모두 통과한 경우만 ``treasury_manager.get``
   + ``Treasury.allocate``/``deallocate`` 도달 (회귀 0)
3. ``Treasury`` 서비스 자체는 단일 책임 유지 — bot 검증을 service 가 아닌
   handler 가 수행
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.client import IPCClient
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer


def _make_service_registry(*, bot_present: bool) -> ServiceRegistry:
    """missing-bot vs present-bot 양 분기를 시뮬레이션할 mock ServiceRegistry."""
    bot_manager = MagicMock()
    if bot_present:
        present_bot = MagicMock()
        # #2128: account-scoping 가드(``bot.config.account_id`` vs 요청
        # ``account_id``)가 추가되어 present-bot 분기는 요청 payload 의
        # ``account_id="domestic"`` 과 일치하는 config 를 가져야 #1792 정상
        # 경로 회귀가 유지된다. mismatch 검증 자체는 #2128 전용 테스트
        # (tests/unit/ipc/test_treasury_account_scoping.py)가 담당한다.
        present_bot.config = MagicMock()
        present_bot.config.account_id = "domestic"
        bot_manager.get_bot = MagicMock(return_value=present_bot)
    else:
        bot_manager.get_bot = MagicMock(return_value=None)

    treasury = MagicMock()
    treasury.allocate = AsyncMock(return_value=True)
    treasury.deallocate = AsyncMock(return_value=True)
    treasury_manager = MagicMock()
    treasury_manager.get = MagicMock(return_value=treasury)

    return ServiceRegistry(
        account=MagicMock(),
        bot_manager=bot_manager,
        treasury_manager=treasury_manager,
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
    )


@pytest.fixture
def socket_path() -> str:
    td = tempfile.mkdtemp(prefix="ipc_1792_", dir="/tmp")
    return str(Path(td) / "t.sock")


# ── 축 1: missing bot → BOT_NOT_FOUND envelope ───────────────────────────


@pytest.mark.asyncio
async def test_treasury_allocate_missing_bot_returns_bot_not_found(
    socket_path: str,
) -> None:
    """``treasury.allocate`` missing bot id → ``BOT_NOT_FOUND`` envelope (#1792)."""
    svc = _make_service_registry(bot_present=False)
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send(
            "treasury.allocate",
            {
                "account_id": "domestic",
                "bot_id": "oracle-missing-bot",
                "amount": 1000.0,
            },
            actor="tester",
        )
        assert response["status"] == "error", response
        assert response["error"]["code"] == "BOT_NOT_FOUND", response
        # 회귀 핵심: status=ok success envelope 반환 금지.
        assert response["status"] != "ok", response
        # 회귀 핵심: missing bot 검증이 ``Treasury.allocate`` 도달을 차단.
        svc.treasury_manager.get.return_value.allocate.assert_not_called()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_treasury_deallocate_missing_bot_returns_bot_not_found(
    socket_path: str,
) -> None:
    """``treasury.deallocate`` missing bot id → ``BOT_NOT_FOUND`` envelope (#1792)."""
    svc = _make_service_registry(bot_present=False)
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send(
            "treasury.deallocate",
            {
                "account_id": "domestic",
                "bot_id": "oracle-missing-bot",
                "amount": 1000.0,
            },
            actor="tester",
        )
        assert response["status"] == "error", response
        assert response["error"]["code"] == "BOT_NOT_FOUND", response
        assert response["status"] != "ok", response
        svc.treasury_manager.get.return_value.deallocate.assert_not_called()
    finally:
        await server.stop()


# ── 축 2: present bot → 정상 통과 (회귀 0) ───────────────────────────────


@pytest.mark.asyncio
async def test_treasury_allocate_present_bot_reaches_service(
    socket_path: str,
) -> None:
    """존재하는 bot id 는 가드를 통과해 ``Treasury.allocate`` 에 도달 (회귀 0)."""
    svc = _make_service_registry(bot_present=True)
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send(
            "treasury.allocate",
            {"account_id": "domestic", "bot_id": "bot-1", "amount": 1000.0},
            actor="tester",
        )
        assert response["status"] == "ok", response
        svc.treasury_manager.get.assert_called_once_with("domestic")
        svc.treasury_manager.get.return_value.allocate.assert_awaited_once_with(
            "bot-1", 1000.0
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_treasury_deallocate_present_bot_reaches_service(
    socket_path: str,
) -> None:
    """존재하는 bot id 는 가드를 통과해 ``Treasury.deallocate`` 에 도달."""
    svc = _make_service_registry(bot_present=True)
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send(
            "treasury.deallocate",
            {"account_id": "domestic", "bot_id": "bot-1", "amount": 1000.0},
            actor="tester",
        )
        assert response["status"] == "ok", response
        svc.treasury_manager.get.return_value.deallocate.assert_awaited_once_with(
            "bot-1", 1000.0
        )
    finally:
        await server.stop()


# ── 축 3: account_id 검증 vs bot 검증 우선순위 ──────────────────────────


@pytest.mark.asyncio
async def test_treasury_allocate_invalid_account_precedes_bot_check(
    socket_path: str,
) -> None:
    """invalid account_id 는 ``BOT_NOT_FOUND`` 보다 먼저 ``VALIDATION_ERROR``.

    handler 첫 문장의 ``require_account_id`` (#1656) 가 bot 가드보다 앞에 있어
    invalid account_id 입력 시 bot 존재 검증에 도달하지 않는다.
    """
    svc = _make_service_registry(bot_present=False)
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send(
            "treasury.allocate",
            {"account_id": "default", "bot_id": "oracle-missing-bot", "amount": 1000.0},
            actor="tester",
        )
        assert response["status"] == "error", response
        assert response["error"]["code"] == "VALIDATION_ERROR", response
        # account 검증이 먼저이므로 bot_manager.get_bot 미호출.
        svc.bot_manager.get_bot.assert_not_called()
    finally:
        await server.stop()
