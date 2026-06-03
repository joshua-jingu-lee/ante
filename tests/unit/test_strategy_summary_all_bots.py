"""strategy summary 가 전략 전체 거래를 ``trades.strategy_id`` 로 집계 (#2144).

기존 동작은 ``_find_bot_id_for_strategy`` 로 전략의 **첫 번째 봇만** 골라
집계했다 (다중 봇/다중 계좌 전략의 성과 누락). 본 모듈은 실제 SQLite DB 에
거래/포지션 이력을 적재하고 ``PerformanceTracker.get_*_summary(strategy_id=...)``
가 전략 전체를 정확히 집계하는지 검증한다:

- 같은 전략 2봇 → 양쪽 거래 합산 (첫 봇만 아님)
- strategy 변경 봇 (그 봇이 다른 전략으로 낸 거래) → 다른-전략 거래 미포함 (오염 없음)
- 삭제된 봇의 과거 거래 → 포함 (strategy_id 필터라 봇 status 무관)
- 0 거래 → 빈 graceful
- cross-account 절대지표 합산
"""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.trade.performance import PerformanceTracker
from ante.trade.position import POSITION_SCHEMA
from ante.trade.recorder import TRADE_SCHEMA


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "summary.db"))
    await db.connect()
    await db.execute_script(TRADE_SCHEMA)
    await db.execute_script(POSITION_SCHEMA)
    try:
        yield db
    finally:
        await db.close()


async def _insert_sell(
    db: Database,
    *,
    trade_id: str,
    bot_id: str,
    strategy_id: str,
    account_id: str,
    pnl: float,
    timestamp: str,
    symbol: str = "005930",
) -> None:
    """체결된 매도 거래 1건 + 대응 position_history(pnl) 적재.

    get_*_summary 는 ``t.status='filled' AND t.side='sell'`` 거래를
    ``position_history.pnl`` 과 trade_id 로 JOIN 해 realized_pnl/승패를
    산출한다. 본 helper 는 그 JOIN 이 성립하도록 양쪽을 함께 넣는다.
    """
    await db.execute(
        """INSERT INTO trades
           (trade_id, bot_id, strategy_id, symbol, side, quantity, price,
            status, timestamp, account_id)
           VALUES (?, ?, ?, ?, 'sell', 10, 70000, 'filled', ?, ?)""",
        (trade_id, bot_id, strategy_id, symbol, timestamp, account_id),
    )
    await db.execute(
        """INSERT INTO position_history
           (bot_id, symbol, action, quantity, price, pnl, timestamp,
            account_id, trade_id)
           VALUES (?, ?, 'sell', 10, 70000, ?, ?, ?, ?)""",
        (bot_id, symbol, pnl, timestamp, account_id, trade_id),
    )


