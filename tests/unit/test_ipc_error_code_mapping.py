"""IPCServer가 예외의 ``code`` 속성을 안정 코드로 노출하는지 검증한다 (#1144 S5).

기존 ``account.delete`` IPC handler는 #1139에서 제거되어 직접 회귀 테스트가
불가능하므로, server-level 매핑 동작을 generic dummy handler로 검증한다.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ante.account.errors import AccountStructuralChangeRequiresStoppedServerError
from ante.broker.exceptions import (
    APIError,
    AuthenticationError,
    TokenRateLimitError,
)
from ante.core.registry import ServiceRegistry
from ante.ipc.client import IPCClient
from ante.ipc.registry import CommandRegistry
from ante.ipc.server import IPCServer
from tests.unit.ipc.request_fixtures import NoArgsRequest
from tests.unit.ipc.validation_messages import validation_message


def _make_service_registry() -> ServiceRegistry:
    """테스트용 ServiceRegistry — 모든 서비스 mock.

    Refs #1850: dispatch wrapper 가 ``required_services`` preflight 를
    수행하므로 ``register_all_handlers`` 가 선언한 의존 service 가
    ``None`` 이면 ``SERVICE_NOT_CONFIGURED`` 로 차단된다. 본 fixture 는
    production-like 한 service set 을 갖춰 handler 실행 경로까지 도달
    가능하도록 ``strategy_registry`` / ``audit_logger`` 도 명시 주입한다.
    """
    return ServiceRegistry(
        account=MagicMock(),
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
        strategy_registry=MagicMock(),
        audit_logger=MagicMock(),
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

    cmd_registry.register(
        "test.cold_path",
        cold_path_handler,
        is_mutating=True,
        request_model=NoArgsRequest,
    )

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
@pytest.mark.parametrize(
    ("make_error", "stable_code"),
    [
        (
            lambda: APIError("잔고 부족", status_code=500, error_code="APBK0501"),
            "BROKER_API_ERROR",
        ),
        (
            lambda: AuthenticationError("인증 실패", error_code="EGW00121"),
            "BROKER_AUTH_FAILED",
        ),
        (
            lambda: TokenRateLimitError("발급 제한", error_code="EGW00133"),
            "BROKER_AUTH_FAILED",
        ),
    ],
    ids=["api_error", "auth_error", "token_rate_limit"],
)
async def test_ipc_envelope_code_is_stable_code_not_broker_raw_code(
    socket_path: str, service_registry: ServiceRegistry, make_error, stable_code
) -> None:
    """broker 예외가 원천 error_code 를 가져도 envelope code 는 안정 코드다."""
    cmd_registry = CommandRegistry()
    raised = make_error()

    async def broker_failure_handler(
        svc: ServiceRegistry, args: dict, actor: str
    ) -> dict:
        raise raised

    cmd_registry.register(
        "test.broker_fail",
        broker_failure_handler,
        is_mutating=True,
        request_model=NoArgsRequest,
    )

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send("test.broker_fail", {})
    finally:
        await server.stop()

    assert raised.error_code
    assert response["status"] == "error"
    assert response["error"]["code"] == stable_code
    assert raised.error_code not in json.dumps(response, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["bot.start", "bot.stop"])
async def test_ipc_bot_lifecycle_state_conflict_maps_to_bot_state_conflict(
    socket_path: str, service_registry: ServiceRegistry, command: str
) -> None:
    """start/stop 의 상태 충돌은 IPC envelope code BOT_STATE_CONFLICT 로 나간다."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ante.bot.exceptions import BotStateConflict
    from ante.ipc.registry import register_all_handlers

    bot = MagicMock()
    bot.config.account_id = "acc-test"
    service_registry.bot_manager.get_bot.return_value = bot
    service_registry.bot_manager.start_bot = AsyncMock(
        side_effect=BotStateConflict("이미 실행 중인 봇입니다")
    )
    service_registry.bot_manager.stop_bot = AsyncMock(
        side_effect=BotStateConflict("실행 중이 아닌 봇입니다")
    )
    service_registry.account.get = AsyncMock(
        return_value=SimpleNamespace(credentials={"app_key": "k"})
    )
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send(command, {"bot_id": "bot-1"}, actor="tester")
    finally:
        await server.stop()

    assert response["status"] == "error"
    assert response["error"]["code"] == "BOT_STATE_CONFLICT"


