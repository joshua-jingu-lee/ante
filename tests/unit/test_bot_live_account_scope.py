"""#2139: Live 전략 컨텍스트의 portfolio/trade history account_id 스코핑 테스트.

``LiveDataProvider`` / ``LiveOrderView`` (#1948) 와 동일하게 live portfolio /
trade history 도 봇 계좌(``config.account_id``) 를 closure 로 binding 해야 한다.
이 테스트는 (1) view 직접 호출 격리, (2) factory 경로 격리, (3) symbol/limit
pass-through 를 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ante.account.models import Account, TradingMode
from ante.bot.config import BotConfig
from ante.bot.context_factory import StrategyContextFactory
from ante.bot.providers.live import LivePortfolioView, LiveTradeHistoryView
from ante.strategy.base import DataProvider

# ── Fake/Stub 구현체 ─────────────────────────────


class _FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        import polars as pl

        return pl.DataFrame({"close": [50000.0]})

    async def get_current_price(self, symbol):
        return 50000.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


@dataclass
class _FakeSnapshot:
    """PositionHistory.get_positions_sync 가 반환하는 PositionSnapshot 대역."""

    symbol: str
    quantity: float
    avg_entry_price: float
    realized_pnl: float = 0.0


@dataclass
class _FakeTrade:
    """TradeRecorder.get_trades 가 반환하는 TradeRecord 대역."""

    trade_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: Any
    order_type: str = "market"
    reason: str = ""
    commission: float = 0.0
    timestamp: Any = None


class _FilledStatus:
    """TradeStatus.FILLED 처럼 ``.value`` 를 갖는 최소 대역."""

    value = "filled"


class _FakePositionHistory:
    """account_id 별 포지션을 분리 저장하고, 조회 시 account_id 를 캡처하는 stub."""

    def __init__(self) -> None:
        # (account_id, bot_id) -> list[_FakeSnapshot]
        self._store: dict[tuple[str, str], list[_FakeSnapshot]] = {}
        self.calls: list[tuple[str, str | None]] = []

    def add(self, account_id: str, bot_id: str, snap: _FakeSnapshot) -> None:
        self._store.setdefault((account_id, bot_id), []).append(snap)

    def get_positions_sync(
        self, bot_id: str, *, account_id: str | None = None
    ) -> list[_FakeSnapshot]:
        self.calls.append((bot_id, account_id))
        # account_id 미전달이면 (버그 재현) 모든 계좌의 동일 bot_id 포지션 합침.
        if account_id is None:
            merged: list[_FakeSnapshot] = []
            for (_acc, b_id), snaps in self._store.items():
                if b_id == bot_id:
                    merged.extend(snaps)
            return merged
        return list(self._store.get((account_id, bot_id), []))


class _FakeRecorder:
    """account_id 별 거래를 분리 저장하고, 조회 시 인자를 캡처하는 stub."""

    def __init__(self) -> None:
        # (account_id, bot_id) -> list[_FakeTrade]
        self._store: dict[tuple[str, str], list[_FakeTrade]] = {}
        self.calls: list[dict[str, Any]] = []

    def add(self, account_id: str, bot_id: str, trade: _FakeTrade) -> None:
        self._store.setdefault((account_id, bot_id), []).append(trade)

    async def get_trades(
        self,
        account_id: str | None = None,
        bot_id: str | None = None,
        strategy_id: str | None = None,
        symbol: str | None = None,
        status: Any = None,
        from_date: Any = None,
        to_date: Any = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[_FakeTrade]:
        self.calls.append(
            {
                "account_id": account_id,
                "bot_id": bot_id,
                "symbol": symbol,
                "limit": limit,
            }
        )
        if account_id is None:
            merged: list[_FakeTrade] = []
            for (_acc, b_id), trades in self._store.items():
                if b_id == bot_id:
                    merged.extend(trades)
            results = merged
        else:
            results = list(self._store.get((account_id, bot_id), []))
        if symbol is not None:
            results = [t for t in results if t.symbol == symbol]
        return results[:limit]


class _FakeTreasury:
    def get_budget_sync(self, bot_id: str) -> None:
        return None


def _filled(trade_id: str, symbol: str) -> _FakeTrade:
    return _FakeTrade(
        trade_id=trade_id,
        symbol=symbol,
        side="buy",
        quantity=1.0,
        price=100.0,
        status=_FilledStatus(),
    )


# ── (1) direct view: account_id 격리 + 조회 account_id 캡처 ──


class TestLiveViewDirectAccountScope:
    def test_portfolio_scopes_to_account(self) -> None:
        """LivePortfolioView(acc-a) 는 acc-a 포지션만 노출하고
        get_positions_sync 를 account_id=acc-a 로 호출한다."""
        ph = _FakePositionHistory()
        ph.add("acc-a", "bot1", _FakeSnapshot("AAA", 1.0, 100.0))
        ph.add("acc-b", "bot1", _FakeSnapshot("BBB", 2.0, 200.0))

        view = LivePortfolioView(
            treasury=_FakeTreasury(),
            position_history=ph,
            account_id="acc-a",
        )
        positions = view.get_positions("bot1")

        assert set(positions.keys()) == {"AAA"}
        assert "BBB" not in positions
        # 조회가 account_id=acc-a 로 스코핑됐는지 검증.
        assert ph.calls == [("bot1", "acc-a")]

    async def test_trade_history_scopes_to_account(self) -> None:
        """LiveTradeHistoryView(acc-a) 는 acc-a 거래만 노출하고
        get_trades 를 account_id=acc-a 로 호출한다."""
        rec = _FakeRecorder()
        rec.add("acc-a", "bot1", _filled("t-a", "AAA"))
        rec.add("acc-b", "bot1", _filled("t-b", "BBB"))

        view = LiveTradeHistoryView(trade_recorder=rec, account_id="acc-a")
        trades = await view.get_trade_history("bot1")

        assert [t["symbol"] for t in trades] == ["AAA"]
        assert all(t["symbol"] != "BBB" for t in trades)
        assert len(rec.calls) == 1
        assert rec.calls[0]["account_id"] == "acc-a"
        assert rec.calls[0]["bot_id"] == "bot1"


# ── (2) factory 경로: 봇 계좌만 노출 ──


def _live_account_service() -> Any:
    class _FakeAccountService:
        def get_sync(self, account_id: str) -> Account:
            return Account(
                account_id=account_id,
                name="test",
                exchange="KRX",
                currency="KRW",
                trading_mode=TradingMode.LIVE,
            )

    return _FakeAccountService()


class _FakeTreasuryManager:
    def get(self, account_id: str) -> _FakeTreasury:
        return _FakeTreasury()


class TestFactoryLiveAccountScope:
    async def test_factory_scopes_portfolio_and_trade_history(self) -> None:
        """StrategyContextFactory 가 봇 계좌(config.account_id) 로 portfolio /
        trade_history 를 binding 해 타 계좌 데이터가 노출되지 않는다."""
        ph = _FakePositionHistory()
        ph.add("acc-a", "bot1", _FakeSnapshot("AAA", 1.0, 100.0))
        ph.add("acc-b", "bot1", _FakeSnapshot("BBB", 2.0, 200.0))

        rec = _FakeRecorder()
        rec.add("acc-a", "bot1", _filled("t-a", "AAA"))
        rec.add("acc-b", "bot1", _filled("t-b", "BBB"))

        factory = StrategyContextFactory(
            data_provider=_FakeDataProvider(),
            account_service=_live_account_service(),
            treasury_manager=_FakeTreasuryManager(),
            position_history=ph,
            trade_recorder=rec,
        )

        ctx = factory.create(
            BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-a")
        )

        positions = ctx.get_positions()
        assert set(positions.keys()) == {"AAA"}

        trades = await ctx.get_trade_history()
        assert [t["symbol"] for t in trades] == ["AAA"]
        # 두 조회 모두 acc-a 로 스코핑됐는지 확인.
        assert ph.calls[-1] == ("bot1", "acc-a")
        assert rec.calls[-1]["account_id"] == "acc-a"

    async def test_factory_isolates_per_bot_account(self) -> None:
        """동일 bot_id 라도 계좌별로 분리된 view 가 생성된다."""
        ph = _FakePositionHistory()
        ph.add("acc-a", "bot1", _FakeSnapshot("AAA", 1.0, 100.0))
        ph.add("acc-b", "bot1", _FakeSnapshot("BBB", 2.0, 200.0))

        rec = _FakeRecorder()
        rec.add("acc-a", "bot1", _filled("t-a", "AAA"))
        rec.add("acc-b", "bot1", _filled("t-b", "BBB"))

        factory = StrategyContextFactory(
            data_provider=_FakeDataProvider(),
            account_service=_live_account_service(),
            treasury_manager=_FakeTreasuryManager(),
            position_history=ph,
            trade_recorder=rec,
        )

        ctx_b = factory.create(
            BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-b")
        )
        assert set(ctx_b.get_positions().keys()) == {"BBB"}
        trades_b = await ctx_b.get_trade_history()
        assert [t["symbol"] for t in trades_b] == ["BBB"]

    async def test_factory_trade_recorder_absent_uses_shared_fallback(self) -> None:
        """trade_recorder 미주입이면 공유 live_trade_history fallback 을 쓴다
        (legacy/test 호환). 공유 인스턴스의 private 멤버에 접근하지 않는다."""
        shared = LiveTradeHistoryView(
            trade_recorder=_FakeRecorder(), account_id="shared-acc"
        )

        factory = StrategyContextFactory(
            data_provider=_FakeDataProvider(),
            account_service=_live_account_service(),
            treasury_manager=_FakeTreasuryManager(),
            position_history=_FakePositionHistory(),
            live_trade_history=shared,
            # trade_recorder 미주입
        )

        ctx = factory.create(
            BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-a")
        )
        # 공유 인스턴스가 그대로 바인딩됐는지 (fallback) 확인.
        assert ctx._trade_history is shared


# ── (3) symbol / limit pass-through ──


class TestTradeHistoryPassThrough:
    async def test_symbol_and_limit_passed_to_get_trades(self) -> None:
        """get_trade_history(symbol=..., limit=...) 가 get_trades 에 그대로 전달."""
        rec = _FakeRecorder()
        rec.add("acc-a", "bot1", _filled("t-1", "AAA"))
        rec.add("acc-a", "bot1", _filled("t-2", "BBB"))

        view = LiveTradeHistoryView(trade_recorder=rec, account_id="acc-a")
        await view.get_trade_history("bot1", symbol="AAA", limit=7)

        assert len(rec.calls) == 1
        call = rec.calls[0]
        assert call["account_id"] == "acc-a"
        assert call["bot_id"] == "bot1"
        assert call["symbol"] == "AAA"
        assert call["limit"] == 7

    async def test_default_limit_preserved(self) -> None:
        """symbol/limit 미지정 시 기본 limit(50) 이 get_trades 로 전달된다."""
        rec = _FakeRecorder()
        view = LiveTradeHistoryView(trade_recorder=rec, account_id="acc-a")
        await view.get_trade_history("bot1")

        assert rec.calls[0]["symbol"] is None
        assert rec.calls[0]["limit"] == 50


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
