"""Member CLI direct path ↔ IPC path error code equivalence lock (#1843 sub-PR 1).

본 모듈은 #1816 의 2차 migration domain (member) 의 대표 fault 5 건이 CLI
direct path 와 IPC envelope path 양쪽에서 **동일한 public code** 를 노출
함을 lock 한다. #1842 (account) 의 1:1 동형 패턴.

검증 대상 fault:

- ``MemberNotFoundError`` → ``MEMBER_NOT_FOUND`` (not_found)
- ``MemberStateConflictError`` → ``MEMBER_STATE_CONFLICT`` (state_conflict;
  ``suspend`` / ``reactivate`` 양쪽 표면)
- ``MemberAlreadyExistsError`` → ``MEMBER_ALREADY_EXISTS`` (state_conflict;
  ``register`` 표면)
- ``MemberInvalidRecoveryCredentialError`` → ``MEMBER_INVALID_RECOVERY_CREDENTIAL``
  (auth; ``reset-password`` 표면)
- ``InvalidScopeError`` → ``MEMBER_INVALID_SCOPE`` (permission; ``register``
  / ``update-scopes`` 표면 + 실제 ``member.update_scopes`` IPC handler 회귀)
- ``PermissionDeniedError`` → ``PERMISSION_DENIED`` (permission; master 검증
  위반, CLI surface override 인 ``_MASTER_REQUIRED_MESSAGE`` 한국어 문구
  보존 확인)

CLI direct path 는 ``CliRunner`` 로 ``ante --format json member ...`` 를
실행해 ``OutputFormatter`` 의 JSON envelope code 를 단언한다 (subprocess
오버헤드 없이 동일 dispatch).

IPC path 는 ``ante.contracts.ipc_error_payload`` helper (server.py:322 의
``getattr(e, "code", "EXECUTION_ERROR")`` 와 동일 코드를 생성 — 실측
``.code`` 가 일치하는 한 contract 동등성, #1842 plan v2 #6) 로 직접 직렬화
하거나, ``InvalidScopeError`` 의 경우 실제 ``member.update_scopes`` IPC
handler 를 ``IPCServer`` 위에서 실행해 envelope code 를 확인한다.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.contracts import ipc_error_payload
from ante.core.registry import ServiceRegistry
from ante.ipc.client import IPCClient
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer
from ante.member.errors import (
    MemberAlreadyExistsError,
    MemberInvalidRecoveryCredentialError,
    MemberNotFoundError,
    MemberStateConflictError,
    PermissionDeniedError,
)
from ante.member.models import Member, MemberRole, MemberType
from ante.member.scopes import InvalidScopeError

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
    """``ante --format json member ...`` 호출용 ``CliRunner`` fixture.

    auth middleware 를 master member 로 우회한다 (account equivalence test
    fixture 동형). ``require_master`` decorator 는 그대로 동작하므로 master
    role 멤버를 주입한다.
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


def _cli_envelope_payload(result_output: str) -> dict:
    """``CliRunner.result.output`` 에서 JSON envelope 첫 객체를 추출."""
    payload_line = next(
        (line for line in result_output.splitlines() if line.startswith("{")),
        None,
    )
    assert payload_line is not None, f"JSON envelope 발견 실패: {result_output!r}"
    return json.loads(payload_line)


# ── (1) MemberNotFoundError ↔ MEMBER_NOT_FOUND ──────────────────────────────


class TestMemberNotFoundEquivalence:
    """``MemberNotFoundError`` 는 양쪽에서 ``MEMBER_NOT_FOUND``.

    CLI direct path: ``member suspend`` 표면 — ``except MemberNotFoundError:
    fmt.error(..., code="MEMBER_NOT_FOUND")`` typed 매핑 (보존).
    """

    def test_cli_direct_not_found_via_suspend(self, runner: CliRunner) -> None:
        exc = MemberNotFoundError("missing")
        svc = AsyncMock()
        db = AsyncMock()
        svc.suspend.side_effect = exc

        async def _create_service():  # noqa: ANN202
            return svc, db

        with patch(
            "ante.cli.commands.member._create_service",
            new=_create_service,
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "member", "suspend", "missing"],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "MEMBER_NOT_FOUND"

    def test_ipc_envelope_not_found(self) -> None:
        exc = MemberNotFoundError("missing")
        assert _ipc_envelope_code(exc) == "MEMBER_NOT_FOUND"


# ── (2) MemberStateConflictError ↔ MEMBER_STATE_CONFLICT (suspend/reactivate)


