"""v005_report_win_rate_ratio 회귀 테스트.

SSOT: docs/specs/report-store/report-store.md ("win_rate": 0.58, ratio 0~1).

#1353 이전에 reports.win_rate 가 percent 단위(예: 62.2)로 기록된 legacy
record가 존재했으며, 신규 frontend 환산식(`value * 100`)이 6220% 같은
회귀 값을 만들었다. v005 마이그레이션은 ``win_rate > 1.0`` 인 모든 record
를 ``/100.0`` 으로 정규화하여 ratio 표현으로 통일한다.
"""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.db.migrations import MIGRATIONS, run_migrations
from ante.db.versions import v005_report_win_rate_ratio


@pytest.fixture
async def db(tmp_path):
    """임시 SQLite DB."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


async def _create_minimal_reports_table(db: Database) -> None:
    """v005 단독 테스트용 최소 reports 스키마.

    실제 ReportStore.initialize 와 컬럼 호환되도록 핵심 필드만 포함한다.
    """
    await db.execute(
        """
        CREATE TABLE reports (
            report_id          TEXT PRIMARY KEY,
            strategy_name      TEXT NOT NULL,
            strategy_version   TEXT NOT NULL,
            strategy_path      TEXT NOT NULL,
            status             TEXT NOT NULL DEFAULT 'submitted',
            submitted_at       TEXT NOT NULL,
            win_rate           REAL
        )
        """
    )


async def _insert_report(db: Database, report_id: str, win_rate: float | None) -> None:
    await db.execute(
        "INSERT INTO reports "
        "(report_id, strategy_name, strategy_version, strategy_path, "
        " status, submitted_at, win_rate) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            report_id,
            "demo",
            "1.0.0",
            "strategies/demo.py",
            "submitted",
            "2026-01-01T00:00:00",
            win_rate,
        ),
    )


async def _select_win_rate(db: Database, report_id: str) -> float | None:
    row = await db.fetch_one(
        "SELECT win_rate FROM reports WHERE report_id = ?", (report_id,)
    )
    assert row is not None
    return row["win_rate"]


class TestV005Registration:
    """v005가 MIGRATIONS 리스트에 등록되어 있다."""

    def test_v005_in_migrations(self) -> None:
        seqs = [seq for seq, _, _ in MIGRATIONS]
        fns = [fn for _, _, fn in MIGRATIONS]
        assert 5 in seqs
        assert v005_report_win_rate_ratio.migrate in fns


class TestV005MigrateUnit:
    """v005 단독 동작 검증."""

    async def test_skips_when_reports_table_absent(self, db: Database) -> None:
        """reports 테이블이 없으면 에러 없이 skip 한다."""
        # 테이블 없음 — 그대로 호출해도 예외 없어야 한다.
        await v005_report_win_rate_ratio.migrate(db)

        # reports 테이블이 새로 생성되어서는 안 된다.
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reports'"
        )
        assert row is None

    async def test_normalizes_legacy_percent_record(self, db: Database) -> None:
        """percent legacy(62.2) → ratio(0.622)."""
        await _create_minimal_reports_table(db)
        await _insert_report(db, "r-legacy", 62.2)

        await v005_report_win_rate_ratio.migrate(db)

        result = await _select_win_rate(db, "r-legacy")
        assert result == pytest.approx(0.622)

    async def test_preserves_ratio_record(self, db: Database) -> None:
        """이미 ratio(0.5)인 record는 변경되지 않는다."""
        await _create_minimal_reports_table(db)
        await _insert_report(db, "r-ratio", 0.5)

        await v005_report_win_rate_ratio.migrate(db)

        result = await _select_win_rate(db, "r-ratio")
        assert result == pytest.approx(0.5)

    async def test_preserves_null_record(self, db: Database) -> None:
        """NULL win_rate 는 그대로 유지된다."""
        await _create_minimal_reports_table(db)
        await _insert_report(db, "r-null", None)

        await v005_report_win_rate_ratio.migrate(db)

        result = await _select_win_rate(db, "r-null")
        assert result is None

    async def test_preserves_zero(self, db: Database) -> None:
        """0.0 (`> 1.0` 조건 미충족)은 변경되지 않는다."""
        await _create_minimal_reports_table(db)
        await _insert_report(db, "r-zero", 0.0)

        await v005_report_win_rate_ratio.migrate(db)

        result = await _select_win_rate(db, "r-zero")
        assert result == pytest.approx(0.0)

    async def test_preserves_one(self, db: Database) -> None:
        """1.0 boundary (`> 1.0` 조건 미충족)은 변경되지 않는다."""
        await _create_minimal_reports_table(db)
        await _insert_report(db, "r-one", 1.0)

        await v005_report_win_rate_ratio.migrate(db)

        result = await _select_win_rate(db, "r-one")
        assert result == pytest.approx(1.0)

    async def test_mixed_records_normalized_correctly(self, db: Database) -> None:
        """다양한 record가 한 번에 섞여도 각각 올바르게 처리된다."""
        await _create_minimal_reports_table(db)
        await _insert_report(db, "legacy", 62.2)
        await _insert_report(db, "ratio", 0.5)
        await _insert_report(db, "null", None)
        await _insert_report(db, "zero", 0.0)
        await _insert_report(db, "one", 1.0)
        # 추가 edge: 100% legacy → 1.0 ratio
        await _insert_report(db, "legacy-100", 100.0)

        await v005_report_win_rate_ratio.migrate(db)

        assert await _select_win_rate(db, "legacy") == pytest.approx(0.622)
        assert await _select_win_rate(db, "ratio") == pytest.approx(0.5)
        assert await _select_win_rate(db, "null") is None
        assert await _select_win_rate(db, "zero") == pytest.approx(0.0)
        assert await _select_win_rate(db, "one") == pytest.approx(1.0)
        assert await _select_win_rate(db, "legacy-100") == pytest.approx(1.0)


class TestV005ViaRunner:
    """전체 마이그레이션 러너를 통한 통합 검증."""

    async def test_v005_applied_via_run_migrations(self, db: Database) -> None:
        """run_migrations 가 v005 까지 순서대로 적용한다."""
        # reports 테이블에 legacy record 를 미리 넣어둔다 (실제로는 v001~v004 이전
        # 쓰기 record를 모방). v001 이후에 reports 테이블이 만들어지더라도 본
        # 시나리오는 percent legacy 값이 남아 있는 production DB 를 흉내낸다.
        await _create_minimal_reports_table(db)
        await _insert_report(db, "r-legacy", 62.2)
        await _insert_report(db, "r-ratio", 0.5)

        result = await run_migrations(db)

        # v005 가 적용되었는지 확인 (라벨 형식: "005_0.8.0")
        assert any(label.startswith("005_") for label in result), result

        assert await _select_win_rate(db, "r-legacy") == pytest.approx(0.622)
        assert await _select_win_rate(db, "r-ratio") == pytest.approx(0.5)

    async def test_v005_idempotent(self, db: Database) -> None:
        """v005 가 두 번 적용되어도 (재실행해도) 추가 변환이 일어나지 않는다."""
        await _create_minimal_reports_table(db)
        await _insert_report(db, "r-legacy", 62.2)

        await run_migrations(db)
        # 1차 적용 후 → 0.622
        assert await _select_win_rate(db, "r-legacy") == pytest.approx(0.622)

        # 두 번째 호출은 schema_version 에 의해 skip 되어야 한다.
        result2 = await run_migrations(db)
        assert result2 == []

        # 값이 추가로 /100 되지 않았는지 확인 (멱등성).
        assert await _select_win_rate(db, "r-legacy") == pytest.approx(0.622)
