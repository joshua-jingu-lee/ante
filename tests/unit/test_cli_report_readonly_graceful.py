"""``report list`` / ``report view`` table-absence graceful + 재전파 (#2114).

#2114 에서 ``report list`` / ``report view`` 를 read-only DB artifact 조회
경로(``open_cli_db(read_only=True)`` + ``initialize()`` 미호출)로 확대하면서,
``reports`` 테이블이 아직 부트스트랩되지 않은 DB 에서는 SELECT 가
``sqlite3.OperationalError: no such table: reports`` 로 실패한다. 본 모듈은:

- G1: ``reports`` 테이블 부재 → ``report list`` 는 빈 목록, ``report view`` 는
  ``REPORT_NOT_FOUND`` 으로 graceful 처리되고 traceback 이 노출되지 않는다.
- G2: ``no such table`` 이외의 ``OperationalError`` (locked / disk I/O /
  malformed 등) 는 **삼키지 않고 재전파**되어 호출 경계에서 ``REPORT_ERROR``
  envelope (exit 1) 로 변환된다. 메시지 한정 분기(``no such table`` 만 graceful)
  를 lock 한다.
- G3: writable DB 회귀 — 정상 reports 테이블이 있는 쓰기 가능 DB 에서 ``list`` /
  ``view`` 가 그대로 동작한다 (read_only 전환이 정상 경로를 깨지 않음).

실제 read-only 파일시스템 (0444/0555) 회귀는 ``test_cli_report_readonly_fs.py``
가 별도로 lock 한다 (#1976 교훈: 결정적 프록시는 실제 WAL PRAGMA 실패 경로를
대체하지 못함). 본 모듈은 table-absence / 재전파 분기를 deterministic 하게
보강한다.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core.database import Database
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.report import ReportStore
from ante.report.models import ReportStatus, StrategyReport

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status=MemberStatus.ACTIVE,
    scopes=[],
)

_REPORT_ID = "rpt-graceful-1"


@pytest.fixture(autouse=True)
def bypass_auth():
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


def _invoke(args: list[str]):
    runner = CliRunner()
    return runner.invoke(cli, args, env={"ANTE_MEMBER_TOKEN": ""})


def _load_json(output: str):
    text = output.lstrip()
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text)
    return obj


def _make_report() -> StrategyReport:
    return StrategyReport(
        report_id=_REPORT_ID,
        strategy_name="strat-G",
        strategy_version="1.0.0",
        strategy_path="strategies/strat_g.py",
        status=ReportStatus.SUBMITTED,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        submitted_by="agent",
        backtest_period="2024-01 ~ 2026-03",
        total_return_pct=5.0,
        total_trades=7,
        summary="s",
        rationale="r",
    )


def _empty_writable_db(path: Path) -> str:
    """``reports`` 테이블이 부재한 빈(writable) DB 파일을 만든다.

    다른 무관한 테이블(``misc``)만 생성해 파일이 valid SQLite DB 이되 ``reports``
    테이블은 없도록 한다 → ``SELECT ... FROM reports`` 가
    ``no such table: reports`` 로 실패하는 조건.
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE misc (x INTEGER)")
        conn.commit()
    finally:
        conn.close()
    return str(path)


def _writable_seeded_db(path: Path) -> str:
    """``reports`` 테이블 + report 1 건을 가진 writable DB 를 만든다."""

    async def _create() -> None:
        db = Database(str(path))
        await db.connect()
        try:
            store = ReportStore(db)
            await store.initialize()
            await store.submit(_make_report())
        finally:
            await db.close()

    asyncio.run(_create())
    return str(path)


# ── G1: 테이블 부재 graceful ──────────────────────────────────────────────


