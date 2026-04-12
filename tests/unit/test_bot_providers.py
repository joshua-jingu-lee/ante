"""Bot Provider + StrategyContextFactory 단위 테스트."""

from __future__ import annotations

import pytest

from ante.bot.config import BotConfig
from ante.bot.context_factory import StrategyContextFactory
from ante.bot.providers.live import LiveOrderView, LivePortfolioView
from ante.bot.providers.paper import PaperExecutor, PaperOrderView, PaperPortfolioView
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderApprovedEvent,
    OrderFilledEvent,
)
from ante.strategy.base import DataProvider
from ante.strategy.context import StrategyContext
from ante.trade.position import PositionHistory
from ante.treasury.treasury import Treasury

# ── Fake/Stub 구현체 ─────────────────────────────


class FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        import polars as pl

        return pl.DataFrame({"close": [50000.0]})

    async def get_current_price(self, symbol):
        return 50000.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


# ── Fixtures ─────────────────────────────────────


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


# ── US-1: LivePortfolioView / LiveOrderView ──────


class TestLivePortfolioView:
    async def test_get_positions_empty(self, db, eventbus):
        """봇에 포지션이 없으면 빈 dict 반환."""
        treasury = Treasury(db=db, eventbus=eventbus)
        await treasury.initialize()
        position_history = PositionHistory(db=db)
        await position_history.initialize()

        view = LivePortfolioView(treasury=treasury, position_history=position_history)
        assert view.get_positions("bot1") == {}

    async def test_get_positions_with_data(self, db, eventbus):
        """포지션이 있으면 심볼별 dict 반환."""
        treasury = Treasury(db=db, eventbus=eventbus)
        await treasury.initialize()
        position_history = PositionHistory(db=db)
        await position_history.initialize()

        # 포지션 삽입
        from ante.trade.models import TradeRecord, TradeStatus

        record = TradeRecord(
            trade_id="t1",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=50000.0,
            status=TradeStatus.FILLED,
            order_type="market",
        )
        await position_history.on_trade(record)

        view = LivePortfolioView(treasury=treasury, position_history=position_history)
        positions = view.get_positions("bot1")
        assert "005930" in positions
        assert positions["005930"]["quantity"] == 10.0
        assert positions["005930"]["avg_entry_price"] == 50000.0

    async def test_get_balance_no_budget(self, db, eventbus):
        """예산 미할당 시 0 반환."""
        treasury = Treasury(db=db, eventbus=eventbus)
        await treasury.initialize()
        position_history = PositionHistory(db=db)
        await position_history.initialize()

        view = LivePortfolioView(treasury=treasury, position_history=position_history)
        balance = view.get_balance("bot1")
        assert balance["allocated"] == 0.0
        assert balance["available"] == 0.0

    async def test_get_balance_with_budget(self, db, eventbus):
        """예산 할당 시 잔고 반환."""
        treasury = Treasury(db=db, eventbus=eventbus)
        await treasury.initialize()
        await treasury.set_account_balance(10_000_000.0)
        await treasury.allocate("bot1", 1_000_000.0)

        position_history = PositionHistory(db=db)
        await position_history.initialize()

        view = LivePortfolioView(treasury=treasury, position_history=position_history)
        balance = view.get_balance("bot1")
        assert balance["allocated"] == 1_000_000.0
        assert balance["available"] == 1_000_000.0


class TestLiveOrderView:
    def test_get_open_orders_empty(self):
        """미체결 주문 없으면 빈 목록."""
        view = LiveOrderView(order_registry=None)
        assert view.get_open_orders("bot1") == []


# ── US-2: PaperPortfolioView / PaperOrderView ───


