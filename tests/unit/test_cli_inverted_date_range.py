"""CLI inverted date range(시작일 > 종료일) 거부 매트릭스 (#1597).

오라클 A7 finding(#1597): 4개 read/report 명령 —
``audit list --from-date/--to-date``, ``trade list --from/--to``,
``treasury snapshot --from/--to``, ``report performance --period daily
--start/--end`` — 이 inverted date range를 non-zero가 아니라 exit 0 빈
결과로 처리하던 ingress drift를 닫는다. ``backtest run``
(``src/ante/cli/commands/backtest.py:72-77``)은 이미
``INVALID_DATE_RANGE`` + ``SystemExit(1)``로 거부 중이며, 본 테스트는
공유 헬퍼 ``reject_inverted_date_range``가 나머지 4곳에 동형으로 적용된
결과를 검증한다.

검증 축:

- invalid-range(from > to): exit 1 + ``INVALID_DATE_RANGE``, 서비스/async
  경로(``_run``/Database/AuditLogger.query/get_trades/treasury/
  ``_run_performance``) **미호출** mock 단정.
- 회귀(유효): from < to / from == to / 한쪽만 / 둘 다 미지정 → exit 0.
- #1593 회귀: ``report performance --period monthly --start ... --end ...``
  은 여전히 ``CLI_OPTION_CONFLICT`` (period-exclusive 먼저, INVALID_DATE_RANGE
  아님); ``--period daily --year`` 도 ``CLI_OPTION_CONFLICT``.
- 형식 invalid(``2026-13-32``)는 기존 click 표준 경로 보존(미변경).
- JSON + text 두 포맷.

Non-Goals: web audit/treasury sibling 위험(별도 follow-up), 4곳 date
파싱 통합 리팩터, 신규 에러코드 신설.
"""

from __future__ import annotations

import inspect
import json
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


