"""Approval CLI direct path ↔ IPC path error code equivalence lock (#1843 sub-PR 2).

본 모듈은 #1816 의 3차 migration domain (approval) 의 대표 fault 3 건이 CLI
path 와 IPC envelope path 양쪽에서 **동일한 public code** 를 노출함을 lock
한다. #1842 (account, 17 PASS) / #1843 sub-PR 1 (member, 14 PASS) 의 1:1
동형 패턴.

검증 대상 fault:

- ``ApprovalNotFoundError`` → ``APPROVAL_NOT_FOUND`` (not_found; ``info``
  / ``review`` 표면 typed except 매핑, IPC envelope helper)
- ``ApprovalStatusConflictError`` → ``APPROVAL_STATUS_CONFLICT`` (state_conflict;
  ``approve`` / ``reject`` 표면 helper resolver — class-level ``.code``,
  실제 ``approval.approve`` IPC handler 회귀 통합)
- ``ApprovalValidationError`` → ``APPROVAL_VALIDATION_ERROR`` (validation;
  ``request`` 표면 service-side 사전검증 거부, IPC envelope helper)

approval CLI 는 service 호출이 모두 IPC 경유 (``ipc_send`` → server →
service) 이므로 CLI direct path equivalence 는 다음 두 axis 로 검증한다:

1. ``ipc_send`` mock 로 IPC envelope 의 ``{code, message}`` 를 주입한 뒤,
   middleware ``ClickException`` 분기 (``ipc_error_code`` 부착) 가 동일
   code 로 CLI envelope 을 surface 함을 확인.
2. ``info`` / ``review`` 처럼 ``_find_request`` 가 CLI 안에서 직접
   ``ApprovalNotFoundError`` 를 raise 하는 경우는 typed except 매핑으로
   동일 코드를 surface 함을 확인.
3. IPC path 는 ``ante.contracts.ipc_error_payload`` helper (server.py:322
   의 ``getattr(e, "code", "EXECUTION_ERROR")`` 와 동일 코드를 생성 —
   실측 ``.code`` 가 일치하는 한 contract 동등성, #1842 plan v2 #6) 로
   직접 직렬화하거나, ``ApprovalStatusConflictError`` 의 경우 실제
   ``approval.approve`` IPC handler 를 ``IPCServer`` 위에서 실행해 envelope
   code 를 확인한다 (#1842 ``account.suspend`` 1:1 동형 회귀 lock).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.approval.errors import ApprovalNotFoundError, ApprovalStatusConflictError
from ante.approval.models import ApprovalValidationError
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
    scopes=["approval:read", "approval:write", "approval:admin"],
)


@pytest.fixture
def runner() -> CliRunner:
    """``ante --format json approval ...`` 호출용 ``CliRunner`` fixture.

    auth middleware 를 master member 로 우회한다 (#1865 ``member`` equivalence
    test fixture 동형). ``require_scope`` decorator 는 그대로 동작하므로 모든
    approval scope (``read`` / ``write`` / ``admin``) 를 부여한다.
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


# ── (1) ApprovalNotFoundError ↔ APPROVAL_NOT_FOUND ──────────────────────────


