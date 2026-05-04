"""Trade 모듈 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
)
from ante.trade.models import (
    PerformanceMetrics,
    PositionSnapshot,
    TradeRecord,
    TradeStatus,
    TradeType,
)
from ante.trade.performance import PerformanceTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder
from ante.trade.service import TradeService

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    return db


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
async def performance(db, recorder):
    return PerformanceTracker(db)


@pytest.fixture
async def service(recorder, position_history, performance):
    return TradeService(recorder, position_history, performance)


@pytest.fixture
def eventbus():
    return EventBus()


def _make_filled_event(
    *,
    bot_id: str = "bot1",
    strategy_id: str = "s1",
    symbol: str = "005930",
    side: str = "buy",
    quantity: float = 10.0,
    price: float = 50000.0,
    commission: float = 0.0,
    order_type: str = "market",
    reason: str = "test",
    account_id: str = "acc-test",
) -> OrderFilledEvent:
    now = datetime.now(UTC)
    return OrderFilledEvent(
        event_id=uuid4(),
        timestamp=now,
        order_id="ord1",
        broker_order_id="bk1",
        bot_id=bot_id,
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        commission=commission,
        order_type=order_type,
        reason=reason,
        account_id=account_id,
    )


# ── TradeRecorder ────────────────────────────────────


class TestTradeRecorder:
    async def test_on_filled_records_trade(self, recorder, db):
        """OrderFilledEvent → trades 테이블에 기록."""
        event = _make_filled_event()
        await recorder._on_filled(event)

        rows = await db.fetch_all("SELECT * FROM trades")
        assert len(rows) == 1
        assert rows[0]["bot_id"] == "bot1"
        assert rows[0]["status"] == "filled"

    async def test_on_filled_updates_position(self, recorder, position_history):
        """체결 시 포지션도 갱신."""
        event = _make_filled_event(side="buy", quantity=10, price=50000)
        await recorder._on_filled(event)

        pos = await position_history.get_current("bot1", "005930")
        assert pos["quantity"] == 10
        assert pos["avg_entry_price"] == 50000.0

    async def test_on_rejected_records(self, recorder, db):
        """OrderRejectedEvent → 거부 기록."""
        event = OrderRejectedEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            order_id="ord1",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=50000.0,
            order_type="market",
            reason="rule violation",
            account_id="acc-test",
        )
        await recorder._on_rejected(event)

        rows = await db.fetch_all("SELECT * FROM trades WHERE status = 'rejected'")
        assert len(rows) == 1
        assert rows[0]["reason"] == "rule violation"

    async def test_on_failed_records(self, recorder, db):
        """OrderFailedEvent → 실패 기록."""
        event = OrderFailedEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            order_id="ord1",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=0.0,
            order_type="market",
            error_message="broker error",
            account_id="acc-test",
        )
        await recorder._on_failed(event)

        rows = await db.fetch_all("SELECT * FROM trades WHERE status = 'failed'")
        assert len(rows) == 1
        assert rows[0]["reason"] == "broker error"

    async def test_on_cancelled_records(self, recorder, db):
        """OrderCancelledEvent → 취소 기록."""
        event = OrderCancelledEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            order_id="ord1",
            broker_order_id="bk1",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=0.0,
            reason="user cancel",
            account_id="acc-test",
        )
        await recorder._on_cancelled(event)

        rows = await db.fetch_all("SELECT * FROM trades WHERE status = 'cancelled'")
        assert len(rows) == 1

    async def test_duplicate_trade_id_ignored(self, recorder, db):
        """동일 trade_id 중복 기록 방지 (INSERT OR IGNORE)."""
        event = _make_filled_event()
        await recorder._on_filled(event)
        await recorder._on_filled(event)

        rows = await db.fetch_all("SELECT * FROM trades")
        assert len(rows) == 1

    async def test_get_trades_filter_bot(self, recorder):
        """봇별 거래 조회."""
        await recorder._on_filled(_make_filled_event(bot_id="bot1"))
        await recorder._on_filled(_make_filled_event(bot_id="bot2"))

        trades = await recorder.get_trades(bot_id="bot1")
        assert len(trades) == 1
        assert trades[0].bot_id == "bot1"

    async def test_get_trades_filter_status(self, recorder, db):
        """상태별 거래 조회."""
        await recorder._on_filled(_make_filled_event())

        event = OrderFailedEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            order_id="ord2",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=0.0,
            order_type="market",
            error_message="err",
            account_id="acc-test",
        )
        await recorder._on_failed(event)

        filled = await recorder.get_trades(status=TradeStatus.FILLED)
        assert len(filled) == 1

        failed = await recorder.get_trades(status=TradeStatus.FAILED)
        assert len(failed) == 1

    async def test_save_adjustment(self, recorder, db):
        """대사 보정 이력 기록."""
        await recorder.save_adjustment(
            bot_id="bot1",
            symbol="005930",
            old_quantity=10,
            new_quantity=15,
            reason="broker mismatch",
            account_id="acc-test",
        )

        rows = await db.fetch_all("SELECT * FROM trades WHERE status = 'adjusted'")
        assert len(rows) == 1
        assert rows[0]["quantity"] == 5  # abs(15-10)

    async def test_eventbus_integration(self, recorder, eventbus):
        """EventBus 구독 통합 테스트."""
        recorder.subscribe(eventbus)

        event = _make_filled_event()
        await eventbus.publish(event)

        trades = await recorder.get_trades()
        assert len(trades) == 1

    async def test_on_filled_buy_notification_includes_cumulative(
        self, recorder, eventbus
    ):
        """매수 알림에 누적 수량, 평단가 포함."""
        from ante.eventbus.events import NotificationEvent

        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))
        recorder.subscribe(eventbus)

        await eventbus.publish(_make_filled_event(side="buy", quantity=10, price=50000))
        await eventbus.publish(_make_filled_event(side="buy", quantity=20, price=60000))

        assert len(captured) == 2
        # 2차 매수 알림: 누적 30주, 평단가 = (10*50000+20*60000)/30 ≈ 56667
        msg = captured[1].message
        assert "누적 30주" in msg
        assert "평단가" in msg

    async def test_on_filled_sell_notification_includes_pnl(self, recorder, eventbus):
        """매도 알림에 잔여 수량, 평단가, 실현 손익 포함."""
        from ante.eventbus.events import NotificationEvent

        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))
        recorder.subscribe(eventbus)

        # 매수 10주 @ 50,000
        await eventbus.publish(_make_filled_event(side="buy", quantity=10, price=50000))
        # 매도 5주 @ 60,000 → 실현 손익 = (60000 - 50000) * 5 = 50,000
        await eventbus.publish(_make_filled_event(side="sell", quantity=5, price=60000))

        assert len(captured) == 2
        sell_msg = captured[1].message
        assert "잔여 5주" in sell_msg
        assert "평단가" in sell_msg
        assert "실현 손익" in sell_msg
        assert "+50,000원" in sell_msg


# ── PositionHistory ──────────────────────────────────


class TestPositionHistory:
    async def test_buy_increases_quantity(self, position_history):
        """매수 시 수량 증가."""
        record = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(record)

        pos = await position_history.get_current("bot1", "005930")
        assert pos["quantity"] == 10
        assert pos["avg_entry_price"] == 50000.0

    async def test_buy_recalculates_avg_price(self, position_history):
        """추가 매수 시 평균 매입가 재계산."""
        record1 = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(record1)

        record2 = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=60000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(record2)

        pos = await position_history.get_current("bot1", "005930")
        assert pos["quantity"] == 20
        assert pos["avg_entry_price"] == 55000.0  # (50000*10 + 60000*10) / 20

    async def test_sell_decreases_quantity(self, position_history):
        """매도 시 수량 감소 + 실현 손익."""
        # 매수
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)

        # 일부 매도
        sell = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=5,
            price=55000,
            status=TradeStatus.FILLED,
            commission=100,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(sell)

        pos = await position_history.get_current("bot1", "005930")
        assert pos["quantity"] == 5
        assert pos["avg_entry_price"] == 50000.0  # 유지
        # pnl = (55000 - 50000) * 5 - 100 = 24900
        assert pos["realized_pnl"] == pytest.approx(24900.0)

    async def test_full_sell_clears_position(self, position_history):
        """전량 매도 시 포지션 quantity=0, avg_entry_price=0."""
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)

        sell = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10,
            price=55000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(sell)

        pos = await position_history.get_current("bot1", "005930")
        assert pos["quantity"] == 0
        assert pos["avg_entry_price"] == 0.0

    async def test_non_filled_ignored(self, position_history):
        """체결 상태가 아닌 기록은 무시."""
        record = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.CANCELLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(record)

        pos = await position_history.get_current("bot1", "005930")
        assert pos["quantity"] == 0

    async def test_get_positions_excludes_closed(self, position_history):
        """기본 조회 시 청산 포지션 제외."""
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)

        # 다른 종목 매수 후 전량 청산
        buy2 = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="000660",
            side="buy",
            quantity=5,
            price=100000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy2)
        sell2 = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="000660",
            side="sell",
            quantity=5,
            price=110000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(sell2)

        positions = await position_history.get_positions("bot1")
        assert len(positions) == 1
        assert positions[0].symbol == "005930"

    async def test_get_positions_include_closed(self, position_history):
        """include_closed=True 시 청산 포지션도 포함."""
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)
        sell = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10,
            price=55000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(sell)

        positions = await position_history.get_positions("bot1", include_closed=True)
        assert len(positions) == 1
        assert positions[0].quantity == 0

    async def test_get_all_positions(self, position_history):
        """전체 봇 포지션 조회."""
        for bot in ["bot1", "bot2"]:
            buy = TradeRecord(
                trade_id=uuid4(),
                bot_id=bot,
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10,
                price=50000,
                status=TradeStatus.FILLED,
                timestamp=datetime.now(UTC),
                account_id="acc-test",
            )
            await position_history.on_trade(buy)

        positions = await position_history.get_all_positions()
        assert len(positions) == 2

    async def test_force_update(self, position_history):
        """Reconciler 강제 포지션 덮어쓰기."""
        await position_history.force_update(
            bot_id="bot1",
            symbol="005930",
            quantity=100,
            avg_entry_price=45000,
            account_id="acc-test",
        )

        pos = await position_history.get_current("bot1", "005930")
        assert pos["quantity"] == 100
        assert pos["avg_entry_price"] == 45000

    async def test_force_update_syncs_cache(self, position_history):
        """force_update() 후 get_positions_sync()가 갱신된 값을 반환."""
        await position_history.force_update(
            bot_id="bot1",
            symbol="005930",
            quantity=50,
            avg_entry_price=60000,
            account_id="acc-test",
        )

        cached = position_history.get_positions_sync("bot1")
        assert len(cached) == 1
        assert cached[0].quantity == 50
        assert cached[0].avg_entry_price == 60000

        # 수량 0으로 갱신하면 캐시에서 제거
        await position_history.force_update(
            bot_id="bot1",
            symbol="005930",
            quantity=0,
            avg_entry_price=0,
            account_id="acc-test",
        )
        assert position_history.get_positions_sync("bot1") == []

    async def test_get_history(self, position_history):
        """포지션 변동 이력 조회."""
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)
        sell = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=5,
            price=55000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(sell)

        history = await position_history.get_history("bot1", "005930")
        assert len(history) == 2  # buy + sell

    async def test_save_history_writes_account_id(self, position_history, db):
        """체결 이력 INSERT 시 account_id가 schema default 'default'가 아닌
        record.account_id로 저장되어야 한다 (#1240 review P2 회귀)."""
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-real",
        )
        await position_history.on_trade(buy)

        sell = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=5,
            price=55000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-real",
        )
        await position_history.on_trade(sell)

        rows = await db.fetch_all(
            "SELECT action, account_id FROM position_history"
            " WHERE bot_id = ? ORDER BY id",
            ("bot1",),
        )
        assert len(rows) == 2
        for row in rows:
            assert row["account_id"] == "acc-real", (
                f"position_history.{row['action']} row의 account_id가 "
                f"{row['account_id']!r} (expected 'acc-real')"
            )

    async def test_oversell_clamps_pnl_to_held_quantity(self, position_history):
        """초과 매도 시 PnL은 보유 수량 기준으로 계산 (#769)."""
        # 50주 매수 @ 50000
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=50,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)

        # 100주 매도 시도 (보유 50주 초과)
        sell = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=100,
            price=55000,
            status=TradeStatus.FILLED,
            commission=0.0,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(sell)

        pos = await position_history.get_current("bot1", "005930")
        # 포지션은 0으로 클램핑
        assert pos["quantity"] == 0
        assert pos["avg_entry_price"] == 0.0
        # PnL은 보유 50주 기준: (55000 - 50000) * 50 = 250000
        # 100주 기준이면 500000이 되므로, 반드시 250000이어야 함
        assert pos["realized_pnl"] == pytest.approx(250000.0)

    async def test_oversell_logs_warning(self, position_history, caplog):
        """초과 매도 시 경고 로그 발행 (#769)."""
        import logging

        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=50,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)

        sell = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=100,
            price=55000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        with caplog.at_level(logging.WARNING, logger="ante.trade.position"):
            await position_history.on_trade(sell)

        assert any("초과 매도 감지" in msg for msg in caplog.messages)

    async def test_oversell_history_records_effective_qty(self, position_history):
        """초과 매도 시 이력에는 유효 수량만 기록 (#769)."""
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=50,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)

        sell = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=100,
            price=55000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(sell)

        history = await position_history.get_history("bot1", "005930")
        sell_entry = [h for h in history if h["action"] == "sell"][0]
        # 이력의 quantity는 유효 수량(50)이어야 함
        assert sell_entry["quantity"] == 50

    async def test_normal_sell_unaffected(self, position_history):
        """정상 매도는 기존 동작과 동일 (#769 회귀 방지)."""
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=100,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)

        sell = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=30,
            price=55000,
            status=TradeStatus.FILLED,
            commission=100,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(sell)

        pos = await position_history.get_current("bot1", "005930")
        assert pos["quantity"] == 70
        # pnl = (55000 - 50000) * 30 - 100 = 149900
        assert pos["realized_pnl"] == pytest.approx(149900.0)