class TestPaperPortfolioView:
    def test_initial_balance(self):
        """초기 잔고 확인."""
        pv = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        balance = pv.get_balance("paper1")
        assert balance["allocated"] == 10_000_000.0
        assert balance["available"] == 10_000_000.0
        assert balance["reserved"] == 0.0

    def test_empty_positions(self):
        """초기 포지션 없음."""
        pv = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        assert pv.get_positions("paper1") == {}

    def test_apply_fill_buy(self):
        """매수 체결 시 포지션/잔고 갱신."""
        pv = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        pv.apply_fill("005930", "buy", 10.0, 50000.0, commission=75.0)

        positions = pv.get_positions("paper1")
        assert positions["005930"]["quantity"] == 10.0
        assert positions["005930"]["avg_entry_price"] == 50000.0

        balance = pv.get_balance("paper1")
        assert balance["available"] == 10_000_000.0 - 500000.0 - 75.0

    def test_apply_fill_sell(self):
        """매도 체결 시 포지션/잔고 갱신."""
        pv = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        pv.apply_fill("005930", "buy", 10.0, 50000.0, commission=75.0)
        pv.apply_fill("005930", "sell", 10.0, 55000.0, commission=82.5)

        positions = pv.get_positions("paper1")
        # 수량 0이면 포지션에서 제외
        assert "005930" not in positions

    def test_check_balance_sufficient(self):
        """잔고 충분 확인."""
        pv = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        assert pv.check_balance(5_000_000.0) is True

    def test_check_balance_insufficient(self):
        """잔고 부족 확인."""
        pv = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        assert pv.check_balance(15_000_000.0) is False

    def test_reserve_and_release(self):
        """자금 예약/해제."""
        pv = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        pv.reserve("ord1", 500_000.0)

        balance = pv.get_balance("paper1")
        assert balance["reserved"] == 500_000.0
        assert balance["available"] == 9_500_000.0

        pv.release_reservation("ord1")
        balance = pv.get_balance("paper1")
        assert balance["reserved"] == 0.0


class TestPaperOrderView:
    def test_empty_orders(self):
        """미체결 주문 없으면 빈 목록."""
        pv = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        ov = PaperOrderView(portfolio=pv)
        assert ov.get_open_orders("paper1") == []

    def test_pending_orders_tracked(self):
        """예약된 주문이 미체결 목록에 나타남."""
        pv = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        pv.reserve("ord1", 500_000.0)

        ov = PaperOrderView(portfolio=pv)
        orders = ov.get_open_orders("paper1")
        assert len(orders) == 1
        assert orders[0]["order_id"] == "ord1"


# ── US-3: PaperExecutor ─────────────────────────


