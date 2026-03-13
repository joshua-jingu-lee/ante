"""수수료 계산 체계 테스트."""

import pytest

from ante.broker.models import CommissionInfo
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderFilledEvent
from ante.treasury import Treasury

# ── US-1: CommissionInfo 모델 ─────────────────────


class TestCommissionInfo:
    def test_defaults(self):
        """기본 수수료율."""
        info = CommissionInfo()
        assert info.commission_rate == 0.00015
        assert info.sell_tax_rate == 0.0023

    def test_custom_rates(self):
        """커스텀 수수료율."""
        info = CommissionInfo(commission_rate=0.0001, sell_tax_rate=0.0018)
        assert info.commission_rate == 0.0001
        assert info.sell_tax_rate == 0.0018

    def test_frozen(self):
        """불변 객체."""
        info = CommissionInfo()
        with pytest.raises(AttributeError):
            info.commission_rate = 0.001  # type: ignore[misc]


class TestCommissionCalculation:
    def test_buy_commission(self):
        """매수 수수료: filled_value × commission_rate."""
        info = CommissionInfo(commission_rate=0.00015, sell_tax_rate=0.0023)
        commission = info.calculate("buy", 1_000_000.0)
        assert commission == pytest.approx(150.0)

    def test_sell_commission_includes_tax(self):
        """매도 수수료: filled_value × (commission_rate + sell_tax_rate)."""
        info = CommissionInfo(commission_rate=0.00015, sell_tax_rate=0.0023)
        commission = info.calculate("sell", 1_000_000.0)
        expected = 1_000_000.0 * (0.00015 + 0.0023)
        assert commission == pytest.approx(expected)

    def test_sell_commission_higher_than_buy(self):
        """매도 수수료가 매수보다 높다."""
        info = CommissionInfo()
        buy_fee = info.calculate("buy", 1_000_000.0)
        sell_fee = info.calculate("sell", 1_000_000.0)
        assert sell_fee > buy_fee

    def test_zero_amount(self):
        """0원 체결 → 수수료 0."""
        info = CommissionInfo()
        assert info.calculate("buy", 0.0) == 0.0
        assert info.calculate("sell", 0.0) == 0.0

    def test_kosdaq_tax_rate(self):
        """코스닥 세율 적용 (0.0018)."""
        info = CommissionInfo(commission_rate=0.00015, sell_tax_rate=0.0018)
        commission = info.calculate("sell", 1_000_000.0)
        expected = 1_000_000.0 * (0.00015 + 0.0018)
        assert commission == pytest.approx(expected)


# ── US-1: KISAdapter.get_commission_info ──────────


class TestKISCommissionInfo:
    def test_kis_default_commission(self):
        """KISAdapter 기본 수수료율."""
        from ante.broker.kis import KISAdapter

        adapter = KISAdapter.__new__(KISAdapter)
        adapter._commission_rate = 0.00015
        adapter._sell_tax_rate = 0.0023

        info = adapter.get_commission_info()
        assert info.commission_rate == 0.00015
        assert info.sell_tax_rate == 0.0023

    def test_kis_custom_commission_from_config(self):
        """KISAdapter config에서 수수료율 읽기."""
        from ante.broker.kis import KISAdapter

        adapter = KISAdapter.__new__(KISAdapter)
        adapter._commission_rate = 0.0001
        adapter._sell_tax_rate = 0.0018

        info = adapter.get_commission_info()
        assert info.commission_rate == 0.0001
        assert info.sell_tax_rate == 0.0018


# ── US-2: PaperExecutor 매도 세금 반영 ────────────