# ── PerformanceTracker ───────────────────────────────


class TestPerformanceTracker:
    async def test_empty_trades_returns_empty_metrics(self, performance):
        """거래 없으면 빈 지표."""
        metrics = await performance.calculate(account_id="acc1", bot_id="nonexistent")
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.net_pnl == 0.0

    async def test_calculate_with_trades(self, recorder, position_history, performance):
        """수익/손실 거래 혼합 시 성과 계산."""
        now = datetime.now(UTC)

        # 매수 1: 005930 10주 @ 50000
        await recorder._on_filled(
            _make_filled_event(
                symbol="005930",
                side="buy",
                quantity=10,
                price=50000,
            )
        )

        # 매도 1: 005930 10주 @ 55000 (수익)
        sell1 = OrderFilledEvent(
            event_id=uuid4(),
            timestamp=now + timedelta(hours=1),
            order_id="ord2",
            broker_order_id="bk2",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            price=55000.0,
            commission=100.0,
            order_type="market",
            account_id="acc-test",
        )
        await recorder._on_filled(sell1)

        # 매수 2: 000660 5주 @ 100000
        buy2 = OrderFilledEvent(
            event_id=uuid4(),
            timestamp=now + timedelta(hours=2),
            order_id="ord3",
            broker_order_id="bk3",
            bot_id="bot1",
            strategy_id="s1",
            symbol="000660",
            side="buy",
            quantity=5.0,
            price=100000.0,
            order_type="market",
            account_id="acc-test",
        )
        await recorder._on_filled(buy2)

        # 매도 2: 000660 5주 @ 90000 (손실)
        sell2 = OrderFilledEvent(
            event_id=uuid4(),
            timestamp=now + timedelta(hours=3),
            order_id="ord4",
            broker_order_id="bk4",
            bot_id="bot1",
            strategy_id="s1",
            symbol="000660",
            side="sell",
            quantity=5.0,
            price=90000.0,
            commission=50.0,
            order_type="market",
            account_id="acc-test",
        )
        await recorder._on_filled(sell2)

        metrics = await performance.calculate(account_id="acc-test", bot_id="bot1")
        assert metrics.total_trades == 2  # 매도 2건
        assert metrics.winning_trades == 1
        assert metrics.losing_trades == 1
        assert metrics.win_rate == pytest.approx(0.5)

    async def test_mdd_calculation(self, performance):
        """MDD 계산 정확성 — equity curve 기반."""
        budget = 1000.0
        pnl_list = [100, 50, -200, 150, -300]
        rate, amount = performance._calculate_mdd(pnl_list, budget)
        # equity: [1100, 1150, 950, 1100, 800]
        # peak: 1150, trough: 800, drawdown: 350
        assert amount == pytest.approx(350.0)
        assert rate == pytest.approx(350.0 / 1150.0)

    async def test_mdd_empty(self, performance):
        """빈 리스트 MDD = 0."""
        rate, amount = performance._calculate_mdd([])
        assert rate == 0.0
        assert amount == 0.0

    async def test_mdd_only_profits(self, performance):
        """수익만 있으면 MDD = 0."""
        rate, amount = performance._calculate_mdd([100, 200, 300], 1000.0)
        assert amount == 0.0

    async def test_mdd_all_loss(self, performance):
        """전 구간 손실 케이스 — equity curve 기반 MDD."""
        budget = 1000.0
        pnl_list = [-100, -200, -150]
        rate, amount = performance._calculate_mdd(pnl_list, budget)
        # equity: [900, 700, 550]
        # peak: 900 (첫 값), trough: 550, drawdown: 350
        assert amount == pytest.approx(350.0)
        assert rate == pytest.approx(350.0 / 900.0)

    async def test_mdd_no_budget_backward_compat(self, performance):
        """bot_allocated_budget=0 (기본값) 시 기존 누적PnL 기반 동작."""
        pnl_list = [100, 50, -200, 150, -300]
        rate, amount = performance._calculate_mdd(pnl_list)
        # equity (budget=0): [100, 150, -50, 100, -200]
        # peak: 150, trough: -200, drawdown amount: 350
        assert amount == pytest.approx(350.0)
        # peak > 0이므로 비율 산출 가능
        assert rate == pytest.approx(350.0 / 150.0)

    async def test_sharpe_under_30_returns_none(self, performance):
        """30건 미만이면 None."""
        assert performance._calculate_sharpe([100, 200]) is None

    async def test_sharpe_30_or_more(self, performance):
        """30건 이상이면 샤프 비율 계산."""
        pnl_list = [100.0 + i * 10 for i in range(30)]
        result = performance._calculate_sharpe(pnl_list)
        assert result is not None
        assert isinstance(result, float)

    async def test_sharpe_zero_std_returns_none(self, performance):
        """표준편차 0이면 None."""
        pnl_list = [100.0] * 30
        assert performance._calculate_sharpe(pnl_list) is None

    async def test_profit_factor_no_loss(self, recorder, position_history, performance):
        """손실 없으면 profit_factor = inf."""
        now = datetime.now(UTC)

        await recorder._on_filled(
            _make_filled_event(side="buy", quantity=10, price=50000)
        )
        sell = OrderFilledEvent(
            event_id=uuid4(),
            timestamp=now + timedelta(hours=1),
            order_id="ord2",
            broker_order_id="bk2",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            price=55000.0,
            order_type="market",
            account_id="acc-test",
        )
        await recorder._on_filled(sell)

        metrics = await performance.calculate(account_id="acc-test", bot_id="bot1")
        assert metrics.profit_factor == float("inf")