class TestPaperExecutor:
    async def test_paper_fill_buy(self, eventbus):
        """Paper 봇의 매수 주문 → 가상 체결."""
        executor = PaperExecutor(eventbus=eventbus, commission_rate=0.00015)

        portfolio = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        executor.register_bot("paper1", portfolio)
        executor.subscribe()

        filled = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-001",
                account_id="acct1",
                bot_id="paper1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="limit",
                price=50000.0,
            )
        )

        assert len(filled) == 1
        assert filled[0].bot_id == "paper1"
        assert filled[0].symbol == "005930"
        assert filled[0].quantity == 10.0
        assert filled[0].price == 50000.0
        assert filled[0].commission == 50000.0 * 10.0 * 0.00015
        assert filled[0].order_id == "ord-001"
        assert filled[0].account_id == "acct1"

        # 포지션 반영 확인
        positions = portfolio.get_positions("paper1")
        assert positions["005930"]["quantity"] == 10.0

    async def test_paper_fill_sell(self, eventbus):
        """Paper 봇의 매도 주문 → 가상 체결."""
        executor = PaperExecutor(eventbus=eventbus, commission_rate=0.00015)
        portfolio = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        executor.register_bot("paper1", portfolio)
        executor.subscribe()

        # 먼저 매수
        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-001",
                account_id="acct1",
                bot_id="paper1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="limit",
                price=50000.0,
            )
        )

        filled = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        # 매도
        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-002",
                account_id="acct1",
                bot_id="paper1",
                strategy_id="s1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="limit",
                price=55000.0,
            )
        )

        # 첫 번째는 매수 체결, 마지막이 매도 체결
        sell_fill = filled[-1]
        assert sell_fill.side == "sell"
        assert sell_fill.price == 55000.0

    async def test_ignores_live_bot(self, eventbus):
        """live 봇의 주문은 무시."""
        executor = PaperExecutor(eventbus=eventbus)
        executor.subscribe()

        filled = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-001",
                account_id="acct1",
                bot_id="live_bot",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="market",
                price=50000.0,
            )
        )

        assert len(filled) == 0

    async def test_commission_calculation(self, eventbus):
        """수수료 계산 검증."""
        executor = PaperExecutor(
            eventbus=eventbus,
            commission_rate=0.001,  # 0.1%
        )
        portfolio = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        executor.register_bot("paper1", portfolio)
        executor.subscribe()

        filled = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-001",
                account_id="acct1",
                bot_id="paper1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=100.0,
                order_type="limit",
                price=50000.0,
            )
        )

        assert filled[0].commission == 50000.0 * 100.0 * 0.001

    async def test_slippage_buy(self, eventbus):
        """매수 슬리피지: 체결가 = 현재가 × (1 + slippage_rate)."""
        executor = PaperExecutor(eventbus=eventbus, slippage_rate=0.001)
        portfolio = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        executor.register_bot("paper1", portfolio)
        executor.subscribe()

        filled = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-001",
                account_id="acct1",
                bot_id="paper1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="market",
                price=50000.0,  # current price fallback
            )
        )

        expected_price = 50000.0 * 1.001
        assert filled[0].price == pytest.approx(expected_price)

    async def test_slippage_sell(self, eventbus):
        """매도 슬리피지: 체결가 = 현재가 × (1 - slippage_rate)."""
        executor = PaperExecutor(eventbus=eventbus, slippage_rate=0.001)
        portfolio = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        # 먼저 포지션 만들기
        portfolio.apply_fill("005930", "buy", 10.0, 50000.0, 0.0)
        executor.register_bot("paper1", portfolio)
        executor.subscribe()

        filled = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-001",
                account_id="acct1",
                bot_id="paper1",
                strategy_id="s1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="market",
                price=50000.0,
            )
        )

        expected_price = 50000.0 * 0.999
        assert filled[0].price == pytest.approx(expected_price)

    async def test_limit_order_no_slippage(self, eventbus):
        """지정가 주문: 슬리피지 없이 지정가 그대로 체결."""
        executor = PaperExecutor(
            eventbus=eventbus,
            slippage_rate=0.01,  # 1% 슬리피지 설정해도
        )
        portfolio = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        executor.register_bot("paper1", portfolio)
        executor.subscribe()

        filled = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-001",
                account_id="acct1",
                bot_id="paper1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="limit",
                price=50000.0,
            )
        )

        assert filled[0].price == 50000.0  # 지정가 그대로

    async def test_unregister_bot(self, eventbus):
        """봇 등록 해제 후 주문 무시."""
        executor = PaperExecutor(eventbus=eventbus)
        portfolio = PaperPortfolioView(bot_id="paper1", initial_balance=10_000_000.0)
        executor.register_bot("paper1", portfolio)
        executor.subscribe()

        executor.unregister_bot("paper1")

        filled = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-001",
                account_id="acct1",
                bot_id="paper1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="limit",
                price=50000.0,
            )
        )

        assert len(filled) == 0


# ── US-4: StrategyContextFactory ─────────────────


