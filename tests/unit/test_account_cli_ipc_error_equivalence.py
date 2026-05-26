"""Account CLI direct path ↔ IPC path error code equivalence lock (#1842).

본 모듈은 #1816 의 1차 migration domain (account) 의 대표 fault 9 건이 CLI
direct path 와 IPC envelope path 양쪽에서 **동일한 public code** 를 노출
함을 lock 한다.

검증 대상 fault:

- ``InvalidAccountIdError`` → ``VALIDATION_ERROR`` (validation)
- ``InvalidExchangeError`` → ``VALIDATION_ERROR`` (validation)
- ``AccountNotFoundError`` → ``ACCOUNT_NOT_FOUND`` (not_found)
- ``AccountAlreadyExistsError`` → ``ACCOUNT_ALREADY_EXISTS`` (state_conflict)
- ``AccountAlreadySuspendedError`` → ``ACCOUNT_ALREADY_SUSPENDED`` (state_conflict)
- ``AccountDeletedError`` → ``ACCOUNT_DELETED`` (state_conflict, update/activate
  surface; ``account delete`` 의 ``ACCOUNT_ALREADY_DELETED`` surface override
  는 별도 lock test 로 분리)
- ``AccountHasActiveBotsError`` → ``ACCOUNT_HAS_ACTIVE_BOTS`` (state_conflict)
- ``BrokerReconnectFailedError`` → ``BROKER_RECONNECT_FAILED`` (external)
- CLI surface override 보존: ``account delete`` 의 ``AccountDeletedError`` →
  ``ACCOUNT_ALREADY_DELETED`` (registry default 와 분기 — UX 의미 보존)

CLI direct path 는 ``CliRunner`` 로 ``ante --format json account ...`` 를
실행해 ``OutputFormatter`` 의 JSON envelope code 를 단언한다 (subprocess
오버헤드 없이 동일 dispatch).

IPC path 는 ``ante.ipc.registry`` 의 실제 핸들러 (account.suspend/activate)
를 ``IPCServer`` 위에서 실행하거나, IPC envelope helper (``ipc_error_payload``)
로 직접 직렬화해 동일 code 를 단언한다.
"""

from __future__ import annotations

import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.account.errors import (
    AccountAlreadyExistsError,
    AccountAlreadySuspendedError,
    AccountDeletedError,
    AccountHasActiveBotsError,
    AccountNotFoundError,
    BrokerReconnectFailedError,
    InvalidExchangeError,
)
from ante.cli.main import cli
from ante.contracts import ipc_error_payload
from ante.core.registry import ServiceRegistry
from ante.ipc.client import IPCClient
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture
def runner() -> CliRunner:
    """``ante --format json account ...`` 호출용 ``CliRunner`` fixture.

    auth middleware 를 master member 로 우회한다 (E bucket fixture 동형).
    """
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx) -> None:  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


def _ipc_envelope_code(exc: BaseException) -> str:
    """주어진 exception 을 IPC envelope 으로 직렬화했을 때의 ``code``.

    IPC server.py:322 가 적용하는 ``getattr(e, "code", "EXECUTION_ERROR")``
    fallback 과 helper(``ipc_error_payload``)의 registry-first resolution 은
    실측 ``.code`` 가 일치하는 한 동일 코드를 생성한다 (#1842 plan v2 #6).
    본 helper 는 helper 경로를 그대로 사용해 contract 동등성을 단언한다.
    """

    payload = ipc_error_payload(exc)
    return payload["code"]