def _make_runner() -> CliRunner:
    """``mix_stderr=False`` runner. click 버전에 따라 fallback."""
    if "mix_stderr" in inspect.signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner.

    ``authenticate_member``와 ``_run_authenticate``를 모두 patch하여 실제
    DB 접근을 방지한다 (#1404 / ``test_cli_date_validation.py`` 패턴).
    """
    r = _make_runner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        def _set_member(ctx):  # noqa: ANN001
            ctx.ensure_object(dict)
            ctx.obj["member"] = _MOCK_MASTER

        with (
            patch("ante.cli.main.authenticate_member", side_effect=_set_member),
            patch("ante.cli.middleware._run_authenticate"),
        ):
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _stdout(result) -> str:
    """mix_stderr 분리 환경에서 stdout만 안전하게 추출."""
    try:
        return result.stdout
    except (ValueError, UnicodeDecodeError):
        return result.output


def _assert_invalid_date_range_json(result) -> None:
    """JSON 포맷 inverted-range 응답 공통 검증."""
    assert result.exit_code == 1
    payload = json.loads(_stdout(result))
    assert payload["status"] == "error"
    assert payload["code"] == "INVALID_DATE_RANGE"


# 각 명령의 invoke args (invalid range: from=2026-02-01 > to=2026-01-01).
_INVALID_CASES = {
    "audit": [
        "audit",
        "list",
        "--from-date",
        "2026-02-01",
        "--to-date",
        "2026-01-01",
    ],
    "trade": [
        "trade",
        "list",
        "--from",
        "2026-02-01",
        "--to",
        "2026-01-01",
    ],
    "treasury": [
        "treasury",
        "snapshot",
        "--from",
        "2026-02-01",
        "--to",
        "2026-01-01",
        "--account",
        "oracle-paper",
    ],
    "report": [
        "report",
        "performance",
        "--period",
        "daily",
        "--start",
        "2026-02-01",
        "--end",
        "2026-01-01",
    ],
}

# 각 명령의 async/service 진입점 — invalid-range 시 호출되면 안 됨.
_ASYNC_ENTRYPOINTS = {
    "audit": "ante.cli.commands.audit._run",
    "trade": "ante.cli.commands.trade._run",
    "treasury": "ante.cli.commands.treasury._run",
    "report": "ante.cli.commands.report.asyncio.run",
}


class TestInvertedRangeRejectedJson:
    """invalid range(from > to) → exit 1 + INVALID_DATE_RANGE (JSON)."""

    @pytest.mark.parametrize("cmd", list(_INVALID_CASES))
    def test_rejected_json(self, runner, cmd):
        with patch(_ASYNC_ENTRYPOINTS[cmd]) as mock_async:
            result = runner.invoke(cli, ["--format", "json", *_INVALID_CASES[cmd]])
        _assert_invalid_date_range_json(result)
        mock_async.assert_not_called()

    @pytest.mark.parametrize("cmd", list(_INVALID_CASES))
    def test_rejected_text(self, runner, cmd):
        with patch(_ASYNC_ENTRYPOINTS[cmd]) as mock_async:
            result = runner.invoke(cli, _INVALID_CASES[cmd])
        assert result.exit_code == 1
        mock_async.assert_not_called()


class TestInvertedRangeNoServiceTouch:
    """invalid range 시 Database/service 레이어 자체에 도달하지 않는다."""

    def test_audit_no_db_no_logger(self, runner):
        with (
            patch("ante.cli.commands.audit._run") as mock_run,
            patch("ante.core.database.Database") as mock_db,
            patch("ante.audit.AuditLogger") as mock_logger,
        ):
            result = runner.invoke(cli, ["--format", "json", *_INVALID_CASES["audit"]])
        _assert_invalid_date_range_json(result)
        mock_run.assert_not_called()
        mock_db.assert_not_called()
        mock_logger.assert_not_called()

    def test_trade_no_service_no_db(self, runner):
        with (
            patch("ante.cli.commands.trade._run") as mock_run,
            patch("ante.cli.commands.trade._create_trade_service") as mock_svc,
            patch("ante.core.database.Database") as mock_db,
        ):
            result = runner.invoke(cli, ["--format", "json", *_INVALID_CASES["trade"]])
        _assert_invalid_date_range_json(result)
        mock_run.assert_not_called()
        mock_svc.assert_not_called()
        mock_db.assert_not_called()

    def test_treasury_no_service_no_db(self, runner):
        with (
            patch("ante.cli.commands.treasury._run") as mock_run,
            patch("ante.cli.commands.treasury._create_treasury") as mock_svc,
            patch("ante.core.database.Database") as mock_db,
        ):
            result = runner.invoke(
                cli, ["--format", "json", *_INVALID_CASES["treasury"]]
            )
        _assert_invalid_date_range_json(result)
        mock_run.assert_not_called()
        mock_svc.assert_not_called()
        mock_db.assert_not_called()

    def test_report_no_run_performance_no_db(self, runner):
        with (
            patch("ante.cli.commands.report.asyncio.run") as mock_run,
            patch("ante.core.database.Database") as mock_db,
        ):
            result = runner.invoke(cli, ["--format", "json", *_INVALID_CASES["report"]])
        _assert_invalid_date_range_json(result)
        mock_run.assert_not_called()
        mock_db.assert_not_called()


class TestValidRangeRegression:
    """유효 조합은 회귀 없이 통과(서비스 진입 도달 — exit 0)."""

    @pytest.mark.parametrize(
        ("cmd", "args"),
        [
            (
                "audit",
                [
                    "audit",
                    "list",
                    "--from-date",
                    "2026-01-01",
                    "--to-date",
                    "2026-02-01",
                ],
            ),
            (
                "audit",
                [
                    "audit",
                    "list",
                    "--from-date",
                    "2026-01-15",
                    "--to-date",
                    "2026-01-15",
                ],
            ),
            (
                "audit",
                ["audit", "list", "--from-date", "2026-01-01"],
            ),
            (
                "audit",
                ["audit", "list", "--to-date", "2026-02-01"],
            ),
            (
                "audit",
                ["audit", "list"],
            ),
            (
                "trade",
                ["trade", "list", "--from", "2026-01-01", "--to", "2026-02-01"],
            ),
            (
                "trade",
                ["trade", "list", "--from", "2026-01-15", "--to", "2026-01-15"],
            ),
            (
                "trade",
                ["trade", "list", "--from", "2026-01-01"],
            ),
            (
                "trade",
                ["trade", "list"],
            ),
            (
                "report",
                [
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-02-01",
                ],
            ),
            (
                "report",
                [
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--start",
                    "2026-01-15",
                    "--end",
                    "2026-01-15",
                ],
            ),
            (
                "report",
                ["report", "performance", "--period", "daily", "--start", "2026-01-01"],
            ),
            (
                "report",
                ["report", "performance"],
            ),
        ],
    )
    def test_valid_passes_to_service(self, runner, cmd, args):
        with patch(_ASYNC_ENTRYPOINTS[cmd]) as mock_async:
            mock_async.return_value = []
            result = runner.invoke(cli, args)
        assert result.exit_code == 0, _stdout(result)
        mock_async.assert_called_once()

    @pytest.mark.parametrize(
        "args",
        [
            [
                "treasury",
                "snapshot",
                "--from",
                "2026-01-01",
                "--to",
                "2026-02-01",
                "--account",
                "oracle-paper",
            ],
            [
                "treasury",
                "snapshot",
                "--from",
                "2026-01-15",
                "--to",
                "2026-01-15",
                "--account",
                "oracle-paper",
            ],
            [
                "treasury",
                "snapshot",
                "--from",
                "2026-01-01",
                "--account",
                "oracle-paper",
            ],
            ["treasury", "snapshot", "--account", "oracle-paper"],
        ],
    )
    def test_treasury_valid_passes_to_service(self, runner, args):
        with patch("ante.cli.commands.treasury._run") as mock_run:
            mock_run.return_value = {
                "account_id": "oracle-paper",
                "snapshot_date": "2026-01-15",
                "total_asset": 1.0,
                "ante_eval_amount": 1.0,
                "ante_purchase_amount": 1.0,
                "unallocated": 0.0,
            }
            result = runner.invoke(cli, ["--format", "json", *args])
        assert result.exit_code == 0, _stdout(result)
        mock_run.assert_called_once()


class TestRegression1593Preserved:
    """#1593 period-exclusive 우선순위/코드 보존(순서 엄수)."""

    def test_monthly_with_start_end_still_conflict(self, runner):
        """monthly + start/end → 여전히 CLI_OPTION_CONFLICT (INVALID_DATE_RANGE 아님).

        inverted(start>end)여도 period-exclusive 검증이 먼저이므로
        CLI_OPTION_CONFLICT로 거부되어야 한다.
        """
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "monthly",
                    "--start",
                    "2026-02-01",
                    "--end",
                    "2026-01-01",
                ],
            )
        assert result.exit_code == 1
        payload = json.loads(_stdout(result))
        assert payload["code"] == "CLI_OPTION_CONFLICT"
        assert payload["code"] != "INVALID_DATE_RANGE"
        mock_run.assert_not_called()

    def test_daily_with_year_still_conflict(self, runner):
        with patch("ante.cli.commands.report.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "report",
                    "performance",
                    "--period",
                    "daily",
                    "--year",
                    "2026",
                ],
            )
        assert result.exit_code == 1
        payload = json.loads(_stdout(result))
        assert payload["code"] == "CLI_OPTION_CONFLICT"
        mock_run.assert_not_called()


class TestFormatInvalidPathPreserved:
    """형식 invalid는 기존 click.BadParameter/UsageError 경로 보존(미변경)."""

    @pytest.mark.parametrize(
        "args",
        [
            ["audit", "list", "--from-date", "2026-13-32", "--to-date", "2026-01-01"],
            ["trade", "list", "--from", "2026-13-32", "--to", "2026-01-01"],
            [
                "treasury",
                "snapshot",
                "--from",
                "2026-13-32",
                "--to",
                "2026-01-01",
                "--account",
                "oracle-paper",
            ],
            [
                "report",
                "performance",
                "--period",
                "daily",
                "--start",
                "2026-13-32",
                "--end",
                "2026-01-01",
            ],
        ],
    )
    def test_format_invalid_not_invalid_date_range(self, runner, args):
        """형식 오류는 click 표준 경로 — INVALID_DATE_RANGE가 아니다.

        click ``BadParameter``는 exit 2 + text stderr이며, 본 헬퍼는
        ``validate_iso_date`` 거부 이후 도달하지 않는다.
        """
        result = runner.invoke(cli, args)
        assert result.exit_code != 0
        assert "INVALID_DATE_RANGE" not in result.output