# ── TradeService ─────────────────────────────────────


class TestTradeService:
    async def test_get_summary(self, service, recorder):
        """get_summary — 포지션 + 성과 + 최근 거래."""
        await recorder._on_filled(
            _make_filled_event(side="buy", quantity=10, price=50000)
        )

        summary = await service.get_summary("bot1", account_id="acc-default")
        assert "positions" in summary
        assert "performance" in summary
        assert "recent_trades" in summary

    async def test_correct_position(self, service, position_history):
        """포지션 강제 보정."""
        # 기존 포지션 생성
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)

        result = await service.correct_position(
            bot_id="bot1",
            symbol="005930",
            quantity=15,
            avg_price=48000,
            reason="broker mismatch",
            account_id="acc-test",
        )

        assert result["old_quantity"] == 10
        assert result["new_quantity"] == 15
        assert result["new_avg_price"] == 48000

        # 보정 후 포지션 확인
        pos = await position_history.get_current("bot1", "005930")
        assert pos["quantity"] == 15

    async def test_insert_adjustment(self, service, recorder):
        """누락 체결 보정 추가."""
        fill = {
            "symbol": "005930",
            "side": "buy",
            "quantity": 5,
            "price": 50000,
        }
        await service.insert_adjustment(
            bot_id="bot1",
            strategy_id="s1",
            fill=fill,
            reason="missed fill",
            account_id="acc-test",
        )

        trades = await recorder.get_trades(bot_id="bot1")
        assert len(trades) == 1
        assert trades[0].status == TradeStatus.ADJUSTED

    async def test_get_positions_delegates(self, service, position_history):
        """포지션 조회 위임."""
        buy = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime.now(UTC),
            account_id="acc-test",
        )
        await position_history.on_trade(buy)

        positions = await service.get_positions("bot1")
        assert len(positions) == 1
        assert isinstance(positions[0], PositionSnapshot)

    async def test_get_performance_delegates(self, service):
        """성과 조회 위임."""
        metrics = await service.get_performance(account_id="acc-default", bot_id="bot1")
        assert isinstance(metrics, PerformanceMetrics)


