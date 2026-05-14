"""CLI ``approval request --expires-in`` traceback 회귀 테스트 (#1518).

대상 invariant:
- ``approval request`` 의 ``_parse_expires_in`` 호출이 try/except 밖에 있어
  invalid expires-in (예: ``"12"``, ``"abc"``, ``"5w"``) 입력 시 Python
  traceback 이 stderr 로 전파되던 ingress drift 를 닫는다.
- ``ValueError`` 외 ``OverflowError`` (큰 숫자 + h/d 입력 시 ``timedelta``
  overflow) 도 동일하게 ``APPROVAL_VALIDATION_ERROR`` 구조화 에러로
  종료시킨다.

oracle probe: ``cli_approval_expires_in_traceback``.

Non-Goals (본 PR 미포함):
- 음수 expires-in semantic 거부는 스펙에 미명시 — 후속 이슈로 추적.
- ``--format json`` JSON envelope 전반의 표준화는 다른 이슈에서 추적.

SSOT:
- 구현 사이트: ``src/ante/cli/commands/approval.py::request`` (``expires_at``
  계산 분기).
- 동형 패턴: 같은 함수 line 57-58 (INVALID_JSON), line 62-66
  (APPROVAL_VALIDATION_ERROR for approval_type), line 92-94 (APPROVAL_ERROR).
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
    """auth bypass + stderr 분리가 적용된 CliRunner.

    ``ante.cli.main.authenticate_member`` 를 patch 하여 root group 의 인증
    검사를 우회한다 (CLI 테스트 표준 패턴). ``mix_stderr=False`` 로 stderr 와
    stdout 을 분리해 traceback 누출 여부를 양쪽 모두에서 검증한다.
    """
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _patch_ipc_success(send_return: dict | None = None):
    """``ipc_send`` 직접 patch — valid 케이스 mock.

    ``approval request`` 는 ``ante.cli.commands.ipc_helpers.ipc_send`` 를
    함수 내부 import 하므로 그 심볼을 직접 patch 한다.
    """
    payload = send_return or {"id": "req-1", "status": "pending"}
    return patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=payload),
    )


class TestApprovalRequestInvalidExpiresIn:
    """invalid expires-in → ``APPROVAL_VALIDATION_ERROR`` + traceback 차단."""

    @pytest.mark.parametrize(
        "bad_expires_in",
        [
            "12",  # 단위 누락 (rstrip 후 "12" → int OK → unit "2" 미지원)
            "abc",  # int 변환 실패
            "5w",  # 미지원 단위
        ],
    )
    def test_invalid_format_rejected_without_traceback(
        self, runner: CliRunner, bad_expires_in: str
    ) -> None:
        """invalid expires-in 입력은 exit 1 + structured error + no traceback.

        IPC 는 호출되지 않아야 한다 (validation 이 ingress 에서 차단).
        """
        with _patch_ipc_success() as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "t",
                    "--expires-in",
                    bad_expires_in,
                ],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        # traceback 노출 차단 invariant — stdout, stderr 양쪽 모두.
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr
        # 구조화 에러 키워드 invariant: code 또는 한국어 메시지.
        combined = result.stdout + result.stderr
        assert (
            "APPROVAL_VALIDATION_ERROR" in combined or "잘못된 expires-in" in combined
        )
        mock_ipc.assert_not_called()

    def test_overflow_number_rejected_without_traceback(
        self, runner: CliRunner
    ) -> None:
        """매우 큰 숫자 + h 입력은 ``timedelta`` ``OverflowError`` 를 유발한다.

        ``ValueError`` 만 catch 하면 traceback 이 노출되므로, 본 invariant 는
        ``OverflowError`` 도 같은 분기에서 처리됨을 회귀 보호한다.
        """
        with _patch_ipc_success() as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "t",
                    "--expires-in",
                    "999999999999999h",
                ],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr
        combined = result.stdout + result.stderr
        assert (
            "APPROVAL_VALIDATION_ERROR" in combined or "잘못된 expires-in" in combined
        )
        mock_ipc.assert_not_called()

    def test_invalid_format_json_envelope(self, runner: CliRunner) -> None:
        """``--format json`` 모드에서 invalid expires-in 은 stdout 의 JSON
        envelope 으로 출력되고 traceback 은 노출되지 않는다.
        """
        with _patch_ipc_success() as mock_ipc:
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
                    "t",
                    "--expires-in",
                    "12",
                ],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr
        # JSON 모드: 마지막 줄이 flat error envelope.
        last_line = result.stdout.strip().splitlines()[-1]
        payload = json.loads(last_line)
        assert payload["status"] == "error"
        assert payload["code"] == "APPROVAL_VALIDATION_ERROR"
        assert "잘못된 expires-in" in payload["message"]
        mock_ipc.assert_not_called()


class TestApprovalRequestValidExpiresIn:
    """valid expires-in 회귀 — 정상 흐름이 IPC 까지 도달한다."""

    @pytest.mark.parametrize("good_expires_in", ["72h", "7d"])
    def test_valid_expires_in_passes_to_ipc(
        self, runner: CliRunner, good_expires_in: str
    ) -> None:
        """valid expires-in 은 try/except 분기를 통과해 IPC 가 호출된다.

        본 invariant 는 try/except 래핑이 정상 입력 경로를 깨뜨리지 않음을
        회귀 보호한다.
        """
        with _patch_ipc_success({"id": "req-good", "status": "pending"}) as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "t",
                    "--expires-in",
                    good_expires_in,
                ],
            )

        assert result.exit_code == 0, (result.stdout, result.stderr)
        mock_ipc.assert_called_once()
        # IPC payload 의 expires_at 은 non-empty ISO 문자열이어야 한다.
        call_args = mock_ipc.call_args
        ipc_payload = call_args[0][1]
        assert ipc_payload["expires_at"]  # 비어있지 않음
        assert "T" in ipc_payload["expires_at"]  # ISO format hint

    def test_empty_expires_in_passes_through_with_empty_string(
        self, runner: CliRunner
    ) -> None:
        """expires-in 미지정 (``""``) 은 ``_parse_expires_in`` 을 호출하지 않고
        ``expires_at=""`` 로 IPC 에 전달된다.
        """
        with _patch_ipc_success() as mock_ipc:
            result = runner.invoke(
                cli,
                [
                    "approval",
                    "request",
                    "--type",
                    "strategy_adopt",
                    "--title",
                    "t",
                ],
            )

        assert result.exit_code == 0, (result.stdout, result.stderr)
        mock_ipc.assert_called_once()
        call_args = mock_ipc.call_args
        ipc_payload = call_args[0][1]
        assert ipc_payload["expires_at"] == ""
