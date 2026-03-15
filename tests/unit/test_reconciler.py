"""PositionReconciler 단위 테스트."""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import PositionMismatchEvent, ReconcileEvent
from ante.trade.performance import PerformanceTracker
from ante.trade.position import PositionHistory
from ante.trade.reconciler import PositionReconciler
from ante.trade.recorder import TradeRecorder
from ante.trade.service import TradeService

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def position_history(db):
    ph = PositionHistory(db)
    await ph.initialize()
    return ph


@pytest.fixture
async def recorder(db, position_history):
    rec = TradeRecorder(db, position_history)
    await rec.initialize()
    return rec


@pytest.fixture
async def service(recorder, position_history):
    perf = PerformanceTracker(recorder._db)
    return TradeService(recorder, position_history, perf)


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
def reconciler(service, eventbus):
    return PositionReconciler(trade_service=service, eventbus=eventbus)


async def _set_position(position_history, bot_id, symbol, qty, avg_price):
    """테스트용 포지션 설정."""
    await position_history.force_update(
        bot_id=bot_id,
        symbol=symbol,
        quantity=qty,
        avg_entry_price=avg_price,
    )


# ── 시나리오 1: 전량 외부 매도 ─────────────────────


class TestFullExternalSell:
    async def test_full_sell_detected_and_corrected(
        self, reconciler, position_history, eventbus
    ):
        """내부 50주, 브로커 0주 → 포지션 0주로 보정."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)

        mismatch_events: list = []
        reconcile_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))
        eventbus.subscribe(ReconcileEvent, lambda e: reconcile_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[],  # 브로커에 없음
        )

        assert len(corrections) == 1
        assert corrections[0]["old_quantity"] == 50
        assert corrections[0]["new_quantity"] == 0
        assert corrections[0]["reason"] == "외부 청산"

        # 이벤트 발행 확인
        assert len(mismatch_events) == 1
        assert mismatch_events[0].symbol == "005930"
        assert mismatch_events[0].internal_qty == 50
        assert mismatch_events[0].broker_qty == 0

        assert len(reconcile_events) == 1
        assert reconcile_events[0].discrepancy_count == 1

        # 포지션 실제로 0주로 변경됨
        pos = await position_history.get_current("bot-1", "005930")
        assert pos["quantity"] == 0


# ── 시나리오 2: 일부 외부 매도 ─────────────────────


class TestPartialExternalSell:
    async def test_partial_sell_corrected(self, reconciler, position_history):
        """내부 50주, 브로커 30주 → 30주로 보정."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 30, "avg_price": 50000},
            ],
        )

        assert len(corrections) == 1
        assert corrections[0]["old_quantity"] == 50
        assert corrections[0]["new_quantity"] == 30
        assert corrections[0]["reason"] == "외부 일부 매도"


# ── 시나리오 3: 불일치 없음 ────────────────────────


class TestNoMismatch:
    async def test_no_correction_when_matched(
        self, reconciler, position_history, eventbus
    ):
        """포지션 일치 시 보정 없음."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)

        reconcile_events: list = []
        eventbus.subscribe(ReconcileEvent, lambda e: reconcile_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 50, "avg_price": 50000},
            ],
        )

        assert corrections == []
        assert len(reconcile_events) == 0

    async def test_no_correction_both_empty(self, reconciler):
        """내부/브로커 모두 빈 포지션."""
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[],
        )
        assert corrections == []


# ── 시나리오 4: 외부 매수 ──────────────────────────


class TestExternalBuy:
    async def test_external_buy_detected(self, reconciler, position_history):
        """내부 0주, 브로커 20주 → 외부 매수로 보정."""
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
        )

        assert len(corrections) == 1
        assert corrections[0]["new_quantity"] == 20
        assert corrections[0]["reason"] == "외부 매수"


# ── 시나리오 5: 복수 종목 불일치 ───────────────────


class TestMultipleSymbols:
    async def test_multiple_corrections(self, reconciler, position_history, eventbus):
        """여러 종목 동시 불일치."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)
        await _set_position(position_history, "bot-1", "000660", 30, 80000)

        mismatch_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 0, "avg_price": 0},
                # 000660 은 브로커에 없음
            ],
        )

        assert len(corrections) == 2
        assert len(mismatch_events) == 2
