"""ante update CLI 명령 단위 테스트."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli


@pytest.fixture()
def runner() -> CliRunner:
    """인증 우회 CliRunner.

    #1404: ``AuthenticatedGroup`` leaf wrapper가 토큰을 강제하므로 master
    멤버 stub을 ``ctx.obj["member"]``에 채워야 한다.
    """
    from ante.member.models import Member, MemberRole, MemberType

    _master = Member(
        member_id="update-test-master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Update Test Master",
        status="active",
        scopes=[],
    )

    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.ensure_object(dict)
                ctx.obj["member"] = _master

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


class TestUpdateCheckFlag:
    """--check 옵션 테스트."""

    def test_check_shows_update_available(self, runner: CliRunner) -> None:
        """PyPI에 더 높은 버전이 있으면 업데이트 가능 메시지를 출력한다."""
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=False),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="2.0.0"),
        ):
            result = runner.invoke(cli, ["update", "--check"])

        assert result.exit_code == 0
        assert "현재 버전: 1.0.0" in result.output
        assert "업데이트 가능: 1.0.0" in result.output
        assert "2.0.0" in result.output

    def test_check_shows_already_latest(self, runner: CliRunner) -> None:
        """이미 최신 버전이면 '이미 최신 버전입니다' 메시지를 출력한다."""
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=False),
            patch("ante.update.checker.get_current_version", return_value="2.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="2.0.0"),
        ):
            result = runner.invoke(cli, ["update", "--check"])

        assert result.exit_code == 0
        assert "이미 최신 버전입니다" in result.output


class TestServerRunningBlock:
    """서버 실행 중 게이트 우선순위 테스트 (#1626).

    의도 변경(#1626 D1/D3): 이전 ``test_server_running_blocks_update``는
    서버 실행 중 ``ante update --check``이 server-running으로 차단(exit 1)
    되는 buggy 순서를 정상으로 단언했다. 그러나 SSOT
    (``docs/specs/cli/02-design-decisions.md`` 위험 명령 확인 방식 +
    precedence normative 규칙)는 ``--check``을 dry-run으로 server-running과
    무관하게(최우선) 처리하도록 명시한다. 따라서 본 클래스는 spec 정합
    의미로 갱신한다 — server-running 차단이 적용되는 경로는 ``--check``이
    아닌 실제 update 호출(``--yes`` 게이트 통과 후)이다.
    """

    def test_check_not_blocked_by_server_running(self, runner: CliRunner) -> None:
        """서버 실행 중이어도 ``--check`` dry-run은 차단되지 않는다 (#1626 D3).

        SSOT: ``--check``은 PyPI 버전 조회만 수행하는 dry-run으로
        ``--yes``/server-running과 무관하며 최우선으로 처리된다.
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="2.0.0"),
        ):
            result = runner.invoke(cli, ["update", "--check"])

        assert result.exit_code == 0
        assert "서버가 실행 중입니다" not in result.output
        assert "업데이트 가능: 1.0.0" in result.output

    def test_server_running_without_yes_returns_confirmation_required(
        self, runner: CliRunner
    ) -> None:
        """서버 실행 + ``--yes`` 누락 → ``CLI_CONFIRMATION_REQUIRED`` (#1626 D1).

        spec precedence: confirmation gate가 server 상태 검사보다 우선.
        server-running 안내(``UPDATE_SERVER_RUNNING``)가 아닌
        ``CLI_CONFIRMATION_REQUIRED``로 거절되어야 한다.
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
        ):
            result = runner.invoke(cli, ["--format", "json", "update"], input=None)

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["code"] == "CLI_CONFIRMATION_REQUIRED"
        assert "--yes" in data["message"]

    def test_server_running_with_yes_without_force_returns_server_running(
        self, runner: CliRunner
    ) -> None:
        """서버 실행 + ``--yes`` + ``--force`` 없음 → ``UPDATE_SERVER_RUNNING``.

        #1626 D2: server-running 에러 코드는 ``UPDATE_SERVER_RUNNING``이며
        ``code`` 가 null 이 아니어야 한다 (이전 buggy 동작은 code=null).
        """
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=True),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "update", "--yes"], input=None
            )

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["code"] == "UPDATE_SERVER_RUNNING"
        assert data["code"] is not None
        assert "서버가 실행 중입니다" in data["message"]


class TestUpdateChecker:
    """checker 모듈 단위 테스트."""

    def test_is_update_available_true(self) -> None:
        from ante.update.checker import is_update_available

        assert is_update_available("1.0.0", "1.1.0") is True

    def test_is_update_available_false_same(self) -> None:
        from ante.update.checker import is_update_available

        assert is_update_available("1.0.0", "1.0.0") is False

    def test_is_update_available_false_lower(self) -> None:
        from ante.update.checker import is_update_available

        assert is_update_available("2.0.0", "1.0.0") is False

    def test_is_update_available_invalid_version(self) -> None:
        from ante.update.checker import is_update_available

        assert is_update_available("invalid", "also-invalid") is False

    def test_get_current_version_fallback(self) -> None:
        from ante.update.checker import get_current_version

        with patch(
            "ante.update.checker.pkg_version",
            side_effect=Exception("not installed"),
        ):
            assert get_current_version() == "dev"

    def test_get_latest_version_failure(self) -> None:
        from ante.update.checker import get_latest_version

        with patch(
            "ante.update.checker.urllib.request.urlopen",
            side_effect=Exception("network error"),
        ):
            assert get_latest_version() is None
