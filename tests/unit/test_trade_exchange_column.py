"""Trade/PositionHistory INSERT exchange 컬럼 저장 테스트. Refs #737, #2487."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.trade.fill_applier import FillApplier
from ante.trade.models import TradeRecord, TradeStatus
from ante.trade.order_tracker import OrderTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    # Refs #1897: aiosqlite Connection 누수 차단.
    try:
        yield db
    finally:
        await db.close()


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
async def tracker(db):
    """#2487: 체결 경로의 exchange 단일 소스."""
    t = OrderTracker(db)
    await t.initialize()
    return t


@pytest.fixture
async def applier(db, tracker, position_history, recorder):
    """#2487: 체결 반영 chokepoint. ``recorder`` 가 trades 스키마를 만든다.

    outbox 미주입 경로라 ``_publish_filled`` 가 직접 발행한다.
    """
    return FillApplier(
        db=db,
        order_tracker=tracker,
        position_history=position_history,
        eventbus=EventBus(),
    )


def _make_record(*, exchange: str = "KRX", side: str = "buy", **kwargs) -> TradeRecord:
    defaults = dict(
        trade_id=uuid4(),
        bot_id="bot1",
        strategy_id="s1",
        symbol="005930",
        side=side,
        quantity=10,
        price=50000,
        status=TradeStatus.FILLED,
        timestamp=datetime.now(UTC),
        exchange=exchange,
    )
    defaults.update(kwargs)
    return TradeRecord(**defaults, account_id="acc-test")


class TestRecorderExchangeColumn:
    """recorder._save()가 exchange 값을 DB에 기록하는지 확인."""

    async def test_default_exchange_saved(self, recorder, db):
        """exchange 기본값(KRX)이 저장된다."""
        record = _make_record()
        await recorder._save(record)

        rows = await db.fetch_all("SELECT exchange FROM trades")
        assert len(rows) == 1
        assert rows[0]["exchange"] == "KRX"

    async def test_custom_exchange_saved(self, recorder, db):
        """KRX가 아닌 exchange 값이 정상 저장된다."""
        record = _make_record(exchange="NASDAQ")
        await recorder._save(record)

        rows = await db.fetch_all("SELECT exchange FROM trades")
        assert len(rows) == 1
        assert rows[0]["exchange"] == "NASDAQ"


class TestPositionHistoryExchangeColumn:
    """position_history._save_history()가 exchange 값을 DB에 기록하는지 확인."""

    async def test_buy_exchange_saved(self, position_history, db):
        """매수 시 position_history에 exchange가 저장된다."""
        record = _make_record(exchange="NYSE", side="buy")
        await position_history.on_trade(record)

        rows = await db.fetch_all("SELECT exchange FROM position_history")
        assert len(rows) == 1
        assert rows[0]["exchange"] == "NYSE"

    async def test_sell_exchange_saved(self, position_history, db):
        """매도 시 position_history에 exchange가 저장된다."""
        buy = _make_record(exchange="NASDAQ", side="buy")
        await position_history.on_trade(buy)

        sell = _make_record(
            exchange="NASDAQ",
            side="sell",
            quantity=5,
            price=55000,
        )
        await position_history.on_trade(sell)

        rows = await db.fetch_all("SELECT exchange FROM position_history")
        assert len(rows) == 2
        assert all(r["exchange"] == "NASDAQ" for r in rows)

    async def test_default_exchange_fallback(self, position_history, db):
        """exchange 미지정 시 기본값 KRX로 저장된다."""
        record = _make_record(side="buy")  # exchange 기본값 = "KRX"
        await position_history.on_trade(record)

        rows = await db.fetch_all("SELECT exchange FROM position_history")
        assert len(rows) == 1
        assert rows[0]["exchange"] == "KRX"


class TestFillPathExchangePropagation:
    """체결 경로 e2e 회귀 락 (#2487).

    위 두 클래스는 ``recorder._save`` / ``position_history.on_trade`` 를 직접
    호출하므로 **결함이 있던 시점에도 통과**한다 — 결함은 「TradeRecord 를
    만드는 쪽이 exchange 를 안 채운다」였기 때문이다. 본 클래스는 실제 체결
    경로(``tracker.open`` → ``applier.apply_cumulative``)를 구동해 그 구간을
    잠근다.

    검증은 **raw SQL** 로 한다 — ``_row_to_record`` / ``_row_to_snapshot`` 은
    exchange 를 복원하지 않으므로(이 PR 범위 밖) ORM-ish 조회로는 확인할 수
    없다.
    """

    ACCOUNT = "acc-test"
    DATE = "20260901"

    async def _seed(self, tracker, *, exchange):
        await tracker.open(
            order_id="ord-2487",
            account_id=self.ACCOUNT,
            bot_id="bot1",
            strategy_id="s1",
            broker_order_id="odno-2487",
            symbol="005930",
            side="buy",
            order_type="limit",
            ordered_qty=10.0,
            submitted_date=self.DATE,
            exchange=exchange,
        )

    async def test_tracker_exchange_reaches_trades_and_position_history(
        self, tracker, applier, db
    ):
        """tracker 에 seed 된 exchange 가 두 영속 테이블에 그대로 도달한다."""
        await self._seed(tracker, exchange="TEST")

        delta = await applier.apply_cumulative(
            account_id=self.ACCOUNT,
            broker_order_id="odno-2487",
            observed_cumulative=10.0,
            avg_price=50000.0,
            submitted_date=self.DATE,
        )
        assert delta == 10.0

        trade_rows = await db.fetch_all("SELECT exchange FROM trades")
        assert len(trade_rows) == 1
        assert trade_rows[0]["exchange"] == "TEST"

        history_rows = await db.fetch_all("SELECT exchange FROM position_history")
        assert len(history_rows) == 1
        assert history_rows[0]["exchange"] == "TEST"

    async def test_legacy_null_exchange_falls_back_to_krx(self, tracker, applier, db):
        """v007 이전 legacy row(exchange NULL)는 "KRX" 로 폴백한다.

        마이그레이션 이전과 동일한 관측값이라 회귀가 없음을 못박는다.
        """
        await self._seed(tracker, exchange=None)

        await applier.apply_cumulative(
            account_id=self.ACCOUNT,
            broker_order_id="odno-2487",
            observed_cumulative=10.0,
            avg_price=50000.0,
            submitted_date=self.DATE,
        )

        trade_rows = await db.fetch_all("SELECT exchange FROM trades")
        assert trade_rows[0]["exchange"] == "KRX"

        history_rows = await db.fetch_all("SELECT exchange FROM position_history")
        assert history_rows[0]["exchange"] == "KRX"
