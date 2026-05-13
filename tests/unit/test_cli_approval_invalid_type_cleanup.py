"""CLI ``ante approval audit-types`` / ``cancel-invalid`` 검증 (#1472).

검증 대상:
- ``audit-types``:
  - invalid 만 노출 / 정상 type row 제외 (서비스 mock 결과를 그대로 렌더링)
  - ``--format json`` 형태가 list[dict] 로 직렬화된다.
  - ``--status`` 가 service 호출에 전달된다.
  - 데코레이터: ``require_auth`` + ``require_scope("approval:read")``.
- ``cancel-invalid``:
  - 데코레이터: ``require_auth`` + ``require_scope("approval:admin")``.
  - scope 부족(agent) 시 비0 exit + IPC 호출 없음.
  - 성공 시 IPC 가 ``approval.cancel_invalid`` 로 호출되고, ``actor`` 는 member id.
  - IPC 실패 시 비0 exit + 에러 출력.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.approval.models import ApprovalStatus, ApprovalType
from ante.cli.commands.approval import audit_types, cancel_invalid
from ante.cli.main import cli
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


def _make_agent(*, scopes: list[str]) -> Member:
    return Member(
        member_id="agent-1",
        type=MemberType.AGENT,
        role=MemberRole.DEFAULT,
        org="default",
        name="Agent",
        status="active",
        scopes=scopes,
    )


@pytest.fixture
def runner() -> CliRunner:
    """master 인증 컨텍스트가 적용된 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, member=None, **kwargs):  # noqa: ANN001
        with patch("ante.cli.main.authenticate_member") as mock_auth:
            target = member or _MOCK_MASTER

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = target

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _patch_ipc(
    send_return: dict | None = None,
    *,
    side_effect: Exception | None = None,
):
    """ipc_helpers 의 IPCClient/socket 을 패치한다."""
    mock_client = AsyncMock()
    if side_effect is not None:
        mock_client.send.side_effect = side_effect
    elif send_return is not None:
        mock_client.send.return_value = send_return
    ipc_cls_patch = patch(
        "ante.cli.commands.ipc_helpers.IPCClient",
        return_value=mock_client,
    )
    socket_patch = patch(
        "ante.cli.commands.ipc_helpers.get_socket_path",
        return_value="/tmp/test.sock",
    )
    return mock_client, ipc_cls_patch, socket_patch


def _mock_service_layer(invalid_requests=None):
    """`Database` + `ApprovalService` 생성자 patch 헬퍼.

    audit-types 는 ``ApprovalService.list_invalid_type_requests`` 만 호출하므로
    그 외 메서드는 stub 으로 충분하다.
    """
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db_cls = MagicMock(return_value=db)

    service = MagicMock()
    service.initialize = AsyncMock()
    service.list_invalid_type_requests = AsyncMock(return_value=invalid_requests or [])
    service_cls = MagicMock(return_value=service)

    return db_cls, service_cls, service


def _make_request(
    *,
    id: str,
    type_: str,
    status: str = ApprovalStatus.PENDING,
    requester: str = "agent-x",
):
    """ApprovalRequest-shaped stub. CLI 가 접근하는 속성만 노출."""
    return MagicMock(
        id=id,
        type=type_,
        status=status,
        requester=requester,
        created_at="2026-04-01T00:00:00+00:00",
        expires_at="",
    )


# ── audit-types CLI ──────────────────────────────────────────────


class TestAuditTypesScopeAndDecorators:
    """audit-types 의 데코레이터 invariant."""

    def test_required_scopes_is_approval_read(self) -> None:
        """``audit-types`` 콜백에 ``approval:read`` scope 가 부착되어야 한다."""
        scopes = getattr(audit_types.callback, "_required_scopes", None)
        assert scopes == ("approval:read",)


class TestAuditTypesOutput:
    """invalid row 만 노출 / json 직렬화."""

    def test_lists_only_invalid_rows_in_json(self, runner: CliRunner) -> None:
        """list_invalid_type_requests 결과만 json 으로 노출되며 정상 type 은 없다."""
        invalid_req = _make_request(
            id="11111111-1111-1111-1111-111111111111",
            type_="oracle_invalid_type",
            status=ApprovalStatus.PENDING,
            requester="agent-bad",
        )
        db_cls, service_cls, service = _mock_service_layer(
            invalid_requests=[invalid_req]
        )

        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.approval.ApprovalService", service_cls),
            patch(
                "ante.cli.main.get_db_path",
                return_value="/tmp/unused-approval.db",
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "audit-types",
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        assert len(payload) == 1
        row = payload[0]
        assert row["id"] == "11111111-1111-1111-1111-111111111111"
        assert row["type"] == "oracle_invalid_type"
        assert row["status"] == "pending"
        # 정상 type 값이 결과에 섞이지 않는다 — invariant.
        valid_types = {t.value for t in ApprovalType}
        assert row["type"] not in valid_types

        service.list_invalid_type_requests.assert_awaited_once_with(status=None)

    def test_empty_result_renders_no_data_text(self, runner: CliRunner) -> None:
        """invalid row 가 없을 때 text 모드는 (no data) 또는 빈 출력."""
        db_cls, service_cls, _service = _mock_service_layer(invalid_requests=[])
        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.approval.ApprovalService", service_cls),
            patch(
                "ante.cli.main.get_db_path",
                return_value="/tmp/unused-approval.db",
            ),
        ):
            result = runner.invoke(cli, ["approval", "audit-types"])

        assert result.exit_code == 0, result.output

    def test_status_filter_propagated_to_service(self, runner: CliRunner) -> None:
        """``--status pending`` 이 list_invalid_type_requests 인자로 전달된다."""
        db_cls, service_cls, service = _mock_service_layer(invalid_requests=[])
        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.approval.ApprovalService", service_cls),
            patch(
                "ante.cli.main.get_db_path",
                return_value="/tmp/unused-approval.db",
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "audit-types",
                    "--status",
                    "pending",
                ],
            )

        assert result.exit_code == 0, result.output
        service.list_invalid_type_requests.assert_awaited_once_with(status="pending")

    def test_invalid_status_rejected_before_db(self, runner: CliRunner) -> None:
        """ApprovalStatus enum 외 ``--status`` 값은 DB 접속 전 차단된다."""
        db_cls = MagicMock()
        with (
            patch("ante.core.database.Database", db_cls),
            patch(
                "ante.cli.main.get_db_path",
                return_value="/tmp/unused-approval.db",
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "audit-types",
                    "--status",
                    "not_a_status",
                ],
            )

        assert result.exit_code == 1
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["code"] == "APPROVAL_INVALID_STATUS"
        db_cls.assert_not_called()