class TestApprovalNotFoundEquivalence:
    """``ApprovalNotFoundError`` 는 양쪽에서 ``APPROVAL_NOT_FOUND``.

    CLI direct path: ``approval info`` 표면 — typed 매핑 (``except
    ApprovalNotFoundError: fmt.error(..., code="APPROVAL_NOT_FOUND")``)
    보존. ``info`` 는 ``_find_request`` (CLI 내부 service 호출) 가 raise
    하므로 IPC 경유가 아니고 CLI 안에서 typed except 가 직접 매칭된다.
    """

    def test_cli_direct_not_found_via_info(self, runner: CliRunner) -> None:
        # ``approval info`` 는 ``asyncio.run(_info())`` → 내부에서 Database
        # connect + ApprovalService initialize + ``_find_request`` 실행.
        # ``_find_request`` 가 service.get(id) → None, list_approvals
        # prefix 매치 0 → ``ApprovalNotFoundError`` raise 하는 시나리오를
        # ApprovalService mock 으로 단순화한다.
        svc = MagicMock()
        svc.initialize = AsyncMock()
        svc.get = AsyncMock(return_value=None)
        svc.list_approvals = AsyncMock(return_value=[])

        db_mock = MagicMock()
        db_mock.connect = AsyncMock()
        db_mock.close = AsyncMock()

        with (
            patch(
                "ante.approval.ApprovalService",
                return_value=svc,
            ),
            patch(
                "ante.core.database.Database",
                return_value=db_mock,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "info",
                    "missing-id",
                    "--db-path",
                    "/tmp/test_approval_equiv.db",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "APPROVAL_NOT_FOUND"

    def test_ipc_envelope_not_found(self) -> None:
        exc = ApprovalNotFoundError("missing-id")
        assert _ipc_envelope_code(exc) == "APPROVAL_NOT_FOUND"


# ── (2) ApprovalStatusConflictError ↔ APPROVAL_STATUS_CONFLICT (approve) ────


class TestApprovalStatusConflictEquivalence:
    """``ApprovalStatusConflictError`` 는 양쪽에서ApprovalStatusConflict
    안정 코드 ``APPROVAL_STATUS_CONFLICT`` (state_conflict 카테고리).

    CLI direct path: ``approval approve`` 표면 — ``ipc_send`` 가 server error
    envelope (code=``APPROVAL_STATUS_CONFLICT``) 를 ``ClickException`` 으로
    변환하고 ``ipc_error_code`` 를 부착한다. middleware 의 ClickException
    분기가 동일 코드로 CLI envelope 을 surface 한다 (``approval.py`` line
    627-628 의 ``except click.ClickException: raise`` 가 middleware 까지 그대로
    bubble).

    IPC path: 실제 ``approval.approve`` handler 를 ``IPCServer`` 위에서
    실행해 envelope code 를 확인한다 (#1842 ``account.suspend`` 1:1 동형
    회귀 lock).
    """

    def test_cli_direct_status_conflict_via_approve(self, runner: CliRunner) -> None:
        # ``ipc_send`` 가 server error envelope 을 ClickException 으로 변환할 때
        # ``ipc_error_code`` 를 부착한다. middleware ``ClickException`` 분기가
        # 동일 코드로 CLI envelope 을 surface.
        import click

        click_exc = click.ClickException(
            "APPROVAL_STATUS_CONFLICT: 결재 'aaa' 상태 'approved' 에서 "
            "'approve' 작업을 수행할 수 없습니다."
        )
        click_exc.ipc_error_code = "APPROVAL_STATUS_CONFLICT"  # type: ignore[attr-defined]
        click_exc.ipc_error_message = (  # type: ignore[attr-defined]
            "결재 'aaa' 상태 'approved' 에서 'approve' 작업을 수행할 수 없습니다."
        )

        async def _raise_status_conflict(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch(
            "ante.cli.commands.ipc_helpers.ipc_send",
            new=_raise_status_conflict,
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "approval", "approve", "aaa"],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "APPROVAL_STATUS_CONFLICT"

    def test_ipc_envelope_status_conflict(self) -> None:
        exc = ApprovalStatusConflictError(
            approval_id="aaa",
            current_status="approved",
            requested_action="approve",
        )
        assert _ipc_envelope_code(exc) == "APPROVAL_STATUS_CONFLICT"

    @pytest.mark.asyncio
    async def test_ipc_envelope_status_conflict_via_real_handler(self) -> None:
        """실제 ``approval.approve`` IPC handler 가 typed code 를 envelope
        으로 surface 한다 (#1842 ``account.suspend`` 1:1 동형 회귀 lock)."""
        td = tempfile.mkdtemp(prefix="ipc_approval_equiv", dir="/tmp")
        socket_path = str(Path(td) / "t.sock")

        approval_service = MagicMock()
        approval_service.approve = AsyncMock(
            side_effect=ApprovalStatusConflictError(
                approval_id="aaa",
                current_status="approved",
                requested_action="approve",
            )
        )
        svc_registry = ServiceRegistry(
            account=MagicMock(),
            bot_manager=MagicMock(),
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=approval_service,
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            member_service=MagicMock(),
        )
        cmd_registry = CommandRegistry()
        register_all_handlers(cmd_registry)

        server = IPCServer(socket_path, svc_registry, cmd_registry)
        await server.start()
        try:
            client = IPCClient(socket_path, timeout=5.0)
            response = await client.send(
                "approval.approve",
                {"id": "aaa"},
                actor="tester",
            )
            assert response["status"] == "error"
            assert response["error"]["code"] == "APPROVAL_STATUS_CONFLICT"
        finally:
            await server.stop()


# ── (3) ApprovalValidationError ↔ APPROVAL_VALIDATION_ERROR (request) ───────


class TestApprovalValidationEquivalence:
    """``ApprovalValidationError`` 는 양쪽에서 ``APPROVAL_VALIDATION_ERROR``.

    CLI direct path: ``approval request`` 표면 — service ``create()`` 의
    사전검증 ``fail`` grade 거부가 IPC envelope (code=``APPROVAL_VALIDATION_ERROR``)
    로 surface 된다. ``ipc_send`` 가 ClickException 으로 변환하고
    ``ipc_error_code`` 를 부착하면 middleware 가 동일 코드로 CLI envelope 을
    surface 한다.

    IPC path: ``ipc_error_payload`` helper 가 class-level ``.code`` (본 PR
    sub-PR 2 에서 신규 부여) 와 registry 등록을 모두 이용해 동일 코드를
    resolve 한다.
    """

    def test_cli_direct_validation_via_request(self, runner: CliRunner) -> None:
        import click

        click_exc = click.ClickException(
            "APPROVAL_VALIDATION_ERROR: 사전 검증 실패: strategy not adoptable"
        )
        click_exc.ipc_error_code = "APPROVAL_VALIDATION_ERROR"  # type: ignore[attr-defined]
        click_exc.ipc_error_message = (  # type: ignore[attr-defined]
            "사전 검증 실패: strategy not adoptable"
        )

        async def _raise_validation(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch(
            "ante.cli.commands.ipc_helpers.ipc_send",
            new=_raise_validation,
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "test",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "APPROVAL_VALIDATION_ERROR"

    def test_ipc_envelope_validation(self) -> None:
        exc = ApprovalValidationError("strategy not adoptable")
        assert _ipc_envelope_code(exc) == "APPROVAL_VALIDATION_ERROR"
