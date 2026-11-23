"""Treasury가 기록하는 벽시계 값을 고정 시계로 단언한다 (#2768).

동기화 시각(``last_synced_at``·``get_summary()["last_sync_time"]``), 예산의
``last_updated``, 일일 스냅샷 보존 정리의 cutoff가 모두 ``ante.core.clock``의
시각을 따르는지 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import DailyReportEvent
from ante.treasury import Treasury

_AT = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
_RETENTION_DAYS = 365 * 5

pytestmark = pytest.mark.parametrize("manual_clock", [_AT], indirect=True)


@pytest.fixture
async def db(tmp_path: Any) -> Any:
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def treasury(manual_clock: Any, db: Database) -> Treasury:
    t = Treasury(db=db, eventbus=EventBus(), account_id="acc-clock")
    await t.initialize()
    await t.set_account_balance(10_000_000.0)
    return t


class _Broker:
    async def get_account_balance(self) -> dict[str, float]:
        return {"cash": 5_000_000.0, "total_assets": 5_000_000.0}

    async def get_buyable(self, symbol: str, **_: Any) -> dict[str, float]:
        return {"order_buyable_amount": 4_800_000.0}

    async def get_positions(self) -> list[dict[str, Any]]:
        return []


class _PositionHistory:
    async def get_all_positions(self, *, account_id: str | None = None) -> list[Any]:
        return []


def _broker() -> Any:
    return _Broker()


def _positions() -> Any:
    return _PositionHistory()


async def test_live_sync_records_fixed_time(treasury: Treasury) -> None:
    await treasury._do_sync(_broker(), _positions())

    assert treasury.last_synced_at == _AT
    assert treasury.get_summary()["last_sync_time"] == _AT.isoformat()


async def test_virtual_sync_records_fixed_time_after_advance(
    treasury: Treasury, manual_clock: Any
) -> None:
    manual_clock.advance(90.0)
    await treasury._do_sync_virtual(_positions())

    expected = _AT + timedelta(seconds=90)
    assert treasury.last_synced_at == expected
    assert treasury.get_summary()["last_sync_time"] == expected.isoformat()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#2798")
async def test_sync_time_survives_reload(treasury: Treasury) -> None:
    await treasury._do_sync(_broker(), _positions())
    if treasury.last_synced_at != _AT:
        pytest.fail(f"준비 실패: 동기화 시각 {treasury.last_synced_at!r}")

    await treasury.load_from_db()

    assert treasury.last_synced_at == _AT


async def test_budget_last_updated_follows_clock(
    treasury: Treasury, manual_clock: Any
) -> None:
    await treasury.allocate("bot-1", 1_000_000.0)
    budget = treasury.get_budget("bot-1")
    assert budget is not None
    assert budget.last_updated == _AT

    manual_clock.advance(3600.0)
    await treasury.deallocate("bot-1", 100_000.0)
    assert budget.last_updated == _AT + timedelta(hours=1)

    await treasury.load_from_db()
    reloaded = treasury.get_budget("bot-1")
    assert reloaded is not None
    assert reloaded.last_updated == _AT + timedelta(hours=1)


def _days_ago(days: int) -> str:
    return (_AT - timedelta(days=days)).strftime("%Y-%m-%d")


async def test_snapshot_retention_cutoff_boundary(treasury: Treasury) -> None:
    kept = [_days_ago(_RETENTION_DAYS - 1), _days_ago(_RETENTION_DAYS)]
    dropped = _days_ago(_RETENTION_DAYS + 1)
    for snapshot_date in [*kept, dropped]:
        await treasury.save_daily_snapshot(snapshot_date)

    await treasury.take_snapshot(
        DailyReportEvent(account_id="acc-clock", report_date=_AT.strftime("%Y-%m-%d"))
    )

    for snapshot_date in kept:
        assert await treasury.get_daily_snapshot(snapshot_date) is not None
    assert await treasury.get_daily_snapshot(dropped) is None
