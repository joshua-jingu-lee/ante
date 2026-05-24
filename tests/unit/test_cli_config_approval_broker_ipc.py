"""Config/Approval/Broker CLI 커맨드 IPC 전환 테스트.

#698: config set, approval request/approve/reject/cancel/reopen,
broker reconcile --fix 커맨드가 IPCClient를 통해 서버에 전달되는지 검증한다.
"""

from __future__ import annotations

import json
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

    def test_config_set_invalid_log_level_json_envelope(
        self, runner: CliRunner
    ) -> None:
        """#1673 oracle A7: invalid log_level → clean JSON error envelope.

        traceback/Click ``Error:`` 누출 없이 stdout 으로
        ``{status:"error",code:"CONFIG_VALIDATION_ERROR",message}`` +
        exit 1 을 반환해야 한다.
        """
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {
                "code": "CONFIG_VALIDATION_ERROR",
                "message": (
                    "system.log_level은 _VALID_LOG_LEVELS 멤버여야 합니다 "
                    "(대소문자 구분)."
                ),
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                ["config", "set", "system.log_level", "debug", "--format", "json"],
            )

        assert result.exit_code == 1, result.output
        data = json.loads(result.stdout)
        assert data == {
            "status": "error",
            "code": "CONFIG_VALIDATION_ERROR",
            "message": (
                "system.log_level은 _VALID_LOG_LEVELS 멤버여야 합니다 (대소문자 구분)."
            ),
        }
        # traceback / Click 기본 ``Error:`` stderr 누출이 없어야 한다.
        assert "Traceback" not in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_config_set_invalid_log_level_text_mode(self, runner: CliRunner) -> None:
        """텍스트 모드 동치: exit 1 + 코드/메시지 stderr (server_error 톤 보존)."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {
                "code": "CONFIG_VALIDATION_ERROR",
                "message": (
                    "system.log_level은 _VALID_LOG_LEVELS 멤버여야 합니다 "
                    "(대소문자 구분)."
                ),
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["config", "set", "system.log_level", "debug"])

        assert result.exit_code == 1, result.output
        assert "CONFIG_VALIDATION_ERROR" in result.output
        assert "Traceback" not in result.output


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
                "type": "strategy_adopt",
                "status": "pending",
                "title": "전략 채택",
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "전략 채택",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "결재 요청 생성" in result.output
        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "approval.request"
        sent = call_args[0][1]
        assert sent["type"] == "strategy_adopt"
        assert sent["title"] == "전략 채택"


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
        # #1794: IPC handler ``_handle_approval_approve`` (registry.py:515) 가
        # ``args["id"]`` 를 기대 — CLI 가 동일 키로 정렬.
        mock_client.send.assert_called_once_with(
            "approval.approve", {"id": "apr-abc"}, "test-master"
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
        # #1794: handler ``_handle_approval_reject`` (registry.py:523) 가
        # ``args["id"]`` 를 기대.
        mock_client.send.assert_called_once_with(
            "approval.reject",
            {"id": "apr-abc", "reason": "부적절"},
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
        # #1794: handler ``_handle_approval_cancel`` (registry.py:533) 가
        # ``args["id"]`` 를 기대. ``cancel-invalid`` 만 별도 계약(approval_id).
        mock_client.send.assert_called_once_with(
            "approval.cancel", {"id": "apr-abc"}, "test-master"
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
        # #1794: handler ``_handle_approval_reopen`` (registry.py:569) 가
        # ``args["id"]`` 를 기대 (body/params optional).
        mock_client.send.assert_called_once_with(
            "approval.reopen", {"id": "apr-abc"}, "test-master"
        )


# ── Broker status/balance/positions IPC ────────────


class TestBrokerStatusIPC:
    def test_status_sends_ipc(self, runner: CliRunner) -> None:
        """broker status가 IPC로 broker.status 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "connected": True,
                "healthy": True,
                "exchange": "KRX",
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "status", "--account", "acc-1"])

        assert result.exit_code == 0, result.output
        assert "연결됨" in result.output
        assert "정상" in result.output
        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "broker.status"
        sent = call_args[0][1]
        assert sent["account_id"] == "acc-1"

    def test_status_without_account_errors(self, runner: CliRunner) -> None:
        """broker status 미지정 시 click이 user-friendly 에러로 거부한다.

        #1217 SPLIT-1: ``--account`` 는 required. CLI 가 빈 dict 를 IPC 로
        보내지 않도록 진입 시점에서 차단한다.
        """
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "status"])

        assert result.exit_code != 0
        assert "--account" in result.output
        mock_client.send.assert_not_called()

    def test_status_fallback_on_server_not_running(self, runner: CliRunner) -> None:
        """서버 미실행 시 직접 연결 폴백. 폴백도 실패하면 에러 표시."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.side_effect = ServerNotRunningError("no server")

        with ipc_cls_patch, socket_patch:
            # 폴백 시 _get_broker가 실패하면 error 키로 표시
            with patch(
                "ante.cli.commands.broker._get_broker",
                side_effect=Exception("no broker"),
            ):
                result = runner.invoke(cli, ["broker", "status", "--account", "acc-1"])

        assert result.exit_code == 0
        assert "미연결" in result.output


class TestBrokerBalanceIPC:
    def test_balance_sends_ipc(self, runner: CliRunner) -> None:
        """broker balance가 IPC로 broker.balance 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "total_balance": 1000000.0,
                "available_cash": 500000.0,
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "balance", "--account", "acc-1"])

        assert result.exit_code == 0, result.output
        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "broker.balance"
        sent = call_args[0][1]
        assert sent["account_id"] == "acc-1"

    def test_balance_without_account_errors(self, runner: CliRunner) -> None:
        """broker balance 미지정 시 click이 user-friendly 에러로 거부한다.

        #1217 SPLIT-1: ``--account`` required. 빈 dict IPC 호출 차단.
        """
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "balance"])

        assert result.exit_code != 0
        assert "--account" in result.output
        mock_client.send.assert_not_called()


