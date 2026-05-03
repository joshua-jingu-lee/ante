"""Member CLI 비대화형 입력 계약 테스트.

이슈 #1177에서 도입한 비대화형 입력 채널을 검증한다.

- ``member revoke <id> --yes`` / 누락 시 ``CLI_CONFIRMATION_REQUIRED``
- ``member reset-password --new-password-env`` / ``--new-password-file`` 성공
- 누락 / 둘 다 지정 / env 부재·공란 / file 부재·공란 실패 케이스
- ``member regenerate-recovery-key --password-env`` / ``--password-file`` 성공
- 위 동일 실패 케이스
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType


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
        assert "--yes" in data["error"]

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
        assert "--new-password-env" in data["error"]
        assert "--new-password-file" in data["error"]

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
        assert "동시에" in data["error"]

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
        assert "--password-env" in data["error"]
        assert "--password-file" in data["error"]

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
        assert "동시에" in data["error"]

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