class TestMemberStateConflictEquivalence:
    """``MemberStateConflictError`` 는 양쪽에서 ``MEMBER_STATE_CONFLICT``.

    CLI direct path: ``member suspend`` / ``member reactivate`` 양쪽 표면
    모두 typed 매핑 (``except MemberStateConflictError:
    fmt.error(..., code="MEMBER_STATE_CONFLICT")``) 보존 — generic
    fallback (``emit_cli_error``) 보다 typed 분기를 우선 매칭한다.
    """

    def test_cli_direct_state_conflict_via_suspend(self, runner: CliRunner) -> None:
        exc = MemberStateConflictError(
            member_id="m-test", current_status="suspended", requested_action="suspend"
        )
        svc = AsyncMock()
        db = AsyncMock()
        svc.suspend.side_effect = exc

        async def _create_service():  # noqa: ANN202
            return svc, db

        with patch(
            "ante.cli.commands.member._create_service",
            new=_create_service,
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "member", "suspend", "m-test"],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "MEMBER_STATE_CONFLICT"

    def test_cli_direct_state_conflict_via_reactivate(self, runner: CliRunner) -> None:
        exc = MemberStateConflictError(
            member_id="m-test", current_status="active", requested_action="reactivate"
        )
        svc = AsyncMock()
        db = AsyncMock()
        svc.reactivate.side_effect = exc

        async def _create_service():  # noqa: ANN202
            return svc, db

        with patch(
            "ante.cli.commands.member._create_service",
            new=_create_service,
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "member", "reactivate", "m-test"],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "MEMBER_STATE_CONFLICT"

    def test_ipc_envelope_state_conflict(self) -> None:
        exc = MemberStateConflictError(
            member_id="m-test", current_status="suspended", requested_action="suspend"
        )
        assert _ipc_envelope_code(exc) == "MEMBER_STATE_CONFLICT"


# ── (3) MemberAlreadyExistsError ↔ MEMBER_ALREADY_EXISTS (register) ─────────


