"""CLI ``report list`` invalid `--status` preflight 회귀 테스트 (#1462).

`ante --format json report list --status <invalid>`가 Python traceback 없이
flat JSON error (`REPORT_INVALID_STATUS`)로 종료하고, DB 접속
(`ante.core.database.Database`)이 일어나기 전에 차단되는지 검증한다.

또한 `report list --help`가 6개 ReportStatus 값
(`draft/submitted/reviewed/adopted/rejected/archived`)을 안내하는지 회귀 보호한다.

SSOT:
- enum: ``src/ante/report/models.py::ReportStatus``
- 패턴: ``src/ante/cli/commands/strategy.py:204-210``
- 계약: ``docs/specs/cli/02-design-decisions.md`` (structured error)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

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
def runner() -> CliRunner:
    """auth bypass가 적용된 CliRunner."""
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


def _mock_store_layer(reports=None):
    """`Database` + `ReportStore` 생성자 patch 헬퍼."""
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db_cls = MagicMock(return_value=db)

    store = MagicMock()
    store.initialize = AsyncMock()
    store.list_reports = AsyncMock(return_value=reports or [])
    # ``from ante.report import ReportStore`` 가 패치된 ReportStore class를 받아야
    # 한다. 호출 시 store 인스턴스를 반환한다.
    store_cls = MagicMock(return_value=store)

    return db_cls, store_cls, store


class TestReportListInvalidPreflight:
    """`report list` invalid `--status` → DB 접속 전 차단 (#1462)."""

    def test_report_list_invalid_status_rejected_before_db(self, runner) -> None:
        """invalid `--status`는 `Database` 생성 전 차단된다.

        ReportStatus enum (SSOT)에 없는 값이 들어오면 preflight가
        `REPORT_INVALID_STATUS` 구조화 에러로 종료시키며, DB 생성자는
        호출되지 않아야 한다.
        """
        db_cls = MagicMock()
        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.cli.main.get_db_path", return_value="/tmp/unused-report.db"),
        ):
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
        assert result.exit_code == 1, result.output
        data = json.loads(result.output.strip())
        assert data["status"] == "error"
        assert data["code"] == "REPORT_INVALID_STATUS"
        assert "oracle_invalid_status" in data["message"]
        assert "Traceback" not in result.output
        db_cls.assert_not_called()


class TestReportListValidStatus:
    """`report list` valid `--status`는 회귀 없이 정상 동작 (#1462)."""

    def test_report_list_valid_status_still_works(self, runner, tmp_path) -> None:
        """valid `--status`는 preflight 통과 후 ReportStore.list_reports 호출.

        #2114: `report list` 는 read-only DB artifact 조회 경로로 확대되어
        `open_cli_db(read_only=True)` 를 거친다 → `Database(db_path,
        read_only=True)` 로 생성되고 `ReportStore.initialize()` (DDL) 는
        호출되지 않는다 (backtest history #1974 / data list #1984 동형).
        """
        db_cls, store_cls, store = _mock_store_layer([])
        db_path = str(tmp_path / "report.db")
        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.report.ReportStore", store_cls),
            patch("ante.cli.main.get_db_path", return_value=db_path),
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
        assert result.exit_code == 0, result.output
        db_cls.assert_called_once_with(db_path, read_only=True)
        # read-only 조회는 schema DDL 부트스트랩(initialize)을 발화하지 않는다.
        store.initialize.assert_not_called()
        store.list_reports.assert_awaited_once_with(
            status=ReportStatus.SUBMITTED,
        )

    def test_report_list_no_status_still_works(self, runner, tmp_path) -> None:
        """`--status` 미지정 시 ReportStore.list_reports(status=None) 호출."""
        db_cls, store_cls, store = _mock_store_layer([])
        db_path = str(tmp_path / "report.db")
        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.report.ReportStore", store_cls),
            patch("ante.cli.main.get_db_path", return_value=db_path),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "report", "list"],
            )
        assert result.exit_code == 0, result.output
        store.list_reports.assert_awaited_once_with(status=None)


class TestReportListHelpString:
    """`report list --help`가 ReportStatus 6개 값을 안내 (#1462)."""

    def test_help_lists_all_six_statuses(self, runner) -> None:
        """help 문자열은 ReportStatus enum 값 6개를 모두 포함한다."""
        result = runner.invoke(cli, ["report", "list", "--help"])
        assert result.exit_code == 0, result.output
        expected = (
            "draft",
            "submitted",
            "reviewed",
            "adopted",
            "rejected",
            "archived",
        )
        for value in expected:
            assert value in result.output, (
                f"`report list --help`에 '{value}' status가 없습니다: {result.output}"
            )
