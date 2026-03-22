"""Trade/PositionHistory INSERT exchange 컬럼 저장 테스트. Refs #737."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ante.core.database import Database
from ante.trade.models import TradeRecord, TradeStatus
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder


@pytest.fixture
async def db(tmp_path):
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
    return TradeRecord(**defaults)


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