# ── Models ───────────────────────────────────────────


class TestModels:
    def test_trade_type_values(self):
        """TradeType 값."""
        assert TradeType.BUY == "buy"
        assert TradeType.SELL == "sell"

    def test_trade_status_values(self):
        """TradeStatus 값."""
        assert TradeStatus.FILLED == "filled"
        assert TradeStatus.CANCELLED == "cancelled"
        assert TradeStatus.REJECTED == "rejected"
        assert TradeStatus.FAILED == "failed"
        assert TradeStatus.ADJUSTED == "adjusted"

    def test_performance_metrics_defaults(self):
        """PerformanceMetrics 기본값."""
        m = PerformanceMetrics()
        assert m.total_trades == 0
        assert m.sharpe_ratio is None
        assert m.first_trade_at is None


# ── Account ID 관련 테스트 ──────────────────────────


class TestAccountIdFields:
    """#563: TradeRecord, PositionSnapshot에 account_id, currency 필드 추가."""

    def test_trade_record_with_account(self):
        """account_id, currency 필드 포함 TradeRecord 생성."""
        record = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            account_id="my-account",
            currency="USD",
        )
        assert record.account_id == "my-account"
        assert record.currency == "USD"

    def test_trade_record_default_values(self):
        """account_id는 명시값으로 보존되고 currency는 'KRW'가 기본값이다."""
        record = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            account_id="acc-test",
        )
        assert record.account_id == "acc-test"
        assert record.currency == "KRW"

    def test_position_snapshot_with_account(self):
        """account_id 필드 포함 PositionSnapshot 생성."""
        snapshot = PositionSnapshot(
            bot_id="bot1",
            symbol="005930",
            quantity=10,
            avg_entry_price=50000,
            account_id="my-account",
        )
        assert snapshot.account_id == "my-account"

    def test_position_snapshot_default_account(self):
        """PositionSnapshot account_id는 명시값으로 보존된다."""
        snapshot = PositionSnapshot(
            bot_id="bot1",
            symbol="005930",
            quantity=10,
            avg_entry_price=50000,
            account_id="acc-test",
        )
        assert snapshot.account_id == "acc-test"