@pytest.mark.asyncio
async def test_ipc_server_falls_back_to_execution_error_when_no_code(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """``code`` 속성이 없는 예외는 ``EXECUTION_ERROR``로 폴백된다 (회귀 보호)."""
    cmd_registry = CommandRegistry()

    async def value_error_handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        raise ValueError("no code attribute")

    cmd_registry.register(
        "test.fail", value_error_handler, is_mutating=True, request_model=NoArgsRequest
    )

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
async def test_ipc_server_surfaces_typed_code_for_account_already_suspended(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """``AccountAlreadySuspendedError`` 는 typed ``code`` 속성을 보유하므로
    IPC envelope 이 ``"ACCOUNT_ALREADY_SUSPENDED"`` 안정 코드를 surface 한다
    (#1812 Group Q state-conflict typed code sweep).

    이전 (#1812 이전): ``code`` 속성 부재 → ``EXECUTION_ERROR`` 폴백. 본 테스트
    의 이전 단언은 회귀 보호용으로 폴백 동작을 lock 했으나, Group Q sweep 이
    state-conflict 표면에 typed code 를 도입하면서 envelope 코드가 정정되었다.
    typed code 회귀 (속성 누락 → ``EXECUTION_ERROR`` 폴백 재발) 차단 lock.
    """
    from ante.account.errors import AccountAlreadySuspendedError

    cmd_registry = CommandRegistry()

    async def already_suspended_handler(svc, args, actor):
        raise AccountAlreadySuspendedError("이미 정지됨")

    cmd_registry.register(
        "test.already_suspended",
        already_suspended_handler,
        is_mutating=True,
        request_model=NoArgsRequest,
    )

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)
        response = await client.send("test.already_suspended", {})
        assert response["status"] == "error"
        # #1812 Group Q: typed code 가 envelope 에 surface 된다
        # (이전 ``EXECUTION_ERROR`` 폴백을 typed 코드로 정정).
        assert response["error"]["code"] == "ACCOUNT_ALREADY_SUSPENDED"
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
    """``bot.create`` IPC dispatch 경로에서 invalid/missing ``account_id`` 는
    ``VALIDATION_ERROR`` 다(#1241 SPLIT-2 회귀 가드).

    #2683: 검사 자리는 요청 모델의 계좌 ID 필드다. 핸들러보다 먼저 거부되므로
    strategy_registry mock 없이도 strategy 처리 **이전**에 실패한다(#1656
    validate-first). 메시지는 ``ipc.md``의 「인자 검증 실패」 형식 전체다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)

        # validate-first: strategy_registry / StrategyLoader workaround 없이
        # (실제 strategy 존재 여부와 무관) invalid/missing account_id 면
        # strategy 처리 **이전**에 VALIDATION_ERROR.

        # Case 1: account_id 키 생략 → VALIDATION_ERROR (EXECUTION_ERROR 아님)
        response = await client.send(
            "bot.create",
            {"strategy_id": "strat-1"},
            actor="tester",
        )
        assert response["status"] == "error"
        assert response["error"] == {
            "code": "VALIDATION_ERROR",
            "message": validation_message("bot.create", ("account_id", "missing")),
        }

        # Case 2: 빈 문자열 account_id → VALIDATION_ERROR
        response = await client.send(
            "bot.create",
            {"strategy_id": "strat-1", "account_id": ""},
            actor="tester",
        )
        assert response["status"] == "error"
        assert response["error"] == {
            "code": "VALIDATION_ERROR",
            "message": validation_message(
                "bot.create", ("account_id", "invalid_account_id")
            ),
        }

        # Case 3: 'default' 예약어 → VALIDATION_ERROR
        response = await client.send(
            "bot.create",
            {"strategy_id": "strat-1", "account_id": "default"},
            actor="tester",
        )
        assert response["status"] == "error"
        assert response["error"] == {
            "code": "VALIDATION_ERROR",
            "message": validation_message(
                "bot.create", ("account_id", "invalid_account_id")
            ),
        }

        # Case 4: 패턴 위반 account_id → VALIDATION_ERROR
        response = await client.send(
            "bot.create",
            {"strategy_id": "strat-1", "account_id": "bad_id!"},
            actor="tester",
        )
        assert response["status"] == "error"
        assert response["error"] == {
            "code": "VALIDATION_ERROR",
            "message": validation_message(
                "bot.create", ("account_id", "invalid_account_id")
            ),
        }
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ipc_dispatch_bot_create_valid_account_missing_other_arg_not_validation(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """#1656 → #2683: **valid** account_id + 다른 필수 인자(strategy_id) 누락은
    요청 모델이 ``strategy_id(missing)`` 으로 거부한다(이전에는 핸들러의
    ``KeyError`` 가 ``EXECUTION_ERROR`` 였다). 계좌 ID는 통과했으므로 메시지에
    ``account_id`` 가 없다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)

        response = await client.send(
            "bot.create",
            {"account_id": "oracle-valid-account"},
            actor="tester",
        )
        assert response["status"] == "error"
        assert response["error"] == {
            "code": "VALIDATION_ERROR",
            "message": validation_message("bot.create", ("strategy_id", "missing")),
        }
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ipc_dispatch_treasury_allocate_invalid_account_validation_error(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """#1656 E bucket: ``treasury.allocate`` IPC dispatch에서 (a) invalid
    account_id 및 (b) account_id 키 생략 payload 둘 다 ``VALIDATION_ERROR``로
    매핑되는지 검증.

    회귀 모델:
        이전에는 ``_handle_treasury_allocate`` 가 ``account_id =
        args["account_id"]`` raw 인덱싱 후 ``svc.treasury_manager.get`` 으로
        흘려, invalid account_id 는 manager 오류로 / account_id 키 생략은
        ``KeyError`` 로 → server.py:323 ``getattr(e, "code",
        "EXECUTION_ERROR")`` → ``EXECUTION_ERROR`` 로 오분류되었다.
        #1656 이 ``require_account_id(args.get("account_id"), ...)`` 를 함수
        첫 문장으로 옮겨, invalid/missing 모두 ``InvalidAccountIdError``
        (code="VALIDATION_ERROR", #1633 SSOT)로 먼저 raise → VALIDATION_ERROR
        envelope이 되도록 한다. #1636 broker 1:1 동형.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)

        # (a) invalid account_id: 'default'/패턴위반/'' (bot_id/amount 동반)
        for invalid in ("default", "bad_id!", ""):
            response = await client.send(
                "treasury.allocate",
                {"account_id": invalid, "bot_id": "bot-1", "amount": 1000.0},
                actor="tester",
            )
            assert response["status"] == "error", response
            assert response["error"]["code"] == "VALIDATION_ERROR", response
            assert response["error"]["code"] != "EXECUTION_ERROR", response
            assert response["error"]["message"] == validation_message(
                "treasury.allocate", ("account_id", "invalid_account_id")
            ), response

        # (b) account_id 키 생략 → KeyError → EXECUTION_ERROR 회귀 차단
        response = await client.send(
            "treasury.allocate",
            {"bot_id": "bot-1", "amount": 1000.0},
            actor="tester",
        )
        assert response["status"] == "error", response
        assert response["error"]["code"] == "VALIDATION_ERROR", response
        assert response["error"]["code"] != "EXECUTION_ERROR", response
        assert response["error"]["message"] == validation_message(
            "treasury.allocate", ("account_id", "missing")
        ), response
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ipc_dispatch_treasury_deallocate_invalid_account_validation_error(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """#1656 E bucket: ``treasury.deallocate`` IPC dispatch에서 (a) invalid
    account_id 및 (b) account_id 키 생략 둘 다 ``VALIDATION_ERROR``.

    ``treasury.allocate`` 와 동형 — handler-first ``require_account_id``
    (``args.get`` + 첫 문장)로 invalid/missing 모두 VALIDATION_ERROR.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)

        # (a) invalid account_id
        for invalid in ("default", "bad_id!", ""):
            response = await client.send(
                "treasury.deallocate",
                {"account_id": invalid, "bot_id": "bot-1", "amount": 1000.0},
                actor="tester",
            )
            assert response["status"] == "error", response
            assert response["error"]["code"] == "VALIDATION_ERROR", response
            assert response["error"]["code"] != "EXECUTION_ERROR", response
            assert response["error"]["message"] == validation_message(
                "treasury.deallocate", ("account_id", "invalid_account_id")
            ), response

        # (b) account_id 키 생략 → KeyError → EXECUTION_ERROR 회귀 차단
        response = await client.send(
            "treasury.deallocate",
            {"bot_id": "bot-1", "amount": 1000.0},
            actor="tester",
        )
        assert response["status"] == "error", response
        assert response["error"]["code"] == "VALIDATION_ERROR", response
        assert response["error"]["code"] != "EXECUTION_ERROR", response
        assert response["error"]["message"] == validation_message(
            "treasury.deallocate", ("account_id", "missing")
        ), response
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ipc_dispatch_treasury_valid_account_missing_other_arg_not_validation(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """**valid** account_id + 다른 필수 인자(bot_id/amount) 누락은 요청 모델이
    서비스 호출 전에 ``VALIDATION_ERROR``(``missing``)로 거부한다(#2683 ⑥. 이전
    #1656 가드는 ``args["bot_id"]`` KeyError → EXECUTION_ERROR를 잠갔다).
    allocate/deallocate 양쪽 가드.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)

        for command in ("treasury.allocate", "treasury.deallocate"):
            response = await client.send(
                command,
                {"account_id": "oracle-valid-account"},
                actor="tester",
            )
            assert response["status"] == "error", response
            assert response["error"] == {
                "code": "VALIDATION_ERROR",
                "message": validation_message(
                    command, ("bot_id", "missing"), ("amount", "missing")
                ),
            }, response
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ipc_dispatch_broker_status_account_scoped_returns_validation_error_code(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """다른 account-scoped IPC 핸들러(``broker.status``, read-only)도 같은
    ``VALIDATION_ERROR`` 매핑이 동작하는지 검증.

    ``bot.create`` 외의 모든 ``require_account_id`` 호출 경로가 ``code`` 속성
    추가로 자동 정렬되었는지 회귀 가드. (#1656에서 ``treasury.allocate``/
    ``treasury.deallocate`` 도 handler-first ``require_account_id`` 로 정렬되어
    별도 테스트가 추가되었다 —
    ``test_ipc_dispatch_treasury_allocate_invalid_account_validation_error`` 등.)
    여기서는 read-only side에서 동등한 매핑이 작동하는지를 ``broker.status`` 로
    검증한다.
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
        assert response["error"]["message"] == validation_message(
            "broker.status", ("account_id", "missing")
        )

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


@pytest.mark.asyncio
async def test_ipc_dispatch_broker_reconcile_invalid_account_only_validation_error(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """``broker.reconcile`` IPC dispatch에서 **bot_id 없는** invalid-account-only
    payload도 ``VALIDATION_ERROR``로 매핑되는지 검증 (#1636 / #1623 Split C).

    회귀 모델:
        이전에는 ``_handle_broker_reconcile``이 ``bot_id = args["bot_id"]`` 를
        ``require_account_id`` **이전**에 읽어, bot_id 없는 invalid-account-only
        direct-IPC probe가 ``KeyError`` → server.py:323 ``getattr(e, "code",
        "EXECUTION_ERROR")`` → ``EXECUTION_ERROR``로 잘못 노출되었다 (#1633
        finding). #1636이 ``require_account_id``를 ``args["bot_id"]`` 이전으로
        옮겨, invalid account_id가 ``InvalidAccountIdError``
        (code="VALIDATION_ERROR", #1633 SSOT)로 먼저 raise되어
        ``VALIDATION_ERROR`` envelope이 되도록 한다.

    ``test_ipc_dispatch_broker_status_...`` (바로 위, broker.status만 커버)
    옆에 reconcile ordering 가드를 추가한다 (#1633 메타리뷰 지적).
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)

        # bot_id 없는 invalid-account-only: account_id 누락 → VALIDATION_ERROR
        # (KeyError → EXECUTION_ERROR 회귀 차단)
        response = await client.send("broker.reconcile", {}, actor="tester")
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR", response
        assert response["error"]["code"] != "EXECUTION_ERROR", response
        assert response["error"]["message"] == validation_message(
            "broker.reconcile", ("account_id", "missing")
        ), response

        # bot_id 없는 invalid-account-only: 'default' 예약어 → VALIDATION_ERROR
        response = await client.send(
            "broker.reconcile",
            {"account_id": "default"},
            actor="tester",
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR", response

        # bot_id 없는 invalid-account-only: 빈 문자열 → VALIDATION_ERROR
        response = await client.send(
            "broker.reconcile",
            {"account_id": ""},
            actor="tester",
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR", response
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_ipc_dispatch_broker_reconcile_valid_account_no_bot_id_reaches_handler(
    socket_path: str, service_registry: ServiceRegistry
) -> None:
    """#2119 account-level 재설계: **valid** account_id 면 bot_id 없이도
    ``require_account_id`` 통과 후 account-level handler 본문에 도달한다.

    이전(#1636)에는 valid account_id + bot_id 누락이 ``args["bot_id"]``
    ``KeyError`` → EXECUTION_ERROR 였으나, account-level 재설계로 bot_id 를
    더 이상 읽지 않으므로 KeyError 가 발생하지 않는다. 본 회귀는:
        - invalid-account-only 는 여전히 VALIDATION_ERROR (위 테스트가 가드).
        - valid account 는 require_account_id 를 통과한 뒤 handler 본문
          (서버 broker 조회)에 도달한다.
    fixture 의 ``account`` 서비스가 MagicMock 이라 ``await
    get_broker(...)`` 가 awaitable 이 아니어서 EXECUTION_ERROR(VALIDATION
    아님)로 표면된다 — KeyError(bot_id) 가 아니라 handler 본문 도달의 증거다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    server = IPCServer(socket_path, service_registry, cmd_registry)
    await server.start()
    try:
        client = IPCClient(socket_path, timeout=5.0)

        # valid account_id + bot_id 누락 → require_account_id 통과 → handler 본문
        # (broker 조회). VALIDATION_ERROR 가 아니어야 한다(account 검증은 통과).
        response = await client.send(
            "broker.reconcile",
            {"account_id": "oracle-valid-account"},
            actor="tester",
        )
        assert response["status"] == "error"
        assert response["error"]["code"] != "VALIDATION_ERROR", response
    finally:
        await server.stop()


def _registry_with_real_treasury() -> tuple[ServiceRegistry, object]:
    from ante.eventbus.bus import EventBus
    from ante.treasury.treasury import Treasury

    treasury = Treasury(db=MagicMock(), eventbus=EventBus(), account_id="acc-a")
    bot = MagicMock()
    bot.config.account_id = "acc-a"
    bot_manager = MagicMock()
    bot_manager.get_bot = MagicMock(return_value=bot)
    treasury_manager = MagicMock()
    treasury_manager.get = MagicMock(return_value=treasury)
    svc = ServiceRegistry(
        account=MagicMock(),
        bot_manager=bot_manager,
        treasury_manager=treasury_manager,
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
        strategy_registry=MagicMock(),
        audit_logger=MagicMock(),
    )
    return svc, treasury


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "amount", "expected_code"),
    [
        ("treasury.allocate", 1_000.0, "TREASURY_INSUFFICIENT_BALANCE"),
        ("treasury.allocate", 0.0, "TREASURY_INVALID_AMOUNT"),
        ("treasury.deallocate", 1_000.0, "TREASURY_BUDGET_NOT_FOUND"),
        ("treasury.deallocate", -5.0, "TREASURY_INVALID_AMOUNT"),
    ],
)
async def test_ipc_dispatch_treasury_rejection_surfaces_typed_code(
    socket_path: str, command: str, amount: float, expected_code: str
) -> None:
    """Treasury 의 거절은 success=False 응답이 아니라 그 예외의 오류 코드로 나간다."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    svc, _treasury = _registry_with_real_treasury()

    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "t1",
                "command": command,
                "args": {"account_id": "acc-a", "bot_id": "bot-1", "amount": amount},
                "actor": "tester",
            }
        )
        assert response["status"] == "error", response
        assert response["error"]["code"] == expected_code, response
        assert "result" not in response
        svc.treasury_manager.get.assert_called_once_with("acc-a")
    finally:
        await server.stop()
