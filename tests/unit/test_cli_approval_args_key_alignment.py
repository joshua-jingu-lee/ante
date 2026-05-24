"""``ante approval`` CLI ↔ IPC handler args 키 정렬 회귀 (#1794).

CLI 표면 ``approval approve``/``reject``/``cancel``/``reopen`` 4 명령은
IPC handler ``_handle_approval_approve``/``_handle_approval_reject``/
``_handle_approval_cancel``/``_handle_approval_reopen``
(src/ante/ipc/registry.py:515/523/533/569) 가 모두 ``args["id"]`` 를 기대
하지만, CLI 가 과거에 ``{"approval_id": id}`` 를 전송하여 handler 에서
``KeyError: 'id'`` 가 발생하던 contract drift 가 있었다. 이 테스트는
``ipc_send`` 를 spy 로 패치하여 CLI 가 보내는 ``args`` dict 에 ``"id"`` 키
가 포함되고 ``"approval_id"`` 키가 사용되지 않음을 락한다.

``approval cancel-invalid`` 는 별도 계약 (``args["approval_id"]``,
registry.py:548) 이므로 이 테스트의 sweep 대상이 아니며 회귀에서 제외한다
(별도 contract).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

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


@pytest.fixture
def runner() -> CliRunner:
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _patch_ipc_send() -> tuple[object, AsyncMock]:
    """``ipc_send`` spy AsyncMock. 모든 명령은 모듈 내부에서 import 하므로
    원본 심볼을 패치한다."""
    spy = AsyncMock(
        return_value={"id": "appr-1", "status": "approved"},
    )
    return patch("ante.cli.commands.ipc_helpers.ipc_send", new=spy), spy


def _extract_args(spy: AsyncMock) -> dict:
    """spy 가 호출된 첫 번째 ``ipc_send(command, args, actor=...)`` 의 args."""
    assert spy.await_count == 1, spy.await_args_list
    call = spy.await_args_list[0]
    # ipc_send(command, args, actor=...) — 위치 인자 1번이 args.
    return call.args[1]


class TestApprovalCliArgsKeyAlignment:
    """4 명령 모두 ``args["id"]`` 사용 (handler 정렬)."""

    def test_approve_sends_id_key(self, runner: CliRunner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        with ipc_patch:
            result = runner.invoke(
                cli,
                ["--format", "json", "approval", "approve", "appr-1"],
            )
        assert result.exit_code == 0, result.output
        args = _extract_args(spy)
        assert "id" in args, args
        assert args["id"] == "appr-1"
        assert "approval_id" not in args, args
        # 정상 envelope passthrough (fmt.success → status="ok" envelope).
        payload = json.loads(result.output.strip())
        assert payload["status"] == "ok", payload

    def test_reject_sends_id_key(self, runner: CliRunner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "reject",
                    "appr-1",
                    "--reason",
                    "test",
                ],
            )
        assert result.exit_code == 0, result.output
        args = _extract_args(spy)
        assert args.get("id") == "appr-1", args
        assert args.get("reason") == "test", args
        assert "approval_id" not in args, args

    def test_cancel_sends_id_key(self, runner: CliRunner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        with ipc_patch:
            result = runner.invoke(
                cli,
                ["--format", "json", "approval", "cancel", "appr-1"],
            )
        assert result.exit_code == 0, result.output
        args = _extract_args(spy)
        assert args.get("id") == "appr-1", args
        assert "approval_id" not in args, args

    def test_reopen_sends_id_key(self, runner: CliRunner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        with ipc_patch:
            result = runner.invoke(
                cli,
                ["--format", "json", "approval", "reopen", "appr-1"],
            )
        assert result.exit_code == 0, result.output
        args = _extract_args(spy)
        assert args.get("id") == "appr-1", args
        assert "approval_id" not in args, args

    def test_reopen_with_body_and_params_sends_id_key(self, runner: CliRunner) -> None:
        """body/params 있는 reopen 경로에서도 ``id`` 키 유지."""
        ipc_patch, spy = _patch_ipc_send()
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "reopen",
                    "appr-1",
                    "--body",
                    "updated body",
                    "--params",
                    '{"k": "v"}',
                ],
            )
        assert result.exit_code == 0, result.output
        args = _extract_args(spy)
        assert args.get("id") == "appr-1", args
        assert args.get("body") == "updated body", args
        assert args.get("params") == {"k": "v"}, args
        assert "approval_id" not in args, args


class TestApprovalCancelInvalidKeptApprovalIdContract:
    """``cancel-invalid`` 만 별도 계약 — ``args["approval_id"]`` 유지 (#1472)."""

    def test_cancel_invalid_uses_approval_id_key(self, runner: CliRunner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        with ipc_patch:
            result = runner.invoke(
                cli,
                ["--format", "json", "approval", "cancel-invalid", "appr-1"],
            )
        assert result.exit_code == 0, result.output
        args = _extract_args(spy)
        # cancel-invalid 는 registry.py:548 의 ``args["approval_id"]`` 계약.
        assert args.get("approval_id") == "appr-1", args
        assert "id" not in args, args