class TestMemberAlreadyExistsEquivalence:
    """``MemberAlreadyExistsError`` 는 양쪽에서 ``MEMBER_ALREADY_EXISTS``.

    CLI direct path: ``member register`` 표면 — typed 매핑 (``except
    MemberAlreadyExistsError: fmt.error(..., code=...)``) 보존.
    """

    def test_cli_direct_already_exists_via_register(self, runner: CliRunner) -> None:
        exc = MemberAlreadyExistsError("dup")
        svc = AsyncMock()
        db = AsyncMock()
        svc.register.side_effect = exc

        async def _create_service():  # noqa: ANN202
            return svc, db

        with patch(
            "ante.cli.commands.member._create_service",
            new=_create_service,
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "member",
                    "register",
                    "--id",
                    "dup",
                    "--type",
                    "human",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "MEMBER_ALREADY_EXISTS"

    def test_ipc_envelope_already_exists(self) -> None:
        exc = MemberAlreadyExistsError("dup")
        assert _ipc_envelope_code(exc) == "MEMBER_ALREADY_EXISTS"


# ── (4) MemberInvalidRecoveryCredentialError ↔ MEMBER_INVALID_RECOVERY_CREDENTIAL


class TestMemberInvalidRecoveryCredentialEquivalence:
    """``MemberInvalidRecoveryCredentialError`` 는 양쪽에서
    ``MEMBER_INVALID_RECOVERY_CREDENTIAL``.

    CLI direct path: ``member reset-password`` 표면 — typed 매핑
    (``except MemberInvalidRecoveryCredentialError: fmt.error(...,
    code=MemberInvalidRecoveryCredentialError.code)``) 보존.
    """

    def test_cli_direct_invalid_recovery_via_reset_password(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        exc = MemberInvalidRecoveryCredentialError("잘못된 recovery key")
        svc = AsyncMock()
        db = AsyncMock()
        svc.list_members = AsyncMock(
            return_value=[
                Member(
                    member_id="master",
                    type=MemberType.HUMAN,
                    role=MemberRole.MASTER,
                    org="default",
                    name="Master",
                    status="active",
                    scopes=[],
                )
            ]
        )
        svc.reset_password = AsyncMock(side_effect=exc)

        async def _create_service():  # noqa: ANN202
            return svc, db

        monkeypatch.setenv("ANTE_TEST_NEW_PASSWORD", "new-pw-12345")

        with patch(
            "ante.cli.commands.member._create_service",
            new=_create_service,
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "wrong-key",
                    "--new-password-env",
                    "ANTE_TEST_NEW_PASSWORD",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "MEMBER_INVALID_RECOVERY_CREDENTIAL"

    def test_ipc_envelope_invalid_recovery_credential(self) -> None:
        exc = MemberInvalidRecoveryCredentialError("잘못된 recovery key")
        assert _ipc_envelope_code(exc) == "MEMBER_INVALID_RECOVERY_CREDENTIAL"


# ── (5) InvalidScopeError ↔ MEMBER_INVALID_SCOPE (CLI + real IPC handler) ───


class TestMemberInvalidScopeEquivalence:
    """``InvalidScopeError`` 는 양쪽에서 ``MEMBER_INVALID_SCOPE``.

    CLI direct path: ``member register`` 표면 — typed 매핑 (``except
    InvalidScopeError: fmt.error(..., code="MEMBER_INVALID_SCOPE")``) 보존.

    IPC path: 실제 ``member.update_scopes`` handler 를 ``IPCServer`` 위에서
    실행해 envelope code 를 확인한다 (#1842 ``account.suspend`` 1:1 동형).
    """

    def test_cli_direct_invalid_scope_via_register(self, runner: CliRunner) -> None:
        exc = InvalidScopeError("oracle:invalid")
        svc = AsyncMock()
        db = AsyncMock()
        svc.register.side_effect = exc

        async def _create_service():  # noqa: ANN202
            return svc, db

        with patch(
            "ante.cli.commands.member._create_service",
            new=_create_service,
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "member",
                    "register",
                    "--id",
                    "m-test",
                    "--type",
                    "human",
                    "--scopes",
                    "oracle:invalid",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "MEMBER_INVALID_SCOPE"

    def test_ipc_envelope_invalid_scope(self) -> None:
        exc = InvalidScopeError("oracle:invalid")
        assert _ipc_envelope_code(exc) == "MEMBER_INVALID_SCOPE"

    @pytest.mark.asyncio
    async def test_ipc_envelope_invalid_scope_via_real_handler(self) -> None:
        """실제 ``member.update_scopes`` IPC handler 가 typed code 를 envelope
        으로 surface 한다 (#1842 ``account.suspend`` 1:1 동형 회귀 lock)."""
        td = tempfile.mkdtemp(prefix="ipc_member_equiv", dir="/tmp")
        socket_path = str(Path(td) / "t.sock")

        member_service = MagicMock()
        member_service.update_scopes = AsyncMock(
            side_effect=InvalidScopeError("oracle:invalid")
        )
        svc_registry = ServiceRegistry(
            account=MagicMock(),
            bot_manager=MagicMock(),
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            member_service=member_service,
            # Refs #1850: ``member.update_scopes`` 는 ``required_services``
            # 에 ``audit_logger`` 를 선언한다 — dispatch wrapper preflight 가
            # 부재 시 SERVICE_NOT_CONFIGURED 로 차단하므로 mock 주입한다.
            audit_logger=MagicMock(),
        )
        cmd_registry = CommandRegistry()
        register_all_handlers(cmd_registry)

        server = IPCServer(socket_path, svc_registry, cmd_registry)
        await server.start()
        try:
            client = IPCClient(socket_path, timeout=5.0)
            response = await client.send(
                "member.update_scopes",
                {"member_id": "m-test", "scopes": ["oracle:invalid"]},
                actor="tester",
            )
            assert response["status"] == "error"
            assert response["error"]["code"] == "MEMBER_INVALID_SCOPE"
        finally:
            await server.stop()


# ── (6) PermissionDeniedError ↔ PERMISSION_DENIED (CLI override 보존) ───────


class TestMemberPermissionDeniedEquivalence:
    """``PermissionDeniedError`` 는 양쪽에서 ``PERMISSION_DENIED``.

    CLI direct path: ``member suspend`` (등 master-guarded 표면) — typed
    매핑 (``except PermissionDeniedError: fmt.error(_MASTER_REQUIRED_MESSAGE,
    code="PERMISSION_DENIED")``) 보존. CLI surface override 는 envelope
    message 에 한국어 친화 문구 (``_MASTER_REQUIRED_MESSAGE``) 를 surface
    하는 책임 — code 는 동일하게 ``PERMISSION_DENIED``.

    IPC path: server.py:322 의 ``getattr(e, "code", ...)`` 는 본 PR 에서
    추가한 class-level ``.code = "PERMISSION_DENIED"`` 를 그대로 surface
    한다 (helper-direct ``ipc_error_payload`` 와 동일 결과).
    """

    def test_cli_direct_permission_denied_via_suspend(self, runner: CliRunner) -> None:
        exc = PermissionDeniedError("master 권한이 필요합니다")
        svc = AsyncMock()
        db = AsyncMock()
        svc.suspend.side_effect = exc

        async def _create_service():  # noqa: ANN202
            return svc, db

        with patch(
            "ante.cli.commands.member._create_service",
            new=_create_service,
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "member", "suspend", "m-test"],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        # CLI surface override: code 는 동일 PERMISSION_DENIED 지만,
        # message 는 ``_MASTER_REQUIRED_MESSAGE`` (한국어 친화 문구) 로
        # surface 된다 — code 일관성과 UX message override 의 동시 보존.
        assert payload["code"] == "PERMISSION_DENIED"
        assert "master" in payload["message"]

    def test_ipc_envelope_permission_denied(self) -> None:
        exc = PermissionDeniedError("master 권한이 필요합니다")
        # server.py:322 ``getattr(e, "code", ...)`` 와 helper ``ipc_error_payload``
        # 가 동일 코드를 produce 함을 verify (CLI/IPC contract 동등성).
        assert _ipc_envelope_code(exc) == "PERMISSION_DENIED"