class TestReportTableAbsenceGraceful:
    def test_list_table_absent_returns_empty(self, tmp_path) -> None:
        """``reports`` 부재 → ``report list`` 빈 목록 + exit 0 + no traceback."""
        db_path = _empty_writable_db(tmp_path / "no_reports.db")
        result = _invoke(["--format", "json", "report", "list", "--db-path", db_path])
        assert result.exit_code == 0, result.output
        assert "Traceback" not in result.output, result.output
        payload = _load_json(result.output)
        rows = payload["data"] if isinstance(payload, dict) else payload
        assert rows == [], payload

    def test_view_table_absent_returns_not_found(self, tmp_path) -> None:
        """``reports`` 부재 → ``report view`` ``REPORT_NOT_FOUND`` + no traceback."""
        db_path = _empty_writable_db(tmp_path / "no_reports.db")
        result = _invoke(
            ["--format", "json", "report", "view", "any-id", "--db-path", db_path]
        )
        assert result.exit_code == 1, result.output
        assert "Traceback" not in result.output, result.output
        payload = _load_json(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "REPORT_NOT_FOUND", payload


# ── G2: no-such-table 이외 OperationalError 재전파 → REPORT_ERROR ──────────


class TestReportOperationalErrorReRaised:
    """``no such table`` 만 graceful; 다른 ``OperationalError`` 는 재전파."""

    def test_list_locked_error_surfaces_report_error(self, tmp_path) -> None:
        """``list_reports`` 가 ``database is locked`` → ``REPORT_ERROR`` (재전파)."""
        with (
            patch("ante.core.database.Database.connect", new=AsyncMock()),
            patch("ante.core.database.Database.close", new=AsyncMock()),
            patch(
                "ante.report.ReportStore.list_reports",
                new=AsyncMock(
                    side_effect=sqlite3.OperationalError("database is locked")
                ),
            ),
        ):
            result = _invoke(
                [
                    "--format",
                    "json",
                    "report",
                    "list",
                    "--db-path",
                    str(tmp_path / "ante.db"),
                ]
            )
        assert result.exit_code == 1, result.output
        assert "Traceback" not in result.output, result.output
        payload = _load_json(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "REPORT_ERROR", payload

    def test_view_malformed_error_surfaces_report_error(self, tmp_path) -> None:
        """``get`` 이 ``malformed`` → ``REPORT_ERROR`` (NOT_FOUND 아님, 재전파)."""
        with (
            patch("ante.core.database.Database.connect", new=AsyncMock()),
            patch("ante.core.database.Database.close", new=AsyncMock()),
            patch(
                "ante.report.ReportStore.get",
                new=AsyncMock(
                    side_effect=sqlite3.OperationalError(
                        "database disk image is malformed"
                    )
                ),
            ),
        ):
            result = _invoke(
                [
                    "--format",
                    "json",
                    "report",
                    "view",
                    "rpt-x",
                    "--db-path",
                    str(tmp_path / "ante.db"),
                ]
            )
        assert result.exit_code == 1, result.output
        assert "Traceback" not in result.output, result.output
        payload = _load_json(result.output)
        assert payload["status"] == "error"
        # malformed 는 graceful(NOT_FOUND) 가 아니라 REPORT_ERROR 로 재전파.
        assert payload["code"] == "REPORT_ERROR", payload


# ── G3: writable DB 회귀 ──────────────────────────────────────────────────


class TestReportWritableRegression:
    """정상 reports 테이블을 가진 writable DB 에서 list/view 회귀 보존."""

    def test_list_writable_db_returns_report(self, tmp_path) -> None:
        db_path = _writable_seeded_db(tmp_path / "seeded.db")
        result = _invoke(["--format", "json", "report", "list", "--db-path", db_path])
        assert result.exit_code == 0, result.output
        payload = _load_json(result.output)
        rows = payload["data"] if isinstance(payload, dict) else payload
        assert any(r["report_id"] == _REPORT_ID for r in rows), payload

    def test_view_writable_db_returns_report(self, tmp_path) -> None:
        db_path = _writable_seeded_db(tmp_path / "seeded.db")
        result = _invoke(
            ["--format", "json", "report", "view", _REPORT_ID, "--db-path", db_path]
        )
        assert result.exit_code == 0, result.output
        payload = _load_json(result.output)
        assert payload["report_id"] == _REPORT_ID, payload
        assert payload["total_trades"] == 7, payload
