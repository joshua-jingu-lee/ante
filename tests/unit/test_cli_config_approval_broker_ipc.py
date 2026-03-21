"""Config/Approval/Broker CLI 커맨드 IPC 전환 테스트.

#698: config set, approval request/approve/reject/cancel/reopen,
broker reconcile --fix 커맨드가 IPCClient를 통해 서버에 전달되는지 검증한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError
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


def _patch_ipc():
    """ipc_helpers의 IPCClient와 get_socket_path를 패치하는 컨텍스트 매니저 반환."""
    mock_client = AsyncMock()
    ipc_cls_patch = patch(
        "ante.cli.commands.ipc_helpers.IPCClient",
        return_value=mock_client,
    )
    socket_patch = patch(
        "ante.cli.commands.ipc_helpers.get_socket_path",
        return_value="/tmp/test.sock",
    )
    return mock_client, ipc_cls_patch, socket_patch


# ── Config set IPC ────────────────────────────────


class TestConfigSetIPC:
    def test_config_set_sends_ipc(self, runner: CliRunner) -> None:
        """config set이 IPC로 config.set 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"key": "risk.max_drawdown", "value": 0.1},
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["config", "set", "risk.max_drawdown", "0.1"])

        assert result.exit_code == 0, result.output
        assert "설정 변경 완료" in result.output
        mock_client.send.assert_called_once_with(
            "config.set",
            {"key": "risk.max_drawdown", "value": "0.1"},
            "test-master",
        )

    def test_config_set_server_error(self, runner: CliRunner) -> None:
        """서버 에러 시 사용자에게 에러 메시지를 출력한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {"code": "STATIC_CONFIG", "message": "정적 설정입니다"},
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["config", "set", "db.path", "/tmp/x"])

        assert result.exit_code != 0
        assert "STATIC_CONFIG" in result.output


# ── Approval IPC ────────────────────────────────


class TestApprovalRequestIPC:
    def test_request_sends_ipc(self, runner: CliRunner) -> None:
        """approval request가 IPC로 approval.request 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "id": "apr-abc",
                "type": "strategy_deploy",
                "status": "pending",
                "title": "전략 배포",
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_deploy",
                    "--title",
                    "전략 배포",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "결재 요청 생성" in result.output
        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "approval.request"
        sent = call_args[0][1]
        assert sent["type"] == "strategy_deploy"
        assert sent["title"] == "전략 배포"


class TestApprovalApproveIPC:
    def test_approve_sends_ipc(self, runner: CliRunner) -> None:
        """approval approve가 IPC로 approval.approve 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"id": "apr-abc", "status": "approved", "type": "test"},
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["approval", "approve", "apr-abc"])

        assert result.exit_code == 0, result.output
        assert "결재 승인" in result.output
        mock_client.send.assert_called_once_with(
            "approval.approve", {"approval_id": "apr-abc"}, "test-master"
        )


class TestApprovalRejectIPC:
    def test_reject_sends_ipc(self, runner: CliRunner) -> None:
        """approval reject가 IPC로 approval.reject 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"id": "apr-abc", "status": "rejected"},
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                ["approval", "reject", "apr-abc", "--reason", "부적절"],
            )

        assert result.exit_code == 0, result.output
        assert "결재 거절" in result.output
        mock_client.send.assert_called_once_with(
            "approval.reject",
            {"approval_id": "apr-abc", "reason": "부적절"},
            "test-master",
        )


class TestApprovalCancelIPC:
    def test_cancel_sends_ipc(self, runner: CliRunner) -> None:
        """approval cancel이 IPC로 approval.cancel 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"id": "apr-abc", "status": "cancelled"},
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["approval", "cancel", "apr-abc"])

        assert result.exit_code == 0, result.output
        assert "결재 철회" in result.output
        mock_client.send.assert_called_once_with(
            "approval.cancel", {"approval_id": "apr-abc"}, "test-master"
        )


class TestApprovalReopenIPC:
    def test_reopen_sends_ipc(self, runner: CliRunner) -> None:
        """approval reopen이 IPC로 approval.reopen 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "id": "apr-abc",
                "type": "test",
                "status": "pending",
                "title": "재상신",
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["approval", "reopen", "apr-abc"])

        assert result.exit_code == 0, result.output
        assert "결재 재상신" in result.output
        mock_client.send.assert_called_once_with(
            "approval.reopen", {"approval_id": "apr-abc"}, "test-master"
        )


# ── Broker reconcile --fix IPC ────────────────────


class TestBrokerReconcileFixIPC:
    def test_reconcile_fix_sends_ipc(self, runner: CliRunner) -> None:
        """broker reconcile --fix가 IPC로 broker.reconcile 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "total_symbols": 5,
                "discrepancies": [],
                "match": True,
                "fix_applied": True,
                "corrections": 2,
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli, ["broker", "reconcile", "--fix", "--account", "acc-1"]
            )

        assert result.exit_code == 0, result.output
        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "broker.reconcile"
        sent = call_args[0][1]
        assert sent["fix"] is True
        assert sent["account_id"] == "acc-1"

    def test_reconcile_fix_without_account(self, runner: CliRunner) -> None:
        """broker reconcile --fix (계좌 미지정)."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "total_symbols": 0,
                "discrepancies": [],
                "match": True,
                "fix_applied": False,
                "corrections": 0,
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "reconcile", "--fix"])

        assert result.exit_code == 0, result.output
        sent = mock_client.send.call_args[0][1]
        assert sent["fix"] is True
        assert "account_id" not in sent


# ── 서버 미기동 에러 ────────────────────────────────


class TestServerNotRunningErrors:
    def test_config_set_server_not_running(self, runner: CliRunner) -> None:
        """config set 시 서버 미기동 에러."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.side_effect = ServerNotRunningError("no server")

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["config", "set", "key", "value"])

        assert result.exit_code != 0
        assert "서버가 실행 중이 아닙니다" in result.output

    def test_approval_approve_server_not_running(self, runner: CliRunner) -> None:
        """approval approve 시 서버 미기동 에러."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.side_effect = ServerNotRunningError("no server")

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["approval", "approve", "apr-1"])

        assert result.exit_code != 0
        assert "서버가 실행 중이 아닙니다" in result.output

    def test_broker_reconcile_fix_server_not_running(self, runner: CliRunner) -> None:
        """broker reconcile --fix 시 서버 미기동 에러."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.side_effect = ServerNotRunningError("no server")

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "reconcile", "--fix"])

        assert result.exit_code != 0
        assert "서버가 실행 중이 아닙니다" in result.output

    def test_approval_request_timeout(self, runner: CliRunner) -> None:
        """approval request IPC 타임아웃."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.side_effect = IPCTimeoutError("timeout")

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "test",
                    "--title",
                    "timeout test",
                ],
            )

        assert result.exit_code != 0
        assert "응답 시간 초과" in result.output
