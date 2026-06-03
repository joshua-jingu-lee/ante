"""``ante data list`` 실제 read-only 파일시스템 회귀 테스트 (#1984).

``data list`` 의 종목명 보강 경로가 read-only DB artifact 를
``Database(read_only=False)`` + ``InstrumentService.initialize()`` (DDL) 로 열어
실제 read-only fs (DB 파일 0444 / 부모 디렉터리 0555) 에서 WAL PRAGMA / DDL 이
``attempt to write a readonly database`` 로 실패하던 버그를 lock 한다 (backtest
history #1974 동형).

#1976 교훈에 따라 **결정적 no-DDL 프록시 테스트로 대체하지 않는다**: 쓰기 가능
temp DB 의 "테이블 미생성" 프록시는 실제 read-only mount 의 WAL PRAGMA writer
연결 실패 경로를 가리지 못한다 (그 누락이 #1974 리오픈을 유발했다). 본 테스트는
실제 권한 조건을 재현한다 (offline-factory.md §2 옵션 A):

- 데이터셋 (ParquetStore) 은 별도 writable 디렉터리에 둔다 — ``data list`` 의
  비-DB 경로는 read-only 대상이 아니다.
- read-only 대상은 ``--db-path`` 아티팩트 (종목명 보강용 instruments DB) 다.
  ``instruments`` 테이블 + ``005930`` 종목명을 미리 생성 후 close.
- WAL 잔여 처리 두 케이스:
  - (case A) ``PRAGMA wal_checkpoint(TRUNCATE)`` 로 ``-wal``/``-shm`` 을 비운 artifact.
  - (case B) ``-wal``/``-shm`` 이 존재하는 상태.
- ``os.chmod(db, 0o444)`` + ``os.chmod(dir, 0o555)`` 후
  ``ante --format json data list --data-path <writable> --db-path <ro>/ante.db``
  실행 → exit 0 + datasets 1 건 + ``name`` == "삼성전자" (이름 보존).

권한 복구는 ``try/finally`` 로 보장한다. root/권한무시 환경에서는 chmod 가
의미 없으므로 skip 한다.

수정 전에는 ``attempt to write a readonly database`` 로 FAIL (DATA_ERROR).
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core.database import Database
from ante.data.store import ParquetStore
from ante.instrument.models import Instrument
from ante.instrument.service import InstrumentService
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


def _make_ohlcv_df(symbol: str) -> pl.DataFrame:
    timestamps = pl.datetime_range(
        datetime.fromisoformat("2026-03-02T09:00:00"),
        datetime.fromisoformat("2026-03-02T09:04:00"),
        interval="1m",
        eager=True,
        time_zone="UTC",
    )
    n = len(timestamps)
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * n,
            "open": [50000.0 + i * 100 for i in range(n)],
            "high": [50100.0 + i * 100 for i in range(n)],
            "low": [49900.0 + i * 100 for i in range(n)],
            "close": [50050.0 + i * 100 for i in range(n)],
            "volume": [1000 + i * 10 for i in range(n)],
            "source": ["test"] * n,
        }
    )


def _seed_dataset(data_path: Path, symbol: str = "005930") -> None:
    """writable ParquetStore 에 OHLCV dataset 1 건을 기록한다."""
    store = ParquetStore(base_path=data_path)
    store.write(symbol, "1m", _make_ohlcv_df(symbol))


def _seed_instruments_db(path: str) -> None:
    """``instruments`` 테이블 + ``005930``("삼성전자") 1 건을 가진 DB 를 생성한다.

    실제 ``Database`` write 경로 (WAL) 로 생성하므로, close 시점에 ``-wal``/
    ``-shm`` artifact 가 남을 수 있다 (case B). case A 는 호출자가 이후
    ``PRAGMA wal_checkpoint(TRUNCATE)`` 로 비운다.
    """

    async def _create() -> None:
        db = Database(path)
        await db.connect()
        try:
            svc = InstrumentService(db)
            await svc.initialize()
            await svc.bulk_upsert(
                [Instrument(symbol="005930", exchange="KRX", name="삼성전자")]
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


def _run_list_under_readonly(runner, data_path: Path, db_dir: Path, db_file: Path):
    """DB 디렉터리/파일을 read-only 로 만든 뒤 ``data list`` 를 실행한다.

    ``--data-path`` (ParquetStore) 는 writable 로 둔다 — read-only 대상은
    종목명 보강용 ``--db-path`` 아티팩트뿐이다. 권한 복구는 ``try/finally`` 로
    보장한다.
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
                "data",
                "list",
                "--data-path",
                str(data_path),
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
class TestDataListReadOnlyFilesystem:
    def test_list_on_readonly_fs_checkpointed_wal(self, runner, tmp_path) -> None:
        """case A: ``-wal``/``-shm`` 을 truncate 한 read-only instruments 조회.

        실제 권한 (DB 파일 0o444 / 디렉터리 0o555) 에서 exit 0 + datasets 1 건
        + ``name`` == "삼성전자" (이름 보존). 수정 전: ``attempt to write a
        readonly database`` 로 FAIL (DATA_ERROR).
        """
        data_path = tmp_path / "data"
        _seed_dataset(data_path)

        db_dir = tmp_path / "ro_checkpointed"
        db_dir.mkdir()
        db_file = db_dir / "ante.db"
        _seed_instruments_db(str(db_file))
        _checkpoint_truncate(str(db_file))

        result = _run_list_under_readonly(runner, data_path, db_dir, db_file)

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["count"] == 1, payload
        assert payload["datasets"][0]["symbol"] == "005930"
        # WAL PRAGMA 실패 없이 read-only DB 에서 이름 보강 보존.
        assert payload["datasets"][0]["name"] == "삼성전자", payload

    def test_list_on_readonly_fs_with_wal_sidecars(self, runner, tmp_path) -> None:
        """case B: ``-wal`` 잔여 + ``-shm`` 부재 → immutable fallback 경로.

        instruments 데이터를 메인 DB 로 checkpoint(TRUNCATE) 한 뒤, crash 잔여를
        모사한 ``-wal`` 헤더 파일을 만들고 ``-shm`` 은 두지 않는다. 실제 read-only
        fs (DB 파일 0o444 / 디렉터리 0o555) 에서:
          - ``mode=ro`` 는 ``-shm`` 을 생성할 수 없어 ``unable to open database
            file`` 로 실패한다.
          - ``immutable=1`` fallback 이 메인 DB (모든 커밋 데이터 보유) 를 일관
            read 한다.
        → exit 0 + datasets 1 건 + ``name`` == "삼성전자". 수정 전:
        ``attempt to write a readonly database`` 로 FAIL.
        """
        data_path = tmp_path / "data"
        _seed_dataset(data_path)

        db_dir = tmp_path / "ro_with_wal"
        db_dir.mkdir()
        db_file = db_dir / "ante.db"
        _seed_instruments_db(str(db_file))
        # 데이터를 메인 DB 로 합치고 -wal/-shm 을 비운다.
        _checkpoint_truncate(str(db_file))
        # crash 잔여를 모사: -shm 없이 -wal 헤더만 존재 → mode=ro 가 실패하고
        # immutable fallback 이 트리거된다.
        wal = db_dir / "ante.db-wal"
        shm = db_dir / "ante.db-shm"
        if shm.exists():
            shm.unlink()
        wal.write_bytes(b"\x37\x7f\x06\x82" + b"\x00" * 28)

        result = _run_list_under_readonly(runner, data_path, db_dir, db_file)

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["count"] == 1, payload
        assert payload["datasets"][0]["symbol"] == "005930"
        assert payload["datasets"][0]["name"] == "삼성전자", payload
