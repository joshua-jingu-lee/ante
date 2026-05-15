"""Member CLI 비대화형 입력 계약 테스트.

이슈 #1177에서 도입한 비대화형 입력 채널을 검증한다.

- ``member revoke <id> --yes`` / 누락 시 ``CLI_CONFIRMATION_REQUIRED``
- ``member reset-password --new-password-env`` / ``--new-password-file`` 성공
- 누락 / 둘 다 지정 / env 부재·공란 / file 부재·공란 실패 케이스
- ``member regenerate-recovery-key --password-env`` / ``--password-file`` 성공
- 위 동일 실패 케이스
- ``member list-invalid-roles`` 두 카테고리 분리 JSON/table 출력, no-row exit 0,
  ``token_hash`` 비노출 회귀 (#1468)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.member.service import InvalidRoleScan


def _make_master() -> Member:
    """테스트용 master Member."""
    return Member(
        member_id="master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Master",
        status="active",
        scopes=[],
    )


def _mock_authenticate(ctx) -> None:  # noqa: ANN001
    """test runner 인증 우회."""
    ctx.obj["member"] = _make_master()


def _invoke_cli(args: list[str]):  # noqa: ANN202
    """CLI를 실행하고 결과를 반환한다 (인증 우회)."""
    runner = CliRunner()
    with patch("ante.cli.main.authenticate_member", side_effect=_mock_authenticate):
        return runner.invoke(
            cli,
            args,
            obj={"member": _make_master()},
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )


def _patch_create_service(
    *,
    list_members_return: list | None = None,
    revoke_return: Member | None = None,
    reset_password_side_effect: object | None = None,
    regenerate_return: str | None = None,
):
    """member._create_service를 mock하는 contextmanager."""
    service = MagicMock()
    service.list_members = AsyncMock(return_value=list_members_return or [])
    service.revoke = AsyncMock(
        return_value=revoke_return
        if revoke_return is not None
        else _make_master_with_status("revoked")
    )
    service.reset_password = AsyncMock(
        side_effect=(
            reset_password_side_effect
            if reset_password_side_effect is not None
            else None
        ),
        return_value=None,
    )
    service.regenerate_recovery_key = AsyncMock(
        return_value=regenerate_return or "ANTE-RK-NEWNEW-1234"
    )
    db = MagicMock()
    db.close = AsyncMock(return_value=None)
    return patch(
        "ante.cli.commands.member._create_service",
        new_callable=AsyncMock,
        return_value=(service, db),
    ), service


def _make_master_with_status(status: str) -> Member:
    """status를 변경한 master Member."""
    return Member(
        member_id="master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Master",
        status=status,
        scopes=[],
    )


# ── member revoke ────────────────────────────────────


class TestMemberRevokeYes:
    """`member revoke`의 --yes 비대화형 게이트."""

    def test_revoke_without_yes_fails_confirmation_required(self) -> None:
        """`--yes` 누락 시 prompt 없이 CLI_CONFIRMATION_REQUIRED로 실패."""
        # _create_service는 호출되지 않아야 한다 (게이트 통과 전 차단).
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
            revoke_return=_make_master_with_status("revoked"),
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "revoke", "agent-1"],
            )

        assert result.exit_code == 1, result.output
        service.revoke.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "CLI_CONFIRMATION_REQUIRED"
        assert "--yes" in data["message"]

    def test_revoke_with_yes_invokes_revoke(self) -> None:
        """`--yes` 명시 시 MemberService.revoke가 실행된다."""
        revoked_member = Member(
            member_id="agent-1",
            type=MemberType.AGENT,
            role=MemberRole.DEFAULT,
            org="default",
            name="Agent",
            status="revoked",
            scopes=[],
        )
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
            revoke_return=revoked_member,
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "revoke",
                    "agent-1",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        service.revoke.assert_awaited_once()
        # actor=master(관리자) 인자도 전달된다.
        call = service.revoke.await_args
        assert call.args[0] == "agent-1"
        assert call.kwargs.get("revoked_by") == "master"


# ── member reset-password ────────────────────────────


class TestMemberResetPasswordEnvFile:
    """`member reset-password`의 --new-password-env / --new-password-file."""

    def test_reset_password_via_env_succeeds(self, monkeypatch) -> None:  # noqa: ANN001
        """ANTE_NEW_PASSWORD 환경변수에서 새 패스워드를 읽어 reset_password 호출."""
        monkeypatch.setenv("ANTE_NEW_PASSWORD", "supersecret-new-password")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-TEST",
                    "--new-password-env",
                    "ANTE_NEW_PASSWORD",
                ],
            )

        assert result.exit_code == 0, result.output
        service.reset_password.assert_awaited_once()
        # (member_id, recovery_key, new_password)
        call = service.reset_password.await_args
        assert call.args[0] == "master"
        assert call.args[1] == "ANTE-RK-TEST"
        assert call.args[2] == "supersecret-new-password"

    def test_reset_password_via_file_succeeds(self, tmp_path) -> None:  # noqa: ANN001
        """파일에서 새 패스워드를 읽어 reset_password 호출 (strip 적용)."""
        pwd_file = tmp_path / "new-password"
        # trailing newline은 strip되어야 한다.
        pwd_file.write_text("file-password-99\n", encoding="utf-8")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-TEST",
                    "--new-password-file",
                    str(pwd_file),
                ],
            )

        assert result.exit_code == 0, result.output
        service.reset_password.assert_awaited_once()
        call = service.reset_password.await_args
        assert call.args[2] == "file-password-99"

    def test_reset_password_without_env_or_file_fails(
        self,
    ) -> None:
        """env/file 옵션 모두 누락 → CLI_MISSING_REQUIRED_INPUT."""
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-TEST",
                ],
            )

        assert result.exit_code == 1, result.output
        service.reset_password.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "CLI_MISSING_REQUIRED_INPUT"
        assert "--new-password-env" in data["message"]
        assert "--new-password-file" in data["message"]

    def test_reset_password_both_env_and_file_fails(
        self,
        tmp_path,  # noqa: ANN001
        monkeypatch,  # noqa: ANN001
    ) -> None:
        """env/file 옵션 둘 다 지정 → CLI_MISSING_REQUIRED_INPUT (상호 배타)."""
        monkeypatch.setenv("ANTE_NEW_PASSWORD", "envvalue")
        pwd_file = tmp_path / "new-password"
        pwd_file.write_text("filevalue", encoding="utf-8")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-TEST",
                    "--new-password-env",
                    "ANTE_NEW_PASSWORD",
                    "--new-password-file",
                    str(pwd_file),
                ],
            )

        assert result.exit_code == 1, result.output
        service.reset_password.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "CLI_MISSING_REQUIRED_INPUT"
        assert "동시에" in data["message"]

    def test_reset_password_env_unset_fails(
        self,
        monkeypatch,  # noqa: ANN001
    ) -> None:
        """존재하지 않는 환경변수 → MEMBER_PASSWORD_ENV_NOT_SET."""
        monkeypatch.delenv("ANTE_NEW_PASSWORD_DOES_NOT_EXIST", raising=False)
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-TEST",
                    "--new-password-env",
                    "ANTE_NEW_PASSWORD_DOES_NOT_EXIST",
                ],
            )

        assert result.exit_code == 1, result.output
        service.reset_password.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "MEMBER_PASSWORD_ENV_NOT_SET"

    def test_reset_password_env_empty_fails(
        self,
        monkeypatch,  # noqa: ANN001
    ) -> None:
        """공란 환경변수 → MEMBER_PASSWORD_ENV_NOT_SET."""
        monkeypatch.setenv("ANTE_NEW_PASSWORD_BLANK", "   \t\n  ")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-TEST",
                    "--new-password-env",
                    "ANTE_NEW_PASSWORD_BLANK",
                ],
            )

        assert result.exit_code == 1, result.output
        service.reset_password.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "MEMBER_PASSWORD_ENV_NOT_SET"

    def test_reset_password_file_missing_fails(
        self,
        tmp_path,  # noqa: ANN001
    ) -> None:
        """존재하지 않는 파일 → MEMBER_PASSWORD_FILE_NOT_FOUND."""
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-TEST",
                    "--new-password-file",
                    str(tmp_path / "no-such-file"),
                ],
            )

        assert result.exit_code == 1, result.output
        service.reset_password.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "MEMBER_PASSWORD_FILE_NOT_FOUND"

    def test_reset_password_file_empty_fails(
        self,
        tmp_path,  # noqa: ANN001
    ) -> None:
        """공란 파일 → MEMBER_PASSWORD_FILE_NOT_FOUND."""
        pwd_file = tmp_path / "empty"
        pwd_file.write_text("   \n\t\n", encoding="utf-8")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-TEST",
                    "--new-password-file",
                    str(pwd_file),
                ],
            )

        assert result.exit_code == 1, result.output
        service.reset_password.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "MEMBER_PASSWORD_FILE_NOT_FOUND"


# ── member regenerate-recovery-key ───────────────────


class TestMemberRegenerateRecoveryKeyEnvFile:
    """`member regenerate-recovery-key`의 --password-env / --password-file."""

    def test_regenerate_via_env_succeeds(self, monkeypatch) -> None:  # noqa: ANN001
        """ANTE_PASSWORD 환경변수에서 현재 패스워드를 읽어 regenerate 호출."""
        monkeypatch.setenv("ANTE_PASSWORD", "current-password-22")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
            regenerate_return="ANTE-RK-NEW-1111",
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                    "--password-env",
                    "ANTE_PASSWORD",
                ],
            )

        assert result.exit_code == 0, result.output
        service.regenerate_recovery_key.assert_awaited_once()
        # (member_id, password)
        call = service.regenerate_recovery_key.await_args
        assert call.args[0] == "master"
        assert call.args[1] == "current-password-22"
        data = json.loads(result.output)
        assert data["recovery_key"] == "ANTE-RK-NEW-1111"

    def test_regenerate_via_file_succeeds(self, tmp_path) -> None:  # noqa: ANN001
        """파일에서 현재 패스워드를 읽어 regenerate 호출."""
        pwd_file = tmp_path / "password"
        pwd_file.write_text("file-current-pwd\n", encoding="utf-8")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
            regenerate_return="ANTE-RK-NEW-2222",
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                    "--password-file",
                    str(pwd_file),
                ],
            )

        assert result.exit_code == 0, result.output
        service.regenerate_recovery_key.assert_awaited_once()
        call = service.regenerate_recovery_key.await_args
        assert call.args[1] == "file-current-pwd"

    def test_regenerate_without_env_or_file_fails(self) -> None:
        """env/file 옵션 모두 누락 → CLI_MISSING_REQUIRED_INPUT."""
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                ],
            )

        assert result.exit_code == 1, result.output
        service.regenerate_recovery_key.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "CLI_MISSING_REQUIRED_INPUT"
        assert "--password-env" in data["message"]
        assert "--password-file" in data["message"]

    def test_regenerate_both_env_and_file_fails(
        self,
        tmp_path,  # noqa: ANN001
        monkeypatch,  # noqa: ANN001
    ) -> None:
        """env/file 옵션 둘 다 지정 → CLI_MISSING_REQUIRED_INPUT (상호 배타)."""
        monkeypatch.setenv("ANTE_PASSWORD", "envvalue")
        pwd_file = tmp_path / "password"
        pwd_file.write_text("filevalue", encoding="utf-8")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                    "--password-env",
                    "ANTE_PASSWORD",
                    "--password-file",
                    str(pwd_file),
                ],
            )

        assert result.exit_code == 1, result.output
        service.regenerate_recovery_key.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "CLI_MISSING_REQUIRED_INPUT"
        assert "동시에" in data["message"]

    def test_regenerate_env_unset_fails(
        self,
        monkeypatch,  # noqa: ANN001
    ) -> None:
        """존재하지 않는 환경변수 → MEMBER_PASSWORD_ENV_NOT_SET."""
        monkeypatch.delenv("ANTE_PASSWORD_DOES_NOT_EXIST", raising=False)
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                    "--password-env",
                    "ANTE_PASSWORD_DOES_NOT_EXIST",
                ],
            )

        assert result.exit_code == 1, result.output
        service.regenerate_recovery_key.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "MEMBER_PASSWORD_ENV_NOT_SET"

    def test_regenerate_env_empty_fails(
        self,
        monkeypatch,  # noqa: ANN001
    ) -> None:
        """공란 환경변수 → MEMBER_PASSWORD_ENV_NOT_SET."""
        monkeypatch.setenv("ANTE_PASSWORD_BLANK", "   ")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                    "--password-env",
                    "ANTE_PASSWORD_BLANK",
                ],
            )

        assert result.exit_code == 1, result.output
        service.regenerate_recovery_key.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "MEMBER_PASSWORD_ENV_NOT_SET"

    def test_regenerate_file_missing_fails(
        self,
        tmp_path,  # noqa: ANN001
    ) -> None:
        """존재하지 않는 파일 → MEMBER_PASSWORD_FILE_NOT_FOUND."""
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                    "--password-file",
                    str(tmp_path / "no-such-file"),
                ],
            )

        assert result.exit_code == 1, result.output
        service.regenerate_recovery_key.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "MEMBER_PASSWORD_FILE_NOT_FOUND"

    def test_regenerate_file_empty_fails(
        self,
        tmp_path,  # noqa: ANN001
    ) -> None:
        """공란 파일 → MEMBER_PASSWORD_FILE_NOT_FOUND."""
        pwd_file = tmp_path / "empty"
        pwd_file.write_text("\n", encoding="utf-8")
        ctx, service = _patch_create_service(
            list_members_return=[_make_master()],
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                    "--password-file",
                    str(pwd_file),
                ],
            )

        assert result.exit_code == 1, result.output
        service.regenerate_recovery_key.assert_not_awaited()
        data = json.loads(result.output)
        assert data["code"] == "MEMBER_PASSWORD_FILE_NOT_FOUND"


# ── prompt 사용 금지 회귀 ─────────────────────────────


class TestPromptApiAbsent:
    """member.py에 click.prompt / click.confirm / confirmation_option이 남지 않음."""

    def test_no_prompt_or_confirm_in_member_module(self) -> None:
        """source 텍스트 회귀 가드 — 비대화형 입력 계약 SSOT 준수."""
        from pathlib import Path

        import ante.cli.commands.member as member_module

        src = Path(member_module.__file__).read_text(encoding="utf-8")
        assert "click.prompt" not in src, "click.prompt가 member.py에 남아 있다"
        assert "click.confirm" not in src, "click.confirm이 member.py에 남아 있다"
        assert "confirmation_option" not in src, (
            "confirmation_option이 member.py에 남아 있다"
        )


# ── PermissionDeniedError 처리 회귀 ───────────────────


class TestNonMasterCliPermissionDenied:
    """비-master CLI 호출이 traceback 없이 의미 있는 메시지로 종료한다 (#1351).

    ``MemberService._assert_master``는 ``PermissionDeniedError``(``MemberError``의
    하위 클래스 — Python 내장 ``PermissionError``와 별개)를 raise한다.
    suspend / reactivate / revoke / rotate-token / register CLI 핸들러가 이
    예외를 catch하지 않으면 uncaught traceback이 노출된다(이슈 #1351 1차 Codex
    review FAIL — Finding 2).
    """

    def _patch_service_with_permission_denied(
        self,
        method_name: str,
    ):  # noqa: ANN202
        """``MemberService.<method_name>``이 ``PermissionDeniedError``를
        raise하도록 mock한 ``_create_service`` 패치 컨텍스트.
        """
        from ante.member.errors import PermissionDeniedError

        service = MagicMock()
        service.list_members = AsyncMock(return_value=[])
        denied = AsyncMock(
            side_effect=PermissionDeniedError(
                f"'{method_name}'은(는) master만 수행할 수 있습니다."
            )
        )
        setattr(service, method_name, denied)
        db = MagicMock()
        db.close = AsyncMock(return_value=None)
        return (
            patch(
                "ante.cli.commands.member._create_service",
                new_callable=AsyncMock,
                return_value=(service, db),
            ),
            service,
            denied,
        )

    def test_suspend_non_master_exits_without_traceback(self) -> None:
        ctx, _service, denied = self._patch_service_with_permission_denied("suspend")
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "suspend", "agent-1"],
            )

        assert result.exit_code == 1, result.output
        denied.assert_awaited_once()
        # JSON formatter에서 의미 있는 메시지로 종료한다 (traceback 부재).
        data = json.loads(result.output)
        assert "master" in data["message"]
        assert "Traceback" not in result.output

    def test_reactivate_non_master_exits_without_traceback(self) -> None:
        ctx, _service, denied = self._patch_service_with_permission_denied("reactivate")
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "reactivate", "agent-1"],
            )

        assert result.exit_code == 1, result.output
        denied.assert_awaited_once()
        data = json.loads(result.output)
        assert "master" in data["message"]
        assert "Traceback" not in result.output

    def test_revoke_non_master_exits_without_traceback(self) -> None:
        ctx, _service, denied = self._patch_service_with_permission_denied("revoke")
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "revoke",
                    "agent-1",
                    "--yes",
                ],
            )

        assert result.exit_code == 1, result.output
        denied.assert_awaited_once()
        data = json.loads(result.output)
        assert "master" in data["message"]
        assert "Traceback" not in result.output

    def test_rotate_token_non_master_exits_without_traceback(self) -> None:
        ctx, _service, denied = self._patch_service_with_permission_denied(
            "rotate_token"
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "rotate-token", "agent-1"],
            )

        assert result.exit_code == 1, result.output
        denied.assert_awaited_once()
        data = json.loads(result.output)
        assert "master" in data["message"]
        assert "Traceback" not in result.output

    def test_register_non_master_exits_without_traceback(self) -> None:
        ctx, _service, denied = self._patch_service_with_permission_denied("register")
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "register",
                    "--id",
                    "agent-1",
                    "--type",
                    "agent",
                ],
            )

        assert result.exit_code == 1, result.output
        denied.assert_awaited_once()
        data = json.loads(result.output)
        assert "master" in data["message"]
        assert "Traceback" not in result.output


# ── member list-invalid-roles (#1468) ─────────────────


def _make_invalid_role_member(
    member_id: str,
    *,
    role: str = "oracle_invalid_role",
    status: str = "active",
    token_hash: str = "redacted-token-hash-must-not-leak",
    token_expires_at: str = "2026-07-01 00:00:00",
    created_at: str = "2026-04-01 00:00:00",
    member_type: str = "agent",
    name: str = "",
) -> Member:
    """invalid-role legacy Member 픽스처."""
    return Member(
        member_id=member_id,
        type=member_type,
        role=role,
        org="default",
        name=name or member_id,
        status=status,
        scopes=[],
        token_hash=token_hash,
        token_expires_at=token_expires_at,
        created_at=created_at,
    )


def _patch_create_service_with_scan(scan: InvalidRoleScan):  # noqa: ANN202
    """``_create_service`` 가 invalid-role scan 만 mock 된 service 를 반환한다."""
    service = MagicMock()
    service.find_invalid_role_members = AsyncMock(return_value=scan)
    db = MagicMock()
    db.close = AsyncMock(return_value=None)
    return patch(
        "ante.cli.commands.member._create_service",
        new_callable=AsyncMock,
        return_value=(service, db),
    ), service


class TestMemberListInvalidRolesNoRows:
    """invalid-role row 가 0건일 때 CLI 동작."""

    def test_cli_list_invalid_roles_no_rows_exit_zero(self) -> None:
        """invalid row 없음 → exit 0, JSON 에 count 모두 0 + summary 노출."""
        ctx, service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[], legacy_revoked=[])
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "list-invalid-roles"],
            )

        assert result.exit_code == 0, result.output
        service.find_invalid_role_members.assert_awaited_once()
        data = json.loads(result.output)
        assert data["actionable_count"] == 0
        assert data["legacy_revoked_count"] == 0
        assert data["actionable"] == []
        assert data["legacy_revoked"] == []
        # summary 키들도 0건일 때 그대로 노출된다.
        assert data["recommended_action"] == "review_then_revoke"
        assert data["valid_roles"] == [
            MemberRole.MASTER.value,
            MemberRole.ADMIN.value,
            MemberRole.DEFAULT.value,
        ]


class TestMemberListInvalidRolesJsonSchema:
    """invalid row 가 있을 때 JSON 스키마 정확성 + token_hash 비노출."""

    def test_cli_list_invalid_roles_command_outputs_json(self) -> None:
        """JSON 출력이 본문 v2 스키마와 일치하고 token_hash 가 누설되지 않는다."""
        actionable = _make_invalid_role_member(
            "agent-bad-1",
            role="oracle_invalid_role",
            status="active",
            token_hash="HASH-MUST-NOT-LEAK-1",
        )
        legacy = _make_invalid_role_member(
            "agent-bad-revoked",
            role="oracle_invalid_role",
            status="revoked",
            token_hash="",  # revoke 후 token_hash 빈 문자열.
            token_expires_at="",
        )
        ctx, service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[legacy])
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "list-invalid-roles"],
            )

        assert result.exit_code == 0, result.output
        service.find_invalid_role_members.assert_awaited_once()

        data = json.loads(result.output)

        # top-level summary
        assert data["recommended_action"] == "review_then_revoke"
        assert data["valid_roles"] == ["master", "admin", "default"]
        assert data["actionable_count"] == 1
        assert data["legacy_revoked_count"] == 1

        # actionable row
        a = data["actionable"][0]
        assert a["member_id"] == "agent-bad-1"
        assert a["role"] == "oracle_invalid_role"
        assert a["type"] == "agent"
        assert a["name"] == "agent-bad-1"
        assert a["status"] == "active"
        assert a["created_at"] == "2026-04-01 00:00:00"
        assert a["has_token"] is True
        assert a["token_expires_at"] == "2026-07-01 00:00:00"
        # ``member revoke`` 가 ``--yes`` 누락 시 ``CLI_CONFIRMATION_REQUIRED`` 로
        # 실패하므로 (#1468 Codex review attempt 1, P2-B), JSON payload 의
        # ``revoke_command`` 는 ``--yes`` 를 포함해 즉시 실행 가능해야 한다.
        # 또한 attempt 2 P2-A: ``member_id`` 를 ``shlex.quote`` 로 셸 안전 인용
        # 하고, 옵션/포지셔널 경계는 ``--`` separator 로 명시한다.
        assert a["revoke_command"] == "ante member revoke --yes -- agent-bad-1"

        # legacy revoked row
        legacy_row = data["legacy_revoked"][0]
        assert legacy_row["member_id"] == "agent-bad-revoked"
        assert legacy_row["status"] == "revoked"
        # token_hash 빈 문자열 → has_token False, token_expires_at == null
        assert legacy_row["has_token"] is False
        assert legacy_row["token_expires_at"] is None
        # attempt 2 P2-B: legacy_revoked row 는 이미 revoked 상태이므로
        # ``MemberService.revoke`` 가 active/suspended 만 허용해 noop 가 된다.
        # 키 자체를 누락해 "추가 조치 불요" 임을 명시한다.
        assert "revoke_command" not in legacy_row

        # 보안: 어떤 row 에도 token_hash 키가 없어야 한다.
        for row in data["actionable"] + data["legacy_revoked"]:
            assert "token_hash" not in row, (
                f"token_hash 가 출력에 포함되어서는 안 된다: {row}"
            )
        # raw token hash 문자열도 출력에 등장하지 않는다.
        assert "HASH-MUST-NOT-LEAK-1" not in result.output

    def test_cli_list_invalid_roles_revoke_command_includes_yes_flag(self) -> None:
        """actionable row 의 ``revoke_command`` 가 ``--yes`` 를 포함한다 (#1468 회귀).

        ``ante member revoke`` 는 ``--yes`` 누락 시 prompt 없이
        ``CLI_CONFIRMATION_REQUIRED`` 로 실패하므로, JSON payload 가 권장 명령으로
        ``--yes`` 없는 형태를 출력하면 운영자가 그대로 복붙해도 실패한다.
        본 명령은 즉시 실행 가능한 형태여야 한다.

        attempt 2 P2-B 후속: legacy_revoked row 는 ``revoke_command`` 키 자체가
        포함되지 않으므로 (이미 revoked → MemberService.revoke 가 noop 으로 실패),
        본 어서션은 ``actionable`` 카테고리에만 적용한다.
        """
        actionable = _make_invalid_role_member(
            "agent-must-have-yes", role="oracle_invalid_role", status="active"
        )
        legacy = _make_invalid_role_member(
            "legacy-also-yes",
            role="oracle_invalid_role",
            status="revoked",
            token_hash="",
            token_expires_at="",
        )
        ctx, _service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[legacy])
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "list-invalid-roles"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        # actionable 카테고리만 ``revoke_command`` 를 갖고, 형식은
        # ``ante member revoke --yes -- <quoted member_id>`` 다.
        for row in data["actionable"]:
            cmd = row["revoke_command"]
            assert "--yes" in cmd, (
                f"revoke_command 는 ``--yes`` 를 포함해야 한다: {cmd!r}"
            )
            # `member_id` 가 셸 메타문자를 포함하지 않는 단순 토큰일 때
            # ``shlex.quote`` 는 따옴표 없이 그대로 반환한다.
            assert cmd == f"ante member revoke --yes -- {row['member_id']}"
        # legacy_revoked row 에는 키 자체가 없다 (P2-B).
        for row in data["legacy_revoked"]:
            assert "revoke_command" not in row, (
                f"legacy_revoked row 는 revoke_command 키를 가지면 안 된다: {row!r}"
            )

    def test_cli_list_invalid_roles_revoke_command_shell_safe_quotes_member_id(
        self,
    ) -> None:
        """공백/메타문자가 든 ``member_id`` 는 ``shlex.quote`` 로 안전 인용된다.

        attempt 2 P2-A: ``member_id`` 는 service/API 에서 형식 제한이 없는
        문자열이라 공백/셸 메타문자/`-`-prefix 가 들어갈 수 있다. 운영자가 payload
        를 복사 실행할 때 인자 splitting / 옵션 파싱 / 셸 substitution 위험이
        없도록 actionable row 의 ``revoke_command`` 는 반드시 ``shlex.quote`` 결과
        를 포함해야 한다.
        """
        import shlex as _shlex

        unsafe_id = "agent bad id"  # 공백 포함 → quote 후 따옴표 감싸짐.
        actionable = _make_invalid_role_member(
            unsafe_id, role="oracle_invalid_role", status="active"
        )
        ctx, _service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[])
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "list-invalid-roles"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        cmd = data["actionable"][0]["revoke_command"]
        quoted = _shlex.quote(unsafe_id)
        # quote 결과는 단순 토큰이 아니라 따옴표로 감싼 형태여야 한다.
        assert quoted != unsafe_id, (
            "테스트 가정: 공백이 든 id 는 shlex.quote 가 따옴표로 감싼다"
        )
        assert cmd == f"ante member revoke --yes -- {quoted}"
        # 원본 공백 id 가 그대로 끼지 않았음을 확인한다 (인용된 형태만 노출).
        assert f"-- {unsafe_id}" not in cmd

    def test_cli_list_invalid_roles_revoke_command_preserves_config_dir(
        self,
        tmp_path,  # noqa: ANN001
    ) -> None:
        """루트 ``--config-dir`` 가 ``revoke_command`` 에 보존 (#1468 attempt 3).

        ``ante --config-dir /path member list-invalid-roles`` 로 다른 인스턴스를
        스캔할 때, payload 의 ``revoke_command`` 가 ``--config-dir`` 을 누락하면
        운영자가 그대로 복사 실행했을 때 default config_dir DB 에 실행되어
        엉뚱한 인스턴스를 건드린다. 본 회귀 테스트는 actionable row 의
        ``revoke_command`` 가 동일한 ``--config-dir`` 을 ``shlex.quote`` 인용된
        형태로 보존하는지 검증한다.
        """
        import shlex as _shlex

        custom_dir = tmp_path / "ante-custom"
        custom_dir.mkdir()
        actionable = _make_invalid_role_member(
            "agent-other-instance", role="oracle_invalid_role", status="active"
        )
        ctx, _service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[])
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "--config-dir",
                    str(custom_dir),
                    "member",
                    "list-invalid-roles",
                ],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        cmd = data["actionable"][0]["revoke_command"]
        # attempt 4 P2: payload 는 ``expanduser().resolve()`` 로 정규화된
        # 절대 경로를 싣는다. tmp_path 는 이미 절대 경로지만 macOS 등에서는
        # ``/var/...`` → ``/private/var/...`` symlink 해소가 발생할 수 있으므로
        # ``resolve()`` 결과를 기준으로 비교한다.
        quoted_dir = _shlex.quote(str(custom_dir.resolve()))
        # ``--config-dir`` 인자가 ``ante`` 와 ``member`` 사이에 들어가며,
        # 경로는 절대 경로 + ``shlex.quote`` 인용된 형태로 보존된다.
        assert cmd == (
            f"ante --config-dir {quoted_dir} "
            f"member revoke --yes -- agent-other-instance"
        )
        # 회귀: ``--yes`` / ``--`` separator / quoted member_id 도 같이 유지된다.
        assert "--yes" in cmd
        assert " -- " in cmd

    def test_cli_list_invalid_roles_revoke_command_quotes_config_dir_with_spaces(
        self,
        tmp_path,  # noqa: ANN001
    ) -> None:
        """``--config-dir`` 경로에 공백이 있어도 ``shlex.quote`` 로 안전 인용된다.

        macOS 의 ``~/Library/Application Support/...`` 같은 공백 포함 경로에서
        운영자가 payload 를 복사 실행할 때 인자 splitting 으로 ``--config-dir``
        값이 첫 토큰만 잡히는 사고를 막는다 (#1468 attempt 3 P2 회귀).
        """
        import shlex as _shlex

        spaced_dir = tmp_path / "ante config with space"
        spaced_dir.mkdir()
        actionable = _make_invalid_role_member(
            "agent-space-dir", role="oracle_invalid_role", status="active"
        )
        ctx, _service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[])
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "--config-dir",
                    str(spaced_dir),
                    "member",
                    "list-invalid-roles",
                ],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        cmd = data["actionable"][0]["revoke_command"]
        # attempt 4 P2: ``resolve()`` 후 절대 경로 기준으로 quote 비교한다.
        resolved_spaced = spaced_dir.resolve()
        quoted_dir = _shlex.quote(str(resolved_spaced))
        # quote 가 따옴표로 감싼 형태여야 한다 (단순 토큰이 아님).
        assert quoted_dir != str(resolved_spaced)
        assert cmd == (
            f"ante --config-dir {quoted_dir} member revoke --yes -- agent-space-dir"
        )

    def test_cli_list_invalid_roles_revoke_command_omits_config_dir_when_default(
        self,
    ) -> None:
        """``--config-dir`` 미지정 시 ``revoke_command`` 에 인자가 들어가지 않는다.

        default config_dir 케이스에서 기존 호출 형태(``ante member revoke ...``)
        를 유지해 운영자 워크플로우/문서를 깨지 않게 한다. 본 회귀 테스트는
        existing test_cli_list_invalid_roles_command_outputs_json 과 함께 default
        형태가 보존됨을 명시적으로 확인한다.
        """
        actionable = _make_invalid_role_member(
            "agent-default-instance", role="oracle_invalid_role", status="active"
        )
        ctx, _service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[])
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "list-invalid-roles"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        cmd = data["actionable"][0]["revoke_command"]
        # default 일 때는 ``--config-dir`` 인자가 아예 없는 표준 형태.
        assert cmd == "ante member revoke --yes -- agent-default-instance"
        assert "--config-dir" not in cmd

    def test_cli_list_invalid_roles_revoke_command_normalizes_relative_config_dir(
        self,
        tmp_path,  # noqa: ANN001
    ) -> None:
        """상대 ``--config-dir`` 도 payload 에서는 **절대 경로** 로 정규화된다.

        attempt 4 P2: 운영자가 ``ante --config-dir custom member
        list-invalid-roles`` 처럼 상대 경로로 호출한 경우, payload 의
        ``revoke_command`` 가 raw ``custom`` 을 그대로 들고 있으면 그 payload 를
        다른 CWD 에서 복사 실행했을 때 새로운 CWD 아래의 ``custom`` 디렉토리를
        가리켜 다른 인스턴스 DB 에 실행될 위험이 있다. ``_explicit_config_dir``
        가 ``Path.expanduser().resolve()`` 로 절대 경로화하므로 payload 는
        실행 위치에 관계없이 처음 스캔한 인스턴스를 가리킨다.

        ``tmp_path`` 안에 상대 디렉토리를 만들고 CliRunner 의 isolated_filesystem
        으로 그 부모를 CWD 로 잡은 뒤, ``--config-dir custom`` 으로 호출한다.
        payload 에는 ``str((cwd / "custom").resolve())`` 가 들어가야 한다.
        """
        import os
        import shlex as _shlex
        from pathlib import Path as _Path

        # tmp_path 내에 상대 경로로 접근할 디렉토리를 미리 만든다.
        # isolated_filesystem 이 잡는 CWD 아래에 동일 이름이 존재해야
        # ``--config-dir custom`` (상대) 해석이 의미를 갖는다.
        relative_name = "custom"
        actionable = _make_invalid_role_member(
            "agent-relative-cfg", role="oracle_invalid_role", status="active"
        )
        ctx, _service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[])
        )

        runner = CliRunner()
        with ctx, runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
            # 상대 경로 ``custom`` 이 가리킬 절대 위치.
            absolute_target = (_Path(cwd) / relative_name).resolve()
            absolute_target.mkdir(parents=True, exist_ok=True)
            assert not os.path.isabs(relative_name)  # 가정: 상대 경로
            with patch(
                "ante.cli.main.authenticate_member", side_effect=_mock_authenticate
            ):
                result = runner.invoke(
                    cli,
                    [
                        "--format",
                        "json",
                        "--config-dir",
                        relative_name,
                        "member",
                        "list-invalid-roles",
                    ],
                    obj={"member": _make_master()},
                    env={"ANTE_MEMBER_TOKEN": ""},
                    catch_exceptions=False,
                )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        cmd = data["actionable"][0]["revoke_command"]
        # 핵심 회귀: payload 의 ``--config-dir`` 값은 **절대 경로** 다.
        # raw ``custom`` 이 그대로 들어가면 다른 CWD 실행 시 인스턴스가 바뀐다.
        assert f"--config-dir {relative_name} " not in cmd, (
            "attempt 4 회귀: payload 에 raw 상대 경로가 그대로 들어가면 안 된다: "
            f"{cmd!r}"
        )
        # 정규화된 절대 경로(``shlex.quote``)가 들어가야 한다.
        quoted_abs = _shlex.quote(str(absolute_target))
        assert cmd == (
            f"ante --config-dir {quoted_abs} member revoke --yes -- agent-relative-cfg"
        )
        # 추가 invariant: payload 의 ``--config-dir`` 토큰 다음 값은 절대 경로
        # (``/`` 로 시작) 여야 한다.
        cfg_token_value_start = cmd.index("--config-dir ") + len("--config-dir ")
        # quote 가 따옴표로 감쌌으면 첫 char 는 따옴표일 수도 있으므로
        # 따옴표/슬래시 둘 중 하나로 시작해야 한다.
        first_char = cmd[cfg_token_value_start]
        assert first_char in ("/", "'", '"'), (
            "payload 의 --config-dir 값은 절대 경로(또는 quoted 절대 경로)여야 한다:"
            f" {cmd!r}"
        )

    def test_cli_list_invalid_roles_legacy_revoked_omits_revoke_command(self) -> None:
        """legacy_revoked row 의 JSON dict 에 ``revoke_command`` 키가 없다.

        attempt 2 P2-B: legacy_revoked row 는 이미 ``status=revoked`` 다.
        ``MemberService.revoke`` 가 active/suspended 만 허용하므로 재실행 시
        실패한다. payload 에 noop 명령을 싣지 않고 키 자체를 누락해 "추가 조치
        불요" 임을 명시한다.
        """
        legacy_only = _make_invalid_role_member(
            "legacy-revoked-1",
            role="oracle_invalid_role",
            status="revoked",
            token_hash="",
            token_expires_at="",
        )
        ctx, _service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[], legacy_revoked=[legacy_only])
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "list-invalid-roles"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["legacy_revoked_count"] == 1
        legacy_row = data["legacy_revoked"][0]
        assert legacy_row["member_id"] == "legacy-revoked-1"
        assert legacy_row["status"] == "revoked"
        # 핵심 회귀: revoke_command 키가 없어야 한다 (None 도 아님).
        assert "revoke_command" not in legacy_row, (
            f"legacy_revoked row 의 dict 키 목록: {list(legacy_row.keys())}"
        )


class TestMemberListInvalidRolesTable:
    """text(table) 모드에서 두 섹션이 모두 표시된다."""

    def test_cli_list_invalid_roles_command_outputs_table(self) -> None:
        """text 모드 — actionable + legacy_revoked 두 섹션 표시."""
        actionable = _make_invalid_role_member(
            "agent-bad-active", role="oracle_invalid_role", status="active"
        )
        legacy = _make_invalid_role_member(
            "agent-bad-revoked",
            role="oracle_invalid_role",
            status="revoked",
            token_hash="",
            token_expires_at="",
        )
        ctx, _service = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[legacy])
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "text", "member", "list-invalid-roles"],
            )

        assert result.exit_code == 0, result.output
        # 두 섹션 헤더가 모두 노출되어야 한다.
        assert "[actionable]" in result.output
        assert "[legacy_revoked]" in result.output
        # 각 row 의 member_id 도 표시된다.
        assert "agent-bad-active" in result.output
        assert "agent-bad-revoked" in result.output
        # summary 도 표시.
        assert "review_then_revoke" in result.output
        # text 모드여도 token_hash 는 누출되지 않는다.
        assert "token_hash" not in result.output


class TestMemberListInvalidRolesTokenHashRegression:
    """``token_hash`` 가 모든 출력 모드에서 노출되지 않는다 (#1468 secret-exposure)."""

    def test_cli_list_invalid_roles_does_not_expose_token_hash(self) -> None:
        """JSON 모드 + text 모드 모두에서 token_hash 비노출 회귀."""
        sensitive_hash = "TOP-SECRET-HASH-VALUE-DO-NOT-LEAK"
        actionable = _make_invalid_role_member(
            "agent-bad",
            role="oracle_invalid_role",
            status=MemberStatus.ACTIVE.value,
            token_hash=sensitive_hash,
        )
        # JSON 모드
        ctx_json, _svc_json = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[])
        )
        with ctx_json:
            result_json = _invoke_cli(
                ["--format", "json", "member", "list-invalid-roles"],
            )
        assert result_json.exit_code == 0, result_json.output
        assert sensitive_hash not in result_json.output
        data = json.loads(result_json.output)
        for row in data["actionable"] + data["legacy_revoked"]:
            assert "token_hash" not in row

        # text 모드
        ctx_text, _svc_text = _patch_create_service_with_scan(
            InvalidRoleScan(actionable=[actionable], legacy_revoked=[])
        )
        with ctx_text:
            result_text = _invoke_cli(
                ["--format", "text", "member", "list-invalid-roles"],
            )
        assert result_text.exit_code == 0, result_text.output
        assert sensitive_hash not in result_text.output
        assert "token_hash" not in result_text.output


# ── 오류 명령 exit code 정렬 회귀 (#1557) ──────────────


def _patch_service_method_raises(
    method_name: str,
    exc: Exception,
):  # noqa: ANN202
    """``MemberService.<method_name>`` 이 ``exc`` 를 raise 하도록 mock 한
    ``_create_service`` 패치 컨텍스트와 (service, mocked_method) 를 돌려준다.

    register 의 중복 ID(``ValueError``), set-emoji / suspend / reactivate /
    revoke / rotate-token 의 존재하지 않는 member_id(``ValueError``),
    reset-password 의 invalid recovery key(``PermissionError``),
    regenerate-recovery-key 의 invalid password(``PermissionError``) 를
    공통 픽스처로 표현한다.

    reset-password / regenerate-recovery-key 는 핸들러가 먼저
    ``service.list_members`` 로 master 를 찾으므로 그 경로도 충족시킨다.
    """
    service = MagicMock()
    service.list_members = AsyncMock(return_value=[_make_master()])
    mocked = AsyncMock(side_effect=exc)
    setattr(service, method_name, mocked)
    db = MagicMock()
    db.close = AsyncMock(return_value=None)
    return (
        patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(service, db),
        ),
        service,
        mocked,
    )


class TestMemberErrorCommandsExitNonZero:
    """오류 명령 8개가 JSON error envelope 출력 + exit 1 로 종료한다 (#1557).

    수정 전: ``except (ValueError[, PermissionError]) as e: fmt.error(str(e));
    return`` 분기가 ``status=error`` envelope 를 출력하면서도 process exit
    code 0 으로 종료해 자동화 호출자가 실패를 감지하지 못했다. fix 적용 전에는
    아래 케이스들이 FAIL(exit 0) 하고, 적용 후 PASS(exit 1) 한다.

    ``code`` 인자는 본 이슈 scope 밖(exit code only)이므로 envelope 의
    ``code`` 는 빈 문자열 그대로다 — 검증은 ``status``/``message``/exit code 만
    한다.
    """

    @pytest.mark.parametrize(
        ("command", "service_method", "exc", "args"),
        [
            pytest.param(
                "register",
                "register",
                ValueError("이미 존재하는 member_id: agent-dup"),
                [
                    "member",
                    "register",
                    "--id",
                    "agent-dup",
                    "--type",
                    "agent",
                ],
                id="register-duplicate-id",
            ),
            pytest.param(
                "set-emoji",
                "update_emoji",
                ValueError("존재하지 않는 멤버: ghost-1"),
                ["member", "set-emoji", "ghost-1", "🚀"],
                id="set-emoji-missing-member",
            ),
            pytest.param(
                "suspend",
                "suspend",
                ValueError("존재하지 않는 멤버: ghost-1"),
                ["member", "suspend", "ghost-1"],
                id="suspend-missing-member",
            ),
            pytest.param(
                "reactivate",
                "reactivate",
                ValueError("존재하지 않는 멤버: ghost-1"),
                ["member", "reactivate", "ghost-1"],
                id="reactivate-missing-member",
            ),
            pytest.param(
                "revoke",
                "revoke",
                ValueError("존재하지 않는 멤버: ghost-1"),
                ["member", "revoke", "ghost-1", "--yes"],
                id="revoke-missing-member",
            ),
            pytest.param(
                "rotate-token",
                "rotate_token",
                ValueError("존재하지 않는 멤버: ghost-1"),
                ["member", "rotate-token", "ghost-1"],
                id="rotate-token-missing-member",
            ),
        ],
    )
    def test_command_error_exits_one_with_envelope(
        self,
        command: str,
        service_method: str,
        exc: Exception,
        args: list[str],
    ) -> None:
        """존재하지 않는 member_id / 중복 ID → exit 1 + JSON error envelope."""
        ctx, _service, mocked = _patch_service_method_raises(service_method, exc)
        with ctx:
            result = _invoke_cli(["--format", "json", *args])

        assert result.exit_code == 1, (
            f"{command}: error 시 exit 1 이어야 한다\n{result.output}"
        )
        mocked.assert_awaited_once()
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["message"] == str(exc)

    def test_reset_password_invalid_recovery_key_exits_one(
        self,
        monkeypatch,  # noqa: ANN001
    ) -> None:
        """reset-password: invalid recovery key(PermissionError) → exit 1 +
        error envelope."""
        monkeypatch.setenv("ANTE_NEW_PASSWORD_1557", "new-pwd-1557")
        exc = PermissionError("유효하지 않은 recovery key")
        ctx, _service, mocked = _patch_service_method_raises("reset_password", exc)
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-INVALID",
                    "--new-password-env",
                    "ANTE_NEW_PASSWORD_1557",
                ],
            )

        assert result.exit_code == 1, result.output
        mocked.assert_awaited_once()
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["message"] == "유효하지 않은 recovery key"

    def test_regenerate_recovery_key_invalid_password_exits_one(
        self,
        monkeypatch,  # noqa: ANN001
    ) -> None:
        """regenerate-recovery-key: invalid password(PermissionError) → exit 1
        + error envelope."""
        monkeypatch.setenv("ANTE_PASSWORD_1557", "wrong-pwd-1557")
        exc = PermissionError("현재 패스워드가 일치하지 않습니다")
        ctx, _service, mocked = _patch_service_method_raises(
            "regenerate_recovery_key", exc
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                    "--password-env",
                    "ANTE_PASSWORD_1557",
                ],
            )

        assert result.exit_code == 1, result.output
        mocked.assert_awaited_once()
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["message"] == "현재 패스워드가 일치하지 않습니다"

    @pytest.mark.parametrize(
        ("service_method", "exc", "args"),
        [
            pytest.param(
                "suspend",
                ValueError("존재하지 않는 멤버: ghost-text"),
                ["member", "suspend", "ghost-text"],
                id="suspend-text-mode",
            ),
            pytest.param(
                "register",
                ValueError("이미 존재하는 member_id: dup-text"),
                [
                    "member",
                    "register",
                    "--id",
                    "dup-text",
                    "--type",
                    "agent",
                ],
                id="register-text-mode",
            ),
        ],
    )
    def test_command_error_exits_one_in_text_mode(
        self,
        service_method: str,
        exc: Exception,
        args: list[str],
    ) -> None:
        """text 모드에서도 오류 명령은 exit 1 로 종료한다 (대표 케이스)."""
        ctx, _service, mocked = _patch_service_method_raises(service_method, exc)
        with ctx:
            result = _invoke_cli(["--format", "text", *args])

        assert result.exit_code == 1, result.output
        mocked.assert_awaited_once()
        assert str(exc) in result.output

    def test_suspend_success_path_still_exits_zero(self) -> None:
        """회귀 가드: 정상 성공 경로는 exit 0 + fmt.success envelope 를 유지한다.

        exit code 정렬은 오직 오류 분기에만 적용된다. 유효 입력의 성공 응답이
        실수로 exit 1 이 되지 않음을 명시적으로 잠근다.
        """
        active_member = Member(
            member_id="agent-ok",
            type=MemberType.AGENT,
            role=MemberRole.DEFAULT,
            org="default",
            name="Agent OK",
            status="suspended",
            scopes=[],
        )
        service = MagicMock()
        service.list_members = AsyncMock(return_value=[_make_master()])
        service.suspend = AsyncMock(return_value=active_member)
        db = MagicMock()
        db.close = AsyncMock(return_value=None)
        ctx = patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(service, db),
        )
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "suspend", "agent-ok"],
            )

        assert result.exit_code == 0, result.output
        service.suspend.assert_awaited_once()
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"]["member_id"] == "agent-ok"