class TestAccountIdDbMigration:
    """#563: DB 마이그레이션으로 account_id, currency 컬럼 추가."""

    async def test_trades_migration_adds_columns(self, db, recorder):
        """trades 테이블에 account_id, currency 컬럼 존재 확인."""
        columns = await db.fetch_all("PRAGMA table_info(trades)")
        col_names = {row["name"] for row in columns}
        assert "account_id" in col_names
        assert "currency" in col_names

    async def test_positions_migration_adds_column(self, db, position_history):
        """positions 테이블에 account_id 컬럼 존재 확인."""
        columns = await db.fetch_all("PRAGMA table_info(positions)")
        col_names = {row["name"] for row in columns}
        assert "account_id" in col_names

    async def test_trade_record_saved_with_account_id(self, recorder, db):
        """account_id, currency가 DB에 저장되는지 확인."""
        record = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            account_id="acct-kr",
            currency="KRW",
            timestamp=datetime.now(UTC),
        )
        await recorder.save(record)

        rows = await db.fetch_all("SELECT * FROM trades")
        assert len(rows) == 1
        assert rows[0]["account_id"] == "acct-kr"
        assert rows[0]["currency"] == "KRW"

    async def test_trade_record_read_with_account_id(self, recorder):
        """조회한 TradeRecord에 account_id, currency가 포함되는지 확인."""
        record = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            account_id="acct-kr",
            currency="USD",
            timestamp=datetime.now(UTC),
        )
        await recorder.save(record)

        trades = await recorder.get_trades(bot_id="bot1")
        assert len(trades) == 1
        assert trades[0].account_id == "acct-kr"
        assert trades[0].currency == "USD"

    async def test_get_trades_filter_by_account_id(self, recorder):
        """account_id로 거래 필터링."""
        for acct in ("acct-1", "acct-2"):
            record = TradeRecord(
                trade_id=uuid4(),
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10,
                price=50000,
                status=TradeStatus.FILLED,
                account_id=acct,
                timestamp=datetime.now(UTC),
            )
            await recorder.save(record)

        trades = await recorder.get_trades(account_id="acct-1")
        assert len(trades) == 1
        assert trades[0].account_id == "acct-1"

    async def test_position_saved_with_account_id(self, position_history):
        """포지션 갱신 시 account_id가 DB에 저장되는지 확인."""
        record = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            account_id="acct-kr",
            timestamp=datetime.now(UTC),
        )
        await position_history.on_trade(record)

        positions = await position_history.get_positions("bot1")
        assert len(positions) == 1
        assert positions[0].account_id == "acct-kr"

    async def test_position_cache_has_account_id(self, position_history):
        """인메모리 캐시에도 account_id가 반영되는지 확인."""
        record = TradeRecord(
            trade_id=uuid4(),
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            account_id="acct-us",
            timestamp=datetime.now(UTC),
        )
        await position_history.on_trade(record)

        cached = position_history.get_positions_sync("bot1")
        assert len(cached) == 1
        assert cached[0].account_id == "acct-us"


