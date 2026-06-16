"""schema_version 테이블 + 중앙 마이그레이션 러너 테스트."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ante.core.database import Database
from ante.db.migrations import (
    MIGRATIONS,
    _accepts_data_path,
    ensure_schema_version_table,
    get_applied_seqs,
    run_migrations,
)
from ante.db.versions import (
    v001_baseline,
    v002_parquet_migration,
    v005_trades_timestamp_isoformat,
    v006_order_tracker_order_price,
)

# v006 마이그레이션 테스트용 — order_price 컬럼이 없는 legacy order_tracker DDL.
_LEGACY_ORDER_TRACKER_DDL = """
CREATE TABLE order_tracker (
    order_id            TEXT PRIMARY KEY,
    account_id          TEXT NOT NULL,
    bot_id              TEXT NOT NULL,
    strategy_id         TEXT NOT NULL,
    broker_order_id     TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    side                TEXT NOT NULL,
    order_type          TEXT NOT NULL DEFAULT '',
    ordered_qty         REAL NOT NULL DEFAULT 0.0,
    recorded_filled_qty REAL NOT NULL DEFAULT 0.0,
    avg_fill_price      REAL NOT NULL DEFAULT 0.0,
    status              TEXT NOT NULL DEFAULT 'open',
    submitted_at        TEXT,
    submitted_date      TEXT NOT NULL,
    last_polled_at      TEXT,
    terminal_at         TEXT
)
"""


@pytest.fixture
async def db(tmp_path):
    """임시 SQLite DB를 생성하고 반환한다."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


class TestEnsureSchemaVersionTable:
    """schema_version 테이블 자동 생성 테스트."""

    async def test_creates_table_when_not_exists(self, db: Database):
        """빈 DB에서 schema_version 테이블을 생성한다."""
        await ensure_schema_version_table(db)

        row = await db.fetch_one(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_version'"
        )
        assert row is not None
        assert row["name"] == "schema_version"

    async def test_idempotent_creation(self, db: Database):
        """두 번 호출해도 에러 없이 동작한다."""
        await ensure_schema_version_table(db)
        await ensure_schema_version_table(db)

        row = await db.fetch_one(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_version'"
        )
        assert row is not None


class TestRunMigrations:
    """마이그레이션 러너 테스트."""

    async def test_applies_all_on_empty_db(self, db: Database):
        """빈 DB에서 전체 마이그레이션 실행 시 schema_version에 모든 seq 기록."""
        result = await run_migrations(db)

        assert len(result) > 0
        assert "001_0.7.0" in result

        applied = await get_applied_seqs(db)
        assert 1 in applied

    async def test_skips_already_applied(self, db: Database):
        """이미 적용된 마이그레이션은 건너뛴다."""
        await run_migrations(db)

        # 수동으로 seq 확인
        applied_before = await get_applied_seqs(db)

        result = await run_migrations(db)

        assert result == []
        applied_after = await get_applied_seqs(db)
        assert applied_before == applied_after

    async def test_idempotent_double_call(self, db: Database):
        """2회 호출 시 두 번째는 빈 리스트를 반환한다 (멱등성)."""
        first = await run_migrations(db)
        second = await run_migrations(db)

        assert len(first) > 0
        assert second == []

    async def test_schema_version_table_auto_created(self, db: Database):
        """run_migrations가 schema_version 테이블을 자동 생성한다."""
        # 테이블이 없는 상태에서 바로 run_migrations 호출
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_version'"
        )
        assert row is None

        await run_migrations(db)

        row = await db.fetch_one(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_version'"
        )
        assert row is not None