def _cli_envelope_code(runner: CliRunner, args: list[str], exc: BaseException) -> str:
    """``_create_account_service`` 를 patch 해 주어진 exception 을 raise 시키고
    CLI ``--format json`` envelope 의 ``code`` 를 반환한다.

    #1856: ``_create_account_service`` 가 async context manager 로 전환됐다.
    """
    from contextlib import asynccontextmanager

    svc = AsyncMock()

    @asynccontextmanager
    async def _create_service(ctx=None):  # noqa: ANN001, ANN202
        yield svc

    # account list/get/update 등 모든 service entry 가 exc 를 raise 하도록
    # 광범위 side_effect 를 설정한다 (대상 callsite 가 어느 메서드든 동일
    # generic except 분기를 타도록).
    for method in ("list", "get", "create", "update", "delete", "repair_timezone"):
        getattr(svc, method).side_effect = exc

    with patch(
        "ante.cli.commands.account._create_account_service",
        new=_create_service,
    ):
        result = runner.invoke(cli, ["--format", "json", *args])

    # CLI 가 exit 1 이 아니면 envelope code 추출이 무의미하다 — 즉시 fail.
    assert result.exit_code != 0, (
        f"CLI 가 정상 종료했다 (exit={result.exit_code}). output={result.output!r}"
    )
    # JSON envelope 첫 객체 추출. ``fmt.success`` mode 와 달리 ``fmt.error``
    # 는 indent 없이 한 줄 — splitlines 첫 번째에서 JSON parse 가능.
    payload_line = next(
        (line for line in result.output.splitlines() if line.startswith("{")),
        None,
    )
    assert payload_line is not None, f"JSON envelope 발견 실패: {result.output!r}"
    payload = json.loads(payload_line)
    assert payload["status"] == "error", payload
    return payload["code"]


# ── (1) InvalidAccountIdError ↔ VALIDATION_ERROR ────────────────────────────


class TestInvalidAccountIdEquivalence:
    """invalid account_id 는 CLI direct path 와 IPC path 모두 ``VALIDATION_ERROR``.

    CLI ingress 가 ``reject_invalid_account_id`` 로 service 호출 이전에 거부
    하므로 service mock 이 raise 하지 않아도 envelope 가 ``VALIDATION_ERROR``
    이다. IPC handler-first ``require_account_id`` 도 동일 코드를 raise한다.
    """

    def test_cli_direct_invalid_account_id_validation_error(
        self, runner: CliRunner
    ) -> None:
        # invalid account_id ("default") → CLI ingress 가 reject_invalid_account_id
        # 로 거부하며 service mock 까지 도달하지 않는다.
        #
        # #1856: ``_create_account_service`` 가 async context manager 로 전환됐다.
        from contextlib import asynccontextmanager

        svc = AsyncMock()

        @asynccontextmanager
        async def _create_service(ctx=None):  # noqa: ANN001, ANN202
            yield svc

        with patch(
            "ante.cli.commands.account._create_account_service",
            new=_create_service,
        ):
            result = runner.invoke(
                cli, ["--format", "json", "account", "info", "default"]
            )

        assert result.exit_code != 0
        payload_line = next(
            (line for line in result.output.splitlines() if line.startswith("{")),
            None,
        )
        assert payload_line is not None
        payload = json.loads(payload_line)
        assert payload["status"] == "error"
        assert payload["code"] == "VALIDATION_ERROR"

    def test_ipc_envelope_invalid_account_id_validation_error(self) -> None:
        """IPC envelope 도 동일하게 ``VALIDATION_ERROR``."""
        from ante.account.errors import InvalidAccountIdError

        assert _ipc_envelope_code(InvalidAccountIdError("bad id")) == "VALIDATION_ERROR"


# ── (2) InvalidExchangeError ↔ VALIDATION_ERROR ─────────────────────────────


class TestInvalidExchangeEquivalence:
    """``InvalidExchangeError`` 는 양쪽에서 ``VALIDATION_ERROR``.

    ``InvalidAccountIdError`` 와 코드를 공유한다 (account 검증 SSOT —
    errors.py:54-57 보강 정렬).
    """

    def test_cli_direct_invalid_exchange_validation_error(
        self, runner: CliRunner
    ) -> None:
        exc = InvalidExchangeError("invalid exchange: *")
        code = _cli_envelope_code(
            runner,
            ["account", "list"],
            exc,
        )
        assert code == "VALIDATION_ERROR"

    def test_ipc_envelope_invalid_exchange_validation_error(self) -> None:
        exc = InvalidExchangeError("invalid exchange: *")
        assert _ipc_envelope_code(exc) == "VALIDATION_ERROR"


# ── (3) AccountNotFoundError ↔ ACCOUNT_NOT_FOUND ────────────────────────────


class TestAccountNotFoundEquivalence:
    """``AccountNotFoundError`` 는 양쪽에서 ``ACCOUNT_NOT_FOUND``."""

    def test_cli_direct_not_found_account_not_found(self, runner: CliRunner) -> None:
        exc = AccountNotFoundError("missing")
        code = _cli_envelope_code(
            runner,
            ["account", "info", "acc-missing"],
            exc,
        )
        assert code == "ACCOUNT_NOT_FOUND"

    def test_ipc_envelope_not_found_account_not_found(self) -> None:
        exc = AccountNotFoundError("missing")
        assert _ipc_envelope_code(exc) == "ACCOUNT_NOT_FOUND"


