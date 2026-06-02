"""ante feed config set CLI 커맨드 테스트.

#1537: unsupported key 거부 시 --format json 일관성 회귀 방지.
"""

from __future__ import annotations

import json
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
    """인증된 상태의 CliRunner — stdout/stderr 분리."""
    r = CliRunner(mix_stderr=False)
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


class TestFeedConfigSetUnsupportedKey:
    """#1537: unsupported key 거부 경로."""

    def test_json_format_emits_envelope(
        self, runner: CliRunner, data_path: str
    ) -> None:
        """--format json: stdout JSON envelope, exit 1."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "feed",
                "config",
                "set",
                "unsupported_key",
                "value",
                "--data-path",
                data_path,
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        payload = json.loads(result.stdout.strip())
        assert payload["status"] == "error"
        assert payload["code"] == "CONFIG_UNSUPPORTED_KEY"
        assert payload["message"].startswith("지원하지 않는 키입니다: unsupported_key")
        assert "지원 키:" in payload["message"]

    def test_text_format_emits_stderr(self, runner: CliRunner, data_path: str) -> None:
        """--format text (default): stderr Error 라인, exit 1."""
        result = runner.invoke(
            cli,
            [
                "feed",
                "config",
                "set",
                "unsupported_key",
                "value",
                "--data-path",
                data_path,
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "Error: 지원하지 않는 키입니다: unsupported_key" in result.stderr
        # JSON envelope이 stdout으로 누출되지 않아야 한다.
        assert result.stdout.strip() == ""


class TestFeedConfigSetSupportedKey:
    """정상 회귀: 지원 키 저장 경로."""

    def test_supported_key_saves_and_reports_success(
        self, runner: CliRunner, data_path: str
    ) -> None:
        """ANTE_DART_API_KEY 저장 시 fmt.success 호출 + .env 파일 기록."""
        result = runner.invoke(
            cli,
            [
                "feed",
                "config",
                "set",
                "ANTE_DART_API_KEY",
                "dart_value_123",
                "--data-path",
                data_path,
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        env_path = Path(data_path) / ".feed" / ".env"
        assert env_path.exists()
        assert "ANTE_DART_API_KEY=dart_value_123" in env_path.read_text()
        assert "Saved ANTE_DART_API_KEY" in result.stdout


class TestFeedConfigSetNewlineRejection:
    """#2051: 개행 포함 value는 키 주입 위험으로 구조화 에러로 거부한다."""

    def test_json_format_rejects_newline_value(
        self, runner: CliRunner, data_path: str
    ) -> None:
        """--format json: 개행 value → exit 1 + 구조화 envelope, 키 미주입."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "feed",
                "config",
                "set",
                "ANTE_DATAGOKR_API_KEY",
                "a\nANTE_DART_API_KEY=evil",
                "--data-path",
                data_path,
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        payload = json.loads(result.stdout.strip())
        assert payload["status"] == "error"
        assert payload["code"] == "CONFIG_INVALID_VALUE"
        assert "개행" in payload["message"]
        # 거부 시 .env가 생성되지 않아 DART 키가 주입되지 않는다.
        assert not (Path(data_path) / ".feed" / ".env").exists()

    def test_text_format_rejects_newline_value(
        self, runner: CliRunner, data_path: str
    ) -> None:
        """--format text: 개행 value → stderr Error 라인, exit 1, 키 미주입."""
        result = runner.invoke(
            cli,
            [
                "feed",
                "config",
                "set",
                "ANTE_DATAGOKR_API_KEY",
                "a\nANTE_DART_API_KEY=evil",
                "--data-path",
                data_path,
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "개행" in result.stderr
        assert result.stdout.strip() == ""
        assert not (Path(data_path) / ".feed" / ".env").exists()