class TestParquetMigrationIntegration:
    """Parquet 마이그레이션의 중앙 러너 통합 테스트."""

    async def test_data_path_passed_to_parquet_migration(
        self, db: Database, tmp_path: Path
    ):
        """마이그레이션 러너에서 data_path 인자가 Parquet 마이그레이션에 전달된다."""
        data_path = tmp_path / "data"
        data_path.mkdir()

        with patch(
            "ante.data.store.migrate_parquet_paths",
            return_value=0,
        ) as mock_migrate:
            await run_migrations(db, data_path=data_path)

        mock_migrate.assert_called_once_with(data_path)

    async def test_parquet_migration_moves_paths(self, db: Database, tmp_path: Path):
        """Parquet 경로 변경이 실제로 적용된다 (구 경로 -> 신 경로)."""
        data_path = tmp_path / "data"
        old_path = data_path / "ohlcv" / "1d" / "005930"
        old_path.mkdir(parents=True)
        (old_path / "2026-01.parquet").write_bytes(b"dummy-parquet-data")

        await run_migrations(db, data_path=data_path)

        # 구 경로 사라짐
        assert not old_path.exists()
        # 신 경로 생성됨
        new_path = data_path / "ohlcv" / "1d" / "KRX" / "005930"
        assert new_path.exists()
        assert (new_path / "2026-01.parquet").read_bytes() == b"dummy-parquet-data"

    async def test_parquet_data_preserved_after_migration(
        self, db: Database, tmp_path: Path
    ):
        """마이그레이션 전후 Parquet 내용이 일치한다."""
        data_path = tmp_path / "data"
        old_path = data_path / "ohlcv" / "1d" / "005930"
        old_path.mkdir(parents=True)
        original_content = b"parquet-binary-content-12345"
        (old_path / "2026-01.parquet").write_bytes(original_content)

        await run_migrations(db, data_path=data_path)

        new_file = data_path / "ohlcv" / "1d" / "KRX" / "005930" / "2026-01.parquet"
        assert new_file.read_bytes() == original_content

    async def test_v002_registered_in_migrations(self):
        """v002_parquet_migration이 MIGRATIONS 리스트에 등록되어 있다."""

        seqs = [seq for seq, _, _ in MIGRATIONS]
        fns = [fn for _, _, fn in MIGRATIONS]
        assert 2 in seqs
        assert v002_parquet_migration.migrate in fns

    async def test_run_migrations_without_data_path(self, db: Database):
        """data_path 없이 호출해도 정상 동작한다 (하위 호환)."""
        result = await run_migrations(db)
        assert "002_0.7.0" in result

        applied = await get_applied_seqs(db)
        assert 2 in applied

    async def test_no_data_path_skips_parquet_move(self, db: Database):
        """data_path=None이면 Parquet 마이그레이션이 파일 이동 없이 완료된다."""
        with patch(
            "ante.data.store.migrate_parquet_paths",
        ) as mock_migrate:
            await run_migrations(db)

        mock_migrate.assert_not_called()


class TestAcceptsDataPath:
    """_accepts_data_path 유틸리티 테스트."""

    def test_v001_does_not_accept_data_path(self):
        """v001_baseline은 data_path 파라미터가 없다."""
        assert not _accepts_data_path(v001_baseline.migrate)

    def test_v002_accepts_data_path(self):
        """v002_parquet_migration은 data_path 파라미터를 받는다."""
        assert _accepts_data_path(v002_parquet_migration.migrate)


