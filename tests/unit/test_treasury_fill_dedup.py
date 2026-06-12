"""Treasury 체결 이벤트 exactly-once-effect 멱등화 (#1957).

#1949 outbox at-least-once 재전달에 대해 Treasury 정산이 진짜 exactly-once
가 되도록 ``treasury_fill_dedup`` 테이블 + 정산 트랜잭션 원자 결합을 검증한다.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderFilledEvent
from ante.treasury import Treasury

ACCOUNT_ID = "domestic"
CURRENCY = "KRW"


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
async def order_tracker(db):
    from ante.trade.order_tracker import OrderTracker

    tracker = OrderTracker(db=db)
    await tracker.initialize()
    return tracker


@pytest.fixture
async def treasury(db, eventbus, order_tracker):
    t = Treasury(
        db=db,
        eventbus=eventbus,
        account_id=ACCOUNT_ID,
        currency=CURRENCY,
        buy_commission_rate=0.00015,
        sell_commission_rate=0.00195,
        order_tracker=order_tracker,
    )
    await t.initialize()
    await t.set_account_balance(10_000_000.0)
    return t


async def _seed_tracker(order_tracker, *, order_id, bot_id, ordered_qty, side="buy"):
    await order_tracker.open(
        order_id=order_id,
        account_id=ACCOUNT_ID,
        bot_id=bot_id,
        strategy_id="s1",
        broker_order_id=f"bk-{order_id}",
        symbol="005930",
        side=side,
        order_type="limit",
        ordered_qty=ordered_qty,
        submitted_date="2026-05-29",
    )


def _buy_fill_event(
    *, order_id, bot_id, quantity, price, commission, fill_dedup_key=""
):
    return OrderFilledEvent(
        order_id=order_id,
        broker_order_id=f"bk-{order_id}",
        bot_id=bot_id,
        strategy_id="s1",
        symbol="005930",
        side="buy",
        quantity=quantity,
        price=price,
        commission=commission,
        order_type="limit",
        account_id=ACCOUNT_ID,
        fill_dedup_key=fill_dedup_key,
    )


def _sell_fill_event(*, order_id, bot_id, quantity, price, commission, fill_dedup_key):
    return OrderFilledEvent(
        order_id=order_id,
        broker_order_id=f"bk-{order_id}",
        bot_id=bot_id,
        strategy_id="s1",
        symbol="005930",
        side="sell",
        quantity=quantity,
        price=price,
        commission=commission,
        order_type="limit",
        account_id=ACCOUNT_ID,
        fill_dedup_key=fill_dedup_key,
    )


def _assert_invariant(treasury, bot_id):
    budget = treasury.get_budget(bot_id)
    assert budget is not None
    expected = budget.allocated - budget.reserved - budget.spent + budget.returned
    assert budget.available == pytest.approx(expected), (
        f"불변식 위반: available={budget.available} != "
        f"{budget.allocated}-{budget.reserved}-{budget.spent}+{budget.returned}"
    )


async def _fill_dedup_count(db, key):
    rows = await db.fetch_all(
        "SELECT * FROM treasury_fill_dedup WHERE fill_dedup_key = ?", (key,)
    )
    return len(rows)


async def _tx_fill_count(db, bot_id):
    rows = await db.fetch_all(
        "SELECT * FROM treasury_transactions WHERE bot_id = ? "
        "AND transaction_type = 'fill'",
        (bot_id,),
    )
    return len(rows)


class TestTreasuryFillDedupSchema:
    async def test_dedup_table_created(self, treasury, db):
        """``treasury_fill_dedup`` 테이블이 _ensure_schema 로 자동 생성된다."""
        cols = await db.fetch_all("PRAGMA table_info(treasury_fill_dedup)")
        names = {c["name"] for c in cols}
        assert names == {"fill_dedup_key", "bot_id", "account_id", "processed_at"}
        # fill_dedup_key 가 PRIMARY KEY
        pk = [c["name"] for c in cols if c["pk"]]
        assert pk == ["fill_dedup_key"]


class TestTreasuryExactlyOnce:
    async def test_buy_redelivery_settles_once(self, treasury, order_tracker, db):
        """같은 비빈키 매수 fill 2회 → spent/reserved/available 1회분, fill tx 1건."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 500_100.0)
        await _seed_tracker(
            order_tracker, order_id="ord1", bot_id="bot1", ordered_qty=10.0
        )
        await order_tracker.record_fill("ord1", 10.0, 50_000.0)

        key = "ord1:500000.0"
        event = _buy_fill_event(
            order_id="ord1",
            bot_id="bot1",
            quantity=10.0,
            price=50_000.0,
            commission=75.0,
            fill_dedup_key=key,
        )

        # 1차 전달
        await treasury._on_order_filled(event)
        budget_after_first = treasury.get_budget("bot1")
        assert budget_after_first is not None
        spent1 = budget_after_first.spent
        reserved1 = budget_after_first.reserved
        available1 = budget_after_first.available

        # 정산 1회 적용 확인
        assert spent1 == pytest.approx(500_075.0)  # 500,000 + 75
        assert reserved1 == pytest.approx(0.0)
        assert available1 == pytest.approx(499_925.0)  # 1M - 500,100 + 25 surplus
        _assert_invariant(treasury, "bot1")

        # 2차 전달 (재전달) — 같은 키
        await treasury._on_order_filled(event)
        budget_after_second = treasury.get_budget("bot1")
        assert budget_after_second is not None

        # 정산 0회 추가 — 값이 1회분과 동일
        assert budget_after_second.spent == pytest.approx(spent1)
        assert budget_after_second.reserved == pytest.approx(reserved1)
        assert budget_after_second.available == pytest.approx(available1)
        _assert_invariant(treasury, "bot1")

        # treasury_transactions fill 행 정확히 1건
        assert await _tx_fill_count(db, "bot1") == 1
        # dedup row 1건
        assert await _fill_dedup_count(db, key) == 1

    async def test_sell_redelivery_returns_once(self, treasury, db):
        """같은 비빈키 매도 fill 2회 → returned/available 1회분, fill tx 1건."""
        await treasury.allocate("bot1", 1_000_000.0)
        key = "ord2:10.0"
        event = _sell_fill_event(
            order_id="ord2",
            bot_id="bot1",
            quantity=10.0,
            price=55_000.0,
            commission=82.5,
            fill_dedup_key=key,
        )

        await treasury._on_order_filled(event)
        budget1 = treasury.get_budget("bot1")
        assert budget1 is not None
        expected_proceeds = 550_000.0 - 82.5
        assert budget1.returned == pytest.approx(expected_proceeds)
        assert budget1.available == pytest.approx(1_000_000.0 + expected_proceeds)

        # 재전달
        await treasury._on_order_filled(event)
        budget2 = treasury.get_budget("bot1")
        assert budget2 is not None
        assert budget2.returned == pytest.approx(expected_proceeds)
        assert budget2.available == pytest.approx(1_000_000.0 + expected_proceeds)
        assert await _tx_fill_count(db, "bot1") == 1

    async def test_partial_then_terminal_distinct_keys_accumulate(
        self, treasury, order_tracker, db
    ):
        """서로 다른 단계(키)는 정상 누적, 같은 단계 재전달만 억제."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 500_100.0)
        await _seed_tracker(
            order_tracker, order_id="ord1", bot_id="bot1", ordered_qty=10.0
        )

        # 1차 partial: 4주
        await order_tracker.record_fill("ord1", 4.0, 50_000.0)
        key1 = "ord1:4.0"
        ev1 = _buy_fill_event(
            order_id="ord1",
            bot_id="bot1",
            quantity=4.0,
            price=50_000.0,
            commission=30.0,
            fill_dedup_key=key1,
        )
        await treasury._on_order_filled(ev1)
        # 재전달 (같은 키) — 억제
        await treasury._on_order_filled(ev1)

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.spent == pytest.approx(200_030.0)  # 4*50,000 + 30
        assert budget.reserved == pytest.approx(300_070.0)
        _assert_invariant(treasury, "bot1")

        # 2차 terminal: 누적 10주 (다른 키) — 정상 누적
        await order_tracker.record_fill("ord1", 10.0, 50_000.0)
        key2 = "ord1:10.0"
        ev2 = _buy_fill_event(
            order_id="ord1",
            bot_id="bot1",
            quantity=6.0,
            price=50_000.0,
            commission=45.0,
            fill_dedup_key=key2,
        )
        await treasury._on_order_filled(ev2)
        # 재전달 (같은 키) — 억제
        await treasury._on_order_filled(ev2)

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.spent == pytest.approx(500_075.0)  # 200,030 + 300,045
        assert budget.reserved == pytest.approx(0.0)
        assert "ord1" not in treasury.get_reservations("bot1")
        _assert_invariant(treasury, "bot1")

        # 두 단계 → fill tx 정확히 2건 (재전달 0회 추가)
        assert await _tx_fill_count(db, "bot1") == 2
        assert await _fill_dedup_count(db, key1) == 1
        assert await _fill_dedup_count(db, key2) == 1


class TestTreasuryAtomicityRollback:
    async def test_rollback_restores_memory_snapshot(self, treasury, order_tracker, db):
        """본문 중 예외 → rollback 후 메모리 snapshot 복원 (split-brain 없음)."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 500_100.0)
        await _seed_tracker(
            order_tracker, order_id="ord1", bot_id="bot1", ordered_qty=10.0
        )
        await order_tracker.record_fill("ord1", 10.0, 50_000.0)

        budget = treasury.get_budget("bot1")
        assert budget is not None
        spent_before = budget.spent
        reserved_before = budget.reserved
        available_before = budget.available
        reservation_before = dict(treasury.get_reservations("bot1"))

        key = "ord1:500000.0"
        event = _buy_fill_event(
            order_id="ord1",
            bot_id="bot1",
            quantity=10.0,
            price=50_000.0,
            commission=75.0,
            fill_dedup_key=key,
        )

        # _log_transaction (정산 본문 끝) 에서 예외 주입 → 트랜잭션 rollback.
        with patch.object(
            treasury, "_log_transaction", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await treasury._on_order_filled(event)

        # 메모리가 진입 전 상태로 복원되어야 함 (stale 없음).
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.spent == pytest.approx(spent_before)
        assert budget.reserved == pytest.approx(reserved_before)
        assert budget.available == pytest.approx(available_before)
        assert treasury.get_reservations("bot1") == reservation_before
        _assert_invariant(treasury, "bot1")

        # DB dedup row 도 rollback 되어야 함 (dedup row ⟺ 정산 1:1).
        assert await _fill_dedup_count(db, key) == 0
        assert await _tx_fill_count(db, "bot1") == 0

        # 재전달 시 정상 1회 정산 (dedup row 가 안 남아 처리 가능).
        await treasury._on_order_filled(event)
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.spent == pytest.approx(500_075.0)
        assert budget.reserved == pytest.approx(0.0)
        assert budget.available == pytest.approx(499_925.0)
        _assert_invariant(treasury, "bot1")
        assert await _fill_dedup_count(db, key) == 1
        assert await _tx_fill_count(db, "bot1") == 1

    async def test_rollback_pops_originally_absent_reservation(
        self, treasury, order_tracker, db
    ):
        """원래 없던 reservation 은 rollback 시 pop 으로 제거 (partial-restore 방지).

        sell fill 은 reservation 을 만들지 않지만, settle 본문 진행 중 예외가 나도
        snapshot 의 '존재 플래그' 가 없던 order_id 를 pop 으로 정리해야 한다.
        """
        await treasury.allocate("bot1", 1_000_000.0)
        # sell 은 reservation 을 사용하지 않음 — ord-sell 은 _reservations 에 없음.
        assert "ord-sell" not in treasury.get_reservations("bot1")

        key = "ord-sell:10.0"
        event = _sell_fill_event(
            order_id="ord-sell",
            bot_id="bot1",
            quantity=10.0,
            price=55_000.0,
            commission=82.5,
            fill_dedup_key=key,
        )

        with patch.object(
            treasury, "_log_transaction", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await treasury._on_order_filled(event)

        # 원래 없던 reservation 이 잘못 생성되지 않아야 함.
        assert "ord-sell" not in treasury.get_reservations("bot1")
        # returned/available 도 진입 전(0 / 1M) 으로 복원.
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.returned == pytest.approx(0.0)
        assert budget.available == pytest.approx(1_000_000.0)
        assert await _fill_dedup_count(db, key) == 0


class TestTreasuryEmptyKeyNotDeduped:
    async def test_empty_key_settles_twice(self, treasury, db):
        """빈키 fill 2회 → 정산 2회 (dedup 비대상, 의도된 동작 고정)."""
        await treasury.allocate("bot1", 2_000_000.0)

        # 빈키 sell 2회 — VirtualProvider 직접발행 정책 (재전달 없음 가정).
        event = _sell_fill_event(
            order_id="ordX",
            bot_id="bot1",
            quantity=10.0,
            price=55_000.0,
            commission=82.5,
            fill_dedup_key="",
        )
        await treasury._on_order_filled(event)
        await treasury._on_order_filled(event)

        budget = treasury.get_budget("bot1")
        assert budget is not None
        proceeds = 550_000.0 - 82.5
        # 2회 적용
        assert budget.returned == pytest.approx(2 * proceeds)
        assert budget.available == pytest.approx(2_000_000.0 + 2 * proceeds)
        # fill tx 2건, dedup 테이블에는 빈키 row 없음
        assert await _tx_fill_count(db, "bot1") == 2
        empty_rows = await db.fetch_all(
            "SELECT * FROM treasury_fill_dedup WHERE fill_dedup_key = ''"
        )
        assert empty_rows == []


class TestTreasuryFillOutboxDrainUnderConcurrentWrite:
    """fill 경로 통합 회귀: 실제 ``Treasury._on_order_filled`` EventBus 구독 +
    ``FillOutboxPublisher.catch_up_once()`` drain 이, 같은 writer 연결을 공유하는
    백그라운드 자동커밋 write 와 동시에 진행돼도 중첩 트랜잭션 오류 없이 정산을
    완료한다(#2365).

    EventBus 가 핸들러 예외를 swallow 하므로 예외를 기대하지 않고, drain 후
    상태를 직접 검증한다: ``treasury_fill_dedup`` row 수 = fill 수, budget
    정산 반영, ``fill_outbox.published=1``.
    """

    async def test_fill_drain_settles_under_concurrent_autocommit(
        self, treasury, order_tracker, db, eventbus
    ):
        from ante.trade.fill_outbox import (
            FillOutbox,
            FillOutboxPublisher,
            make_fill_dedup_key,
        )

        outbox = FillOutbox(db)
        await outbox.initialize()
        publisher = FillOutboxPublisher(outbox=outbox, eventbus=eventbus)

        # 보조 테이블(백그라운드 자동커밋 write 대상).
        await db.execute_script("CREATE TABLE bg (id INTEGER PRIMARY KEY, val TEXT);")

        # buy fill 예산/예약 준비.
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 500_100.0)
        await _seed_tracker(
            order_tracker, order_id="ord1", bot_id="bot1", ordered_qty=10.0
        )
        await order_tracker.record_fill("ord1", 10.0, 50_000.0)

        key = make_fill_dedup_key("ord1", 10.0)
        payload = {
            "account_id": ACCOUNT_ID,
            "order_id": "ord1",
            "broker_order_id": "bk-ord1",
            "bot_id": "bot1",
            "strategy_id": "s1",
            "symbol": "005930",
            "side": "buy",
            "quantity": 10.0,
            "price": 50_000.0,
            "commission": 75.0,
            "order_type": "limit",
            "fill_dedup_key": key,
        }
        # outbox 에 fill row enqueue (트랜잭션 밖 자동커밋).
        await outbox.enqueue(fill_dedup_key=key, payload=payload)

        # 백그라운드 자동커밋 write 를 commit 직전에 고정해 race 윈도우를 만든다.
        writer = db._get_writer()
        real_commit = writer.commit
        reached = asyncio.Event()
        released = asyncio.Event()
        first = {"gated": False}

        async def gated_commit(*args, **kwargs):
            # 첫 commit(백그라운드 write)만 barrier 로 고정한다.
            if not first["gated"]:
                first["gated"] = True
                reached.set()
                await released.wait()
            return await real_commit(*args, **kwargs)

        with patch.object(writer, "commit", side_effect=gated_commit):
            bg = asyncio.create_task(
                db.execute("INSERT INTO bg (id, val) VALUES (1, 'bg')")
            )
            await asyncio.wait_for(reached.wait(), timeout=5.0)

            # 윈도우 안에서 outbox drain → Treasury._on_order_filled 가
            # transaction() 진입(수정 전: 중첩 트랜잭션 오류로 정산 누락).
            drain = asyncio.create_task(publisher.catch_up_once())
            await asyncio.sleep(0.05)
            released.set()

            published_count = await asyncio.wait_for(drain, timeout=5.0)
            await asyncio.wait_for(bg, timeout=5.0)

        # 발행 1건.
        assert published_count == 1

        # dedup row 수 = fill 수(1).
        assert await _fill_dedup_count(db, key) == 1
        # budget 정산 반영(spent = 500,000 + 75).
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.spent == pytest.approx(500_075.0)
        assert budget.reserved == pytest.approx(0.0)
        _assert_invariant(treasury, "bot1")
        # fill tx 1건.
        assert await _tx_fill_count(db, "bot1") == 1
        # outbox published=1.
        rows = await db.fetch_all(
            "SELECT published FROM fill_outbox WHERE fill_dedup_key = ?", (key,)
        )
        assert len(rows) == 1
        assert rows[0]["published"] == 1
        # 백그라운드 write 도 보존.
        bg_rows = await db.fetch_all("SELECT id, val FROM bg")
        assert [(r["id"], r["val"]) for r in bg_rows] == [(1, "bg")]