class TestStrategySummaryAllBots:
    async def test_two_bots_same_strategy_are_summed(self, db):
        """같은 전략을 쓰는 2봇 → 양쪽 거래가 합산된다 (첫 봇만 아님)."""
        await _insert_sell(
            db,
            trade_id="t-a",
            bot_id="bot-a",
            strategy_id="strat-1",
            account_id="acc-a",
            pnl=10_000.0,
            timestamp="2026-03-10 10:00:00",
        )
        await _insert_sell(
            db,
            trade_id="t-b",
            bot_id="bot-b",
            strategy_id="strat-1",
            account_id="acc-a",
            pnl=5_000.0,
            timestamp="2026-03-10 11:00:00",
        )

        tracker = PerformanceTracker(db)
        result = await tracker.get_daily_summary(strategy_id="strat-1")

        assert len(result) == 1
        day = result[0]
        assert day.date == "2026-03-10"
        # 두 봇 거래 모두 포함 (첫 봇만이면 1건/10_000 만 보였을 것).
        assert day.trade_count == 2
        assert day.realized_pnl == pytest.approx(15_000.0)
        assert day.win_rate == pytest.approx(1.0)

    async def test_first_bot_only_would_miss_second_bot(self, db):
        """대조군: bot_id 단일 필터는 그 봇 거래만 본다 (회귀 가드)."""
        await _insert_sell(
            db,
            trade_id="t-a",
            bot_id="bot-a",
            strategy_id="strat-1",
            account_id="acc-a",
            pnl=10_000.0,
            timestamp="2026-03-10 10:00:00",
        )
        await _insert_sell(
            db,
            trade_id="t-b",
            bot_id="bot-b",
            strategy_id="strat-1",
            account_id="acc-a",
            pnl=5_000.0,
            timestamp="2026-03-10 11:00:00",
        )

        tracker = PerformanceTracker(db)
        first_bot_only = await tracker.get_daily_summary(bot_id="bot-a")
        assert first_bot_only[0].trade_count == 1
        assert first_bot_only[0].realized_pnl == pytest.approx(10_000.0)

    async def test_strategy_changed_bot_does_not_contaminate(self, db):
        """봇이 다른 전략으로 낸 거래는 strategy_id 필터에 안 잡힌다 (오염 없음).

        같은 봇(bot-a)이 strat-1 과 strat-2 로 각각 거래를 냈을 때,
        strat-1 집계에는 strat-2 거래가 섞이지 않는다.
        """
        await _insert_sell(
            db,
            trade_id="t-1",
            bot_id="bot-a",
            strategy_id="strat-1",
            account_id="acc-a",
            pnl=10_000.0,
            timestamp="2026-03-10 10:00:00",
        )
        await _insert_sell(
            db,
            trade_id="t-2",
            bot_id="bot-a",
            strategy_id="strat-2",
            account_id="acc-a",
            pnl=99_000.0,
            timestamp="2026-03-10 12:00:00",
        )

        tracker = PerformanceTracker(db)
        result = await tracker.get_daily_summary(strategy_id="strat-1")

        assert len(result) == 1
        assert result[0].trade_count == 1
        # strat-2 의 99_000 은 포함되지 않는다.
        assert result[0].realized_pnl == pytest.approx(10_000.0)

    async def test_deleted_bot_past_trades_included(self, db):
        """삭제된 봇의 과거 거래도 포함된다 (strategy_id 필터라 봇 status 무관).

        trades.strategy_id 로 집계하므로 봇이 bots 테이블에 존재하는지/
        status 가 deleted 인지와 무관하게 거래 시점 전략 귀속으로 잡힌다.
        (bots 테이블 자체를 만들지 않아도 집계가 성립함을 함께 확인.)
        """
        await _insert_sell(
            db,
            trade_id="t-old",
            bot_id="bot-deleted",
            strategy_id="strat-1",
            account_id="acc-a",
            pnl=7_000.0,
            timestamp="2026-03-10 09:00:00",
        )

        tracker = PerformanceTracker(db)
        result = await tracker.get_daily_summary(strategy_id="strat-1")

        assert len(result) == 1
        assert result[0].trade_count == 1
        assert result[0].realized_pnl == pytest.approx(7_000.0)

    async def test_zero_trades_returns_empty_gracefully(self, db):
        """전략에 거래가 없으면 빈 리스트 (graceful)."""
        tracker = PerformanceTracker(db)
        result = await tracker.get_daily_summary(strategy_id="strat-empty")
        assert result == []

    async def test_cross_account_absolute_metrics_summed(self, db):
        """여러 계좌의 거래도 절대지표(realized_pnl/trade_count)로 합산된다."""
        await _insert_sell(
            db,
            trade_id="t-acc-a",
            bot_id="bot-a",
            strategy_id="strat-1",
            account_id="acc-a",
            pnl=10_000.0,
            timestamp="2026-03-10 10:00:00",
        )
        await _insert_sell(
            db,
            trade_id="t-acc-b",
            bot_id="bot-b",
            strategy_id="strat-1",
            account_id="acc-b",
            pnl=20_000.0,
            timestamp="2026-03-10 11:00:00",
        )

        tracker = PerformanceTracker(db)
        result = await tracker.get_daily_summary(strategy_id="strat-1")

        assert len(result) == 1
        assert result[0].trade_count == 2
        assert result[0].realized_pnl == pytest.approx(30_000.0)

    async def test_weekly_and_monthly_summary_strategy_scoped(self, db):
        """weekly/monthly 도 strategy_id 로 전략 전체를 집계한다."""
        await _insert_sell(
            db,
            trade_id="t-w-a",
            bot_id="bot-a",
            strategy_id="strat-1",
            account_id="acc-a",
            pnl=10_000.0,
            timestamp="2026-03-10 10:00:00",
        )
        await _insert_sell(
            db,
            trade_id="t-w-b",
            bot_id="bot-b",
            strategy_id="strat-1",
            account_id="acc-a",
            pnl=5_000.0,
            timestamp="2026-03-11 10:00:00",
        )

        tracker = PerformanceTracker(db)
        weekly = await tracker.get_weekly_summary(strategy_id="strat-1")
        monthly = await tracker.get_monthly_summary(strategy_id="strat-1")

        assert len(weekly) == 1
        assert weekly[0].trade_count == 2
        assert weekly[0].realized_pnl == pytest.approx(15_000.0)

        assert len(monthly) == 1
        assert monthly[0].year == 2026
        assert monthly[0].month == 3
        assert monthly[0].trade_count == 2
        assert monthly[0].realized_pnl == pytest.approx(15_000.0)