class TestMigrationAutoBackup:
    """마이그레이션 실행 전 자동 DB 백업 테스트 (Refs #1097)."""

    async def test_backup_called_when_pending_exists(
        self, db: Database, monkeypatch: pytest.MonkeyPatch
    ):
        """미적용 마이그레이션이 있을 때 backup_db가 한 번 호출된다."""
        calls: list[tuple[Path, str]] = []

        def fake_backup(src_path: Path, version: str) -> Path:
            calls.append((src_path, version))
            return src_path.parent / f"{src_path.name}.bak.v{version}"

        monkeypatch.setattr("ante.db.migrations.backup_db", fake_backup)

        await run_migrations(db)

        assert len(calls) == 1
        src, version = calls[0]
        # 첫 번째 미적용 마이그레이션의 version이 사용된다.
        first_pending_version = sorted(MIGRATIONS, key=lambda x: x[0])[0][1]
        assert version == first_pending_version
        assert src.name == "test.db"

    async def test_backup_not_called_when_no_pending(
        self, db: Database, monkeypatch: pytest.MonkeyPatch
    ):
        """모든 마이그레이션이 이미 적용됐으면 backup_db가 호출되지 않는다."""
        # 먼저 한 번 전부 적용
        await run_migrations(db)

        calls: list[tuple[Path, str]] = []

        def fake_backup(src_path: Path, version: str) -> Path:
            calls.append((src_path, version))
            return src_path

        monkeypatch.setattr("ante.db.migrations.backup_db", fake_backup)

        result = await run_migrations(db)

        assert result == []
        assert calls == []

    async def test_backup_called_only_once_even_with_multiple_pending(
        self, db: Database, monkeypatch: pytest.MonkeyPatch
    ):
        """미적용 마이그레이션이 여러 건이어도 backup_db는 1회만 호출된다."""
        calls: list[tuple[Path, str]] = []

        def fake_backup(src_path: Path, version: str) -> Path:
            calls.append((src_path, version))
            return src_path.parent / f"{src_path.name}.bak.v{version}"

        monkeypatch.setattr("ante.db.migrations.backup_db", fake_backup)

        result = await run_migrations(db)

        # 여러 마이그레이션이 적용됐어도
        assert len(result) >= 2
        # 백업은 1회만
        assert len(calls) == 1

    async def test_backup_failure_propagates(
        self, db: Database, monkeypatch: pytest.MonkeyPatch
    ):
        """backup_db에서 예외가 발생하면 마이그레이션이 중단된다."""

        def failing_backup(src_path: Path, version: str) -> Path:
            raise FileNotFoundError("원본 DB 없음")

        monkeypatch.setattr("ante.db.migrations.backup_db", failing_backup)

        with pytest.raises(FileNotFoundError):
            await run_migrations(db)

        # 예외 발생 시 마이그레이션이 적용되지 않아야 한다.
        applied = await get_applied_seqs(db)
        assert applied == set()


