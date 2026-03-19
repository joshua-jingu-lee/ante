"""봇 중지 시 미체결 예약 자금 자동 해제 테스트."""

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import BotStoppedEvent
from ante.treasury import Treasury


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
    t = Treasury(db=db, eventbus=eventbus)
    await t.initialize()
    await t.set_account_balance(10_000_000.0)
    await t.allocate("bot1", 5_000_000.0)
    await t.allocate("bot2", 3_000_000.0)
    return t


# ── US-2: 봇별 예약 내역 조회 ──────────────────────


class TestGetReservations:
    async def test_empty_reservations(self, treasury):
        """예약 없는 봇 → 빈 dict."""
        result = treasury.get_reservations("bot1")
        assert result == {}

    async def test_single_reservation(self, treasury):
        """단일 예약."""
        await treasury.reserve_for_order("bot1", "ord1", 100_000.0)
        result = treasury.get_reservations("bot1")
        assert result == {"ord1": 100_000.0}

    async def test_multiple_reservations(self, treasury):
        """복수 예약."""
        await treasury.reserve_for_order("bot1", "ord1", 100_000.0)
        await treasury.reserve_for_order("bot1", "ord2", 200_000.0)
        result = treasury.get_reservations("bot1")
        assert result == {"ord1": 100_000.0, "ord2": 200_000.0}

    async def test_filters_by_bot_id(self, treasury):
        """다른 봇의 예약은 필터링."""
        await treasury.reserve_for_order("bot1", "ord1", 100_000.0)
        await treasury.reserve_for_order("bot2", "ord2", 200_000.0)
        assert treasury.get_reservations("bot1") == {"ord1": 100_000.0}
        assert treasury.get_reservations("bot2") == {"ord2": 200_000.0}

    async def test_reservation_removed_after_release(self, treasury):
        """해제 후 조회 결과에서 제거."""
        await treasury.reserve_for_order("bot1", "ord1", 100_000.0)
        await treasury.release_reservation("bot1", "ord1")
        assert treasury.get_reservations("bot1") == {}


# ── US-1: 봇 중지 시 예약 자금 일괄 해제 ────────────


class TestBotStopRelease:
    async def test_bot_stopped_releases_all_reservations(self, treasury, eventbus):
        """BotStoppedEvent → 해당 봇 예약 전부 해제."""
        await treasury.reserve_for_order("bot1", "ord1", 100_000.0)
        await treasury.reserve_for_order("bot1", "ord2", 200_000.0)

        budget_before = treasury.get_budget("bot1")
        available_before = budget_before.available

        await eventbus.publish(BotStoppedEvent(bot_id="bot1"))

        budget_after = treasury.get_budget("bot1")
        assert budget_after.reserved == 0.0
        assert budget_after.available == pytest.approx(available_before + 300_000.0)
        assert treasury.get_reservations("bot1") == {}

    async def test_bot_stopped_does_not_affect_other_bots(self, treasury, eventbus):
        """다른 봇의 예약은 영향 없음."""
        await treasury.reserve_for_order("bot1", "ord1", 100_000.0)
        await treasury.reserve_for_order("bot2", "ord2", 200_000.0)

        await eventbus.publish(BotStoppedEvent(bot_id="bot1"))

        assert treasury.get_reservations("bot2") == {"ord2": 200_000.0}
        budget2 = treasury.get_budget("bot2")
        assert budget2.reserved == 200_000.0

    async def test_bot_stopped_no_reservations_noop(self, treasury, eventbus):
        """예약 없는 봇 중지 → 아무 변화 없음."""
        budget_before = treasury.get_budget("bot1")

        await eventbus.publish(BotStoppedEvent(bot_id="bot1"))

        budget_after = treasury.get_budget("bot1")
        assert budget_after.available == budget_before.available
        assert budget_after.reserved == budget_before.reserved

    async def test_bot_stopped_logs_transaction(self, treasury, eventbus, db):
        """해제 시 거래 이력에 bot_stopped_release 기록."""
        await treasury.reserve_for_order("bot1", "ord1", 100_000.0)

        await eventbus.publish(BotStoppedEvent(bot_id="bot1"))

        rows = await db.fetch_all(
            "SELECT * FROM treasury_transactions "
            "WHERE transaction_type = 'bot_stopped_release'"
        )
        assert len(rows) == 1
        assert rows[0]["bot_id"] == "bot1"
        assert rows[0]["amount"] == pytest.approx(100_000.0)
        assert "1건" in rows[0]["description"]

    async def test_bot_stopped_releases_correct_total(self, treasury, eventbus):
        """여러 예약 해제 시 총 금액이 정확."""
        await treasury.reserve_for_order("bot1", "ord1", 150_000.0)
        await treasury.reserve_for_order("bot1", "ord2", 250_000.0)
        await treasury.reserve_for_order("bot1", "ord3", 100_000.0)

        await eventbus.publish(BotStoppedEvent(bot_id="bot1"))

        budget = treasury.get_budget("bot1")
        assert budget.reserved == 0.0
        # available should have all 500k returned
        assert budget.available == pytest.approx(5_000_000.0 - 500_000.0 + 500_000.0)

    async def test_unknown_bot_stopped_no_error(self, treasury, eventbus):
        """존재하지 않는 봇 중지 → 에러 없이 무시."""
        await eventbus.publish(BotStoppedEvent(bot_id="unknown_bot"))
        # 에러 없이 통과


# ── 기존 예약/해제 호환성 ──────────────────────────


class TestReservationCompatibility:
    async def test_reserve_and_release_still_works(self, treasury):
        """기존 reserve/release 정상 동작."""
        await treasury.reserve_for_order("bot1", "ord1", 100_000.0)
        budget = treasury.get_budget("bot1")
        assert budget.reserved == 100_000.0

        await treasury.release_reservation("bot1", "ord1")
        budget = treasury.get_budget("bot1")
        assert budget.reserved == 0.0

    async def test_nonexistent_order_release_noop(self, treasury):
        """존재하지 않는 주문 해제 → 무시."""
        await treasury.release_reservation("bot1", "nonexistent")
        budget = treasury.get_budget("bot1")
        assert budget.available == 5_000_000.0