class TestStrategyContextFactory:
    def test_create_paper_context(self, eventbus):
        """Paper 봇 StrategyContext 생성."""
        executor = PaperExecutor(eventbus=eventbus)
        factory = StrategyContextFactory(
            data_provider=FakeDataProvider(),
            paper_executor=executor,
        )

        config = BotConfig(
            bot_id="paper1",
            strategy_id="s1",
        )
        # AccountService 미설정 → VIRTUAL 모드(paper) 기본 동작
        ctx = factory.create(config)

        assert isinstance(ctx, StrategyContext)
        assert ctx.bot_id == "paper1"

        # Paper 봇이 PaperExecutor에 등록되었는지 확인
        assert "paper1" in executor._portfolios

        # Treasury 미설정 시 초기 잔고 0
        balance = ctx.get_balance()
        assert balance["allocated"] == 0.0

    def test_create_live_context(self, eventbus):
        """Live 봇 StrategyContext 생성 (Account.trading_mode=LIVE)."""
        from ante.account.models import Account, TradingMode
        from ante.bot.providers.live import LiveOrderView, LivePortfolioView

        # AccountService mock: get_sync가 LIVE 모드 Account를 반환
        class FakeAccountService:
            def get_sync(self, account_id):
                return Account(
                    account_id=account_id,
                    name="test",
                    exchange="KRX",
                    currency="KRW",
                    trading_mode=TradingMode.LIVE,
                )

        # 가짜 live providers
        class FakeLivePortfolio(LivePortfolioView):
            def __init__(self):
                pass

            def get_positions(self, bot_id):
                return {}

            def get_balance(self, bot_id):
                return {"allocated": 0.0, "available": 0.0, "reserved": 0.0}

        class FakeLiveOrders(LiveOrderView):
            def __init__(self):
                pass

            def get_open_orders(self, bot_id):
                return []

        factory = StrategyContextFactory(
            data_provider=FakeDataProvider(),
            account_service=FakeAccountService(),
            live_portfolio=FakeLivePortfolio(),
            live_order_view=FakeLiveOrders(),
        )

        config = BotConfig(bot_id="live1", strategy_id="s1", account_id="live-acct")
        ctx = factory.create(config)

        assert isinstance(ctx, StrategyContext)
        assert ctx.bot_id == "live1"

    def test_resolve_paper_balance_with_budget(self, eventbus):
        """TreasuryManager 존재 + BotBudget 배정 시 allocated 값 반환."""
        from ante.treasury.models import BotBudget

        class FakeTreasury:
            def get_budget(self, bot_id):
                if bot_id == "paper1":
                    return BotBudget(bot_id="paper1", allocated=2_000_000.0)
                return None

        class FakeTreasuryManager:
            def get(self, account_id):
                return FakeTreasury()

        executor = PaperExecutor(eventbus=eventbus)
        factory = StrategyContextFactory(
            data_provider=FakeDataProvider(),
            paper_executor=executor,
            treasury_manager=FakeTreasuryManager(),
        )

        config = BotConfig(bot_id="paper1", strategy_id="s1", account_id="acct1")
        ctx = factory.create(config)

        balance = ctx.get_balance()
        assert balance["allocated"] == 2_000_000.0

    def test_resolve_paper_balance_key_error(self, eventbus):
        """TreasuryManager 존재하나 bot_id 미배정 시 0.0 반환."""

        class FakeTreasuryManager:
            def get(self, account_id):
                raise KeyError(account_id)

        executor = PaperExecutor(eventbus=eventbus)
        factory = StrategyContextFactory(
            data_provider=FakeDataProvider(),
            paper_executor=executor,
            treasury_manager=FakeTreasuryManager(),
        )

        config = BotConfig(bot_id="paper1", strategy_id="s1", account_id="no-acct")
        ctx = factory.create(config)

        balance = ctx.get_balance()
        assert balance["allocated"] == 0.0

    def test_live_without_providers_raises(self, eventbus):
        """Live providers 미설정 시 에러."""
        from ante.account.models import Account, TradingMode

        class FakeAccountService:
            def get_sync(self, account_id):
                return Account(
                    account_id=account_id,
                    name="test",
                    exchange="KRX",
                    currency="KRW",
                    trading_mode=TradingMode.LIVE,
                )

        factory = StrategyContextFactory(
            data_provider=FakeDataProvider(),
            account_service=FakeAccountService(),
        )
        config = BotConfig(bot_id="live1", strategy_id="s1", account_id="live-acct")

        with pytest.raises(ValueError, match="Provider"):
            factory.create(config)


# ── US-5: BotManager + Factory 통합 ─────────────


