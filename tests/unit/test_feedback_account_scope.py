"""PerformanceFeedback account_id 스코핑 회귀 테스트 (#2136).

봇 계좌(acc-a)와 타 계좌(acc-b) 데이터가 섞인 상황에서, bot-scoped 조회가
``BotManager.get_bot(bot_id)`` 로 resolve한 계좌(acc-a)로만 스코핑되는지 검증한다.

`TradeService.get_positions(bot_id, *, account_id=None)` /
`get_trades(account_id=None, bot_id=None, ...)` 는 ``account_id`` 가 주어졌을 때만
SQL `account_id=?` 조건을 붙인다. fake trade service는 그 계약을 모사하여,
``account_id`` kwarg를 수신해 해당 계좌 행만 반환하고, 호출 인자를 캡처한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from ante.bot.exceptions import BotNotFoundError
from ante.report.feedback import PerformanceFeedback
from ante.trade.models import PerformanceMetrics, PositionSnapshot
from ante.trade.recorder import TradeRecord, TradeStatus

BOT_ID = "bot-shared"
ACC_A = "acc-a"
ACC_B = "acc-b"


def _position(symbol: str, account_id: str) -> PositionSnapshot:
    return PositionSnapshot(
        bot_id=BOT_ID,
        symbol=symbol,
        quantity=1.0,
        avg_entry_price=100.0,
        realized_pnl=10.0,
        account_id=account_id,
    )


def _trade(symbol: str, account_id: str, day: int) -> TradeRecord:
    return TradeRecord(
        trade_id=f"t-{account_id}-{symbol}",
        bot_id=BOT_ID,
        strategy_id="s1",
        symbol=symbol,
        side="sell",
        quantity=1.0,
        price=100.0,
        status=TradeStatus.FILLED,
        timestamp=datetime(2026, 1, day, tzinfo=UTC),
        account_id=account_id,
    )


class FakeTradeService:
    """account_id kwarg를 수신해 해당 계좌 행만 반환하고 호출을 캡처하는 fake.

    ``account_id=None`` 이면 all-account 정책(모든 계좌 행 반환)을 모사하여,
    스코핑이 빠지면 타 계좌 데이터가 섞여 테스트가 실패하도록 한다.
    """

    def __init__(
        self,
        positions: list[PositionSnapshot],
        trades: list[TradeRecord],
    ) -> None:
        self._positions = positions
        self._trades = trades
        self.get_positions_calls: list[dict] = []
        self.get_trades_calls: list[dict] = []

    async def get_performance(
        self, *, account_id: str, bot_id: str | None = None
    ) -> PerformanceMetrics:
        return PerformanceMetrics(
            total_trades=1,
            winning_trades=1,
            losing_trades=0,
            win_rate=1.0,
            total_pnl=10.0,
            total_commission=0.0,
            net_pnl=10.0,
            avg_profit=10.0,
            avg_loss=0.0,
            profit_factor=1.0,
            max_drawdown=0.0,
            max_drawdown_amount=0.0,
            sharpe_ratio=0.0,
        )

    async def get_positions(
        self,
        bot_id: str,
        include_closed: bool = False,
        *,
        account_id: str | None = None,
    ) -> list[PositionSnapshot]:
        self.get_positions_calls.append({"bot_id": bot_id, "account_id": account_id})
        rows = [p for p in self._positions if p.bot_id == bot_id]
        if account_id is not None:
            rows = [p for p in rows if p.account_id == account_id]
        return rows

    async def get_trades(
        self,
        account_id: str | None = None,
        bot_id: str | None = None,
        *,
        status: TradeStatus | None = None,
        limit: int = 100,
        **_: object,
    ) -> list[TradeRecord]:
        self.get_trades_calls.append(
            {
                "account_id": account_id,
                "bot_id": bot_id,
                "status": status,
                "limit": limit,
            }
        )
        rows = list(self._trades)
        if bot_id is not None:
            rows = [t for t in rows if t.bot_id == bot_id]
        if account_id is not None:
            rows = [t for t in rows if t.account_id == account_id]
        if status is not None:
            rows = [t for t in rows if t.status == status]
        return rows[:limit]


class FakeBotManager:
    """get_bot이 acc-a 계좌의 봇을 반환하는 fake. 미등록 bot_id는 None."""

    def __init__(self, account_id: str = ACC_A) -> None:
        self._bot = SimpleNamespace(config=SimpleNamespace(account_id=account_id))

    def get_bot(self, bot_id: str):  # noqa: ANN201 - fake
        return self._bot if bot_id == BOT_ID else None


@pytest.fixture
def positions() -> list[PositionSnapshot]:
    # acc-a: AAA, acc-b: BBB (타 계좌 stale row)
    return [_position("AAA", ACC_A), _position("BBB", ACC_B)]


@pytest.fixture
def trades() -> list[TradeRecord]:
    # acc-a: AAA(1/1), acc-b: BBB(1/2)
    return [_trade("AAA", ACC_A, 1), _trade("BBB", ACC_B, 2)]


@pytest.fixture
def feedback(positions, trades) -> PerformanceFeedback:
    return PerformanceFeedback(FakeTradeService(positions, trades), FakeBotManager())


# ── (a) get_bot_performance ──────────────────────────


async def test_get_bot_performance_scoped_to_bot_account(feedback):
    """current_positions가 acc-a만, get_positions가 account_id=acc-a로 호출."""
    result = await feedback.get_bot_performance(BOT_ID)

    symbols = [p["symbol"] for p in result["current_positions"]]
    assert symbols == ["AAA"]  # acc-b의 BBB 미포함

    ts = feedback._trade
    assert ts.get_positions_calls == [{"bot_id": BOT_ID, "account_id": ACC_A}]


# ── (b) get_trade_history ────────────────────────────


async def test_get_trade_history_scoped_to_bot_account(feedback):
    """acc-a 거래만, get_trades account_id=acc-a, limit 보존."""
    result = await feedback.get_trade_history(BOT_ID, limit=50)

    symbols = [t["symbol"] for t in result]
    assert symbols == ["AAA"]  # acc-b의 BBB 미포함

    ts = feedback._trade
    assert len(ts.get_trades_calls) == 1
    call = ts.get_trades_calls[0]
    assert call["account_id"] == ACC_A
    assert call["bot_id"] == BOT_ID
    assert call["limit"] == 50  # limit 보존


# ── (c) get_equity_curve ─────────────────────────────


async def test_get_equity_curve_scoped_to_bot_account(feedback):
    """acc-a만, get_trades account_id=acc-a, status=FILLED·limit=10000 보존."""
    curve = await feedback.get_equity_curve(BOT_ID, initial_balance=0.0)

    # acc-a의 AAA 거래(1/1)만 곡선에 반영 → 단일 날짜
    assert [pt["date"] for pt in curve] == ["2026-01-01"]

    ts = feedback._trade
    assert len(ts.get_trades_calls) == 1
    call = ts.get_trades_calls[0]
    assert call["account_id"] == ACC_A
    assert call["bot_id"] == BOT_ID
    assert call["status"] == TradeStatus.FILLED  # status 보존
    assert call["limit"] == 10000  # limit 보존


# ── (d) BotNotFoundError 전파 ────────────────────────


async def test_get_trade_history_missing_bot_raises(feedback):
    """미존재 bot_id → BotNotFoundError (get_bot_performance와 동일 계약)."""
    with pytest.raises(BotNotFoundError):
        await feedback.get_trade_history("missing-bot")


async def test_get_equity_curve_missing_bot_raises(feedback):
    """미존재 bot_id → BotNotFoundError (get_bot_performance와 동일 계약)."""
    with pytest.raises(BotNotFoundError):
        await feedback.get_equity_curve("missing-bot")