# ── (4) AccountAlreadyExistsError ↔ ACCOUNT_ALREADY_EXISTS ──────────────────


class TestAccountAlreadyExistsEquivalence:
    """``AccountAlreadyExistsError`` 는 양쪽에서 ``ACCOUNT_ALREADY_EXISTS``."""

    def test_cli_direct_already_exists(self, runner: CliRunner) -> None:
        exc = AccountAlreadyExistsError("dup")
        # account create 표면. 필수 옵션 (broker-type/account-id/name/trading-mode)
        # + test broker 의 required_credentials (app_key/app_secret) 를 모두
        # 제공해 service.create 호출까지 도달시킨다. cold-path runtime guard
        # 도 우회한다 (CLI defense-in-depth 는 본 lock 범위 밖).
        svc = AsyncMock()
        svc.create.side_effect = exc

        @asynccontextmanager
        async def _create_service(ctx=None):  # noqa: ANN001, ANN202
            yield svc

        with (
            patch(
                "ante.cli.commands.account._create_account_service",
                new=_create_service,
            ),
            patch(
                "ante.cli.commands.account._assert_no_active_runtime",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "account",
                    "create",
                    "--account-id",
                    "acc-dup",
                    "--name",
                    "dup",
                    "--broker-type",
                    "test",
                    "--trading-mode",
                    "virtual",
                    "--credential",
                    "app_key=k",
                    "--credential",
                    "app_secret=s",
                ],
            )

        assert result.exit_code != 0, result.output
        payload_line = next(
            (line for line in result.output.splitlines() if line.startswith("{")),
            None,
        )
        assert payload_line is not None, result.output
        payload = json.loads(payload_line)
        assert payload["status"] == "error"
        assert payload["code"] == "ACCOUNT_ALREADY_EXISTS"

    def test_ipc_envelope_already_exists(self) -> None:
        exc = AccountAlreadyExistsError("dup")
        assert _ipc_envelope_code(exc) == "ACCOUNT_ALREADY_EXISTS"


# ── (5) AccountAlreadySuspendedError ↔ ACCOUNT_ALREADY_SUSPENDED ────────────


class TestAccountAlreadySuspendedEquivalence:
    """``AccountAlreadySuspendedError`` 는 양쪽에서 ``ACCOUNT_ALREADY_SUSPENDED``.

    CLI direct path: ``account suspend`` 는 ``ipc_send`` 위임. ``ipc_send``
    를 raise 하도록 patch 한 뒤 generic except → emit_cli_error 흐름이
    registry-first 로 typed code 를 surface 함을 확인한다.

    IPC path: 실제 ``account.suspend`` handler 를 ``IPCServer`` 위에서 실행해
    envelope code 를 확인한다.
    """

    def test_cli_direct_already_suspended(self, runner: CliRunner) -> None:
        exc = AccountAlreadySuspendedError("이미 정지됨")

        async def _raise(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise exc

        with patch(
            "ante.cli.commands.ipc_helpers.ipc_send",
            new=AsyncMock(side_effect=_raise),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "account", "suspend", "acc-test"],
            )

        assert result.exit_code != 0, result.output
        payload_line = next(
            (line for line in result.output.splitlines() if line.startswith("{")),
            None,
        )
        assert payload_line is not None, result.output
        payload = json.loads(payload_line)
        assert payload["status"] == "error"
        assert payload["code"] == "ACCOUNT_ALREADY_SUSPENDED"

    @pytest.mark.asyncio
    async def test_ipc_envelope_already_suspended_via_real_handler(self) -> None:
        """실제 ``account.suspend`` IPC handler 가 typed code 를 envelope 으로
        surface 한다.

        ``test_ipc_error_code_mapping.py`` 의 dummy-handler 기반 단언과 1:1
        동형의 실제-handler 기반 회귀 lock.
        """
        td = tempfile.mkdtemp(prefix="ipc_equiv", dir="/tmp")
        socket_path = str(Path(td) / "t.sock")

        account_svc = MagicMock()
        account_svc.suspend = AsyncMock(
            side_effect=AccountAlreadySuspendedError("이미 정지됨")
        )
        # Refs #1852: account.suspend handler 가 required_services 에
        # ``audit_logger`` 를 보유하므로 wrapper preflight (SERVICE_NOT_CONFIGURED)
        # 를 피하려면 ServiceRegistry 에 ``audit_logger`` 를 주입해야 한다.
        audit_logger = MagicMock()
        audit_logger.log = AsyncMock(return_value=None)
        svc_registry = ServiceRegistry(
            account=account_svc,
            bot_manager=MagicMock(),
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            audit_logger=audit_logger,
        )
        cmd_registry = CommandRegistry()
        register_all_handlers(cmd_registry)

        server = IPCServer(socket_path, svc_registry, cmd_registry)
        await server.start()
        try:
            client = IPCClient(socket_path, timeout=5.0)
            response = await client.send(
                "account.suspend",
                {"account_id": "acc-test"},
                actor="tester",
            )
            assert response["status"] == "error"
            assert response["error"]["code"] == "ACCOUNT_ALREADY_SUSPENDED"
        finally:
            await server.stop()


