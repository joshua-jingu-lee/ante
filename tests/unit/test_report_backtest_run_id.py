"""report submit --run backtest_run_id durable 저장 테스트 (#1999).

P2: ``report submit --run`` 이 backtest run 존재만 검증하고 참조를 저장하지
않던 회귀를 차단한다. ``backtest_run_id`` 를 ``reports`` 테이블 컬럼으로 영속하고,
``--run`` 과 payload ``backtest_run_id`` 양쪽 경로를 ``BacktestRunStore`` 존재
검증한다 (payload 우회 차단). 검증 시나리오:

- store 레벨: submit → DB 영속 + get/list(_row_to_report) 라운드트립.
- 멱등 ALTER: pre-#1999 테이블(backtest_run_id 없음)에 2회 init 무해, NULL → "".
- upsert_draft UPDATE: backtest_run_id 보존.
- get_schema().optional_fields 노출.
- ReportSubmitRequest(extra=forbid) backtest_run_id 검증 통과.
- CLI: --run → DB 저장 + 출력 echo; payload-only → 검증 후 저장(미존재 우회 차단);
  --run + payload 충돌 → --run 우선(silent override); 참조 없음 → "".
- report view 출력 payload 에 backtest_run_id (view drift).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core.database import Database
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.report.models import ReportStatus, StrategyReport
from ante.report.store import ReportStore
from ante.report.validation import ReportSubmitRequest

# ── store-level fixtures ──────────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB (명시적 close 로 aiosqlite 누수 차단)."""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def store(db):
    s = ReportStore(db)
    await s.initialize()
    return s


def _make_report(
    *,
    report_id: str = "rpt-001",
    strategy_name: str = "momentum_breakout",
    status: ReportStatus = ReportStatus.SUBMITTED,
    backtest_run_id: str = "",
) -> StrategyReport:
    return StrategyReport(
        report_id=report_id,
        strategy_name=strategy_name,
        strategy_version="1.0.0",
        strategy_path="strategies/momentum_breakout.py",
        status=status,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        submitted_by="agent",
        backtest_period="2024-01 ~ 2026-03",
        backtest_run_id=backtest_run_id,
        total_return_pct=15.3,
        total_trades=42,
        sharpe_ratio=1.2,
        max_drawdown_pct=-8.5,
        win_rate=58.0,
        summary="20일 이동평균 돌파 매매 전략",
        rationale="모멘텀 효과를 활용한 추세 추종",
        risks="횡보장에서 잦은 손절 발생 가능",
    )


# ── (a) store: submit → DB 영속 + get/list 라운드트립 ─────────────────


class TestStoreDurablePersistence:
    async def test_submit_persists_backtest_run_id(self, store):
        """submit 시 backtest_run_id 가 DB 컬럼에 저장되고 get 으로 복원된다."""
        await store.submit(_make_report(backtest_run_id="run-abc"))

        fetched = await store.get("rpt-001")
        assert fetched is not None
        assert fetched.backtest_run_id == "run-abc"

    async def test_list_round_trips_backtest_run_id(self, store):
        """list_reports(_row_to_report)도 backtest_run_id 를 복원한다."""
        await store.submit(_make_report(report_id="rpt-001", backtest_run_id="run-1"))
        await store.submit(_make_report(report_id="rpt-002", backtest_run_id=""))

        rows = {r.report_id: r for r in await store.list_reports()}
        assert rows["rpt-001"].backtest_run_id == "run-1"
        assert rows["rpt-002"].backtest_run_id == ""

    async def test_no_reference_defaults_empty(self, store):
        """(d) 참조 없이 제출하면 backtest_run_id 는 빈 문자열."""
        await store.submit(_make_report(backtest_run_id=""))

        fetched = await store.get("rpt-001")
        assert fetched is not None
        assert fetched.backtest_run_id == ""

    async def test_upsert_draft_preserves_backtest_run_id(self, store):
        """(f) upsert_draft 갱신 시 backtest_run_id UPDATE 보존."""
        draft = _make_report(
            report_id="rpt-draft",
            status=ReportStatus.DRAFT,
            backtest_run_id="run-old",
        )
        await store.upsert_draft(draft)

        updated = _make_report(
            report_id="rpt-draft-new",
            status=ReportStatus.DRAFT,
            backtest_run_id="run-new",
        )
        rid = await store.upsert_draft(updated)

        fetched = await store.get(rid)
        assert fetched is not None
        assert fetched.backtest_run_id == "run-new"