class TestPaperExecutorCommission:
    async def test_buy_commission(self):
        """PaperExecutor 매수 수수료 = commission_rate만 적용."""
        from ante.bot.providers.paper import PaperExecutor, PaperPortfolioView

        eventbus = EventBus()
        executor = PaperExecutor(
            eventbus=eventbus,
            commission_rate=0.00015,
            sell_tax_rate=0.0023,
        )

        portfolio = PaperPortfolioView(bot_id="bot1", initial_balance=10_000_000.0)
        executor.register_bot("bot1", portfolio)
        executor.subscribe()

        received: list[OrderFilledEvent] = []
        eventbus.subscribe(OrderFilledEvent, lambda e: received.append(e))

        from ante.eventbus.events import OrderRequestEvent

        await eventbus.publish(
            OrderRequestEvent(
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="limit",
                price=50_000.0,
            )
        )

        assert len(received) == 1
        filled_value = 50_000.0 * 10.0
        expected_commission = filled_value * 0.00015
        assert received[0].commission == pytest.approx(expected_commission)

    async def test_sell_commission_includes_tax(self):
        """PaperExecutor 매도 수수료 = commission_rate + sell_tax_rate."""
        from ante.bot.providers.paper import PaperExecutor, PaperPortfolioView

        eventbus = EventBus()
        executor = PaperExecutor(
            eventbus=eventbus,
            commission_rate=0.00015,
            sell_tax_rate=0.0023,
        )

        portfolio = PaperPortfolioView(bot_id="bot1", initial_balance=10_000_000.0)
        # 먼저 보유 포지션 설정
        portfolio._positions["005930"] = {
            "quantity": 100.0,
            "avg_entry_price": 50_000.0,
            "realized_pnl": 0.0,
        }
        executor.register_bot("bot1", portfolio)
        executor.subscribe()

        received: list[OrderFilledEvent] = []
        eventbus.subscribe(OrderFilledEvent, lambda e: received.append(e))

        from ante.eventbus.events import OrderRequestEvent

        await eventbus.publish(
            OrderRequestEvent(
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="limit",
                price=55_000.0,
            )
        )

        assert len(received) == 1
        filled_value = 55_000.0 * 10.0
        expected_commission = filled_value * (0.00015 + 0.0023)
        assert received[0].commission == pytest.approx(expected_commission)


# ── US-3: 설정 기본값 ────────────────────────────


class TestCommissionDefaults:
    def test_defaults_include_commission_rate(self):
        """config/defaults.py에 broker.commission_rate 포함."""
        from ante.config.defaults import DEFAULTS

        assert "broker.commission_rate" in DEFAULTS
        assert DEFAULTS["broker.commission_rate"] == 0.00015

    def test_defaults_include_sell_tax_rate(self):
        """config/defaults.py에 broker.sell_tax_rate 포함."""
        from ante.config.defaults import DEFAULTS

        assert "broker.sell_tax_rate" in DEFAULTS
        assert DEFAULTS["broker.sell_tax_rate"] == 0.0023


# ── US-4: Treasury 수수료 추정 통합 ──────────────


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return EventBus()


class TestTreasuryCommission:
    async def test_treasury_accepts_sell_tax_rate(self, db, eventbus):
        """Treasury가 sell_tax_rate 파라미터를 수용."""
        t = Treasury(
            db=db,
            eventbus=eventbus,
            commission_rate=0.00015,
            sell_tax_rate=0.0023,
        )
        await t.initialize()
        assert t.commission_rate == 0.00015
        assert t.sell_tax_rate == 0.0023

    async def test_treasury_default_sell_tax_rate(self, db, eventbus):
        """Treasury 기본 sell_tax_rate = 0.0023."""
        t = Treasury(db=db, eventbus=eventbus)
        await t.initialize()
        assert t.sell_tax_rate == 0.0023

    async def test_update_commission_rates(self, db, eventbus):
        """수수료율 동적 업데이트."""
        t = Treasury(db=db, eventbus=eventbus)
        await t.initialize()

        t.update_commission_rates(0.0001, 0.0018)
        assert t.commission_rate == 0.0001
        assert t.sell_tax_rate == 0.0018

    async def test_buy_reservation_uses_commission_rate(self, db, eventbus):
        """매수 예약 시 commission_rate 사용."""
        from ante.eventbus.events import OrderApprovedEvent, OrderValidatedEvent

        t = Treasury(
            db=db,
            eventbus=eventbus,
            commission_rate=0.001,  # 높은 수수료율로 테스트
            sell_tax_rate=0.0023,
        )
        await t.initialize()
        await t.set_account_balance(10_000_000.0)
        await t.allocate("bot1", 5_000_000.0)

        received = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50_000.0,
                order_type="market",
            )
        )

        assert len(received) == 1
        # reserved_amount = 10*50000 * (1 + 0.001) = 500,500
        assert received[0].reserved_amount == pytest.approx(500_500.0)
