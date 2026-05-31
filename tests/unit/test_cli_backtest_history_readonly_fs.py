"""``ante backtest history`` 실제 read-only 파일시스템 회귀 테스트 (#1974 R2).

#1976 은 ``backtest history`` 에서 ``BacktestRunStore.initialize()`` (schema DDL)
만 제거했고, 검증은 쓰기 가능 temp DB 의 "테이블 미생성" 프록시였다. 그러나
**실제 read-only 파일시스템 (DB 파일 0444 / 디렉터리 0555)** 에서는 여전히
``Database.connect()`` 가 writer+reader 두 연결을 열고 각각
``PRAGMA journal_mode=WAL`` (쓰기 필요) 을 실행해
``attempt to write a readonly database`` 로 실패한다.

본 테스트는 그 실제 권한 조건을 재현한다 (offline-factory.md §2 옵션 A):

- 임시 DB 에 ``backtest_runs`` 스키마 + ``momentum`` 이력 1 건을 미리 생성 후 close.
- WAL 잔여 처리 두 케이스:
  - (case A) ``PRAGMA wal_checkpoint(TRUNCATE)`` 로 ``-wal``/``-shm`` 을 비운 artifact.
  - (case B) ``-wal``/``-shm`` 이 존재하는 상태.
- ``os.chmod(db, 0o444)`` + ``os.chmod(dir, 0o555)`` 후
  ``ante --format json backtest history momentum --db-path <ro>/ante.db`` 실행 →
  exit 0 + ``runs`` 1 건.

권한 복구는 ``try/finally`` 로 보장 (dir 0o755, file 0o644) — tmp cleanup 이
read-only 디렉터리 때문에 실패하지 않도록 한다. root/권한무시 환경에서는 chmod
가 의미 없으므로 skip 한다.

수정 전에는 ``attempt to write a readonly database`` 로 FAIL (BACKTEST_ERROR).
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.backtest.run_store import BACKTEST_RUNS_SCHEMA
from ante.cli.main import cli
from ante.core.database import Database
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

# root (또는 권한무시 환경) 에서는 0o444/0o555 chmod 가 효력이 없어
# read-only fs 시나리오를 재현할 수 없으므로 skip 한다.
_requires_unprivileged = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="read-only fs 시나리오는 root/권한무시 환경에서 재현되지 않음",
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


def _seed_db_with_one_run(path: str) -> None:
    """``backtest_runs`` 스키마 + ``momentum`` 이력 1 건을 가진 DB 를 생성한다.

    실제 ``Database`` write 경로 (WAL) 로 생성하므로, close 시점에 ``-wal``/
    ``-shm`` artifact 가 남을 수 있다 (case B). case A 는 호출자가 이후
    ``PRAGMA wal_checkpoint(TRUNCATE)`` 로 비운다.
    """

    async def _create() -> None:
        db = Database(path)
        await db.connect()
        try:
            await db.execute_script(BACKTEST_RUNS_SCHEMA)
            await db.execute(
                """INSERT INTO backtest_runs
                   (run_id, strategy_name, strategy_version, params_json,
                    total_return_pct, sharpe_ratio, max_drawdown_pct,
                    total_trades, win_rate, result_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "run-momentum-1",
                    "momentum",
                    "1.0.0",
                    "{}",
                    12.34,
                    1.5,
                    -3.2,
                    7,
                    0.57,
                    "",
                    "2026-05-31T00:00:00+00:00",
                ),
            )
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


def _run_history_under_readonly(runner, db_dir: Path, db_file: Path):
    """디렉터리/파일을 read-only 로 만든 뒤 ``backtest history`` 를 실행한다.

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
        return runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "history",
                "momentum",
                "--db-path",
                str(db_file),
            ],
        )
    finally:
        os.chmod(db_dir, 0o755)
        os.chmod(db_file, 0o644)
        for s in sidecars:
            if s.exists():
                os.chmod(s, 0o644)


@_requires_unprivileged
class TestBacktestHistoryReadOnlyFilesystem:
    def test_history_on_readonly_fs_checkpointed_wal(self, runner, tmp_path) -> None:
        """case A: ``-wal``/``-shm`` 을 truncate 한 read-only artifact 조회.

        실제 권한 (파일 0o444 / 디렉터리 0o555) 에서 exit 0 + runs 1 건.
        수정 전: ``attempt to write a readonly database`` 로 FAIL.
        """
        db_dir = tmp_path / "ro_checkpointed"
        db_dir.mkdir()
        db_file = db_dir / "ante.db"
        _seed_db_with_one_run(str(db_file))
        _checkpoint_truncate(str(db_file))

        result = _run_history_under_readonly(runner, db_dir, db_file)

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "runs" in data, data
        assert len(data["runs"]) == 1, data
        assert data["runs"][0]["strategy_name"] == "momentum"
        assert data["runs"][0]["run_id"] == "run-momentum-1"

    def test_history_on_readonly_fs_with_wal_sidecars(self, runner, tmp_path) -> None:
        """case B: ``-wal`` 잔여 + ``-shm`` 부재 → immutable fallback 경로.

        ``backtest_runs`` 데이터를 메인 DB 로 checkpoint(TRUNCATE) 한 뒤, crash
        잔여를 모사한 ``-wal`` 헤더 파일을 만들고 ``-shm`` 은 두지 않는다. 실제
        read-only fs(파일 0o444 / 디렉터리 0o555) 에서:
          - ``mode=ro`` 는 ``-shm`` 을 생성할 수 없어 ``unable to open database
            file`` 로 실패한다.
          - ``immutable=1`` fallback 이 메인 DB(모든 커밋 데이터 보유) 를 일관
            read 한다.
        → exit 0 + runs 1 건. 수정 전: ``attempt to write a readonly database``
        로 FAIL.

        주의: Ante 의 ``Database.close()`` 는 마지막 연결 종료 시 WAL 을
        checkpoint 하고 sidecar 를 제거하므로, 정상적으로 freeze 된 backtest
        artifact 는 모든 커밋 데이터가 메인 DB 에 있다. 따라서 immutable fallback
        은 데이터 손실 없이 신뢰 가능하다(non-checkpointed live WAL 은 artifact
        대상이 아님 — offline-factory.md §2 옵션 A Non-Goals).
        """
        db_dir = tmp_path / "ro_with_wal"
        db_dir.mkdir()
        db_file = db_dir / "ante.db"
        _seed_db_with_one_run(str(db_file))
        # 데이터를 메인 DB 로 합치고 -wal/-shm 을 비운다.
        _checkpoint_truncate(str(db_file))
        # crash 잔여를 모사: -shm 없이 -wal 헤더만 존재 → mode=ro 가 실패하고
        # immutable fallback 이 트리거된다.
        wal = db_dir / "ante.db-wal"
        shm = db_dir / "ante.db-shm"
        if shm.exists():
            shm.unlink()
        wal.write_bytes(b"\x37\x7f\x06\x82" + b"\x00" * 28)

        result = _run_history_under_readonly(runner, db_dir, db_file)

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "runs" in data, data
        assert len(data["runs"]) == 1, data
        assert data["runs"][0]["strategy_name"] == "momentum"
        assert data["runs"][0]["run_id"] == "run-momentum-1"