# ── (6) AccountDeletedError ↔ ACCOUNT_DELETED (update/activate surface) ─────


class TestAccountDeletedEquivalence:
    """``AccountDeletedError`` 는 ``account activate`` 등 generic 표면에서 양쪽
    ``ACCOUNT_DELETED`` (registry default).

    ``account delete`` 의 ``ACCOUNT_ALREADY_DELETED`` surface override 는
    별도 ``TestAccountDeleteSurfaceOverride`` lock 으로 분리.
    """

    def test_cli_direct_deleted_via_activate(self, runner: CliRunner) -> None:
        """``account activate`` (ipc_send 위임 표면) 에서 IPC handler 가
        ``AccountDeletedError`` 를 raise 하면 CLI envelope 가 typed code
        (``ACCOUNT_DELETED``) 를 surface 한다.
        """
        exc = AccountDeletedError("deleted")

        async def _raise(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise exc

        with patch(
            "ante.cli.commands.ipc_helpers.ipc_send",
            new=AsyncMock(side_effect=_raise),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "account", "activate", "acc-test"],
            )

        assert result.exit_code != 0, result.output
        payload_line = next(
            (line for line in result.output.splitlines() if line.startswith("{")),
            None,
        )
        assert payload_line is not None, result.output
        payload = json.loads(payload_line)
        assert payload["status"] == "error"
        assert payload["code"] == "ACCOUNT_DELETED"

    def test_ipc_envelope_deleted(self) -> None:
        exc = AccountDeletedError("deleted")
        assert _ipc_envelope_code(exc) == "ACCOUNT_DELETED"


# ── (7) AccountHasActiveBotsError ↔ ACCOUNT_HAS_ACTIVE_BOTS ─────────────────


class TestAccountHasActiveBotsEquivalence:
    """``AccountHasActiveBotsError`` 는 양쪽에서 ``ACCOUNT_HAS_ACTIVE_BOTS``."""

    def test_cli_direct_has_active_bots(self, runner: CliRunner) -> None:
        exc = AccountHasActiveBotsError("acc-test", 2)
        # account delete 표면 — typed except 명시 매핑이 ``ACCOUNT_HAS_ACTIVE_BOTS``
        # 코드를 명시 surface 한다 (보존).
        svc = AsyncMock()
        svc.delete.side_effect = exc

        @asynccontextmanager
        async def _create_service(ctx=None):  # noqa: ANN001, ANN202
            yield svc

        with (
            patch(
                "ante.cli.commands.account._create_account_service",
                new=_create_service,
            ),
            patch(
                "ante.cli.commands.account._assert_no_active_runtime",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "account", "delete", "acc-test", "--yes"],
            )

        assert result.exit_code != 0, result.output
        payload_line = next(
            (line for line in result.output.splitlines() if line.startswith("{")),
            None,
        )
        assert payload_line is not None, result.output
        payload = json.loads(payload_line)
        assert payload["status"] == "error"
        assert payload["code"] == "ACCOUNT_HAS_ACTIVE_BOTS"

    def test_ipc_envelope_has_active_bots(self) -> None:
        exc = AccountHasActiveBotsError("acc-test", 2)
        assert _ipc_envelope_code(exc) == "ACCOUNT_HAS_ACTIVE_BOTS"


# ── (8) BrokerReconnectFailedError ↔ BROKER_RECONNECT_FAILED ────────────────


