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
        assert a["revoke_command"] == "ante member revoke agent-bad-1 --yes"

        # legacy revoked row
        legacy_row = data["legacy_revoked"][0]
        assert legacy_row["member_id"] == "agent-bad-revoked"
        assert legacy_row["status"] == "revoked"
        # token_hash 빈 문자열 → has_token False, token_expires_at == null
        assert legacy_row["has_token"] is False
        assert legacy_row["token_expires_at"] is None

        # 보안: 어떤 row 에도 token_hash 키가 없어야 한다.
        for row in data["actionable"] + data["legacy_revoked"]:
            assert "token_hash" not in row, (
                f"token_hash 가 출력에 포함되어서는 안 된다: {row}"
            )
        # raw token hash 문자열도 출력에 등장하지 않는다.
        assert "HASH-MUST-NOT-LEAK-1" not in result.output

    def test_cli_list_invalid_roles_revoke_command_includes_yes_flag(self) -> None:
        """``revoke_command`` 출력이 ``--yes`` 를 포함한다 (#1468 P2-B 회귀).

        ``ante member revoke`` 는 ``--yes`` 누락 시 prompt 없이
        ``CLI_CONFIRMATION_REQUIRED`` 로 실패하므로, JSON payload 가 권장 명령으로
        ``--yes`` 없는 형태를 출력하면 운영자가 그대로 복붙해도 실패한다.
        본 명령은 즉시 실행 가능한 형태여야 한다.
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
        # actionable 과 legacy_revoked 두 카테고리 모두 ``--yes`` 를 포함해야 한다.
        for row in data["actionable"] + data["legacy_revoked"]:
            cmd = row["revoke_command"]
            assert cmd.endswith(" --yes"), (
                f"revoke_command 는 ``--yes`` 로 끝나야 한다: {cmd!r}"
            )
            assert cmd == f"ante member revoke {row['member_id']} --yes"


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
