"""``ante data list`` read-only DB 조회 회귀 테스트 (#1984).

``data list`` 는 ParquetStore (파일) 에서 datasets 를 읽는 offline read 명령이며,
DB 는 종목명 보강 (``InstrumentService.get_name``) 에만 쓰인다. 따라서 read-only
DB artifact 에서 schema DDL (``InstrumentService.initialize()`` → ``CREATE TABLE
instruments``) 이나 writer 연결 (WAL PRAGMA) 을 발화하면 안 된다
(offline-factory.md §2 옵션 A, ``backtest history`` #1974 동형). 핵심 회귀 락:

(b)  read-only DB 에 ``instruments`` 테이블 존재 → 이름 보강 보존
     (``load_readonly`` 캐시 워밍 — symbol fallback 퇴화 아님).
(b2) ``instruments`` 부재 ("no such table") → symbol fallback graceful, traceback
     없음.
(c)  writable DB → 이름 enrichment 정상 (회귀).
(d)  malformed DB → ``DATA_ERROR`` 재전파 (no-such-table 만 graceful — 메시지
     의존 테스트 락).

실제 read-only **파일시스템** (0444 DB + 0555 부모 dir) 의 WAL PRAGMA 실패
경로 검증은 :mod:`tests.unit.test_cli_data_list_readonly_fs` 가 담당한다 (결정적
프록시로 대체 금지 — #1976 교훈).

CliRunner / auth 우회 fixture 는 ``test_cli_backtest_history_readonly.py`` 를
미러한다.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
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
    """``data list`` 가 datasets 1 건을 반환하도록 최소 OHLCV DataFrame 생성."""
    from datetime import datetime

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
    """ParquetStore 에 OHLCV dataset 1 건을 기록한다 (``data list`` 비-DB 경로)."""
    store = ParquetStore(base_path=data_path)
    store.write(symbol, "1m", _make_ohlcv_df(symbol))


def _seed_instruments_db(path: str, *, with_name: bool) -> None:
    """``instruments`` 테이블을 가진 DB 를 생성한다.

    ``with_name`` 이면 ``InstrumentService.bulk_upsert`` 로 종목명을 1 건 넣는다.
    """

    async def _create() -> None:
        db = Database(path)
        await db.connect()
        try:
            svc = InstrumentService(db)
            await svc.initialize()
            if with_name:
                await svc.bulk_upsert(
                    [Instrument(symbol="005930", exchange="KRX", name="삼성전자")]
                )
        finally:
            await db.close()

    asyncio.run(_create())


def _make_empty_db(path: str) -> None:
    """``instruments`` 테이블이 없는 빈 DB 파일을 생성한다.

    파일이 존재하지 않으면 ``open_cli_db`` → ``Database.connect()`` 가 파일을
    새로 생성하므로, connect→close 만 수행해 스키마 없는 빈 DB 파일을 미리 만든다.
    """

    async def _create() -> None:
        db = Database(path)
        await db.connect()
        await db.close()

    asyncio.run(_create())


def _instruments_table_exists(path: str) -> bool:
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'instruments'"
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _run_data_list(runner, data_path: Path, db_file: Path):
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


class TestDataListReadOnlyDb:
    def test_instruments_present_preserves_name_enrichment(
        self, runner, tmp_path
    ) -> None:
        """(b) instruments 테이블 존재 → 이름 보강 보존 (load_readonly 캐시 로드).

        symbol fallback 퇴화가 아니라 실제 종목명 ("삼성전자") 이 보존되어야
        한다. 이는 단순 ``initialize()`` skip (캐시 비어 silent 퇴화) 와 본
        ``load_readonly()`` (캐시 워밍) 의 차이를 lock 한다.
        """
        data_path = tmp_path / "data"
        _seed_dataset(data_path)
        db_file = tmp_path / "ante.db"
        _seed_instruments_db(str(db_file), with_name=True)

        result = _run_data_list(runner, data_path, db_file)

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["count"] == 1, payload
        assert payload["datasets"][0]["symbol"] == "005930"
        assert payload["datasets"][0]["name"] == "삼성전자", payload

    def test_instruments_absent_symbol_fallback_graceful(
        self, runner, tmp_path
    ) -> None:
        """(b2) instruments 부재 → symbol fallback graceful, traceback 없음.

        - exit 0 + datasets 1 건.
        - ``name`` 이 symbol fallback ("005930") 으로 정규화.
        - 실행 후에도 ``instruments`` 테이블이 생성되지 않음 (read-only DDL
          부작용 부재).
        - traceback / DATA_ERROR 미노출.
        """
        data_path = tmp_path / "data"
        _seed_dataset(data_path)
        db_file = tmp_path / "ante.db"
        _make_empty_db(str(db_file))
        assert not _instruments_table_exists(str(db_file))

        result = _run_data_list(runner, data_path, db_file)

        assert result.exit_code == 0, result.output
        assert "Traceback" not in result.output, result.output
        assert "DATA_ERROR" not in result.output, result.output
        payload = json.loads(result.output)
        assert payload["count"] == 1, payload
        assert payload["datasets"][0]["symbol"] == "005930"
        # 캐시 미스 → symbol fallback.
        assert payload["datasets"][0]["name"] == "005930", payload
        # 핵심 회귀 락: read-only 조회가 instruments 테이블을 생성하지 않음.
        assert not _instruments_table_exists(str(db_file))

    def test_writable_db_name_enrichment_regression(self, runner, tmp_path) -> None:
        """(c) writable DB → 이름 enrichment 정상 (회귀 보존).

        read_only 마이그레이션 후에도 일반(쓰기 가능) DB 의 종목명 보강이
        그대로 동작해야 한다.
        """
        data_path = tmp_path / "data"
        _seed_dataset(data_path)
        db_file = tmp_path / "ante.db"
        _seed_instruments_db(str(db_file), with_name=True)

        result = _run_data_list(runner, data_path, db_file)

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["datasets"][0]["name"] == "삼성전자", payload

    def test_malformed_db_reraises_as_data_error(self, runner, tmp_path) -> None:
        """(d) malformed DB → ``DATA_ERROR`` 재전파 (no-such-table 만 graceful).

        ``instruments`` 테이블은 존재하지만 DB 파일이 손상된 경우, ``_warm_cache``
        의 ``SELECT`` 가 ``no such table`` 이 아닌 OperationalError 로 실패한다.
        traceback 대신 public error code (``DATA_ERROR``) + exit 1 로 변환되어야
        한다 (메시지 의존 graceful 가드의 좁힘을 lock).
        """
        data_path = tmp_path / "data"
        _seed_dataset(data_path)
        db_file = tmp_path / "ante.db"
        # 유효한 instruments DB 를 만든 뒤 메인 파일 본문을 손상시킨다 (헤더는
        # 유지해 connect probe 는 통과하고 SELECT 시점에 malformed 로 실패).
        _seed_instruments_db(str(db_file), with_name=True)
        # WAL sidecar 를 제거해 손상이 메인 파일 read 로 surface 하도록 한다.
        for sidecar in (
            Path(str(db_file) + "-wal"),
            Path(str(db_file) + "-shm"),
        ):
            if sidecar.exists():
                sidecar.unlink()
        raw = bytearray(db_file.read_bytes())
        # SQLite 헤더 (첫 100 바이트) 는 보존하고 그 이후 페이지 본문을 깨뜨린다.
        for i in range(100, len(raw)):
            raw[i] = 0xFF
        db_file.write_bytes(bytes(raw))

        result = _run_data_list(runner, data_path, db_file)

        assert result.exit_code == 1, result.output
        assert "Traceback" not in result.output, result.output
        payload = json.loads(result.output)
        assert payload.get("code") == "DATA_ERROR", payload