# ── #1217: legacy account_id 처리 / correct_position 사전 검증 ──


class TestWarmCacheLegacyAccountId:
    """#1217: 기존 DB의 invalid account_id row를 warm_cache가 skip해야 한다."""

    async def test_warm_cache_skips_invalid_account_id_row(
        self, db, position_history, caplog
    ):
        """positions 테이블에 'default' account_id row가 있어도 부팅 실패하지 않는다."""
        import logging

        # legacy 'default' row를 직접 삽입 (정상 경로로는 만들 수 없음)
        await db.execute(
            "INSERT INTO positions "
            "(bot_id, symbol, quantity, avg_entry_price, "
            "realized_pnl, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy-bot", "005930", 5.0, 10000.0, 0.0, "default"),
        )
        # 정상 row도 함께 삽입하여 skip 외 row는 정상 적재되는지 검증
        await db.execute(
            "INSERT INTO positions "
            "(bot_id, symbol, quantity, avg_entry_price, "
            "realized_pnl, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("ok-bot", "005931", 3.0, 20000.0, 0.0, "acc-test"),
        )

        with caplog.at_level(logging.WARNING, logger="ante.trade.position"):
            await position_history._warm_cache()

        # legacy bot은 캐시에 적재되지 않음
        assert position_history.get_positions_sync("legacy-bot") == []
        # 정상 bot은 적재됨
        ok_positions = position_history.get_positions_sync("ok-bot")
        assert len(ok_positions) == 1
        assert ok_positions[0].account_id == "acc-test"

        # warning 로그가 기록되어야 함
        assert any("invalid account_id" in record.message for record in caplog.records)