# ── (e) 멱등 ALTER: pre-#1999 테이블 마이그레이션 ─────────────────────


class TestIdempotentMigration:
    async def test_double_initialize_is_harmless(self, db):
        """2회 init 이 duplicate-column OperationalError 를 삼키고 무해하다."""
        store = ReportStore(db)
        await store.initialize()
        # 두 번째 init 은 ALTER 가 "duplicate column name" 으로 실패하나 catch 됨.
        await store.initialize()

        # 정상 동작 확인.
        await store.submit(_make_report(backtest_run_id="run-x"))
        fetched = await store.get("rpt-001")
        assert fetched is not None
        assert fetched.backtest_run_id == "run-x"

    async def test_legacy_table_without_column_migrates(self, db):
        """pre-#1999 테이블(backtest_run_id 없음)에 init 하면 컬럼이 추가된다."""
        # backtest_run_id 컬럼이 없는 legacy reports 테이블을 직접 만든다.
        await db.execute(
            """CREATE TABLE reports (
                report_id          TEXT PRIMARY KEY,
                strategy_name      TEXT NOT NULL,
                strategy_version   TEXT NOT NULL,
                strategy_path      TEXT NOT NULL,
                status             TEXT NOT NULL DEFAULT 'submitted',
                submitted_at       TEXT NOT NULL,
                submitted_by       TEXT DEFAULT 'agent',
                backtest_period    TEXT DEFAULT '',
                total_return_pct   REAL DEFAULT 0.0,
                total_trades       INTEGER DEFAULT 0,
                sharpe_ratio       REAL,
                max_drawdown_pct   REAL,
                win_rate           REAL,
                summary            TEXT DEFAULT '',
                rationale          TEXT DEFAULT '',
                risks              TEXT DEFAULT '',
                recommendations    TEXT DEFAULT '',
                detail_json        TEXT DEFAULT '{}',
                user_notes         TEXT DEFAULT '',
                reviewed_at        TEXT
            )"""
        )
        # legacy row 1건 (backtest_run_id 컬럼 없음).
        await db.execute(
            """INSERT INTO reports
               (report_id, strategy_name, strategy_version, strategy_path,
                status, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "rpt-legacy",
                "legacy_strat",
                "0.1",
                "strategies/legacy.py",
                ReportStatus.SUBMITTED.value,
                datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
            ),
        )

        store = ReportStore(db)
        await store.initialize()  # ALTER 로 backtest_run_id 추가.

        # legacy row 는 NULL → "" 정규화.
        legacy = await store.get("rpt-legacy")
        assert legacy is not None
        assert legacy.backtest_run_id == ""

        # 새 row 는 backtest_run_id 저장 가능.
        await store.submit(_make_report(backtest_run_id="run-new"))
        fetched = await store.get("rpt-001")
        assert fetched is not None
        assert fetched.backtest_run_id == "run-new"

    async def test_other_operational_error_propagates(self, db):
        """duplicate-column 이외 OperationalError 는 전파된다 (narrow catch)."""
        store = ReportStore(db)

        # 마이그레이션 실행 시 무관한 OperationalError 를 주입한다.
        import sqlite3

        original_execute = db.execute

        async def _raise_disk_error(query, *args, **kwargs):
            if query.strip().startswith("ALTER TABLE reports"):
                raise sqlite3.OperationalError("disk I/O error")
            return await original_execute(query, *args, **kwargs)

        with patch.object(db, "execute", side_effect=_raise_disk_error):
            with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
                await store.initialize()


# ── (g) get_schema().optional_fields ──────────────────────────────────


def test_get_schema_exposes_backtest_run_id():
    """get_schema().optional_fields 에 backtest_run_id 가 노출된다."""
    schema = ReportStore.get_schema()
    assert "backtest_run_id" in schema["optional_fields"]


# ── (h) ReportSubmitRequest(extra=forbid) backtest_run_id 검증 ─────────


class TestSubmitRequestValidation:
    def test_backtest_run_id_accepted(self):
        """extra=forbid 모델이 backtest_run_id 를 명시 필드로 받는다."""
        req = ReportSubmitRequest.model_validate(
            {
                "strategy_name": "s",
                "strategy_version": "1.0",
                "strategy_path": "strategies/s.py",
                "backtest_period": "2024-01 ~ 2026-03",
                "total_return_pct": 1.0,
                "total_trades": 1,
                "summary": "요약",
                "rationale": "근거",
                "backtest_run_id": "run-payload",
            }
        )
        assert req.backtest_run_id == "run-payload"

    def test_backtest_run_id_defaults_empty(self):
        """미지정 시 backtest_run_id 는 빈 문자열 기본값."""
        req = ReportSubmitRequest.model_validate(
            {
                "strategy_name": "s",
                "strategy_version": "1.0",
                "strategy_path": "strategies/s.py",
                "backtest_period": "2024-01 ~ 2026-03",
                "total_return_pct": 1.0,
                "total_trades": 1,
                "summary": "요약",
                "rationale": "근거",
            }
        )
        assert req.backtest_run_id == ""


# ── CLI end-to-end fixtures ───────────────────────────────────────────


_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status=MemberStatus.ACTIVE,
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


async def _seed_backtest_run(db_path: str, run_id: str) -> None:
    """결정적 run_id 로 backtest_runs row 1건을 시드한다."""
    from ante.backtest.run_store import BacktestRunStore

    database = Database(db_path)
    await database.connect()
    try:
        await BacktestRunStore(database).initialize()
        await database.execute(
            """INSERT INTO backtest_runs
               (run_id, strategy_name, strategy_version, params_json,
                total_return_pct, sharpe_ratio, max_drawdown_pct,
                total_trades, win_rate, result_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                "momentum",
                "1.0.0",
                "{}",
                15.0,
                1.2,
                -8.5,
                42,
                58.0,
                "",
                datetime(2026, 3, 19, tzinfo=UTC).isoformat(),
            ),
        )
    finally:
        await database.close()


