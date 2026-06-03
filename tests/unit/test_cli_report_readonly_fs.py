"""``ante report list`` / ``report view`` 실제 read-only 파일시스템 회귀 (#2114).

``report list`` / ``report view`` 가 read-only DB artifact 를
``Database(read_only=False)`` + ``ReportStore.initialize()`` (CREATE TABLE
reports DDL) 로 열어, 실제 read-only fs (DB 파일 0444 / 부모 디렉터리 0555) 에서
WAL PRAGMA / DDL 이 ``attempt to write a readonly database`` 로 실패하던 버그를
lock 한다 (backtest history #1974 / data list #1984 동형).

#1976 교훈에 따라 **결정적 no-DDL 프록시 테스트로 대체하지 않는다**: 쓰기 가능
temp DB 의 "테이블 미생성" 프록시는 실제 read-only mount 의 WAL PRAGMA writer
연결 실패 경로를 가리지 못한다 (그 누락이 #1974 리오픈을 유발했다). 본 테스트는
실제 권한 조건을 재현한다 (offline-factory.md §적용 범위, 옵션 A):

- ``reports`` 테이블 + report 1 건을 ``ReportStore`` 의 실제 write 경로 (WAL)
  로 미리 생성 후 close. (case A) ``PRAGMA wal_checkpoint(TRUNCATE)`` 로 ``-wal``/
  ``-shm`` 을 비운 artifact. (case B) ``-wal`` 잔여 + ``-shm`` 부재 → immutable
  fallback 경로.
- auth 멤버 DB 는 ``--db-path`` 아티팩트와 다른 트리이며, 본 테스트는 auth 를
  mock 으로 우회하므로 read-only 대상은 ``--db-path`` 아티팩트뿐이다.
- ``os.chmod(db, 0o444)`` + ``os.chmod(dir, 0o555)`` 후
  ``ante --format json report list --db-path <ro>/ante.db`` /
  ``report view <id> --db-path <ro>/ante.db`` 실행 → exit 0 + 결과 보존.

권한 복구는 ``try/finally`` 로 보장한다. root/권한무시 환경에서는 chmod 가
의미 없으므로 skip 한다.

수정 전에는 ``attempt to write a readonly database`` 로 FAIL (REPORT_ERROR).
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

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

# root (또는 권한무시 환경) 에서는 0o444/0o555 chmod 가 효력이 없어
# read-only fs 시나리오를 재현할 수 없으므로 skip 한다.
_requires_unprivileged = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="read-only fs 시나리오는 root/권한무시 환경에서 재현되지 않음",
)

_REPORT_ID = "rpt-ro-1"


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


def _make_report() -> StrategyReport:
    return StrategyReport(
        report_id=_REPORT_ID,
        strategy_name="momentum_breakout",
        strategy_version="1.0.0",
        strategy_path="strategies/momentum_breakout.py",
        status=ReportStatus.SUBMITTED,
        submitted_at=datetime(2026, 3, 2, tzinfo=UTC),
        submitted_by="agent",
        backtest_period="2024-01 ~ 2026-03",
        total_return_pct=15.3,
        total_trades=42,
        sharpe_ratio=1.2,
        max_drawdown_pct=-8.5,
        win_rate=58.0,
        summary="20일 이동평균 돌파",
        rationale="모멘텀",
        risks="횡보장 손절",
    )


def _seed_reports_db(path: str) -> None:
    """``reports`` 테이블 + report 1 건을 가진 DB 를 실제 write 경로로 생성한다.

    ``Database`` write 경로 (WAL) 로 생성하므로 close 시점에 ``-wal``/``-shm``
    artifact 가 남을 수 있다 (case B). case A 는 호출자가 이후
    ``PRAGMA wal_checkpoint(TRUNCATE)`` 로 비운다.
    """

    async def _create() -> None:
        db = Database(path)
        await db.connect()
        try:
            store = ReportStore(db)
            await store.initialize()
            await store.submit(_make_report())
        finally:
            await db.close()

    asyncio.run(_create())


def _checkpoint_truncate(path: str) -> None:
    """``PRAGMA wal_checkpoint(TRUNCATE)`` 로 ``-wal``/``-shm`` 을 비운다 (case A)."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def _run_under_readonly(runner, db_dir: Path, db_file: Path, args: list[str]):
    """DB 디렉터리/파일을 read-only 로 만든 뒤 ``ante report ...`` 를 실행한다.

    권한 복구는 ``try/finally`` 로 보장한다.
    """
    sidecars = [
        db_dir / f"{db_file.name}-wal",
        db_dir / f"{db_file.name}-shm",
    ]
    # 파일 → 디렉터리 순으로 read-only. 디렉터리가 0o555 이면 그 안의 파일
    # 권한 변경이 불가하므로 파일을 먼저 chmod 한다.
    os.chmod(db_file, 0o444)
    for s in sidecars:
        if s.exists():
            os.chmod(s, 0o444)
    os.chmod(db_dir, 0o555)
    try:
        return runner.invoke(cli, args)
    finally:
        os.chmod(db_dir, 0o755)
        os.chmod(db_file, 0o644)
        for s in sidecars:
            if s.exists():
                os.chmod(s, 0o644)