class TestBotManagerWithFactory:
    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await database.close()

    async def test_create_bot_with_factory(self, eventbus, db):
        """Factory를 통한 봇 생성 (ctx 미지정)."""
        from ante.bot import BotManager, StrategyContextFactory
        from ante.strategy.base import Strategy, StrategyMeta

        class SimpleStrategy(Strategy):
            meta = StrategyMeta(name="simple", version="1.0.0", description="test")

            async def on_step(self, context):
                return []

        executor = PaperExecutor(eventbus=eventbus)
        factory = StrategyContextFactory(
            data_provider=FakeDataProvider(),
            paper_executor=executor,
        )
        manager = BotManager(eventbus=eventbus, db=db, context_factory=factory)
        await manager.initialize()

        config = BotConfig(
            bot_id="paper1",
            strategy_id="s1",
        )
        bot = await manager.create_bot(config, SimpleStrategy)

        assert bot.bot_id == "paper1"
        assert "paper1" in executor._portfolios

    async def test_create_bot_with_explicit_ctx(self, eventbus, db):
        """기존 방식: ctx 직접 주입."""
        from ante.bot import BotManager
        from ante.strategy.base import Strategy, StrategyMeta

        class SimpleStrategy(Strategy):
            meta = StrategyMeta(name="simple", version="1.0.0", description="test")

            async def on_step(self, context):
                return []

        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()

        ctx = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=PaperPortfolioView(bot_id="bot1", initial_balance=1_000_000.0),
            order_view=PaperOrderView(
                PaperPortfolioView(bot_id="bot1", initial_balance=1_000_000.0)
            ),
        )
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        bot = await manager.create_bot(config, SimpleStrategy, ctx)
        assert bot.bot_id == "bot1"

    async def test_create_bot_no_ctx_no_factory_raises(self, eventbus, db):
        """ctx도 factory도 없으면 에러."""
        from ante.bot import BotError, BotManager
        from ante.strategy.base import Strategy, StrategyMeta

        class SimpleStrategy(Strategy):
            meta = StrategyMeta(name="simple", version="1.0.0", description="test")

            async def on_step(self, context):
                return []

        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()

        config = BotConfig(bot_id="bot1", strategy_id="s1")
        with pytest.raises(BotError, match="factory"):
            await manager.create_bot(config, SimpleStrategy)

    async def test_remove_paper_bot_unregisters(self, eventbus, db):
        """Paper 봇 삭제 시 PaperExecutor에서 등록 해제."""
        from ante.bot import BotManager, StrategyContextFactory
        from ante.strategy.base import Strategy, StrategyMeta

        class SimpleStrategy(Strategy):
            meta = StrategyMeta(name="simple", version="1.0.0", description="test")

            async def on_step(self, context):
                return []

        executor = PaperExecutor(eventbus=eventbus)
        factory = StrategyContextFactory(
            data_provider=FakeDataProvider(),
            paper_executor=executor,
        )
        manager = BotManager(eventbus=eventbus, db=db, context_factory=factory)
        await manager.initialize()

        config = BotConfig(bot_id="paper1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy)
        assert "paper1" in executor._portfolios

        await manager.remove_bot("paper1")
        assert "paper1" not in executor._portfolios


# ── PositionHistory 캐시 테스트 ──────────────────


class TestPositionHistoryCache:
    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await database.close()

    async def test_sync_positions_after_trade(self, db):
        """체결 후 동기 캐시에 포지션 반영."""
        ph = PositionHistory(db=db)
        await ph.initialize()

        from ante.trade.models import TradeRecord, TradeStatus

        record = TradeRecord(
            trade_id="t1",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=50000.0,
            status=TradeStatus.FILLED,
            order_type="market",
        )
        await ph.on_trade(record)

        positions = ph.get_positions_sync("bot1")
        assert len(positions) == 1
        assert positions[0].symbol == "005930"
        assert positions[0].quantity == 10.0

    async def test_sync_positions_empty(self, db):
        """포지션 없으면 빈 목록."""
        ph = PositionHistory(db=db)
        await ph.initialize()

        positions = ph.get_positions_sync("bot1")
        assert positions == []

    async def test_cache_warm_on_init(self, db):
        """초기화 시 DB에서 캐시 워밍."""
        ph1 = PositionHistory(db=db)
        await ph1.initialize()

        from ante.trade.models import TradeRecord, TradeStatus

        record = TradeRecord(
            trade_id="t1",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=50000.0,
            status=TradeStatus.FILLED,
            order_type="market",
        )
        await ph1.on_trade(record)

        # 새 인스턴스로 다시 초기화 → 캐시 워밍
        ph2 = PositionHistory(db=db)
        await ph2.initialize()

        positions = ph2.get_positions_sync("bot1")
        assert len(positions) == 1
        assert positions[0].quantity == 10.0

    async def test_cache_updates_on_sell(self, db):
        """매도 후 포지션이 0이면 캐시에서 제거."""
        ph = PositionHistory(db=db)
        await ph.initialize()

        from ante.trade.models import TradeRecord, TradeStatus

        buy = TradeRecord(
            trade_id="t1",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            price=50000.0,
            status=TradeStatus.FILLED,
            order_type="market",
        )
        await ph.on_trade(buy)

        sell = TradeRecord(
            trade_id="t2",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            price=55000.0,
            status=TradeStatus.FILLED,
            order_type="market",
        )
        await ph.on_trade(sell)

        positions = ph.get_positions_sync("bot1")
        assert positions == []