async def _fetch_report_backtest_run_id(db_path: str, report_id: str) -> str | None:
    """저장된 report 의 backtest_run_id 를 직접 조회한다."""
    database = Database(db_path)
    await database.connect()
    try:
        store = ReportStore(database)
        await store.initialize()
        report = await store.get(report_id)
        return report.backtest_run_id if report else None
    finally:
        await database.close()


def _write_report_file(tmp_path, **overrides) -> str:
    data = {
        "strategy_name": "momentum",
        "strategy_version": "1.0.0",
        "strategy_path": "strategies/momentum.py",
        "backtest_period": "2025-01 ~ 2025-12",
        "total_return_pct": 15.0,
        "total_trades": 42,
        "summary": "테스트 리포트",
        "rationale": "테스트",
    }
    data.update(overrides)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ── CLI: --run / payload / 충돌 / 우회 차단 (real DB) ──────────────────


class TestCliSubmitDurable:
    def test_a_submit_with_run_persists_and_echoes(self, runner, tmp_path):
        """(a) --run → DB backtest_run_id 저장 + 출력 echo."""
        import asyncio

        db_path = str(tmp_path / "ante.db")
        asyncio.run(_seed_backtest_run(db_path, "run-1"))
        report_file = _write_report_file(tmp_path)

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "report",
                "submit",
                report_file,
                "--db-path",
                db_path,
                "--run",
                "run-1",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "ok"
        report_id = data["data"]["report_id"]
        assert data["data"]["backtest_run_id"] == "run-1"

        stored = asyncio.run(_fetch_report_backtest_run_id(db_path, report_id))
        assert stored == "run-1"

    def test_b_payload_only_validated_and_persisted(self, runner, tmp_path):
        """(b) payload backtest_run_id만(--run 없음) → 검증 후 저장."""
        import asyncio

        db_path = str(tmp_path / "ante.db")
        asyncio.run(_seed_backtest_run(db_path, "run-payload"))
        report_file = _write_report_file(tmp_path, backtest_run_id="run-payload")

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "report",
                "submit",
                report_file,
                "--db-path",
                db_path,
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        report_id = data["data"]["report_id"]
        assert data["data"]["backtest_run_id"] == "run-payload"

        stored = asyncio.run(_fetch_report_backtest_run_id(db_path, report_id))
        assert stored == "run-payload"

    def test_b_payload_only_missing_run_rejected(self, runner, tmp_path):
        """(b) payload 우회 차단: 미존재 run 을 payload 로 주면 검증 에러."""
        import asyncio

        db_path = str(tmp_path / "ante.db")
        # backtest_runs 테이블만 초기화 (해당 run 은 없음).
        asyncio.run(_seed_backtest_run(db_path, "other-run"))
        report_file = _write_report_file(tmp_path, backtest_run_id="ghost-run")

        result = runner.invoke(
            cli,
            [
                "report",
                "submit",
                report_file,
                "--db-path",
                db_path,
            ],
        )
        assert result.exit_code == 1, result.output
        assert "ghost-run" in result.output

        # 미존재 run 참조는 영속되지 않는다 (저장 자체가 일어나지 않음).
        report_id = "any"
        stored = asyncio.run(_fetch_report_backtest_run_id(db_path, report_id))
        assert stored is None

    def test_c_run_option_wins_over_payload(self, runner, tmp_path):
        """(c) --run + payload 충돌 → --run 우선(silent override)."""
        import asyncio

        db_path = str(tmp_path / "ante.db")
        # --run 값만 실존, payload 값은 미존재 run. --run 우선이면 검증 통과.
        asyncio.run(_seed_backtest_run(db_path, "run-cli"))
        report_file = _write_report_file(
            tmp_path, backtest_run_id="run-payload-ignored"
        )

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "report",
                "submit",
                report_file,
                "--db-path",
                db_path,
                "--run",
                "run-cli",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        report_id = data["data"]["report_id"]
        # --run 이 payload 를 silent override 한다.
        assert data["data"]["backtest_run_id"] == "run-cli"

        stored = asyncio.run(_fetch_report_backtest_run_id(db_path, report_id))
        assert stored == "run-cli"

    def test_d_no_reference_persists_empty(self, runner, tmp_path):
        """(d) 참조 없음(--run/payload 모두 없음) → "" 저장 + 검증 생략."""
        import asyncio

        db_path = str(tmp_path / "ante.db")
        report_file = _write_report_file(tmp_path)

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "report",
                "submit",
                report_file,
                "--db-path",
                db_path,
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        report_id = data["data"]["report_id"]
        assert data["data"]["backtest_run_id"] == ""

        stored = asyncio.run(_fetch_report_backtest_run_id(db_path, report_id))
        assert stored == ""


# ── (i) report view 출력 payload 에 backtest_run_id (view drift) ──────


class TestCliViewEchoesBacktestRunId:
    def test_view_payload_includes_backtest_run_id(self, runner, tmp_path):
        """(i) report view --format json 출력에 backtest_run_id 노출."""
        import asyncio

        db_path = str(tmp_path / "ante.db")
        asyncio.run(_seed_backtest_run(db_path, "run-view"))
        report_file = _write_report_file(tmp_path)

        submit_result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "report",
                "submit",
                report_file,
                "--db-path",
                db_path,
                "--run",
                "run-view",
            ],
        )
        assert submit_result.exit_code == 0, submit_result.output
        report_id = json.loads(submit_result.output)["data"]["report_id"]

        view_result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "report",
                "view",
                report_id,
                "--db-path",
                db_path,
            ],
        )
        assert view_result.exit_code == 0, view_result.output
        view_payload = json.loads(view_result.output)
        assert view_payload["backtest_run_id"] == "run-view"
