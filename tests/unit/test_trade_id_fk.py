"""trade_id FK 기반 JOIN 단위 테스트 (#785)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ante.trade.models import TradeRecord, TradeStatus
from ante.trade.performance import PerformanceTracker
from ante.trade.position import PositionHistory


class TestPositionHistoryTradeId:
    """PositionHistory._save_history 가 trade_id를 저장하는지 검증."""

    @pytest.mark.asyncio
    async def test_save_history_includes_trade_id(self):
        """_save_history 호출 시 trade_id가 INSERT 파라미터에 포함된다."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.execute_script = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])
        db.fetch_one = AsyncMock(return_value=None)

        ph = PositionHistory(db)

        trade_id = uuid4()
        record = TradeRecord(
            trade_id=trade_id,
            bot_id="bot-1",
            strategy_id="strat-1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=70000.0,
            status=TradeStatus.FILLED,
            timestamp=datetime(2026, 3, 23, 10, 0, 0),
        )

        await ph.on_trade(record)

        # _save_history 에서 INSERT 실행됨
        insert_calls = [
            c for c in db.execute.call_args_list if "position_history" in str(c)
        ]
        assert len(insert_calls) >= 1
        # 마지막 파라미터가 trade_id 문자열
        params = insert_calls[0][0][1]
        assert str(trade_id) in params

    @pytest.mark.asyncio
    async def test_on_trade_sell_passes_trade_id(self):
        """매도 on_trade 시 trade_id가 position_history에 저장된다."""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.execute_script = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])
        # 매도 시 기존 포지션이 있어야 함
        db.fetch_one = AsyncMock(
            return_value={
                "bot_id": "bot-1",
                "symbol": "005930",
                "quantity": 10.0,
                "avg_entry_price": 65000.0,
                "realized_pnl": 0.0,
            }
        )

        ph = PositionHistory(db)

        trade_id = uuid4()
        record = TradeRecord(
            trade_id=trade_id,
            bot_id="bot-1",
            strategy_id="strat-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            price=70000.0,
            status=TradeStatus.FILLED,
            timestamp=datetime(2026, 3, 23, 11, 0, 0),
        )

        await ph.on_trade(record)

        insert_calls = [
            c for c in db.execute.call_args_list if "position_history" in str(c)
        ]
        assert len(insert_calls) >= 1
        params = insert_calls[0][0][1]
        assert str(trade_id) in params


class TestPerformanceTrackerTradeIdJoin:
    """PerformanceTracker가 trade_id 기반 JOIN을 사용하는지 검증."""

    @pytest.mark.asyncio
    async def test_calculate_pnl_uses_trade_id(self):
        """_calculate_pnl_per_trade가 trade_id로 조회한다."""
        db = AsyncMock()
        trade_id = uuid4()
        db.fetch_one = AsyncMock(return_value={"pnl": 50000.0})

        tracker = PerformanceTracker(db)
        sell_trade = TradeRecord(
            trade_id=trade_id,
            bot_id="bot-1",
            strategy_id="strat-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            price=70000.0,
            status=TradeStatus.FILLED,
            timestamp=datetime(2026, 3, 23, 11, 0, 0),
        )

        pnl_list = await tracker._calculate_pnl_per_trade([sell_trade], "bot-1")

        assert pnl_list == [50000.0]
        # trade_id 파라미터로 조회했는지 확인
        call_args = db.fetch_one.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "trade_id = ?" in query
        assert str(trade_id) in params

    @pytest.mark.asyncio
    async def test_daily_summary_join_uses_trade_id(self):
        """일별 집계 SQL이 trade_id 기반 JOIN을 사용한다."""
        db = AsyncMock()
        db.fetch_all = AsyncMock(return_value=[])

        tracker = PerformanceTracker(db)
        await tracker.get_daily_summary()

        call_args = db.fetch_all.call_args
        query = call_args[0][0]
        assert "ph.trade_id" in query
        # 기존 price/quantity JOIN 조건이 없어야 함
        assert "ph.price = t.price" not in query
        assert "ph.quantity = t.quantity" not in query

    @pytest.mark.asyncio
    async def test_duplicate_price_sell_resolved_by_trade_id(self):
        """동일 가격 반복 매도 시 trade_id로 정확히 구분된다."""
        db = AsyncMock()
        trade_id_1 = uuid4()
        trade_id_2 = uuid4()

        # 두 번 호출되면 각기 다른 pnl 반환
        db.fetch_one = AsyncMock(
            side_effect=[
                {"pnl": 10000.0},
                {"pnl": -5000.0},
            ]
        )

        tracker = PerformanceTracker(db)

        # 동일 종목, 동일 가격, 동일 수량이지만 trade_id가 다른 두 매도
        sell_1 = TradeRecord(
            trade_id=trade_id_1,
            bot_id="bot-1",
            strategy_id="strat-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            price=70000.0,
            status=TradeStatus.FILLED,
            timestamp=datetime(2026, 3, 23, 11, 0, 0),
        )
        sell_2 = TradeRecord(
            trade_id=trade_id_2,
            bot_id="bot-1",
            strategy_id="strat-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            price=70000.0,
            status=TradeStatus.FILLED,
            timestamp=datetime(2026, 3, 23, 12, 0, 0),
        )

        pnl_list = await tracker._calculate_pnl_per_trade([sell_1, sell_2], "bot-1")

        assert pnl_list == [10000.0, -5000.0]
        # 각각 다른 trade_id로 조회했는지 확인
        calls = db.fetch_one.call_args_list
        assert len(calls) == 2
        assert str(trade_id_1) in calls[0][0][1]
        assert str(trade_id_2) in calls[1][0][1]