class TestBrokerPositionsIPC:
    def test_positions_sends_ipc(self, runner: CliRunner) -> None:
        """broker positions가 IPC로 broker.positions 커맨드를 전송한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "positions": [
                    {
                        "symbol": "005930",
                        "quantity": 10,
                        "avg_price": 70000.0,
                        "eval_amount": 700000.0,
                    }
                ]
            },
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "positions", "--account", "acc-1"])

        assert result.exit_code == 0, result.output
        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "broker.positions"
        sent = call_args[0][1]
        assert sent["account_id"] == "acc-1"

    def test_positions_empty(self, runner: CliRunner) -> None:
        """보유 종목이 없으면 안내 메시지를 출력한다."""
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"positions": []},
        }

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "positions", "--account", "acc-1"])

        assert result.exit_code == 0, result.output

    def test_positions_without_account_errors(self, runner: CliRunner) -> None:
        """broker positions 미지정 시 click이 user-friendly 에러로 거부한다.

        #1217 SPLIT-1: ``--account`` required. 빈 dict IPC 호출 차단.
        """
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "positions"])

        assert result.exit_code != 0
        assert "--account" in result.output
        mock_client.send.assert_not_called()


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

    def test_reconcile_fix_without_account_errors(self, runner: CliRunner) -> None:
        """broker reconcile --fix 미지정 시 click이 user-friendly 에러로 거부한다.

        #1217 SPLIT-1: ``--account`` required. 빈 dict IPC 호출 차단.
        """
        mock_client, ipc_cls_patch, socket_patch = _patch_ipc()

        with ipc_cls_patch, socket_patch:
            result = runner.invoke(cli, ["broker", "reconcile", "--fix"])

        assert result.exit_code != 0
        assert "--account" in result.output
        mock_client.send.assert_not_called()


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
            result = runner.invoke(
                cli, ["broker", "reconcile", "--fix", "--account", "acc-1"]
            )

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
                    "strategy_adopt",
                    "--title",
                    "timeout test",
                ],
            )

        assert result.exit_code != 0
        assert "응답 시간 초과" in result.output