@_requires_unprivileged
class TestReportListReadOnlyFilesystem:
    """``report list`` 실제 read-only fs 조회 (case A / case B)."""

    def test_list_on_readonly_fs_checkpointed_wal(self, runner, tmp_path) -> None:
        """case A: ``-wal``/``-shm`` truncate 후 read-only report 목록 조회."""
        db_dir = tmp_path / "ro_checkpointed"
        db_dir.mkdir()
        db_file = db_dir / "ante.db"
        _seed_reports_db(str(db_file))
        _checkpoint_truncate(str(db_file))

        result = _run_under_readonly(
            runner,
            db_dir,
            db_file,
            ["--format", "json", "report", "list", "--db-path", str(db_file)],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        rows = payload["data"] if isinstance(payload, dict) else payload
        assert any(r["report_id"] == _REPORT_ID for r in rows), payload

    def test_list_on_readonly_fs_with_wal_sidecars(self, runner, tmp_path) -> None:
        """case B: ``-wal`` 잔여 + ``-shm`` 부재 → immutable fallback 경로."""
        db_dir = tmp_path / "ro_with_wal"
        db_dir.mkdir()
        db_file = db_dir / "ante.db"
        _seed_reports_db(str(db_file))
        _checkpoint_truncate(str(db_file))
        wal = db_dir / "ante.db-wal"
        shm = db_dir / "ante.db-shm"
        if shm.exists():
            shm.unlink()
        wal.write_bytes(b"\x37\x7f\x06\x82" + b"\x00" * 28)

        result = _run_under_readonly(
            runner,
            db_dir,
            db_file,
            ["--format", "json", "report", "list", "--db-path", str(db_file)],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        rows = payload["data"] if isinstance(payload, dict) else payload
        assert any(r["report_id"] == _REPORT_ID for r in rows), payload


@_requires_unprivileged
class TestReportViewReadOnlyFilesystem:
    """``report view`` 실제 read-only fs 조회 (case A / case B)."""

    def test_view_on_readonly_fs_checkpointed_wal(self, runner, tmp_path) -> None:
        """case A: ``-wal``/``-shm`` truncate 후 read-only report 상세 조회."""
        db_dir = tmp_path / "ro_checkpointed"
        db_dir.mkdir()
        db_file = db_dir / "ante.db"
        _seed_reports_db(str(db_file))
        _checkpoint_truncate(str(db_file))

        result = _run_under_readonly(
            runner,
            db_dir,
            db_file,
            [
                "--format",
                "json",
                "report",
                "view",
                _REPORT_ID,
                "--db-path",
                str(db_file),
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["report_id"] == _REPORT_ID, payload
        assert payload["total_trades"] == 42, payload

    def test_view_on_readonly_fs_with_wal_sidecars(self, runner, tmp_path) -> None:
        """case B: ``-wal`` 잔여 + ``-shm`` 부재 → immutable fallback 경로."""
        db_dir = tmp_path / "ro_with_wal"
        db_dir.mkdir()
        db_file = db_dir / "ante.db"
        _seed_reports_db(str(db_file))
        _checkpoint_truncate(str(db_file))
        wal = db_dir / "ante.db-wal"
        shm = db_dir / "ante.db-shm"
        if shm.exists():
            shm.unlink()
        wal.write_bytes(b"\x37\x7f\x06\x82" + b"\x00" * 28)

        result = _run_under_readonly(
            runner,
            db_dir,
            db_file,
            [
                "--format",
                "json",
                "report",
                "view",
                _REPORT_ID,
                "--db-path",
                str(db_file),
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["report_id"] == _REPORT_ID, payload
