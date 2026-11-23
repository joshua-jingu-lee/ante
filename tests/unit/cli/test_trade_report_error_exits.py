"""``trade``·``report`` 명령의 실패 경로 특성 테스트 (#2664 PR ①).

두 파일의 에러 출구 13곳을 JSON·text 두 모드로 하나씩 지난다. 기대값은
리터럴이다. JSON은 stdout 전체를 사전으로, text는 stderr의 줄 전체를 비교한다.
경계는 안팎 짝으로 둔다(바깥 사례는 한 인자만 바꾼다).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pydantic
import pytest
from click.testing import CliRunner, Result

from ante.cli.main import cli
from ante.core.database import OperationalError
from ante.member.models import Member, MemberRole, MemberType

_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_PYDANTIC_DOCS_VERSION = ".".join(pydantic.VERSION.split(".")[:2])

_VALID_REPORT = {
    "strategy_name": "s",
    "strategy_version": "1",
    "strategy_path": "strategies/s.py",
    "backtest_period": "2026-01-01~2026-02-01",
    "total_return_pct": 1.5,
    "total_trades": 3,
    "summary": "요약",
    "rationale": "근거",
}


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _invoke(args: list[str], *patches: Any) -> Result:
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        for p in patches:
            stack.enter_context(p)
        return runner.invoke(cli, args)


def _failing_db(message: str) -> Callable[..., Any]:
    @asynccontextmanager
    async def _open(*args: object, **kwargs: object) -> AsyncIterator[Any]:
        raise RuntimeError(message)
        yield

    return _open


def _db_yielding(db: Any) -> Callable[..., Any]:
    @asynccontextmanager
    async def _open(*args: object, **kwargs: object) -> AsyncIterator[Any]:
        yield db

    return _open


def _assert_json(result: Result, envelope: dict[str, str]) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == envelope
    assert result.stderr == ""


def _assert_text(result: Result, lines: list[str]) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert result.stderr.splitlines() == lines


def _no_trade_row() -> Any:
    db = MagicMock()
    db.fetch_one = AsyncMock(return_value=None)
    return patch("ante.cli.commands.trade.open_cli_db", new=_db_yielding(db))


def _no_report() -> tuple[Any, Any]:
    store = MagicMock()
    store.return_value.get = AsyncMock(return_value=None)
    return (
        patch("ante.cli.commands.report.open_cli_db", new=_db_yielding(MagicMock())),
        patch("ante.report.ReportStore", new=store),
    )


def _empty_performance() -> tuple[Any, Any]:
    tracker = MagicMock()
    tracker.return_value.get_daily_summary = AsyncMock(return_value=[])
    tracker.return_value.get_monthly_summary = AsyncMock(return_value=[])
    return (
        patch("ante.cli.commands.report.open_cli_db", new=_db_yielding(MagicMock())),
        patch("ante.trade.performance.PerformanceTracker", new=tracker),
    )


def _locked_performance_db() -> Any:
    db = MagicMock()
    db.fetch_all = AsyncMock(side_effect=OperationalError("database is locked"))
    return patch("ante.cli.commands.report.open_cli_db", new=_db_yielding(db))


def _failing_database_class(message: str) -> Any:
    database = MagicMock()
    database.return_value.connect = AsyncMock(side_effect=RuntimeError(message))
    return patch("ante.core.database.Database", new=database)


@pytest.fixture
def report_file(tmp_path: Path) -> Callable[[str], str]:
    def _write(content: str) -> str:
        path = tmp_path / "report.json"
        path.write_text(content, encoding="utf-8")
        return str(path)

    return _write


class TestTradeInfo:
    def test_lookup_failure_json(self) -> None:
        result = _invoke(
            ["--format", "json", "trade", "info", "t-500"],
            patch(
                "ante.cli.commands.trade.open_cli_db",
                new=_failing_db("거래 저장소 응답 없음"),
            ),
        )
        _assert_json(
            result,
            {
                "status": "error",
                "code": "TRADE_ERROR",
                "message": "거래 저장소 응답 없음",
            },
        )

    def test_lookup_failure_text(self) -> None:
        result = _invoke(
            ["--format", "text", "trade", "info", "t-500"],
            patch(
                "ante.cli.commands.trade.open_cli_db",
                new=_failing_db("거래 저장소 응답 없음"),
            ),
        )
        _assert_text(result, ["Error: TRADE_ERROR: 거래 저장소 응답 없음"])

    def test_not_found_json(self) -> None:
        result = _invoke(
            ["--format", "json", "trade", "info", "t-404"], _no_trade_row()
        )
        _assert_json(
            result,
            {
                "status": "error",
                "code": "TRADE_NOT_FOUND",
                "message": "거래를 찾을 수 없습니다: t-404",
            },
        )

    def test_not_found_text(self) -> None:
        result = _invoke(
            ["--format", "text", "trade", "info", "t-404"], _no_trade_row()
        )
        _assert_text(result, ["Error: TRADE_NOT_FOUND: 거래를 찾을 수 없습니다: t-404"])


class TestReportSubmit:
    @pytest.mark.parametrize(
        ("content", "message"),
        [
            pytest.param(
                "{bad",
                "Invalid JSON: Expecting property name enclosed in double quotes: "
                "line 1 column 2 (char 1)",
                id="invalid-json",
            ),
            pytest.param(
                "[1]",
                "Report file must be a JSON object, got list",
                id="not-object",
            ),
            pytest.param(
                json.dumps({**_VALID_REPORT, "total_trades": -1}),
                "[{'type': 'greater_than_equal', 'loc': ('total_trades',), "
                "'msg': 'Input should be greater than or equal to 0', "
                f"'url': 'https://errors.pydantic.dev/{_PYDANTIC_DOCS_VERSION}"
                "/v/greater_than_equal'}]",
                id="model-validation",
            ),
        ],
    )
    def test_validation_json(
        self, report_file: Callable[[str], str], content: str, message: str
    ) -> None:
        result = _invoke(["--format", "json", "report", "submit", report_file(content)])
        _assert_json(
            result,
            {"status": "error", "code": "REPORT_VALIDATION_ERROR", "message": message},
        )

    @pytest.mark.parametrize(
        ("content", "line"),
        [
            pytest.param(
                "{bad",
                "Error: REPORT_VALIDATION_ERROR: Invalid JSON: Expecting property "
                "name enclosed in double quotes: line 1 column 2 (char 1)",
                id="invalid-json",
            ),
            pytest.param(
                "[1]",
                "Error: REPORT_VALIDATION_ERROR: "
                "Report file must be a JSON object, got list",
                id="not-object",
            ),
            pytest.param(
                json.dumps({**_VALID_REPORT, "total_trades": -1}),
                "Error: REPORT_VALIDATION_ERROR: [{'type': 'greater_than_equal', "
                "'loc': ('total_trades',), "
                "'msg': 'Input should be greater than or equal to 0', "
                f"'url': 'https://errors.pydantic.dev/{_PYDANTIC_DOCS_VERSION}"
                "/v/greater_than_equal'}]",
                id="model-validation",
            ),
        ],
    )
    def test_validation_text(
        self, report_file: Callable[[str], str], content: str, line: str
    ) -> None:
        result = _invoke(["--format", "text", "report", "submit", report_file(content)])
        _assert_text(result, [line])

    def test_store_failure_json(
        self, report_file: Callable[[str], str], tmp_path: Path
    ) -> None:
        result = _invoke(
            [
                "--format",
                "json",
                "report",
                "submit",
                report_file(json.dumps(_VALID_REPORT)),
                "--db-path",
                str(tmp_path / "r.db"),
            ],
            _failing_database_class("리포트 DB 연결 실패"),
        )
        _assert_json(
            result,
            {
                "status": "error",
                "code": "REPORT_ERROR",
                "message": "리포트 DB 연결 실패",
            },
        )

    def test_store_failure_text(
        self, report_file: Callable[[str], str], tmp_path: Path
    ) -> None:
        result = _invoke(
            [
                "--format",
                "text",
                "report",
                "submit",
                report_file(json.dumps(_VALID_REPORT)),
                "--db-path",
                str(tmp_path / "r.db"),
            ],
            _failing_database_class("리포트 DB 연결 실패"),
        )
        _assert_text(result, ["Error: REPORT_ERROR: 리포트 DB 연결 실패"])


_INVALID_STATUS_MESSAGE = (
    "잘못된 status 값: 'bogus'. 허용값: "
    "['adopted', 'archived', 'draft', 'rejected', 'reviewed', 'submitted']"
)


class TestReportList:
    def test_invalid_status_json(self) -> None:
        result = _invoke(["--format", "json", "report", "list", "--status", "bogus"])
        _assert_json(
            result,
            {
                "status": "error",
                "code": "REPORT_INVALID_STATUS",
                "message": _INVALID_STATUS_MESSAGE,
            },
        )

    def test_invalid_status_text(self) -> None:
        result = _invoke(["--format", "text", "report", "list", "--status", "bogus"])
        _assert_text(
            result, [f"Error: REPORT_INVALID_STATUS: {_INVALID_STATUS_MESSAGE}"]
        )

    def test_listing_failure_json(self) -> None:
        result = _invoke(
            ["--format", "json", "report", "list", "--status", "adopted"],
            patch(
                "ante.cli.commands.report.open_cli_db",
                new=_failing_db("리포트 목록 조회 실패"),
            ),
        )
        _assert_json(
            result,
            {
                "status": "error",
                "code": "REPORT_ERROR",
                "message": "리포트 목록 조회 실패",
            },
        )

    def test_listing_failure_text(self) -> None:
        result = _invoke(
            ["--format", "text", "report", "list", "--status", "adopted"],
            patch(
                "ante.cli.commands.report.open_cli_db",
                new=_failing_db("리포트 목록 조회 실패"),
            ),
        )
        _assert_text(result, ["Error: REPORT_ERROR: 리포트 목록 조회 실패"])


_MONTHLY_RANGE_MESSAGE = (
    "--start/--end 옵션은 --period monthly와 함께 사용할 수 없습니다. (daily 전용)"
)
_DAILY_YEAR_MESSAGE = (
    "--year 옵션은 --period daily와 함께 사용할 수 없습니다. (monthly 전용)"
)
_YEAR_MESSAGE = "monthly --year는 양수 calendar year여야 합니다. (0 이하 거부)"


class TestReportPerformance:
    @pytest.mark.parametrize(
        ("options", "code", "message"),
        [
            pytest.param(
                ["--period", "monthly", "--start", "2026-03-02"],
                "CLI_OPTION_CONFLICT",
                _MONTHLY_RANGE_MESSAGE,
                id="monthly-start",
            ),
            pytest.param(
                ["--period", "daily", "--year", "2025"],
                "CLI_OPTION_CONFLICT",
                _DAILY_YEAR_MESSAGE,
                id="daily-year",
            ),
            pytest.param(
                ["--period", "monthly", "--year", "0"],
                "REPORT_VALIDATION_ERROR",
                _YEAR_MESSAGE,
                id="year-zero",
            ),
        ],
    )
    def test_rejected_json(self, options: list[str], code: str, message: str) -> None:
        result = _invoke(["--format", "json", "report", "performance", *options])
        _assert_json(result, {"status": "error", "code": code, "message": message})

    @pytest.mark.parametrize(
        ("options", "line"),
        [
            pytest.param(
                ["--period", "monthly", "--start", "2026-03-02"],
                f"Error: CLI_OPTION_CONFLICT: {_MONTHLY_RANGE_MESSAGE}",
                id="monthly-start",
            ),
            pytest.param(
                ["--period", "daily", "--year", "2025"],
                f"Error: CLI_OPTION_CONFLICT: {_DAILY_YEAR_MESSAGE}",
                id="daily-year",
            ),
            pytest.param(
                ["--period", "monthly", "--year", "0"],
                f"Error: REPORT_VALIDATION_ERROR: {_YEAR_MESSAGE}",
                id="year-zero",
            ),
        ],
    )
    def test_rejected_text(self, options: list[str], line: str) -> None:
        result = _invoke(["--format", "text", "report", "performance", *options])
        _assert_text(result, [line])

    @pytest.mark.parametrize(
        "options",
        [
            pytest.param(["--period", "monthly"], id="monthly-without-start"),
            pytest.param(["--period", "daily"], id="daily-without-year"),
            pytest.param(["--period", "monthly", "--year", "1"], id="year-one"),
        ],
    )
    def test_accepted_counterpart_json(self, options: list[str]) -> None:
        result = _invoke(
            ["--format", "json", "report", "performance", *options],
            *_empty_performance(),
        )
        assert result.exit_code == 0, (result.stdout, result.stderr)
        assert json.loads(result.stdout) == {
            "status": "ok",
            "message": "",
            "data": {"message": "집계 데이터가 없습니다.", "summaries": []},
        }
        assert result.stderr == ""

    @pytest.mark.parametrize("period", ["daily", "monthly"])
    def test_db_locked_json(self, period: str) -> None:
        result = _invoke(
            ["--format", "json", "report", "performance", "--period", period],
            _locked_performance_db(),
        )
        _assert_json(
            result,
            {
                "status": "error",
                "code": "EXECUTION_ERROR",
                "message": "database is locked",
            },
        )

    @pytest.mark.parametrize("period", ["daily", "monthly"])
    def test_db_locked_text(self, period: str) -> None:
        result = _invoke(
            ["--format", "text", "report", "performance", "--period", period],
            _locked_performance_db(),
        )
        _assert_text(result, ["Error: EXECUTION_ERROR: database is locked"])


class TestReportView:
    def test_lookup_failure_json(self) -> None:
        result = _invoke(
            ["--format", "json", "report", "view", "r-500"],
            patch(
                "ante.cli.commands.report.open_cli_db",
                new=_failing_db("리포트 조회 실패"),
            ),
        )
        _assert_json(
            result,
            {"status": "error", "code": "REPORT_ERROR", "message": "리포트 조회 실패"},
        )

    def test_lookup_failure_text(self) -> None:
        result = _invoke(
            ["--format", "text", "report", "view", "r-500"],
            patch(
                "ante.cli.commands.report.open_cli_db",
                new=_failing_db("리포트 조회 실패"),
            ),
        )
        _assert_text(result, ["Error: REPORT_ERROR: 리포트 조회 실패"])

    def test_not_found_json(self) -> None:
        result = _invoke(["--format", "json", "report", "view", "r-404"], *_no_report())
        _assert_json(
            result,
            {
                "status": "error",
                "code": "REPORT_NOT_FOUND",
                "message": "리포트를 찾을 수 없습니다: r-404",
            },
        )

    def test_not_found_text(self) -> None:
        result = _invoke(["--format", "text", "report", "view", "r-404"], *_no_report())
        _assert_text(
            result, ["Error: REPORT_NOT_FOUND: 리포트를 찾을 수 없습니다: r-404"]
        )