class TestBrokerReconnectFailedEquivalence:
    """``BrokerReconnectFailedError`` 는 양쪽에서 ``BROKER_RECONNECT_FAILED``."""

    def test_cli_direct_broker_reconnect_failed(self, runner: CliRunner) -> None:
        exc = BrokerReconnectFailedError("재연결 실패")
        # set-credentials 표면 — service.update 가 raise → generic except →
        # emit_cli_error 로 typed code surface.
        svc = AsyncMock()

        # _resolve_credentials 가 도달하기 전 svc.get 으로 broker_type 을 알아야
        # 한다 — preset 이 있는 broker_type 으로 mock account 를 반환한다.
        from decimal import Decimal

        from ante.account.models import Account, AccountStatus, TradingMode

        svc.get = AsyncMock(
            return_value=Account(
                account_id="acc-test",
                name="test",
                exchange="TEST",
                currency="KRW",
                broker_type="test",
                status=AccountStatus("active"),
                trading_mode=TradingMode("virtual"),
                credentials={},
                buy_commission_rate=Decimal("0.00015"),
                sell_commission_rate=Decimal("0.00195"),
            )
        )
        svc.update = AsyncMock(side_effect=exc)

        @asynccontextmanager
        async def _create_service(ctx=None):  # noqa: ANN001, ANN202
            yield svc

        with (
            patch(
                "ante.cli.commands.account._create_account_service",
                new=_create_service,
            ),
            patch(
                "ante.cli.commands.account._assert_no_active_runtime",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "account",
                    "set-credentials",
                    "acc-test",
                    "--credential",
                    "app_key=k",
                    "--credential",
                    "app_secret=s",
                ],
            )

        assert result.exit_code != 0, result.output
        payload_line = next(
            (line for line in result.output.splitlines() if line.startswith("{")),
            None,
        )
        assert payload_line is not None, result.output
        payload = json.loads(payload_line)
        assert payload["status"] == "error"
        assert payload["code"] == "BROKER_RECONNECT_FAILED"

    def test_ipc_envelope_broker_reconnect_failed(self) -> None:
        exc = BrokerReconnectFailedError("재연결 실패")
        assert _ipc_envelope_code(exc) == "BROKER_RECONNECT_FAILED"


# ── (9) CLI surface override 보존 ───────────────────────────────────────────


class TestAccountDeleteSurfaceOverride:
    """``account delete`` 의 ``AccountDeletedError`` → ``ACCOUNT_ALREADY_DELETED``
    surface override 보존 (CLI UX layer — registry default 와 분기).

    registry default 는 ``ACCOUNT_DELETED`` (state_conflict) 이지만,
    ``account delete`` 표면은 already-deleted UX 의미를 명시 surface 하기
    위해 typed except 로 ``ACCOUNT_ALREADY_DELETED`` 코드를 surface 한다
    (errors.py:96-100 NOTE / #1812 sweep).

    emit_cli_error 정렬 후에도 typed except 가 generic 분기보다 먼저 매치
    하므로 override 가 보존됨을 lock 한다.
    """

    def test_account_delete_preserves_already_deleted_code(
        self, runner: CliRunner
    ) -> None:
        exc = AccountDeletedError("deleted")
        svc = AsyncMock()
        svc.delete.side_effect = exc

        @asynccontextmanager
        async def _create_service(ctx=None):  # noqa: ANN001, ANN202
            yield svc

        with (
            patch(
                "ante.cli.commands.account._create_account_service",
                new=_create_service,
            ),
            patch(
                "ante.cli.commands.account._assert_no_active_runtime",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "account", "delete", "acc-test", "--yes"],
            )

        assert result.exit_code != 0, result.output
        payload_line = next(
            (line for line in result.output.splitlines() if line.startswith("{")),
            None,
        )
        assert payload_line is not None, result.output
        payload = json.loads(payload_line)
        assert payload["status"] == "error"
        # CLI surface override: registry default (ACCOUNT_DELETED) 가 아닌
        # CLI UX 코드 (ACCOUNT_ALREADY_DELETED) 가 surface 된다.
        assert payload["code"] == "ACCOUNT_ALREADY_DELETED"
        # 분리 lock: IPC envelope 는 여전히 registry default 인 ACCOUNT_DELETED
        # 이다 (CLI/IPC divergence 가 의도적임을 명시).
        assert _ipc_envelope_code(exc) == "ACCOUNT_DELETED"