class TestCorrectPositionAccountIdValidation:
    """#1217: correct_position 진입 시 account_id 사전 검증."""

    async def test_correct_position_rejects_invalid_account_id(
        self, service, position_history
    ):
        """invalid account_id ('default') 입력 시 InvalidAccountIdError raise."""
        from ante.account.errors import InvalidAccountIdError

        with pytest.raises(InvalidAccountIdError):
            await service.correct_position(
                bot_id="bot1",
                symbol="005930",
                quantity=5,
                account_id="default",
            )

    async def test_correct_position_rejects_empty_account_id(
        self, service, position_history
    ):
        """빈 account_id도 거부."""
        from ante.account.errors import InvalidAccountIdError

        with pytest.raises(InvalidAccountIdError):
            await service.correct_position(
                bot_id="bot1",
                symbol="005930",
                quantity=5,
                account_id="",
            )

    async def test_correct_position_invalid_account_id_does_not_touch_db(
        self, service, position_history, db
    ):
        """invalid account_id는 force_update commit 전에 차단되어 DB 변경이 없다."""
        from ante.account.errors import InvalidAccountIdError

        with pytest.raises(InvalidAccountIdError):
            await service.correct_position(
                bot_id="bot-x",
                symbol="005932",
                quantity=99,
                account_id="default",
            )

        rows = await db.fetch_all(
            "SELECT * FROM positions WHERE bot_id = ? AND symbol = ?",
            ("bot-x", "005932"),
        )
        assert rows == []


class TestPositionReadLegacyAccountId:
    """#1217: get_positions / get_all_positions read 경로도 legacy row skip."""

    async def test_get_positions_skips_legacy_invalid_account_id(
        self, db, position_history, caplog
    ):
        """get_positions가 invalid account_id row를 skip하고 정상 row만 반환한다."""
        import logging

        # legacy 'default' row + 정상 row 동일 봇에 삽입
        await db.execute(
            "INSERT INTO positions "
            "(bot_id, symbol, quantity, avg_entry_price, "
            "realized_pnl, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mixed-bot", "005930", 5.0, 10000.0, 0.0, "default"),
        )
        await db.execute(
            "INSERT INTO positions "
            "(bot_id, symbol, quantity, avg_entry_price, "
            "realized_pnl, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("mixed-bot", "005931", 3.0, 20000.0, 0.0, "acc-test"),
        )

        with caplog.at_level(logging.WARNING, logger="ante.trade.position"):
            positions = await position_history.get_positions("mixed-bot")

        # InvalidAccountIdError가 raise되지 않아야 함, 정상 row만 반환
        assert len(positions) == 1
        assert positions[0].symbol == "005931"
        assert positions[0].account_id == "acc-test"
        # warning 로그가 기록되어야 함
        assert any(
            "invalid account_id" in record.message and "get_positions" in record.message
            for record in caplog.records
        )

    async def test_get_positions_include_closed_skips_legacy(
        self, db, position_history, caplog
    ):
        """include_closed=True 경로도 legacy row를 skip한다."""
        import logging

        await db.execute(
            "INSERT INTO positions "
            "(bot_id, symbol, quantity, avg_entry_price, "
            "realized_pnl, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("closed-bot", "005930", 0.0, 10000.0, 100.0, "default"),
        )
        await db.execute(
            "INSERT INTO positions "
            "(bot_id, symbol, quantity, avg_entry_price, "
            "realized_pnl, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("closed-bot", "005931", 0.0, 20000.0, 50.0, "acc-test"),
        )

        with caplog.at_level(logging.WARNING, logger="ante.trade.position"):
            positions = await position_history.get_positions(
                "closed-bot", include_closed=True
            )

        assert len(positions) == 1
        assert positions[0].symbol == "005931"

    async def test_get_all_positions_skips_legacy_invalid_account_id(
        self, db, position_history, caplog
    ):
        """get_all_positions가 invalid account_id row를 skip하고 정상 row만 반환한다."""
        import logging

        await db.execute(
            "INSERT INTO positions "
            "(bot_id, symbol, quantity, avg_entry_price, "
            "realized_pnl, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy-bot-a", "005930", 5.0, 10000.0, 0.0, "default"),
        )
        await db.execute(
            "INSERT INTO positions "
            "(bot_id, symbol, quantity, avg_entry_price, "
            "realized_pnl, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("ok-bot-b", "005931", 3.0, 20000.0, 0.0, "acc-test"),
        )

        with caplog.at_level(logging.WARNING, logger="ante.trade.position"):
            positions = await position_history.get_all_positions()

        assert len(positions) == 1
        assert positions[0].bot_id == "ok-bot-b"
        assert positions[0].account_id == "acc-test"
        assert any(
            "invalid account_id" in record.message
            and "get_all_positions" in record.message
            for record in caplog.records
        )


