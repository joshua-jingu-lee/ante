"""Approval invalid type 거부 테스트 (#1469).

CLI ``ante approval request --type <invalid>`` 와 ``ApprovalService.create``
는 ``ApprovalType`` enum SSOT 에 없는 값은 거부해야 한다.

검증 대상:
- CLI JSON 모드: invalid type → exit 1 + flat JSON error code
  ``APPROVAL_VALIDATION_ERROR``, IPC 호출 없음.
- CLI text 모드: invalid type → exit 1 + stderr 메시지.
- CLI: 10개 valid ApprovalType 값은 정상적으로 IPC 전송 + exit 0.
- CLI: ``click.ClickException`` 은 그대로 전파.
- Service: ``ApprovalService.create(type=<invalid>, ...)`` → ``ValueError``.
- Service: 10개 valid 값은 정상 ``ApprovalRequest`` 생성.
- Service: enum 검증이 ``_validate_params`` 보다 먼저 호출됨.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.approval.models import ApprovalType
from ante.approval.service import ApprovalService
from ante.cli.main import cli
from ante.core.database import Database
from ante.eventbus.bus import EventBus
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


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _patch_ipc(send_return: dict | None = None) -> tuple:
    """ipc_helpers의 IPCClient와 get_socket_path를 패치한다."""
    mock_client = AsyncMock()
    if send_return is not None:
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


# ── CLI: invalid type ─────────────────────────────────────────────


class TestCLIApprovalRequestInvalidType:
    """CLI ``ante approval request --type <invalid>`` 검증."""

    def test_invalid_type_json_mode_exits_with_flat_error(
        self, runner: CliRunner
    ) -> None:
        """JSON 모드: invalid type → exit 1 + flat JSON error."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "request",
                    "--type",
                    "oracle_invalid_type",
                    "--title",
                    "Oracle invalid approval type",
                    "--params",
                    "{}",
                ],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["status"] == "error"
        assert payload["code"] == "APPROVAL_VALIDATION_ERROR"
        assert "oracle_invalid_type" in payload["message"]

    def test_invalid_type_does_not_call_ipc_send(self, runner: CliRunner) -> None:
        """JSON 모드: invalid type → IPC 전송 호출 없음."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "request",
                    "--type",
                    "oracle_invalid_type",
                    "--title",
                    "T",
                ],
            )

        assert result.exit_code == 1
        mock_client.send.assert_not_called()

    def test_invalid_type_text_mode_exits_with_error(self) -> None:
        """text 모드: invalid type → exit 1 + stderr ``Error:`` 메시지."""
        # CliRunner 새 click 에서 mix_stderr는 생성자 인자
        r = CliRunner(mix_stderr=False)

        def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
            with patch("ante.cli.main.authenticate_member") as mock_auth:

                def _set_member(ctx):  # noqa: ANN001
                    ctx.obj = ctx.obj or {}
                    ctx.obj["member"] = _MOCK_MASTER

                mock_auth.side_effect = _set_member
                return CliRunner.invoke(r, cli_cmd, args, **kwargs)

        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()

        with ipc_cls_patch, socket_patch:
            result = _invoke_with_auth(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "oracle_invalid_type",
                    "--title",
                    "T",
                ],
            )

        assert result.exit_code == 1
        # text 모드는 stderr 로 ``Error: ...`` 출력
        assert "Error" in result.stderr
        assert "oracle_invalid_type" in result.stderr
        mock_client.send.assert_not_called()


# ── CLI: valid types parametrized ──────────────────────────────────


_VALID_APPROVAL_TYPES = [t.value for t in ApprovalType]


class TestCLIApprovalRequestValidTypes:
    """10개의 valid ApprovalType 값이 정상 처리되는지 확인."""

    @pytest.mark.parametrize("approval_type", _VALID_APPROVAL_TYPES)
    def test_valid_type_passes_through_to_ipc(
        self, runner: CliRunner, approval_type: str
    ) -> None:
        """valid ApprovalType 값은 IPC로 전달되고 exit 0."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc(
            send_return={
                "id": "req-1",
                "status": "ok",
                "result": {
                    "id": "apr-abc",
                    "type": approval_type,
                    "status": "pending",
                    "title": "T",
                },
            }
        )

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    approval_type,
                    "--title",
                    "T",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "approval.request"
        sent = call_args[0][1]
        assert sent["type"] == approval_type


# ── CLI: ClickException 전파 ───────────────────────────────────────


class TestCLIApprovalRequestClickExceptionPropagation:
    """``_create()`` 내부 ``click.ClickException`` 은 formatter 우회."""

    def test_click_exception_propagates(self, runner: CliRunner) -> None:
        """IPC 헬퍼가 ``click.ClickException`` 을 raise 하면 그대로 전파."""

        async def _raise_click_exception(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click.ClickException("서버 미실행")

        with patch(
            "ante.cli.commands.ipc_helpers.ipc_send",
            side_effect=_raise_click_exception,
        ):
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "T",
                ],
            )

        # ClickException 은 click 표준 처리로 exit 1
        assert result.exit_code == 1
        # APPROVAL_ERROR 로 wrap 되지 않고 ClickException 메시지가 그대로
        assert "APPROVAL_ERROR" not in result.output
        assert "서버 미실행" in result.output


# ── Service: invalid / valid types ─────────────────────────────────


@pytest.fixture
async def approval_service(tmp_path):
    """ApprovalService 인스턴스 (실제 DB 사용)."""
    db = Database(str(tmp_path / "approval.db"))
    await db.connect()
    eventbus = EventBus()
    svc = ApprovalService(db=db, eventbus=eventbus)
    await svc.initialize()
    yield svc
    await db.close()


class TestApprovalServiceCreateInvalidType:
    """``ApprovalService.create`` 의 enum 검증."""

    async def test_invalid_type_raises_value_error(
        self, approval_service: ApprovalService
    ) -> None:
        """invalid type → ``ValueError`` (defense-in-depth)."""
        with pytest.raises(ValueError, match="invalid approval type"):
            await approval_service.create(
                type="oracle_invalid_type",
                requester="agent-01",
                title="invalid",
            )

    @pytest.mark.parametrize("approval_type", _VALID_APPROVAL_TYPES)
    async def test_valid_type_creates_request(
        self,
        approval_service: ApprovalService,
        approval_type: str,
    ) -> None:
        """10개 valid ApprovalType 값 → 정상 ApprovalRequest."""
        # account-scoped 타입은 account_id 가 params 에 필요하므로 제공한다.
        params: dict = {"account_id": "acct-test"}
        req = await approval_service.create(
            type=approval_type,
            requester="agent-01",
            title=f"test {approval_type}",
            params=params,
        )
        assert req.type == approval_type
        assert req.requester == "agent-01"
        assert req.id

    async def test_enum_validation_runs_before_validate_params(self, tmp_path) -> None:
        """invalid type 은 ``_validate_params`` 호출 없이 raise."""
        db = Database(str(tmp_path / "approval2.db"))
        await db.connect()
        eventbus = EventBus()

        # validator mock — 호출되면 안 됨
        validator_mock = MagicMock()

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"oracle_invalid_type": validator_mock},
        )
        await svc.initialize()

        with pytest.raises(ValueError, match="invalid approval type"):
            await svc.create(
                type="oracle_invalid_type",
                requester="agent",
                title="t",
            )

        validator_mock.assert_not_called()
        await db.close()