# ── cancel-invalid CLI ───────────────────────────────────────────


class TestCancelInvalidScopeAndDecorators:
    """cancel-invalid 의 데코레이터 invariant — 핵심 보안 가드."""

    def test_required_scopes_is_approval_admin(self) -> None:
        """``cancel-invalid`` 콜백에 ``approval:admin`` scope 가 부착되어야 한다."""
        scopes = getattr(cancel_invalid.callback, "_required_scopes", None)
        assert scopes == ("approval:admin",), (
            "cancel-invalid 는 approval:admin scope 가 필수 — invariant 위반"
        )

    def test_agent_without_admin_scope_is_rejected(self, runner: CliRunner) -> None:
        """agent 가 admin scope 없이 호출하면 비0 exit + IPC 호출 없음."""
        agent_read_only = _make_agent(scopes=["approval:read"])
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc(send_return={"id": "x"})

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "cancel-invalid",
                    "11111111-1111-1111-1111-111111111111",
                ],
                member=agent_read_only,
            )

        assert result.exit_code != 0
        mock_client.send.assert_not_called()

    def test_agent_with_write_scope_is_rejected(self, runner: CliRunner) -> None:
        """approval:write 만 가진 agent 도 cancel-invalid 는 거부 (admin 필수)."""
        agent_write = _make_agent(scopes=["approval:write"])
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc(send_return={"id": "x"})

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "cancel-invalid",
                    "11111111-1111-1111-1111-111111111111",
                ],
                member=agent_write,
            )

        assert result.exit_code != 0
        mock_client.send.assert_not_called()

    def test_agent_with_admin_scope_passes_through(self, runner: CliRunner) -> None:
        """approval:admin 보유 agent 는 IPC 까지 도달한다."""
        agent_admin = _make_agent(scopes=["approval:admin"])
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc(
            send_return={
                "id": "inv-1",
                "status": "cancelled",
                "type": "oracle_invalid_type",
            }
        )

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "cancel-invalid",
                    "inv-1",
                ],
                member=agent_admin,
            )

        assert result.exit_code == 0, result.output
        mock_client.send.assert_called_once()


class TestCancelInvalidIPCCall:
    """cancel-invalid 의 IPC payload / 에러 처리."""

    def test_success_sends_approval_cancel_invalid_with_actor(
        self, runner: CliRunner
    ) -> None:
        """IPC 가 정확한 command name, args, actor 로 호출된다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc(
            send_return={
                "id": "inv-1",
                "status": "cancelled",
                "type": "oracle_invalid_type",
            }
        )

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "cancel-invalid",
                    "inv-1",
                ],
            )

        assert result.exit_code == 0, result.output
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "approval.cancel_invalid"
        assert call_args[0][1] == {"approval_id": "inv-1"}
        # actor 는 인증된 member_id (master).
        assert call_args[0][2] == "test-master"

    def test_ipc_failure_exits_nonzero_with_error(self, runner: CliRunner) -> None:
        """IPC 가 RuntimeError 등을 raise 하면 비0 exit + 에러 메시지."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc(
            side_effect=RuntimeError("not an invalid-type request")
        )

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "cancel-invalid",
                    "valid-1",
                ],
            )

        assert result.exit_code != 0, result.output
        # JSON 모드: error code 노출
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["status"] == "error"
        assert "not an invalid-type request" in payload["message"]

    def test_success_json_payload_includes_result(self, runner: CliRunner) -> None:
        """``--format json`` 성공 시 IPC 응답이 data 에 포함된다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc(
            send_return={
                "id": "inv-1",
                "status": "cancelled",
                "type": "oracle_invalid_type",
            }
        )

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "cancel-invalid",
                    "inv-1",
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["data"]["id"] == "inv-1"
        assert payload["data"]["status"] == "cancelled"