class TestMigrationsCliDbPath:
    """Codex 10차 review Finding 2 — `python -m ante.db.migrations` 의
    --db-path / ANTE_DB_PATH 지원 테스트.

    `ante update` 가 서브프로세스로 migrations 러너를 호출할 때 실제 DB
    경로를 전달하려면 `__main__` 블록이 CLI 인자 또는 환경변수를 받아야
    한다. 과거 `Database("db/ante.db")` 하드코딩 회귀를 방지한다.
    """

    def test_cli_accepts_db_path_argument(self, tmp_path: Path) -> None:
        """--db-path 인자로 전달된 DB 파일에 마이그레이션이 적용된다."""
        db_file = tmp_path / "custom.db"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ante.db.migrations",
                "--db-path",
                str(db_file),
                "--data-path",
                str(tmp_path / "data"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"migrations 러너 실패: stdout={result.stdout} stderr={result.stderr}"
        )
        # 지정된 경로에만 DB 파일이 생성돼야 한다.
        assert db_file.exists(), "--db-path 로 전달한 파일이 생성돼야 합니다"

    def test_cli_accepts_ante_db_path_env(self, tmp_path: Path) -> None:
        """ANTE_DB_PATH 환경변수로도 DB 경로를 전달할 수 있다."""
        import os as _os

        db_file = tmp_path / "env.db"
        env = _os.environ.copy()
        env["ANTE_DB_PATH"] = str(db_file)
        env["ANTE_DATA_PATH"] = str(tmp_path / "data")
        result = subprocess.run(
            [sys.executable, "-m", "ante.db.migrations"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, (
            f"migrations 러너 실패: stdout={result.stdout} stderr={result.stderr}"
        )
        assert db_file.exists(), "ANTE_DB_PATH 로 전달한 파일이 생성돼야 합니다"


async def _bootstrap_trades_schema(db: Database) -> None:
    """trades 스키마를 부트스트랩한다 (TradeRecorder.initialize 경유)."""
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder

    ph = PositionHistory(db)
    await ph.initialize()
    rec = TradeRecorder(db, ph)
    await rec.initialize()


async def _insert_trade_row(db: Database, trade_id: str, timestamp: str) -> None:
    """trades 에 raw timestamp 행을 직접 주입한다 (마이그레이션 테스트 한정)."""
    await db.execute(
        "INSERT INTO trades "
        "(trade_id, bot_id, strategy_id, symbol, side, quantity, price, status, "
        " order_type, reason, commission, timestamp, order_id, account_id, "
        " currency, exchange) "
        "VALUES (?, 'bot1', 's1', '005930', 'buy', 10.0, 50000.0, 'filled', "
        "'market', 'seed', 0.0, ?, ?, 'acc-real', 'KRW', 'KRX')",
        (trade_id, timestamp, trade_id),
    )


class TestV005TradesTimestampIsoformat:
    """#2371: v005 — trades.timestamp 공백 포맷 → UTC-aware isoformat 협소 변환."""

    async def test_registered_in_migrations(self):
        """v005 가 MIGRATIONS 리스트에 등록되어 있다."""
        seqs = [seq for seq, _, _ in MIGRATIONS]
        fns = [fn for _, _, fn in MIGRATIONS]
        assert 5 in seqs
        assert v005_trades_timestamp_isoformat.migrate in fns

    async def test_blank_format_row_converted_others_unchanged(self, db: Database):
        """공백 19자 행만 변환, isoformat 행·변형 행은 불변."""
        await _bootstrap_trades_schema(db)
        # (a) 공백 구분 19자 UTC 행 — 변환 대상.
        await _insert_trade_row(
            db, "11111111-1111-1111-1111-111111111111", "2026-06-12 09:30:00"
        )
        # (b) 이미 isoformat aware 행 — 불변.
        await _insert_trade_row(
            db, "22222222-2222-2222-2222-222222222222", "2026-06-12T04:43:53+00:00"
        )
        # (c) 변형 행: '+09:00' suffix(19자 아님, 텍스트) — 불변.
        await _insert_trade_row(
            db, "33333333-3333-3333-3333-333333333333", "2026-06-12 09:30:00+09:00"
        )

        await v005_trades_timestamp_isoformat.migrate(db)

        rows = await db.fetch_all("SELECT trade_id, timestamp FROM trades")
        ts_by_id = {r["trade_id"]: r["timestamp"] for r in rows}
        # (a) 공백 19자 행 → isoformat UTC 로 변환.
        assert (
            ts_by_id["11111111-1111-1111-1111-111111111111"]
            == "2026-06-12T09:30:00+00:00"
        )
        # (b) isoformat 행 불변.
        assert (
            ts_by_id["22222222-2222-2222-2222-222222222222"]
            == "2026-06-12T04:43:53+00:00"
        )
        # (c) 변형 행 불변(19자 아님 + GLOB 미일치).
        assert (
            ts_by_id["33333333-3333-3333-3333-333333333333"]
            == "2026-06-12 09:30:00+09:00"
        )

    async def test_idempotent_rerun(self, db: Database):
        """재실행 멱등 — 변환 후 패턴 미일치라 두 번째 실행은 no-op."""
        await _bootstrap_trades_schema(db)
        await _insert_trade_row(
            db, "11111111-1111-1111-1111-111111111111", "2026-06-12 09:30:00"
        )

        await v005_trades_timestamp_isoformat.migrate(db)
        first = await db.fetch_one(
            "SELECT timestamp FROM trades "
            "WHERE trade_id = '11111111-1111-1111-1111-111111111111'"
        )
        assert first is not None
        assert first["timestamp"] == "2026-06-12T09:30:00+00:00"

        # 재실행 — 변환된 행은 패턴 미일치라 불변.
        await v005_trades_timestamp_isoformat.migrate(db)
        second = await db.fetch_one(
            "SELECT timestamp FROM trades "
            "WHERE trade_id = '11111111-1111-1111-1111-111111111111'"
        )
        assert second is not None
        assert second["timestamp"] == "2026-06-12T09:30:00+00:00"

    async def test_no_trades_table_noop(self, db: Database):
        """trades 테이블 부재 DB 에서 no-op 통과(fresh install 가드)."""
        # trades 스키마를 부트스트랩하지 않은 빈 DB.
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
        )
        assert row is None
        # 예외 없이 통과해야 한다.
        await v005_trades_timestamp_isoformat.migrate(db)

    async def test_run_migrations_applies_v005(self, db: Database):
        """run_migrations 전체 실행이 v005 를 적용하고 공백 행을 변환한다."""
        await _bootstrap_trades_schema(db)
        await _insert_trade_row(
            db, "11111111-1111-1111-1111-111111111111", "2026-06-12 09:30:00"
        )

        applied = await run_migrations(db)
        assert "005_0.10.1" in applied

        row = await db.fetch_one(
            "SELECT timestamp FROM trades "
            "WHERE trade_id = '11111111-1111-1111-1111-111111111111'"
        )
        assert row is not None
        assert row["timestamp"] == "2026-06-12T09:30:00+00:00"

        applied_seqs = await get_applied_seqs(db)
        assert 5 in applied_seqs


async def _order_tracker_columns(db: Database) -> set[str]:
    rows = await db.fetch_all("PRAGMA table_info(order_tracker)")
    return {row["name"] for row in rows}


class TestV006OrderTrackerOrderPrice:
    """#2391: v006 — order_tracker 에 order_price 컬럼 추가."""

    async def test_registered_in_migrations(self):
        """v006 가 MIGRATIONS 리스트에 등록되어 있다."""
        seqs = [seq for seq, _, _ in MIGRATIONS]
        fns = [fn for _, _, fn in MIGRATIONS]
        assert 6 in seqs
        assert v006_order_tracker_order_price.migrate in fns

    async def test_adds_column_to_existing_table(self, db: Database):
        """기존(legacy) order_tracker 테이블에 order_price 컬럼을 ALTER 추가한다."""
        await db.execute(_LEGACY_ORDER_TRACKER_DDL)
        # 기존 row(원주문 가격 미상) 삽입.
        await db.execute(
            """INSERT INTO order_tracker
                   (order_id, account_id, bot_id, strategy_id, broker_order_id,
                    symbol, side, submitted_date)
               VALUES ('ord-legacy', 'acct-A', 'bot-1', 'strat-1', '0001',
                       '005930', 'buy', '20260601')""",
        )
        assert "order_price" not in await _order_tracker_columns(db)

        await v006_order_tracker_order_price.migrate(db)

        cols = await _order_tracker_columns(db)
        assert "order_price" in cols
        # 기존 row 는 NULL 로 남는다.
        row = await db.fetch_one(
            "SELECT order_price FROM order_tracker WHERE order_id = 'ord-legacy'"
        )
        assert row is not None
        assert row["order_price"] is None

    async def test_idempotent_rerun(self, db: Database):
        """컬럼이 이미 있으면 재실행 no-op (멱등)."""
        await db.execute(_LEGACY_ORDER_TRACKER_DDL)
        await v006_order_tracker_order_price.migrate(db)
        # 재실행 — 예외 없이 통과.
        await v006_order_tracker_order_price.migrate(db)
        cols = await _order_tracker_columns(db)
        assert "order_price" in cols

    async def test_no_table_noop(self, db: Database):
        """order_tracker 테이블 부재 DB 에서 no-op 통과(fresh install 가드)."""
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='order_tracker'"
        )
        assert row is None
        await v006_order_tracker_order_price.migrate(db)

    async def test_run_migrations_applies_v006(self, db: Database):
        """run_migrations 전체 실행이 기존 order_tracker 에 컬럼을 추가한다."""
        await db.execute(_LEGACY_ORDER_TRACKER_DDL)

        applied = await run_migrations(db)
        assert "006_0.11.0" in applied

        cols = await _order_tracker_columns(db)
        assert "order_price" in cols

        applied_seqs = await get_applied_seqs(db)
        assert 6 in applied_seqs
