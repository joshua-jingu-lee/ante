"""ante feed init CLI 커맨드 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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
    """인증된 상태의 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # type: ignore[no-untyped-def]
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx: object) -> None:
                import click

                ctx = click.get_current_context()
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


@pytest.fixture
def data_path(tmp_path: Path) -> str:
    """임시 데이터 디렉토리 경로 (문자열)."""
    return str(tmp_path / "data")


def _invoke_init(runner: CliRunner, data_path: str) -> object:
    """feed init 커맨드를 실행한다."""
    return runner.invoke(
        cli,
        ["feed", "init", data_path],
        catch_exceptions=False,
    )


class TestFeedInit:
    def test_creates_config_toml(self, runner: CliRunner, data_path: str) -> None:
        result = _invoke_init(runner, data_path)
        config_path = Path(data_path) / ".feed" / "config.toml"
        assert config_path.exists(), f"config.toml 미생성. 출력: {result.output}"

    def test_creates_checkpoints_dir(self, runner: CliRunner, data_path: str) -> None:
        _invoke_init(runner, data_path)
        checkpoints = Path(data_path) / ".feed" / "checkpoints"
        assert checkpoints.is_dir()

    def test_creates_reports_dir(self, runner: CliRunner, data_path: str) -> None:
        _invoke_init(runner, data_path)
        reports = Path(data_path) / ".feed" / "reports"
        assert reports.is_dir()

    def test_output_contains_created_paths(
        self, runner: CliRunner, data_path: str
    ) -> None:
        result = _invoke_init(runner, data_path)
        assert "Created" in result.output

    def test_output_contains_api_key_guide(
        self, runner: CliRunner, data_path: str
    ) -> None:
        result = _invoke_init(runner, data_path)
        assert "API 키 설정이 필요합니다" in result.output

    def test_idempotent_second_call(self, runner: CliRunner, data_path: str) -> None:
        _invoke_init(runner, data_path)
        result = _invoke_init(runner, data_path)
        # 두 번째 실행도 오류 없이 완료되어야 함
        assert result.exit_code == 0

    def test_exit_code_zero_on_success(self, runner: CliRunner, data_path: str) -> None:
        result = _invoke_init(runner, data_path)
        assert result.exit_code == 0
