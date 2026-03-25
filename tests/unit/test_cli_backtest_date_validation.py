"""CLI backtest run 날짜 검증 테스트."""

from __future__ import annotations

from unittest.mock import patch

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


def _make_runner():
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


class TestBacktestDateValidation:
    """backtest run 시작일/종료일 검증."""

    def test_start_after_end_returns_exit_code_1(self, tmp_path):
        """시작일이 종료일 이후이면 exit code 1."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-01-01",
                "--end",
                "2025-01-01",
            ],
        )
        assert result.exit_code == 1
        assert "시작일" in result.output

    def test_start_after_end_error_message(self, tmp_path):
        """에러 메시지에 날짜 정보가 포함된다."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-06-01",
                "--end",
                "2025-06-01",
            ],
        )
        assert result.exit_code == 1
        assert "2026-06-01" in result.output
        assert "2025-06-01" in result.output

    def test_same_date_is_allowed(self, tmp_path):
        """시작일 == 종료일은 허용 (날짜 검증 통과, INVALID_DATE_RANGE 에러 없음)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2025-06-01",
                "--end",
                "2025-06-01",
            ],
        )
        # 날짜 검증 에러가 아닌 것만 확인 (이후 단계에서 다른 에러 발생 가능)
        assert "시작일" not in result.output

    def test_invalid_date_format(self, tmp_path):
        """잘못된 날짜 형식이면 exit code 1."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "not-a-date",
                "--end",
                "2025-01-01",
            ],
        )
        assert result.exit_code == 1
        assert "날짜 형식" in result.output
