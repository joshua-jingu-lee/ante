"""Daily Asset Snapshot 단위 테스트 (#682).

take_snapshot, get_snapshots, _cleanup_old_snapshots,
DailyReportEvent 구독을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import DailyReportEvent
from ante.treasury import Treasury

ACCOUNT_ID = "domestic"
CURRENCY = "KRW"


# -- Fixtures -------------------------------------------------


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def treasury(db, eventbus):
    t = Treasury(
        db=db,
        eventbus=eventbus,
        account_id=ACCOUNT_ID,
        currency=CURRENCY,
    )
    await t.initialize()
    await t.set_account_balance(10_000_000.0)
    return t


def _make_event(
    report_date: str = "2026-03-21",
    daily_pnl: float = 50_000.0,
    daily_return: float = 0.005,
    net_trade_amount: float = 1_000_000.0,
    unrealized_pnl: float = 150_000.0,
    account_id: str = ACCOUNT_ID,
) -> DailyReportEvent:
    return DailyReportEvent(
        account_id=account_id,
        report_date=report_date,
        trade_count=3,
        has_trades=True,
        daily_pnl=daily_pnl,
        daily_return=daily_return,
        net_trade_amount=net_trade_amount,
        unrealized_pnl=unrealized_pnl,
    )


# -- DDL: 확장 컬럼 존재 확인 ------------------------------------


class TestSnapshotSchema:
    async def test_schema_has_performance_columns(self, db, treasury):
        """DDL에 성과 필드 컬럼이 존재한다."""
        rows = await db.fetch_all("PRAGMA table_info(treasury_daily_snapshots)")
        col_names = {r["name"] for r in rows}
        expected = {
            "account_id",
            "snapshot_date",
            "total_asset",
            "ante_eval_amount",
            "ante_purchase_amount",
            "unallocated",
            "account_balance",
            "total_allocated",
            "bot_count",
            "daily_pnl",
            "daily_return",
            "net_trade_amount",
            "unrealized_pnl",
            "created_at",
        }
        assert expected.issubset(col_names)


# -- take_snapshot -----------------------------------------------


class TestTakeSnapshot:
    async def test_take_snapshot_saves_all_fields(self, treasury):
        """take_snapshot은 자산 현황 + 성과 필드를 모두 저장한다."""
        event = _make_event()
        await treasury.take_snapshot(event)

        snap = await treasury.get_daily_snapshot("2026-03-21")
        assert snap is not None
        assert snap["account_id"] == ACCOUNT_ID
        assert snap["snapshot_date"] == "2026-03-21"
        assert snap["daily_pnl"] == 50_000.0
        assert snap["daily_return"] == 0.005
        assert snap["net_trade_amount"] == 1_000_000.0
        assert snap["unrealized_pnl"] == 150_000.0
        # 자산 현황 필드도 존재
        assert snap["account_balance"] == 10_000_000.0
        assert snap["bot_count"] == 0

    async def test_take_snapshot_upsert(self, treasury):
        """동일 계좌+날짜에 대해 INSERT OR REPLACE 동작."""
        event1 = _make_event(daily_pnl=100.0)
        event2 = _make_event(daily_pnl=200.0)

        await treasury.take_snapshot(event1)
        await treasury.take_snapshot(event2)

        snap = await treasury.get_daily_snapshot("2026-03-21")
        assert snap is not None
        assert snap["daily_pnl"] == 200.0

    async def test_take_snapshot_includes_summary_fields(self, treasury):
        """take_snapshot은 get_summary() 값을 자산 필드에 반영한다."""
        # 봇 예산 할당하여 summary 값 변경
        await treasury.allocate("bot1", 3_000_000.0)

        event = _make_event()
        await treasury.take_snapshot(event)

        snap = await treasury.get_daily_snapshot("2026-03-21")
        assert snap is not None
        assert snap["total_allocated"] == 3_000_000.0
        assert snap["unallocated"] == 7_000_000.0
        assert snap["bot_count"] == 1

    async def test_total_asset_equals_ante_eval_plus_unallocated(self, treasury):
        """total_asset은 ante_eval_amount + unallocated 이어야 한다 (#743)."""
        await treasury.allocate("bot1", 3_000_000.0)

        event = _make_event()
        await treasury.take_snapshot(event)

        snap = await treasury.get_daily_snapshot("2026-03-21")
        assert snap is not None
        expected = snap["ante_eval_amount"] + snap["unallocated"]
        assert snap["total_asset"] == expected

    async def test_save_daily_snapshot_total_asset_formula(self, treasury):
        """save_daily_snapshot도 total_asset = ante_eval_amount + unallocated (#743)."""
        await treasury.allocate("bot1", 2_000_000.0)
        await treasury.save_daily_snapshot("2026-03-21")

        snap = await treasury.get_daily_snapshot("2026-03-21")
        assert snap is not None
        expected = snap["ante_eval_amount"] + snap["unallocated"]
        assert snap["total_asset"] == expected

    async def test_take_snapshot_ignores_non_daily_report_event(self, treasury):
        """DailyReportEvent가 아닌 이벤트는 무시한다."""
        await treasury.take_snapshot("not an event")
        snap = await treasury.get_daily_snapshot("2026-03-21")
        assert snap is None


# -- get_snapshots (범위 조회) -----------------------------------


class TestGetSnapshots:
    async def test_get_snapshots_range(self, treasury):
        """날짜 범위로 스냅샷을 조회한다."""
        for day in range(18, 22):
            event = _make_event(
                report_date=f"2026-03-{day:02d}",
                daily_pnl=float(day * 100),
            )
            await treasury.take_snapshot(event)

        result = await treasury.get_snapshots("2026-03-19", "2026-03-21")
        assert len(result) == 3
        assert result[0]["snapshot_date"] == "2026-03-19"
        assert result[-1]["snapshot_date"] == "2026-03-21"

    async def test_get_snapshots_empty(self, treasury):
        """범위에 해당하는 스냅샷이 없으면 빈 리스트."""
        result = await treasury.get_snapshots("2025-01-01", "2025-01-31")
        assert result == []

    async def test_get_snapshots_ordered_by_date(self, treasury):
        """결과는 날짜 오름차순 정렬."""
        # 역순으로 삽입
        for day in [21, 19, 20]:
            event = _make_event(report_date=f"2026-03-{day:02d}")
            await treasury.take_snapshot(event)

        result = await treasury.get_snapshots("2026-03-19", "2026-03-21")
        dates = [s["snapshot_date"] for s in result]
        assert dates == ["2026-03-19", "2026-03-20", "2026-03-21"]


# -- _cleanup_old_snapshots ------------------------------------


class TestCleanupOldSnapshots:
    async def test_cleanup_deletes_old_snapshots(self, treasury):
        """5년 초과 스냅샷이 삭제된다."""
        old_date = (datetime.now(UTC) - timedelta(days=365 * 5 + 1)).strftime(
            "%Y-%m-%d"
        )
        recent_date = "2026-03-21"

        # 오래된 스냅샷 직접 삽입
        await treasury.save_daily_snapshot(old_date)
        # 최근 스냅샷은 take_snapshot으로 (cleanup 트리거)
        event = _make_event(report_date=recent_date)
        await treasury.take_snapshot(event)

        old_snap = await treasury.get_daily_snapshot(old_date)
        recent_snap = await treasury.get_daily_snapshot(recent_date)

        assert old_snap is None
        assert recent_snap is not None

    async def test_cleanup_keeps_recent_snapshots(self, treasury):
        """5년 이내 스냅샷은 유지된다."""
        dates = ["2022-01-01", "2023-06-15", "2026-03-21"]
        for d in dates:
            event = _make_event(report_date=d)
            await treasury.take_snapshot(event)

        # 2022-01-01은 약 4년 전이므로 유지
        for d in dates:
            snap = await treasury.get_daily_snapshot(d)
            assert snap is not None, f"{d} should be retained"


# -- DailyReportEvent 구독 (EventBus) ---------------------------


class TestDailyReportSubscription:
    async def test_eventbus_triggers_snapshot(self, treasury, eventbus):
        """DailyReportEvent 발행 시 자동으로 스냅샷이 저장된다."""
        event = _make_event()
        await eventbus.publish(event)

        snap = await treasury.get_daily_snapshot("2026-03-21")
        assert snap is not None
        assert snap["daily_pnl"] == 50_000.0

    async def test_eventbus_ignores_other_account(self, db, eventbus):
        """다른 계좌의 이벤트는 무시한다."""
        t = Treasury(
            db=db,
            eventbus=eventbus,
            account_id="overseas",
            currency="USD",
        )
        await t.initialize()

        # domestic 계좌 이벤트 발행
        event = _make_event(account_id=ACCOUNT_ID)
        await eventbus.publish(event)

        # overseas treasury에는 저장되지 않음
        snap = await t.get_daily_snapshot("2026-03-21")
        assert snap is None


# -- save_daily_snapshot (하위 호환) ----------------------------


class TestSaveDailySnapshotCompat:
    async def test_save_daily_snapshot_still_works(self, treasury):
        """기존 save_daily_snapshot도 확장된 스키마에서 동작한다."""
        await treasury.save_daily_snapshot("2026-03-21")

        snap = await treasury.get_daily_snapshot("2026-03-21")
        assert snap is not None
        assert snap["account_balance"] == 10_000_000.0
        # 성과 필드는 기본값
        assert snap["daily_pnl"] == 0.0
        assert snap["daily_return"] == 0.0

    async def test_take_snapshot_overwrites_save_daily(self, treasury):
        """save_daily_snapshot 후 take_snapshot이 성과 필드를 덮어쓴다."""
        await treasury.save_daily_snapshot("2026-03-21")
        event = _make_event(daily_pnl=99_999.0)
        await treasury.take_snapshot(event)

        snap = await treasury.get_daily_snapshot("2026-03-21")
        assert snap is not None
        assert snap["daily_pnl"] == 99_999.0
