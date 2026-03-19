"""DRAFT upsert 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ante.report.models import ReportStatus, StrategyReport
from ante.report.store import ReportStore


@pytest.fixture
async def report_store(tmp_path):
    """테스트용 ReportStore."""
    from ante.core.database import Database

    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    await db.connect()

    store = ReportStore(db)
    await store.initialize()
    yield store

    await db.close()


def _make_draft(
    strategy_name: str = "momentum",
    total_return_pct: float = 10.0,
    report_id: str = "rpt-1",
) -> StrategyReport:
    return StrategyReport(
        report_id=report_id,
        strategy_name=strategy_name,
        strategy_version="1.0.0",
        strategy_path="strategies/momentum.py",
        status=ReportStatus.DRAFT,
        submitted_at=datetime.now(tz=UTC),
        submitted_by="system",
        backtest_period="2025-01 ~ 2025-12",
        total_return_pct=total_return_pct,
        total_trades=42,
        summary="초안",
    )


class TestDraftUpsert:
    @pytest.mark.asyncio
    async def test_upsert_creates_new_draft(self, report_store):
        """기존 DRAFT가 없을 때 새로 생성."""
        report = _make_draft()
        result_id = await report_store.upsert_draft(report)

        assert result_id == "rpt-1"
        stored = await report_store.get("rpt-1")
        assert stored is not None
        assert stored.status == ReportStatus.DRAFT
        assert stored.total_return_pct == 10.0

    @pytest.mark.asyncio
    async def test_upsert_overwrites_existing_draft(self, report_store):
        """동일 전략의 기존 DRAFT를 덮어쓰기."""
        report1 = _make_draft(total_return_pct=10.0, report_id="rpt-1")
        await report_store.upsert_draft(report1)

        report2 = _make_draft(total_return_pct=20.0, report_id="rpt-2")
        result_id = await report_store.upsert_draft(report2)

        # 기존 report_id 유지
        assert result_id == "rpt-1"

        # 내용이 업데이트됨
        stored = await report_store.get("rpt-1")
        assert stored is not None
        assert stored.total_return_pct == 20.0

        # 새 report_id는 저장되지 않음
        not_found = await report_store.get("rpt-2")
        assert not_found is None

    @pytest.mark.asyncio
    async def test_upsert_different_strategies(self, report_store):
        """다른 전략의 DRAFT는 독립 유지."""
        report_a = _make_draft(strategy_name="strategy_a", report_id="rpt-a")
        report_b = _make_draft(strategy_name="strategy_b", report_id="rpt-b")

        await report_store.upsert_draft(report_a)
        await report_store.upsert_draft(report_b)

        stored_a = await report_store.get("rpt-a")
        stored_b = await report_store.get("rpt-b")
        assert stored_a is not None
        assert stored_b is not None
        assert stored_a.strategy_name == "strategy_a"
        assert stored_b.strategy_name == "strategy_b"

    @pytest.mark.asyncio
    async def test_submitted_does_not_block_new_draft(self, report_store):
        """SUBMITTED 상태 리포트는 DRAFT 슬롯을 점유하지 않음."""
        # DRAFT 생성 후 SUBMITTED로 전환
        report1 = _make_draft(total_return_pct=10.0, report_id="rpt-1")
        await report_store.upsert_draft(report1)
        await report_store.update_status("rpt-1", ReportStatus.SUBMITTED)

        # 새 DRAFT는 별도로 생성됨
        report2 = _make_draft(total_return_pct=20.0, report_id="rpt-2")
        result_id = await report_store.upsert_draft(report2)

        assert result_id == "rpt-2"

        # 둘 다 존재
        stored1 = await report_store.get("rpt-1")
        stored2 = await report_store.get("rpt-2")
        assert stored1 is not None
        assert stored1.status == ReportStatus.SUBMITTED
        assert stored2 is not None
        assert stored2.status == ReportStatus.DRAFT
