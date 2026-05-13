"""CLI report list --status invalid 입력 검증 회귀 테스트 (#1462).

`ante --format json report list --status <invalid>`가 Python traceback이 아닌
flat JSON error(`REPORT_VALIDATION_ERROR`)로 종료하는지, heavy `ante.report`
패키지 진입이 선제 차단되는지 검증한다. #1461 strategy list 패턴을 따른다.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.commands.report import VALID_REPORT_STATUSES
from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from ante.report.models import ReportStatus

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
def runner():
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


class TestReportListInvalidStatus:
    """`report list --status <invalid>` 입력 검증 (#1462)."""

    def test_invalid_status_json_returns_flat_error(self, runner):
        """JSON 모드: invalid status → exit 1 + flat JSON error."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "report",
                "list",
                "--status",
                "oracle_invalid_status",
            ],
        )
        assert result.exit_code == 1
        data = json.loads(result.output.strip())
        assert data["status"] == "error"
        assert data["code"] == "REPORT_VALIDATION_ERROR"
        assert "oracle_invalid_status" in data["message"]
        assert "Traceback" not in result.output

    def test_invalid_status_does_not_invoke_service(self, runner):
        """invalid status는 `_list` coroutine을 실행하지 않는다 (preflight)."""
        with patch(
            "ante.cli.commands.report.asyncio.run",
        ) as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "list",
                    "--status",
                    "oracle_invalid_status",
                ],
            )
            assert result.exit_code == 1
            mock_run.assert_not_called()

    def test_invalid_status_text_mode(self):
        """text 모드: invalid status → exit 1 + stderr `Error: ...`, stdout 비어있음."""
        if "mix_stderr" in inspect.signature(CliRunner).parameters:
            r = CliRunner(mix_stderr=False)
        else:
            r = CliRunner()

        with (
            patch("ante.cli.main.authenticate_member") as mock_auth,
            patch("ante.cli.commands.report.asyncio.run") as mock_run,
        ):

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            result = r.invoke(
                cli,
                ["report", "list", "--status", "oracle_invalid_status"],
            )

        assert result.exit_code == 1
        mock_run.assert_not_called()
        assert result.stdout == ""
        assert "Error:" in result.stderr
        assert "Traceback" not in result.stderr

    def test_no_status_passes_preflight(self, runner):
        """status 미지정 → preflight 통과 → exit 0."""
        with patch(
            "ante.cli.commands.report.asyncio.run",
            return_value=[],
        ):
            result = runner.invoke(cli, ["--format", "json", "report", "list"])
            assert result.exit_code == 0

    @pytest.mark.parametrize("valid_status", [s.value for s in ReportStatus])
    def test_valid_statuses_pass_preflight(self, runner, valid_status):
        """SSOT enum의 모든 valid value는 preflight를 통과한다."""
        with patch(
            "ante.cli.commands.report.asyncio.run",
            return_value=[],
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "report", "list", "--status", valid_status],
            )
            assert result.exit_code == 0

    def test_service_hydration_error_maps_to_report_error(self, runner):
        """service 단계의 일반 Exception은 `REPORT_ERROR`로 분류된다."""
        with patch(
            "ante.cli.commands.report.asyncio.run",
            side_effect=RuntimeError("hydration boom"),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "list",
                    "--status",
                    "submitted",
                ],
            )
            assert result.exit_code == 1
            data = json.loads(result.output.strip())
            assert data["status"] == "error"
            assert data["code"] == "REPORT_ERROR"
            assert "hydration boom" in data["message"]
            assert "Traceback" not in result.output

    def test_click_exception_propagates_without_formatter(self, runner):
        """내부에서 `click.ClickException`이 발생하면 그대로 전파된다."""
        with patch(
            "ante.cli.commands.report.asyncio.run",
            side_effect=click.UsageError("intentional click usage error"),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "list",
                    "--status",
                    "submitted",
                ],
            )
            assert result.exit_code == 2
            assert "intentional click usage error" in result.output
            assert '"code": "REPORT_ERROR"' not in result.output

    def test_preflight_set_matches_enum_ssot(self):
        """CLI preflight copy가 `ReportStatus` SSOT와 동치인지 회귀."""
        assert VALID_REPORT_STATUSES == {s.value for s in ReportStatus}