class TestTradeReadLegacyAccountId:
    """#1217: get_trades / DailyReport read 경로도 legacy row skip."""

    @staticmethod
    async def _insert_legacy_trade(
        db,
        *,
        trade_id: str,
        bot_id: str = "legacy-bot",
        symbol: str = "005930",
        side: str = "buy",
        quantity: float = 1.0,
        price: float = 10000.0,
        status: str = "filled",
        timestamp: str | None = None,
        account_id: str = "default",
    ) -> None:
        ts = timestamp or datetime.now(UTC).isoformat()
        await db.execute(
            """INSERT INTO trades
               (trade_id, bot_id, strategy_id, symbol, side, quantity, price,
                status, order_type, reason, commission, timestamp, order_id,
                account_id, currency, exchange)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade_id,
                bot_id,
                "s-legacy",
                symbol,
                side,
                quantity,
                price,
                status,
                "market",
                "legacy",
                0.0,
                ts,
                None,
                account_id,
                "KRW",
                "KRX",
            ),
        )

    async def test_get_trades_skips_legacy_invalid_account_id(
        self, recorder, db, caplog
    ):
        """get_trades가 legacy 'default' account_id row를 skip한다."""
        import logging

        legacy_id = str(uuid4())
        valid_id = str(uuid4())

        # legacy 'default' row + 정상 row 혼재 삽입
        await self._insert_legacy_trade(
            db,
            trade_id=legacy_id,
            bot_id="legacy-bot",
            account_id="default",
        )
        await self._insert_legacy_trade(
            db,
            trade_id=valid_id,
            bot_id="ok-bot",
            account_id="acc-test",
        )

        with caplog.at_level(logging.WARNING, logger="ante.trade.recorder"):
            trades = await recorder.get_trades()

        # InvalidAccountIdError가 raise되지 않아야 함, 정상 row만 반환
        assert len(trades) == 1
        assert trades[0].bot_id == "ok-bot"
        assert trades[0].account_id == "acc-test"
        # warning 로그가 기록되어야 함
        assert any(
            "invalid account_id" in record.message and "get_trades" in record.message
            for record in caplog.records
        )

    async def test_get_trades_account_id_filter_does_not_raise_on_default(
        self, recorder, db, caplog
    ):
        """account_id=None 호출도 legacy default row 있을 때 raise 없이 동작."""
        import logging

        await self._insert_legacy_trade(
            db,
            trade_id=str(uuid4()),
            account_id="default",
        )

        with caplog.at_level(logging.WARNING, logger="ante.trade.recorder"):
            trades = await recorder.get_trades(account_id=None)

        assert trades == []
        assert any("invalid account_id" in record.message for record in caplog.records)

    async def test_performance_get_filled_trades_skips_legacy(
        self, performance, db, caplog
    ):
        """PerformanceTracker._get_filled_trades 경유 (metrics 등) 도 skip."""
        import logging

        legacy_id = str(uuid4())
        valid_id = str(uuid4())
        ts = datetime.now(UTC).isoformat()

        # legacy 'default' row + 정상 row 혼재
        await TestTradeReadLegacyAccountId._insert_legacy_trade(
            db,
            trade_id=legacy_id,
            bot_id="legacy-bot",
            side="sell",
            account_id="default",
            timestamp=ts,
        )
        await TestTradeReadLegacyAccountId._insert_legacy_trade(
            db,
            trade_id=valid_id,
            bot_id="ok-bot",
            side="sell",
            account_id="acc-test",
            timestamp=ts,
        )

        # 1) account_id='acc-test' 필터: SQL 단계에서 default 제외, 정상 1건 반환
        with caplog.at_level(logging.WARNING, logger="ante.trade.performance"):
            valid_trades = await performance._get_filled_trades(account_id="acc-test")
        assert len(valid_trades) == 1
        assert valid_trades[0].account_id == "acc-test"

        # 2) account_id='default' 필터: SQL 매칭은 되지만 모델 변환에서 skip
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="ante.trade.performance"):
            legacy_trades = await performance._get_filled_trades(account_id="default")
        assert legacy_trades == []
        assert any(
            "invalid account_id" in record.message
            and "_get_filled_trades" in record.message
            for record in caplog.records
        )
