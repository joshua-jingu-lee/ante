"""Rule Engine 모듈 단위 테스트."""

from datetime import time
from unittest.mock import AsyncMock

import pytest

from ante.account.models import Account, AccountStatus
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.rule import (
    DailyLossLimitRule,
    PositionSizeRule,
    Rule,
    RuleAction,
    RuleContext,
    RuleEngine,
    RuleEngineManager,
    RuleEvaluation,
    RuleResult,
    TotalExposureLimitRule,
    TradeFrequencyRule,
    TradingHoursRule,
    UnrealizedLossLimitRule,
)

# ── Fixtures ─────────────────────────────────────


@pytest.fixture
def base_context():
    """기본 RuleContext."""
    return RuleContext(
        bot_id="bot1",
        account_id="domestic",
        strategy_id="momentum_v1",
        symbol="005930",
        side="buy",
        quantity=10.0,
        order_type="market",
        current_price=50000.0,
        current_position=0.0,
        available_balance=1000000.0,
        bot_allocated_budget=1000000.0,
        account_status="active",
        daily_pnl=0.0,
        total_pnl=100000.0,
        prev_day_total_asset=100000.0,
    )


@pytest.fixture
def mock_account_service():
    """AccountService 목 객체."""
    service = AsyncMock()
    account = Account(
        account_id="domestic",
        name="국내주식",
        exchange="KRX",
        currency="KRW",
        broker_type="test",
        status=AccountStatus.ACTIVE,
    )
    service.get = AsyncMock(return_value=account)
    service.suspend = AsyncMock()
    return service


# ── RuleResult / RuleEvaluation ──────────────────


class TestRuleDataModels:
    def test_rule_result_values(self):
        """RuleResult 값 확인."""
        assert RuleResult.PASS == "pass"
        assert RuleResult.WARN == "warn"
        assert RuleResult.BLOCK == "block"
        assert RuleResult.REJECT == "reject"

    def test_rule_action_halt_account(self):
        """RuleAction에 HALT_ACCOUNT이 존재한다."""
        assert RuleAction.HALT_ACCOUNT == "halt_account"
        # HALT_SYSTEM은 더 이상 존재하지 않아야 함
        assert not hasattr(RuleAction, "HALT_SYSTEM")

    def test_rule_evaluation_frozen(self):
        """RuleEvaluation은 불변 객체."""
        ev = RuleEvaluation(
            rule_id="r1",
            rule_name="test",
            result=RuleResult.PASS,
            action=RuleAction.LOG,
            message="ok",
        )
        with pytest.raises(AttributeError):
            ev.result = RuleResult.REJECT  # type: ignore[misc]

    def test_rule_context_mutable(self):
        """RuleContext는 가변 객체 (엔진이 필드를 채우므로)."""
        ctx = RuleContext(
            bot_id="b1",
            account_id="domestic",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
        )
        ctx.current_price = 50000.0
        assert ctx.current_price == 50000.0

    def test_rule_context_account_fields(self):
        """RuleContext에 account_id, currency, account_status 필드가 있다."""
        ctx = RuleContext(
            bot_id="b1",
            account_id="domestic",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            currency="KRW",
            account_status="active",
        )
        assert ctx.account_id == "domestic"
        assert ctx.currency == "KRW"
        assert ctx.account_status == "active"

    def test_rule_context_no_system_status(self):
        """RuleContext에 system_status 필드가 없다 (account_status로 대체)."""
        ctx = RuleContext(account_id="acc-test")
        assert not hasattr(ctx, "system_status")
        assert hasattr(ctx, "account_status")


# ── DailyLossLimitRule ───────────────────────────


class TestDailyLossLimitRule:
    @pytest.fixture
    def rule(self):
        return DailyLossLimitRule(
            "daily_loss", {"name": "Daily Loss", "max_daily_loss_percent": 0.05}
        )

    def test_pass_no_loss(self, rule, base_context):
        """손실 없으면 통과."""
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_pass_within_limit(self, rule, base_context):
        """손실이 한도 내면 통과."""
        base_context.daily_pnl = -3000.0
        base_context.prev_day_total_asset = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_buy_exceeds_limit(self, rule, base_context):
        """손실이 한도 초과하면 매수는 REJECT + NOTIFY (매도는 허용)."""
        base_context.daily_pnl = -10000.0
        base_context.prev_day_total_asset = 100000.0
        base_context.side = "buy"
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT
        assert result.action == RuleAction.NOTIFY
        assert result.metadata["prev_day_total_asset"] == 100000.0
        assert "Buy orders blocked" in result.message
        assert "Sell orders are still allowed" in result.message

    def test_pass_sell_during_loss_limit(self, rule, base_context):
        """손실 한도 초과 상태에서도 매도(손절)는 PASS."""
        base_context.daily_pnl = -10000.0
        base_context.prev_day_total_asset = 100000.0
        base_context.side = "sell"
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS
        assert "sell order is allowed" in result.message

    def test_pass_zero_prev_day_total_asset(self, rule, base_context):
        """전일 총 자산이 0이면 통과 (0으로 나누기 방지)."""
        base_context.daily_pnl = -1000.0
        base_context.prev_day_total_asset = 0.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_pass_large_asset_small_loss(self, rule, base_context):
        """자산 1억, 손실 50만 -> 0.5% < 5% -> PASS."""
        base_context.daily_pnl = -500000.0
        base_context.prev_day_total_asset = 100000000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_small_asset_large_loss(self, rule, base_context):
        """자산 100만, 손실 10만 -> 10% > 5% -> REJECT + NOTIFY."""
        base_context.daily_pnl = -100000.0
        base_context.prev_day_total_asset = 1000000.0
        base_context.side = "buy"
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT
        assert result.action == RuleAction.NOTIFY


# ── TotalExposureLimitRule ───────────────────────


class TestTotalExposureLimitRule:
    @pytest.fixture
    def rule(self):
        return TotalExposureLimitRule(
            "exposure",
            {
                "name": "Exposure Limit",
                "max_exposure_percent": 0.20,
                "max_exposure_amount": 500000.0,
            },
        )

    def test_pass_within_limit(self, rule, base_context):
        """노출이 한도 내면 통과 (분모: 총 자산)."""
        base_context.total_asset = 1000000.0  # 총 자산 100만
        base_context.total_exposure = 100000.0  # 전 봇 노출 10만
        base_context.quantity = 1.0  # 주문 5만 -> 합산 15만 < min(50만, 20만) = 20만
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_exceeds_amount(self, rule, base_context):
        """절대 금액 한도 초과 시 REJECT."""
        base_context.total_asset = 10000000.0  # 총 자산 1000만 -> 비율 한도 200만
        base_context.total_exposure = 400000.0  # 전 봇 노출 40만
        base_context.quantity = 3.0  # 주문 15만 -> 합산 55만 > min(50만, 200만) = 50만
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT
        assert result.action == RuleAction.NOTIFY

    def test_reject_exceeds_percent(self, rule, base_context):
        """비율 한도 초과 시 REJECT (분모: 총 자산)."""
        base_context.total_asset = 200000.0  # 총 자산 20만 -> 20% = 4만
        base_context.total_exposure = 30000.0  # 전 봇 노출 3만
        base_context.quantity = 1.0  # 주문 5만 -> 합산 8만 > min(50만, 4만) = 4만
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_pass_zero_total_asset(self, rule, base_context):
        """총 자산이 0이면 PASS (검사 불가)."""
        base_context.total_asset = 0.0
        base_context.total_exposure = 50000.0
        base_context.quantity = 1.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_multi_bot_combined_exposure(self, rule, base_context):
        """다수 봇 합산 노출이 한도 초과 시 REJECT (핵심 버그 검증)."""
        base_context.total_asset = 1000000.0  # 총 자산 100만
        base_context.total_exposure = 180000.0  # 봇 A 9만 + 봇 B 9만 = 18만
        base_context.quantity = 1.0  # 주문 5만 -> 합산 23만 > 20만
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_pass_sell_during_exposure_limit(self, rule, base_context):
        """노출 한도 초과 상태에서도 매도(손절)는 PASS."""
        base_context.total_asset = 1000000.0
        base_context.total_exposure = 180000.0
        base_context.quantity = 1.0
        base_context.side = "sell"
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS
        assert "Sell order is always allowed" in result.message


# ── TradingHoursRule ─────────────────────────────


class TestTradingHoursRule:
    @pytest.fixture
    def rule(self):
        return TradingHoursRule(
            "hours",
            {"name": "Trading Hours", "allowed_hours": "09:00-15:30"},
        )

    def test_pass_during_hours(self, rule, base_context):
        """거래 시간 내면 통과."""
        base_context.metadata["current_time"] = time(10, 0)
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_before_hours(self, rule, base_context):
        """거래 시간 전 차단."""
        base_context.metadata["current_time"] = time(8, 30)
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_reject_after_hours(self, rule, base_context):
        """거래 시간 후 차단."""
        base_context.metadata["current_time"] = time(16, 0)
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_pass_at_boundary(self, rule, base_context):
        """경계 시간 통과."""
        base_context.metadata["current_time"] = time(9, 0)
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

        base_context.metadata["current_time"] = time(15, 30)
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS


# ── PositionSizeRule ─────────────────────────────


class TestPositionSizeRule:
    @pytest.fixture
    def rule(self):
        return PositionSizeRule(
            "pos_size",
            {
                "name": "Position Size",
                "max_position_percent": 0.10,
                "max_position_amount": 200000.0,
            },
        )

    def test_pass_within_limit(self, rule, base_context):
        """포지션이 한도 내면 통과."""
        base_context.quantity = 1.0  # 50,000 < 100,000 (10%)
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_exceeds_limit(self, rule, base_context):
        """포지션이 한도 초과 시 REJECT."""
        base_context.quantity = 5.0  # 250,000 > 100,000
        base_context.current_position = 0.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_includes_existing_position(self, rule, base_context):
        """기존 포지션 포함하여 한도 계산."""
        base_context.quantity = 1.0  # 신규 50,000
        base_context.current_position = 2.0  # 기존 100,000
        # 총 150,000 > 100,000
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_uses_bot_allocated_budget_not_available_balance(self, rule, base_context):
        """분모가 bot_allocated_budget이며 available_balance가 아님을 검증."""
        # available_balance가 크더라도 bot_allocated_budget이 작으면 REJECT
        base_context.available_balance = 10_000_000.0  # 1천만 (큰 값)
        base_context.bot_allocated_budget = 500_000.0  # 50만
        base_context.quantity = 2.0  # 주문가치 100,000
        base_context.current_position = 0.0
        # balance_limit = 500,000 * 0.10 = 50,000
        # position_limit = min(200,000, 50,000) = 50,000
        # total_position_value = 100,000 > 50,000 → REJECT
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_stable_denominator_across_purchases(self, rule, base_context):
        """매수로 가용잔고가 줄어도 bot_allocated_budget은 변하지 않아 비율이 안정적."""
        base_context.bot_allocated_budget = 1_000_000.0
        base_context.available_balance = 200_000.0  # 이미 많이 매수함
        base_context.quantity = 1.0  # 50,000
        base_context.current_position = 0.0
        # balance_limit = 1,000,000 * 0.10 = 100,000
        # position_limit = min(200,000, 100,000) = 100,000
        # total_position_value = 50,000 < 100,000 → PASS
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_zero_budget_skips_percent_check(self, rule, base_context):
        """budget 0이면 limit>0 불충족으로 PASS."""
        base_context.bot_allocated_budget = 0.0
        base_context.quantity = 100.0  # 큰 주문
        result = rule.evaluate(base_context)
        # position_limit = min(200000, 0) = 0
        # total > 0 > 0 → False (0 is not > 0) → PASS
        assert result.result == RuleResult.PASS


# ── UnrealizedLossLimitRule ──────────────────────


class TestUnrealizedLossLimitRule:
    @pytest.fixture
    def rule(self):
        return UnrealizedLossLimitRule(
            "unrealized_loss",
            {
                "name": "Unrealized Loss",
                "max_unrealized_loss_percent": 0.10,
            },
        )

    def test_pass_no_loss(self, rule, base_context):
        """손실 없으면 통과."""
        base_context.unrealized_pnl = 5000.0
        base_context.bot_allocated_budget = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_buy_exceeds_loss(self, rule, base_context):
        """미실현 손실 한도 초과 + 매수 시 REJECT."""
        base_context.side = "buy"
        base_context.unrealized_pnl = -15000.0
        base_context.bot_allocated_budget = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_pass_sell_exceeds_loss(self, rule, base_context):
        """미실현 손실 한도 초과 + 매도 시 통과 (포지션 정리 허용)."""
        base_context.side = "sell"
        base_context.unrealized_pnl = -15000.0
        base_context.bot_allocated_budget = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_pass_loss_within_limit(self, rule, base_context):
        """미실현 손실이 한도 이내면 통과."""
        base_context.side = "buy"
        base_context.unrealized_pnl = -5000.0
        base_context.bot_allocated_budget = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_pass_no_budget(self, rule, base_context):
        """할당 예산이 0이면 비율 계산 불가, 통과."""
        base_context.side = "buy"
        base_context.unrealized_pnl = -15000.0
        base_context.bot_allocated_budget = 0.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_metadata_contains_details(self, rule, base_context):
        """REJECT 시 metadata에 상세 정보 포함."""
        base_context.side = "buy"
        base_context.unrealized_pnl = -15000.0
        base_context.bot_allocated_budget = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT
        assert result.metadata["unrealized_pnl"] == -15000.0
        assert result.metadata["loss_percent"] == pytest.approx(0.15)
        assert result.metadata["limit_percent"] == 0.10


# ── TradeFrequencyRule ───────────────────────────


class TestTradeFrequencyRule:
    @pytest.fixture
    def rule(self):
        return TradeFrequencyRule(
            "frequency",
            {"name": "Frequency", "max_trades_per_hour": 5},
        )

    def test_pass_within_limit(self, rule, base_context):
        """빈도 한도 내면 통과."""
        base_context.metadata["recent_trade_count"] = 3
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_exceeds_limit(self, rule, base_context):
        """빈도 한도 초과 시 REJECT."""
        base_context.metadata["recent_trade_count"] = 5
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_pass_no_metadata(self, rule, base_context):
        """메타데이터 없으면 0으로 간주, 통과."""
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS


# ── RuleEngine ───────────────────────────────────


class TestRuleEngine:
    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def engine(self, eventbus, mock_account_service):
        return RuleEngine(
            eventbus=eventbus,
            account_id="domestic",
            account_service=mock_account_service,
        )

    def test_evaluate_no_rules(self, engine, base_context):
        """룰이 없으면 PASS."""
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.PASS
        assert len(result.evaluations) == 0

    def test_evaluate_account_rule_pass(self, engine, base_context):
        """계좌 룰 통과."""
        engine.add_account_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05})
        )
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.PASS

    def test_evaluate_global_rule_pass(self, engine, base_context):
        """add_global_rule 하위 호환 테스트."""
        engine.add_global_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05})
        )
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.PASS

    def test_evaluate_account_rule_block(self, engine, base_context):
        """계좌 룰 차단 시 전략별 룰은 평가하지 않음."""
        engine.add_account_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05})
        )
        engine.add_strategy_rule(
            "momentum_v1",
            PositionSizeRule("ps", {"max_position_percent": 0.10}),
        )

        base_context.daily_pnl = -10000.0
        base_context.prev_day_total_asset = 100000.0
        result = engine.evaluate(base_context)

        assert result.overall_result == RuleResult.REJECT
        # 계좌 룰만 평가됨
        assert len(result.evaluations) == 1
        assert result.evaluations[0].rule_id == "dl"

    def test_evaluate_strategy_rule_reject(self, engine, base_context):
        """전략별 룰 거부."""
        engine.add_strategy_rule(
            "momentum_v1",
            PositionSizeRule(
                "ps",
                {
                    "max_position_percent": 0.10,
                    "max_position_amount": 200000.0,
                },
            ),
        )
        base_context.quantity = 5.0  # 250,000 > limit
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.REJECT

    def test_evaluate_priority_order(self, engine, base_context):
        """룰은 priority 순서로 평가."""
        rule_low = DailyLossLimitRule(
            "low", {"priority": 10, "max_daily_loss_percent": 0.05}
        )
        rule_high = TradingHoursRule(
            "high", {"priority": 1, "allowed_hours": "09:00-15:30"}
        )
        engine.add_account_rule(rule_low)
        engine.add_account_rule(rule_high)

        base_context.metadata["current_time"] = time(10, 0)
        result = engine.evaluate(base_context)

        assert result.evaluations[0].rule_id == "high"
        assert result.evaluations[1].rule_id == "low"

    def test_load_rules_from_config(self, engine, base_context):
        """설정에서 룰 로드."""
        configs = [
            {
                "type": "daily_loss_limit",
                "id": "dl",
                "max_daily_loss_percent": 0.03,
            },
            {
                "type": "trading_hours",
                "id": "th",
                "allowed_hours": "09:00-15:30",
            },
        ]
        engine.load_rules_from_config(configs)

        base_context.metadata["current_time"] = time(10, 0)
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.PASS
        assert len(result.evaluations) == 2

    def test_load_unknown_rule_type(self, engine):
        """알 수 없는 룰 타입은 무시."""
        engine.load_rules_from_config([{"type": "nonexistent", "id": "x"}])
        assert len(engine._global_rules) == 0

    def test_clear_rules(self, engine):
        """룰 초기화."""
        engine.add_account_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05})
        )
        engine.add_strategy_rule(
            "s1", PositionSizeRule("ps", {"max_position_percent": 0.10})
        )
        engine.clear_rules()
        assert len(engine._global_rules) == 0
        assert len(engine._strategy_rules) == 0

    def test_disabled_rule_skipped(self, engine, base_context):
        """비활성화된 룰은 건너뜀."""
        rule = DailyLossLimitRule(
            "dl",
            {"enabled": False, "max_daily_loss_percent": 0.001},
        )
        engine.add_account_rule(rule)
        base_context.daily_pnl = -5000.0
        base_context.prev_day_total_asset = 100000.0
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.PASS
        assert len(result.evaluations) == 0

    def test_engine_account_id(self, engine):
        """RuleEngine에 account_id가 설정된다."""
        assert engine.account_id == "domestic"

    def test_engine_with_account_service(self, eventbus):
        """AccountService만으로 동작."""
        service = AsyncMock()
        engine = RuleEngine(
            eventbus=eventbus,
            account_id="test",
            account_service=service,
        )
        ctx = RuleContext(
            bot_id="b1",
            account_id="test",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=1.0,
            order_type="market",
        )
        result = engine.evaluate(ctx)
        assert result.overall_result == RuleResult.PASS


# ── RuleEngine EventBus 통합 ─────────────────────


class TestRuleEngineEventBus:
    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    async def engine(self, eventbus, mock_account_service):
        engine = RuleEngine(
            eventbus=eventbus,
            account_id="domestic",
            account_service=mock_account_service,
        )
        engine.start()
        return engine

    async def test_order_validated_on_pass(self, engine, eventbus):
        """룰 통과 시 OrderValidatedEvent 발행."""
        received = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: received.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=50000.0,
        )
        await eventbus.publish(order)

        assert len(received) == 1
        assert received[0].bot_id == "bot1"
        assert received[0].account_id == "domestic"

    async def test_order_rejected_on_block(self, engine, eventbus):
        """룰 차단 시 OrderRejectedEvent 발행."""
        engine.clear_rules()
        engine.add_account_rule(
            TradingHoursRule(
                "hours",
                {"allowed_hours": "00:00-00:01"},  # 거의 항상 차단
            )
        )

        received = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: received.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=50000.0,
        )
        await eventbus.publish(order)

        assert len(received) == 1
        assert "Trading not allowed" in received[0].reason

    async def test_event_filtering_different_account(self, engine, eventbus):
        """다른 account_id의 OrderRequestEvent는 무시한다."""
        received_validated = []
        received_rejected = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: received_validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: received_rejected.append(e))

        # 다른 계좌의 주문
        order = OrderRequestEvent(
            account_id="us-stock",
            bot_id="bot1",
            strategy_id="s1",
            symbol="AAPL",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=150.0,
        )
        await eventbus.publish(order)

        assert len(received_validated) == 0
        assert len(received_rejected) == 0

    async def test_halt_account_action(self, engine, eventbus, mock_account_service):
        """HALT_ACCOUNT 발동 시 AccountService.suspend() 호출."""
        engine.add_account_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.001})
        )

        # context에서 손실을 탐지하도록 metadata 설정
        # DailyLossLimitRule은 context.daily_pnl과 total_pnl로 판단
        # _on_order_request에서 기본 context는 pnl=0이므로,
        # 직접 _execute_actions 테스트
        from ante.eventbus.events import OrderRequestEvent

        event = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=50000.0,
        )
        await engine._execute_actions([RuleAction.HALT_ACCOUNT], event)

        mock_account_service.suspend.assert_awaited_once_with(
            "domestic",
            reason="Critical rule violation",
            suspended_by="rule_engine",
        )

    async def test_rule_engine_rejects_invalid_signal_side(
        self, engine, eventbus, monkeypatch
    ):
        """side가 buy/sell 외 값이면 룰 평가 이전에 거부한다.

        회귀: A7 oracle이 검출한 버그 — Signal.side='hold' 주문이
        RuleEngine을 통과해 Treasury 예약/broker 호출까지 진행되던 결함.
        docs/specs/strategy/03-02-signal-fields.md에 따라 side는
        "buy" | "sell"만 허용된다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        # evaluate / _query_treasury_data가 호출되지 않아야 한다.
        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for invalid side")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError("_query_treasury_data must not run for invalid side")

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="hold",
            quantity=10.0,
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="A7 oracle regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid signal side" in ev.reason
        assert "'hold'" in ev.reason
        assert ev.account_id == "domestic"
        assert ev.bot_id == "bot1"
        assert ev.strategy_id == "s1"
        assert ev.symbol == "005930"
        # OrderRejectedEvent.side는 sqlite TEXT NOT NULL 컬럼에 바인딩되므로
        # 항상 str이어야 한다. 문자열 입력은 그대로 전파된다.
        assert isinstance(ev.side, str)
        assert ev.side == "hold"
        assert ev.quantity == 10.0
        assert ev.price == 1000.0
        assert ev.order_type == "limit"
        assert ev.exchange == "KRX"
        assert ev.order_id == str(order.event_id)

    @pytest.mark.parametrize(
        "bad_side",
        [[], {}, ["buy"], {"buy": True}, set(), 123, None],
        ids=["list-empty", "dict-empty", "list-buy", "dict-buy", "set", "int", "none"],
    )
    async def test_rule_engine_rejects_unhashable_signal_side(
        self, engine, eventbus, monkeypatch, bad_side
    ):
        """비문자열(특히 unhashable) side 값도 fail-closed 거부한다.

        Codex P2 회귀: list/dict 같은 unhashable 타입이 ``event.side``로
        들어오면 ``frozenset`` membership 검사가 ``TypeError: unhashable type``을
        raise해 ``OrderRejectedEvent``가 발행되지 않고 EventBus가 로그만
        남기던 결함. ``isinstance(event.side, str)`` 가드로 차단한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for invalid side")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError("_query_treasury_data must not run for invalid side")

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side=bad_side,  # type: ignore[arg-type]
            quantity=10.0,
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="Codex P2 unhashable-side regression",
        )

        # publish가 TypeError를 leak하지 않고 정상적으로 reject 이벤트를
        # 발행해야 한다 (fail-closed).
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid signal side" in ev.reason
        assert repr(bad_side) in ev.reason
        assert ev.account_id == "domestic"
        assert ev.bot_id == "bot1"
        assert ev.strategy_id == "s1"
        assert ev.symbol == "005930"
        # Codex P2 #2 회귀: 비문자열 side는 TradeRecorder가 sqlite TEXT 컬럼에
        # 바인딩할 수 없으므로 RuleEngine이 repr()로 정규화해야 한다.
        # ([] → "[]", None → "None", 등)
        assert isinstance(ev.side, str)
        assert ev.side == repr(bad_side)
        assert ev.quantity == 10.0
        assert ev.price == 1000.0
        assert ev.order_type == "limit"
        assert ev.exchange == "KRX"
        assert ev.order_id == str(order.event_id)

    async def test_rule_engine_rejects_invalid_order_type(
        self, engine, eventbus, monkeypatch
    ):
        """order_type이 허용 집합 외 값이면 룰 평가 이전에 거부한다.

        회귀(#1298): A7 oracle이 검출한 버그 — Signal.order_type='trail' 주문이
        RuleEngine을 통과해 Treasury 예약 → broker adapter 호출까지 진행되어
        broker 실패 4건이 누적되었다.
        docs/specs/strategy/03-02-signal-fields.md에 따라 order_type은
        "market" | "limit" | "stop" | "stop_limit"만 허용된다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for invalid order_type")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for invalid order_type"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="trail",
            price=1000.0,
            exchange="KRX",
            reason="A7 oracle order_type regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid order type" in ev.reason
        assert "'trail'" in ev.reason
        assert ev.account_id == "domestic"
        assert ev.bot_id == "bot1"
        assert ev.strategy_id == "s1"
        assert ev.symbol == "005930"
        assert ev.side == "buy"
        assert ev.quantity == 10.0
        assert ev.price == 1000.0
        # 입력이 정상 문자열인 경우 그대로 전파
        assert isinstance(ev.order_type, str)
        assert ev.order_type == "trail"
        assert ev.exchange == "KRX"
        assert ev.order_id == str(order.event_id)

    @pytest.mark.parametrize(
        "bad_order_type",
        [[], {}, set(), {"limit": True}, 123, None],
        ids=["list-empty", "dict-empty", "set", "dict-limit", "int", "none"],
    )
    async def test_rule_engine_rejects_unhashable_order_type(
        self, engine, eventbus, monkeypatch, bad_order_type
    ):
        """비문자열(특히 unhashable) order_type 값도 fail-closed 거부한다.

        회귀(#1298): list/dict 같은 unhashable 타입이 ``event.order_type``으로
        들어오면 ``frozenset`` membership 검사가 ``TypeError: unhashable type``을
        raise해 ``OrderRejectedEvent``가 발행되지 않는다. 또한 sqlite TEXT 컬럼에
        바인딩되므로 ``OrderRejectedEvent.order_type``은 항상 str로 정규화돼야
        한다(side 게이트와 동일한 패턴).
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for invalid order_type")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for invalid order_type"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type=bad_order_type,  # type: ignore[arg-type]
            price=1000.0,
            exchange="KRX",
            reason="Codex P2 unhashable-order-type regression",
        )

        # publish가 TypeError를 leak하지 않고 정상적으로 reject 이벤트를
        # 발행해야 한다 (fail-closed).
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid order type" in ev.reason
        assert repr(bad_order_type) in ev.reason
        assert ev.account_id == "domestic"
        assert ev.bot_id == "bot1"
        assert ev.strategy_id == "s1"
        assert ev.symbol == "005930"
        assert ev.side == "buy"
        assert ev.quantity == 10.0
        assert ev.price == 1000.0
        # 비문자열 order_type은 sqlite TEXT 컬럼에 바인딩할 수 없으므로
        # RuleEngine이 repr()로 정규화해야 한다 ([] → "[]", None → "None", 등).
        assert isinstance(ev.order_type, str)
        assert ev.order_type == repr(bad_order_type)
        assert ev.exchange == "KRX"
        assert ev.order_id == str(order.event_id)

    async def test_rule_engine_rejects_cross_field_invalid_payload(
        self, engine, eventbus, monkeypatch
    ):
        """side와 order_type이 동시에 비문자열이어도 reject 이벤트가 깨지지 않는다.

        회귀(#1298 cross-field 보강): #1306 invalid-side 게이트가 먼저 fire하지만,
        이때 ``OrderRejectedEvent.order_type``을 정규화하지 않으면 sqlite TEXT
        바인딩이 실패해 audit trail이 깨진다. 두 필드 모두 ``repr()``로 정규화돼
        ``str``로 발행돼야 한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for invalid payload")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for invalid payload"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side=[],  # type: ignore[arg-type]
            quantity=10.0,
            order_type=[],  # type: ignore[arg-type]
            price=1000.0,
            exchange="KRX",
            reason="Cross-field invalid payload regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        # invalid-side 게이트가 먼저 fire한다.
        assert "Invalid signal side" in ev.reason
        # 두 필드 모두 sqlite TEXT 바인딩 가능한 str이어야 한다.
        assert isinstance(ev.side, str)
        assert ev.side == repr([])  # "[]"
        # cross-field 보강 회귀 잠금: order_type도 정규화돼야 한다.
        assert isinstance(ev.order_type, str)
        assert ev.order_type == repr([])  # "[]"

    async def test_rule_engine_rejects_cross_field_invalid_symbol_payload(
        self, engine, eventbus, monkeypatch
    ):
        """side·order_type·symbol이 동시에 비문자열이어도 reject 이벤트가 깨지지 않는다.

        회귀(#1299 cross-field 보강): invalid-side 게이트가 먼저 fire하지만,
        ``OrderRejectedEvent.symbol``을 정규화하지 않으면 sqlite TEXT 컬럼 바인딩이
        실패해 audit trail이 깨진다. 세 필드 모두 ``repr()``로 정규화돼 ``str``로
        발행돼야 한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for invalid payload")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for invalid payload"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol=[],  # type: ignore[arg-type]
            side=[],  # type: ignore[arg-type]
            quantity=10.0,
            order_type=[],  # type: ignore[arg-type]
            price=1000.0,
            exchange="KRX",
            reason="Cross-field invalid symbol payload regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        # invalid-side 게이트가 먼저 fire한다 (symbol 게이트보다 우선).
        assert "Invalid signal side" in ev.reason
        # 세 필드 모두 sqlite TEXT 바인딩 가능한 str이어야 한다.
        assert isinstance(ev.side, str)
        assert ev.side == repr([])  # "[]"
        assert isinstance(ev.order_type, str)
        assert ev.order_type == repr([])  # "[]"
        # #1299 cross-field 회귀 잠금: symbol도 repr()로 정규화돼야 한다.
        assert isinstance(ev.symbol, str)
        assert ev.symbol == repr([])  # "[]"

    async def test_rule_engine_rejects_invalid_krx_numeric_symbol(
        self, engine, eventbus, monkeypatch
    ):
        """exchange='KRX'에서 6자리 숫자가 아닌 symbol은 룰 평가 이전에 거부한다.

        회귀(#1299): A7 oracle이 검출한 버그 — Signal.symbol='INVALID',
        exchange='KRX' 주문이 RuleEngine→Treasury→broker까지 진행되어
        KIS 40070000(매매불가 종목)이 발생했다. 현재 Ante KIS-domestic 경로는
        6자리 숫자 PDNO만 가정하므로, 그 형식을 만족하지 않는 KRX symbol은
        fail-closed로 거부한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for invalid KRX symbol")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for invalid KRX symbol"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="INVALID",
            side="buy",
            quantity=10.0,
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="A7 oracle KRX symbol regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid KRX numeric symbol" in ev.reason
        assert "'INVALID'" in ev.reason
        assert ev.account_id == "domestic"
        assert ev.bot_id == "bot1"
        assert ev.strategy_id == "s1"
        assert isinstance(ev.symbol, str)
        assert ev.symbol == "INVALID"
        assert ev.side == "buy"
        assert ev.quantity == 10.0
        assert ev.price == 1000.0
        assert ev.order_type == "limit"
        assert ev.exchange == "KRX"
        assert ev.order_id == str(order.event_id)

    @pytest.mark.parametrize(
        "bad_symbol",
        ["12345", "1234567", "05A123", ""],
        ids=["too-short", "too-long", "alpha-mixed", "empty"],
    )
    async def test_rule_engine_rejects_short_or_long_krx_numeric_symbol(
        self, engine, eventbus, monkeypatch, bad_symbol
    ):
        """6자리 숫자가 아닌 KRX symbol은 모두 거부한다 (5자리/7자리/혼용/빈문자열)."""
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for invalid KRX symbol")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for invalid KRX symbol"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol=bad_symbol,
            side="buy",
            quantity=10.0,
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="A7 oracle KRX symbol shape regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid KRX numeric symbol" in ev.reason
        assert isinstance(ev.symbol, str)
        assert ev.symbol == bad_symbol
        assert ev.exchange == "KRX"

    async def test_rule_engine_accepts_valid_krx_numeric_symbol(self, engine, eventbus):
        """6자리 숫자 KRX symbol은 형식 게이트를 통과해 룰 평가 흐름에 진입한다."""
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="069500",  # KODEX 200 ETF
            side="buy",
            quantity=10.0,
            order_type="limit",
            price=30000.0,
            exchange="KRX",
            reason="valid KRX numeric symbol",
        )
        await eventbus.publish(order)

        # 형식 게이트는 통과해야 하므로 KRX-symbol reason의 reject은 없어야 한다.
        # (룰이 비어있으므로 OrderValidatedEvent가 발행돼야 한다.)
        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].symbol == "069500"
        assert validated[0].order_id == str(order.event_id)

    @pytest.mark.parametrize(
        "bad_symbol",
        [[], {}, set(), 123, None],
        ids=["list", "dict", "set", "int", "none"],
    )
    async def test_rule_engine_rejects_unhashable_krx_symbol(
        self, engine, eventbus, monkeypatch, bad_symbol
    ):
        """비문자열 KRX symbol(unhashable 포함)도 fail-closed 거부 + repr() 정규화."""
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for invalid KRX symbol")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for invalid KRX symbol"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol=bad_symbol,  # type: ignore[arg-type]
            side="buy",
            quantity=10.0,
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="Codex P2 unhashable-symbol regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid KRX numeric symbol" in ev.reason
        # OrderRejectedEvent.symbol은 sqlite TEXT NOT NULL 컬럼에 바인딩되므로
        # 항상 str로 정규화돼야 한다 (#1299 cross-field 보강).
        assert isinstance(ev.symbol, str)
        assert ev.symbol == repr(bad_symbol)
        assert ev.exchange == "KRX"

    async def test_rule_engine_skips_symbol_check_for_non_krx_exchange(
        self, engine, eventbus
    ):
        """비-KRX exchange는 symbol 형식 게이트를 스킵하고 broker adapter에 위임한다."""
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        # 다른 account_id로 보내면 _on_order_request 핸들러가 즉시 return하므로,
        # 같은 account_id="domestic"으로 NASDAQ exchange 주문을 보낸다.
        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="AAPL",  # 비-숫자, KRX였다면 거부됐을 것
            side="buy",
            quantity=10.0,
            order_type="limit",
            price=150.0,
            exchange="NASDAQ",
            reason="non-KRX exchange should bypass symbol gate",
        )
        await eventbus.publish(order)

        # KRX symbol 게이트가 스킵되므로 형식 reject은 없어야 한다.
        # (룰이 비어있으므로 룰 평가 후 OrderValidatedEvent가 발행돼야 한다.)
        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].symbol == "AAPL"

    @pytest.mark.parametrize("side", ["buy", "sell"])
    async def test_rule_engine_rejects_limit_order_without_price(
        self, engine, eventbus, monkeypatch, side
    ):
        """order_type='limit'이고 price=None이면 룰 평가 이전에 거부한다.

        회귀(#1300): A7 oracle이 검출한 버그 — Signal.order_type='limit',
        side='sell', price=None 주문이 RuleEngine→Treasury→broker까지 진행되어
        KIS 호출 단계에서 HTTP 500이 발생했다. limit는 가격 지정이 invariant이므로
        fail-closed로 거부한다. side='buy'/'sell' 양쪽에서 동일하게 동작해야 한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for limit order without price")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for limit order without price"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side=side,
            quantity=10.0,
            order_type="limit",
            price=None,
            exchange="KRX",
            reason="A7 oracle limit-without-price regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Missing price" in ev.reason
        assert "limit" in ev.reason
        assert ev.account_id == "domestic"
        assert ev.bot_id == "bot1"
        assert ev.strategy_id == "s1"
        assert ev.symbol == "005930"
        assert ev.side == side
        assert ev.quantity == 10.0
        assert ev.price is None
        assert ev.order_type == "limit"
        assert ev.exchange == "KRX"
        assert ev.order_id == str(order.event_id)

    async def test_rule_engine_rejects_stop_limit_order_without_price(
        self, engine, eventbus, monkeypatch
    ):
        """order_type='stop_limit'이고 price=None이면 룰 평가 이전에 거부한다.

        회귀(#1300): stop_limit도 가격 지정이 invariant이므로 limit와 동일하게
        fail-closed로 거부한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError(
                "evaluate must not run for stop_limit order without price"
            )

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for stop_limit order without price"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop_limit",
            price=None,
            stop_price=49000.0,
            exchange="KRX",
            reason="A7 oracle stop_limit-without-price regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Missing price" in ev.reason
        assert "stop_limit" in ev.reason
        assert ev.symbol == "005930"
        assert ev.side == "sell"
        assert ev.order_type == "stop_limit"
        assert ev.price is None
        assert ev.exchange == "KRX"

    async def test_rule_engine_accepts_market_order_without_price(
        self, engine, eventbus
    ):
        """order_type='market'이고 price=None이면 본 게이트는 통과한다.

        market의 price=None은 스펙상 옵션이므로 RuleEngine 단의 limit/stop_limit
        게이트는 영향이 없어야 한다. (buy market quote=None 처리는 Treasury #1294
        별도 분기 책임이므로 본 단위 테스트는 RuleEngine까지만 검증한다 — Treasury
        미구독 상태이므로 OrderValidatedEvent가 발행돼야 한다.)
        """
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=None,
            exchange="KRX",
            reason="market without price should pass limit/stop_limit gate",
        )
        await eventbus.publish(order)

        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].symbol == "005930"
        assert validated[0].order_type == "market"
        assert validated[0].price is None

    async def test_rule_engine_accepts_limit_order_with_price(self, engine, eventbus):
        """order_type='limit'이고 price가 지정되면 본 게이트를 통과한다."""
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="limit with price should pass gate",
        )
        await eventbus.publish(order)

        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].symbol == "005930"
        assert validated[0].order_type == "limit"
        assert validated[0].price == 1000.0

    @pytest.mark.parametrize("side", ["buy", "sell"])
    async def test_rule_engine_rejects_stop_order_without_stop_price(
        self, engine, eventbus, monkeypatch, side
    ):
        """order_type='stop'이고 stop_price=None이면 룰 평가 이전에 거부한다.

        회귀(#1301): A7 oracle이 검출한 버그 — Signal.order_type='stop',
        side='sell', stop_price=None 주문이 RuleEngine→OrderApproved→
        StopOrderRegistered까지 진행되어 terminal event가 누락되었다.
        stop은 트리거 가격(stop_price) 지정이 invariant이므로 fail-closed로
        거부한다. side='buy'/'sell' 양쪽에서 동일하게 동작해야 한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError(
                "evaluate must not run for stop order without stop_price"
            )

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for stop order without stop_price"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side=side,
            quantity=10.0,
            order_type="stop",
            price=None,
            stop_price=None,
            exchange="KRX",
            reason="A7 oracle stop-without-stop_price regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Missing stop_price" in ev.reason
        assert "stop" in ev.reason
        assert ev.account_id == "domestic"
        assert ev.bot_id == "bot1"
        assert ev.strategy_id == "s1"
        assert ev.symbol == "005930"
        assert ev.side == side
        assert ev.quantity == 10.0
        assert ev.order_type == "stop"
        assert ev.exchange == "KRX"
        assert ev.order_id == str(order.event_id)

    async def test_rule_engine_rejects_stop_limit_order_without_stop_price(
        self, engine, eventbus, monkeypatch
    ):
        """order_type='stop_limit'이고 stop_price=None이면 룰 평가 이전에 거부한다.

        회귀(#1301): stop_limit도 트리거 가격 지정이 invariant이므로 stop와
        동일하게 fail-closed로 거부한다. price는 지정되어 있어 #1300 price
        게이트는 통과하지만, stop_price=None이면 본 게이트에서 거부된다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError(
                "evaluate must not run for stop_limit order without stop_price"
            )

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for stop_limit order "
                "without stop_price"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop_limit",
            price=1000.0,
            stop_price=None,
            exchange="KRX",
            reason="A7 oracle stop_limit-without-stop_price regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Missing stop_price" in ev.reason
        assert "stop_limit" in ev.reason
        assert ev.symbol == "005930"
        assert ev.side == "sell"
        assert ev.order_type == "stop_limit"
        assert ev.price == 1000.0
        assert ev.exchange == "KRX"

    async def test_rule_engine_accepts_stop_order_with_stop_price(
        self, engine, eventbus
    ):
        """order_type='stop'이고 stop_price가 지정되면 본 게이트를 통과한다."""
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            price=None,
            stop_price=950.0,
            exchange="KRX",
            reason="stop with stop_price should pass gate",
        )
        await eventbus.publish(order)

        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].symbol == "005930"
        assert validated[0].order_type == "stop"
        assert validated[0].stop_price == 950.0

    async def test_rule_engine_accepts_market_order_without_stop_price(
        self, engine, eventbus
    ):
        """order_type='market'이고 stop_price=None이면 본 게이트는 통과한다.

        market은 stop_price 게이트 대상이 아니므로 영향이 없어야 한다.
        """
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=None,
            stop_price=None,
            exchange="KRX",
            reason="market without stop_price should pass stop_price gate",
        )
        await eventbus.publish(order)

        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].order_type == "market"
        assert validated[0].stop_price is None

    async def test_rule_engine_accepts_limit_order_without_stop_price(
        self, engine, eventbus
    ):
        """order_type='limit'이고 stop_price=None이면 본 게이트는 통과한다.

        limit은 stop_price 게이트 대상이 아니므로 영향이 없어야 한다.
        price만 지정되어 있으면 #1300 price 게이트도 통과해 OrderValidatedEvent가
        발행된다.
        """
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="limit",
            price=1000.0,
            stop_price=None,
            exchange="KRX",
            reason="limit without stop_price should pass stop_price gate",
        )
        await eventbus.publish(order)

        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].order_type == "limit"
        assert validated[0].price == 1000.0
        assert validated[0].stop_price is None

    async def test_rule_engine_stop_limit_price_gate_fires_before_stop_price_gate(
        self, engine, eventbus, monkeypatch
    ):
        """stop_limit + price=None + stop_price=None이면 #1300 price 게이트가 우선 fire.

        preflight 체인 우선순위 잠금: limit/stop_limit price 게이트(#1300)가
        stop/stop_limit stop_price 게이트(#1301)보다 위에 위치해야 한다.
        reason에 'Missing price'가 포함되고 'Missing stop_price'는 미포함이어야 한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run when price gate fires")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run when price gate fires"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop_limit",
            price=None,
            stop_price=None,
            exchange="KRX",
            reason="stop_limit missing both price and stop_price",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        # price 게이트(#1300)가 우선 fire — stop_price 게이트보다 먼저 거부
        assert "Missing price" in ev.reason
        assert "Missing stop_price" not in ev.reason
        assert ev.order_type == "stop_limit"

    async def test_rule_engine_rejects_nan_quantity(
        self, engine, eventbus, monkeypatch
    ):
        """quantity=NaN이면 룰 평가/Treasury 조회 이전에 거부한다.

        회귀(#1302): A7 oracle이 검출한 버그 — Signal.quantity=NaN, side='buy',
        order_type='limit', price=1000 주문이 RuleEngine→OrderValidatedEvent→
        Treasury 진입 후 sqlite `bot_budgets.available NOT NULL` 위반으로
        실패했다. NaN quantity는 Treasury 예약 호출 이전에 fail-closed로
        거부해야 한다. rejection payload의 quantity는 sqlite REAL NOT NULL
        호환을 위해 0.0으로 정규화된다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []
        unrealized_calls: list[tuple[str, float, str]] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for NaN quantity")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError("_query_treasury_data must not run for NaN quantity")

        async def _spy_unrealized(bot_id, current_price, order_symbol):
            unrealized_calls.append((bot_id, current_price, order_symbol))
            raise AssertionError(
                "_calculate_bot_unrealized_pnl must not run for NaN quantity"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)
        monkeypatch.setattr(engine, "_calculate_bot_unrealized_pnl", _spy_unrealized)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=float("nan"),
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="A7 oracle NaN-quantity regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert unrealized_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid quantity" in ev.reason
        assert "nan" in ev.reason.lower()
        assert ev.account_id == "domestic"
        assert ev.bot_id == "bot1"
        assert ev.strategy_id == "s1"
        assert ev.symbol == "005930"
        assert ev.side == "buy"
        assert ev.order_type == "limit"
        assert ev.price == 1000.0
        assert ev.exchange == "KRX"
        assert ev.order_id == str(order.event_id)
        # rejection payload의 quantity는 sqlite REAL NOT NULL 호환을 위해
        # 0.0으로 정규화된다.
        assert ev.quantity == 0.0

    @pytest.mark.parametrize("bad_quantity", [float("inf"), float("-inf")])
    async def test_rule_engine_rejects_inf_quantity(
        self, engine, eventbus, monkeypatch, bad_quantity
    ):
        """quantity=±inf이면 룰 평가/Treasury 조회 이전에 거부한다."""
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []
        unrealized_calls: list[tuple[str, float, str]] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for inf quantity")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError("_query_treasury_data must not run for inf quantity")

        async def _spy_unrealized(bot_id, current_price, order_symbol):
            unrealized_calls.append((bot_id, current_price, order_symbol))
            raise AssertionError(
                "_calculate_bot_unrealized_pnl must not run for inf quantity"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)
        monkeypatch.setattr(engine, "_calculate_bot_unrealized_pnl", _spy_unrealized)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=bad_quantity,
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="A7 oracle inf-quantity regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert unrealized_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid quantity" in ev.reason
        assert "inf" in ev.reason.lower()
        assert ev.quantity == 0.0
        assert ev.symbol == "005930"
        assert ev.order_type == "limit"

    @pytest.mark.parametrize("bad_quantity", ["10", None, [], True])
    async def test_rule_engine_rejects_non_number_quantity(
        self, engine, eventbus, monkeypatch, bad_quantity
    ):
        """quantity가 number가 아니면 (str/None/list/bool) 룰 평가 이전에 거부한다.

        bool은 isinstance(True, int)==True이므로 명시적으로 거부 대상에 포함한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []
        unrealized_calls: list[tuple[str, float, str]] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for non-number quantity")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for non-number quantity"
            )

        async def _spy_unrealized(bot_id, current_price, order_symbol):
            unrealized_calls.append((bot_id, current_price, order_symbol))
            raise AssertionError(
                "_calculate_bot_unrealized_pnl must not run for non-number quantity"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)
        monkeypatch.setattr(engine, "_calculate_bot_unrealized_pnl", _spy_unrealized)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=bad_quantity,  # type: ignore[arg-type]
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="A7 oracle non-number-quantity regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert unrealized_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid quantity" in ev.reason
        # reason에 repr(bad_quantity)이 포함되어 audit trail에 원시값 보존
        assert repr(bad_quantity) in ev.reason
        # rejection payload의 quantity는 sqlite REAL NOT NULL 호환을 위해
        # 0.0으로 정규화된다.
        assert ev.quantity == 0.0

    async def test_rule_engine_accepts_positive_finite_quantity(self, engine, eventbus):
        """quantity=10.0이면 본 게이트를 통과해 OrderValidatedEvent가 발행된다.

        기존 흐름이 유지됨을 보장하는 회귀 테스트. 본 PR은 NaN/inf/non-number
        quantity만 거부하므로, 양수 finite quantity는 계속 통과해야 한다.
        """
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="positive finite quantity should pass quantity gate",
        )
        await eventbus.publish(order)

        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].quantity == 10.0
        assert validated[0].order_type == "limit"
        assert validated[0].price == 1000.0

    async def test_rule_engine_rejects_overflow_int_quantity(
        self, engine, eventbus, monkeypatch
    ):
        """``float`` 변환 시 ``OverflowError``를 유발하는 거대 ``int`` quantity 거부.

        회귀(#1302 P2): Python ``int``는 임의 정밀도라 ``10**400`` 같은 거대한
        정수는 ``math.isfinite`` (또는 ``math.isnan``/``math.isinf``) 호출 시
        ``float(value)`` 변환에서 ``OverflowError: int too large to convert to
        float``를 던진다. 본 게이트가 ``_on_order_request``의 ``try`` 블록
        밖이라 예외가 EventBus 핸들러까지 leak되면 ``OrderRejectedEvent``가
        발행되지 않아 audit trail이 끊기고 게이트가 fail-open된다.
        ``_is_finite_quantity`` helper 내부에서 ``OverflowError``를 가드하여
        fail-closed reject 경로로 빠지는지 잠근다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []
        unrealized_calls: list[tuple[str, float, str]] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for overflow int quantity")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for overflow int quantity"
            )

        async def _spy_unrealized(bot_id, current_price, order_symbol):
            unrealized_calls.append((bot_id, current_price, order_symbol))
            raise AssertionError(
                "_calculate_bot_unrealized_pnl must not run for overflow int quantity"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)
        monkeypatch.setattr(engine, "_calculate_bot_unrealized_pnl", _spy_unrealized)

        # 10**400은 float(...) 변환 시 OverflowError를 안정적으로 재현한다.
        overflow_quantity = 10**400

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=overflow_quantity,  # type: ignore[arg-type]
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="A7 oracle overflow-int-quantity regression",
        )

        # OverflowError가 EventBus 핸들러까지 leak되면 publish가 예외를 던지므로,
        # 이 호출이 정상 반환되는 것 자체가 게이트가 fail-closed인지 확인하는
        # primary assertion이다.
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert unrealized_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid quantity" in ev.reason
        # rejection payload의 quantity는 sqlite REAL NOT NULL 호환을 위해
        # 0.0으로 정규화된다 (overflow int → 0.0).
        assert ev.quantity == 0.0

    async def test_rule_engine_rejects_nan_price(self, engine, eventbus, monkeypatch):
        """price=NaN이면 룰 평가/Treasury 조회 이전에 거부한다.

        회귀(#1303): A7 oracle이 검출한 버그 — Signal.price=NaN, side='buy',
        order_type='limit', quantity=1 주문이 RuleEngine→OrderValidatedEvent→
        Treasury 진입 후 sqlite NOT NULL 위반으로 실패했다. NaN price는
        Treasury 예약 호출 이전에 fail-closed로 거부해야 한다. rejection
        payload의 price는 ``_coerce_finite_optional_price``로 ``None``으로
        정규화된다 (trades.price REAL nullable 호환).
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []
        unrealized_calls: list[tuple[str, float, str]] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for NaN price")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError("_query_treasury_data must not run for NaN price")

        async def _spy_unrealized(bot_id, current_price, order_symbol):
            unrealized_calls.append((bot_id, current_price, order_symbol))
            raise AssertionError(
                "_calculate_bot_unrealized_pnl must not run for NaN price"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)
        monkeypatch.setattr(engine, "_calculate_bot_unrealized_pnl", _spy_unrealized)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=1.0,
            order_type="limit",
            price=float("nan"),
            exchange="KRX",
            reason="A7 oracle NaN-price regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert unrealized_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid price" in ev.reason
        assert "nan" in ev.reason.lower()
        assert ev.account_id == "domestic"
        assert ev.bot_id == "bot1"
        assert ev.strategy_id == "s1"
        assert ev.symbol == "005930"
        assert ev.side == "buy"
        assert ev.order_type == "limit"
        assert ev.quantity == 1.0
        assert ev.exchange == "KRX"
        assert ev.order_id == str(order.event_id)
        # rejection payload의 price는 trades.price REAL nullable 호환을 위해
        # None으로 정규화된다 (NaN → None via _coerce_finite_optional_price).
        assert ev.price is None

    @pytest.mark.parametrize("bad_price", [float("inf"), float("-inf")])
    async def test_rule_engine_rejects_inf_price(
        self, engine, eventbus, monkeypatch, bad_price
    ):
        """price=±inf이면 룰 평가/Treasury 조회 이전에 거부한다."""
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []
        unrealized_calls: list[tuple[str, float, str]] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for inf price")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError("_query_treasury_data must not run for inf price")

        async def _spy_unrealized(bot_id, current_price, order_symbol):
            unrealized_calls.append((bot_id, current_price, order_symbol))
            raise AssertionError(
                "_calculate_bot_unrealized_pnl must not run for inf price"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)
        monkeypatch.setattr(engine, "_calculate_bot_unrealized_pnl", _spy_unrealized)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=1.0,
            order_type="limit",
            price=bad_price,
            exchange="KRX",
            reason="A7 oracle inf-price regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert unrealized_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid price" in ev.reason
        assert "inf" in ev.reason.lower()
        # builder가 inf price를 None으로 정규화 (trades.price REAL nullable 호환).
        assert ev.price is None
        assert ev.symbol == "005930"
        assert ev.order_type == "limit"

    @pytest.mark.parametrize("bad_price", ["100", [], {}, True, 10**400])
    async def test_rule_engine_rejects_non_number_price(
        self, engine, eventbus, monkeypatch, bad_price
    ):
        """price가 number가 아니면 (str/list/dict/bool/large-int) 거부한다.

        - bool은 isinstance(True, int)==True이므로 명시적으로 거부 대상에 포함.
        - 10**400은 float(...) 변환 시 OverflowError를 유발하는 거대 int.
          ``_is_finite_quantity`` helper의 OverflowError 가드가 동작해
          fail-closed 거부 경로로 빠지는지 함께 잠근다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []
        unrealized_calls: list[tuple[str, float, str]] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError("evaluate must not run for non-number price")

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for non-number price"
            )

        async def _spy_unrealized(bot_id, current_price, order_symbol):
            unrealized_calls.append((bot_id, current_price, order_symbol))
            raise AssertionError(
                "_calculate_bot_unrealized_pnl must not run for non-number price"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)
        monkeypatch.setattr(engine, "_calculate_bot_unrealized_pnl", _spy_unrealized)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=1.0,
            order_type="limit",
            price=bad_price,  # type: ignore[arg-type]
            exchange="KRX",
            reason="A7 oracle non-number-price regression",
        )

        # OverflowError가 EventBus 핸들러까지 leak되면 publish가 예외를 던지므로,
        # 정상 반환되는 것 자체가 fail-closed 잠금 검증 (large-int 케이스).
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert unrealized_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        assert "Invalid price" in ev.reason
        # reason에 repr(bad_price)가 포함되어 audit trail에 원시값 보존
        assert repr(bad_price) in ev.reason
        # rejection payload의 price는 trades.price REAL nullable 호환을 위해
        # None으로 정규화된다 (비-number → None).
        assert ev.price is None

    async def test_rule_engine_accepts_market_with_none_price(self, engine, eventbus):
        """price=None + order_type='market'은 본 게이트를 통과한다.

        market 주문의 price=None은 스펙상 정상이며 #1300 게이트도 limit/stop_limit
        에만 해당한다. 본 PR이 추가하는 NaN/inf 게이트가 ``price is None`` 케이스를
        false-positive로 거부하지 않는지 회귀 잠금.
        """
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=1.0,
            order_type="market",
            price=None,
            exchange="KRX",
            reason="market with None price should pass price gate",
        )
        await eventbus.publish(order)

        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].price is None
        assert validated[0].order_type == "market"

    async def test_rule_engine_accepts_finite_price(self, engine, eventbus):
        """price=1000.0 + order_type='limit'은 본 게이트를 통과한다.

        finite numeric price는 본 PR 게이트의 정상 흐름. limit 주문의 정상
        진행이 깨지지 않는지 회귀 잠금.
        """
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=1.0,
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="finite limit price should pass price gate",
        )
        await eventbus.publish(order)

        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].price == 1000.0
        assert validated[0].order_type == "limit"

    async def test_rule_engine_accepts_market_with_finite_price(self, engine, eventbus):
        """price=1000.0 + order_type='market'은 본 게이트를 통과한다.

        market 주문에 price 값이 함께 실려도 (extra field 거부는 본 PR 비대상)
        finite numeric이면 본 게이트는 통과해야 한다. 회귀 잠금.
        """
        validated: list[OrderValidatedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=1.0,
            order_type="market",
            price=1000.0,
            exchange="KRX",
            reason="market with finite price should pass price gate",
        )
        await eventbus.publish(order)

        assert len(rejected) == 0
        assert len(validated) == 1
        assert validated[0].price == 1000.0
        assert validated[0].order_type == "market"

    @pytest.mark.parametrize(
        ("quantity", "side", "order_type", "price", "stop_price", "expected_reason"),
        [
            # #1300 limit-price 게이트: NaN quantity + price=None
            (
                float("nan"),
                "buy",
                "limit",
                None,
                None,
                "Missing price",
            ),
            # #1298 invalid-order_type 게이트: inf quantity + order_type='trail'
            (
                float("inf"),
                "buy",
                "trail",
                1000.0,
                None,
                "Invalid order type",
            ),
            # #1301 stop_price 게이트: NaN quantity + stop_price=None
            (
                float("nan"),
                "buy",
                "stop",
                None,
                None,
                "Missing stop_price",
            ),
            # #1297 invalid-side 게이트: str quantity + invalid side
            (
                "bad",
                "hold",
                "market",
                None,
                None,
                "Invalid signal side",
            ),
        ],
    )
    async def test_rule_engine_normalizes_nan_quantity_in_cross_field_rejects(
        self,
        engine,
        eventbus,
        monkeypatch,
        quantity,
        side,
        order_type,
        price,
        stop_price,
        expected_reason,
    ):
        """cross-field invalid payload에서 quantity도 0.0으로 정규화된다.

        회귀(#1302 cross-field 보강): 본 PR 이전에는 새 NaN/inf/non-number
        quantity 게이트가 stop_price 게이트(#1301) 직후에 위치했으나, 그보다
        앞선 게이트들(invalid-side / invalid-order_type / invalid-krx-symbol /
        limit-price / stop-price)은 ``OrderRejectedEvent.quantity`` payload에
        ``event.quantity``를 그대로 실어 NaN/inf/str이 ``trades.quantity REAL
        NOT NULL`` 컬럼 바인딩을 깨뜨릴 수 있었다. 모든 reject 경로가 동일한
        ``_coerce_finite_quantity`` helper로 통일됐는지 잠근다.

        각 케이스는 quantity 게이트 도달 전에 다른 게이트가 먼저 fire하므로
        reason은 첫 게이트의 reason을 그대로 유지하고 ('Invalid quantity'가
        아님), quantity만 0.0으로 정규화돼야 한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        # 본 게이트들은 모두 룰 평가/Treasury 조회 이전에 fire하므로
        # 호출되어선 안 된다.
        evaluate_calls: list[object] = []
        treasury_calls: list[str] = []

        def _spy_evaluate(context):
            evaluate_calls.append(context)
            raise AssertionError(
                "evaluate must not run for cross-field invalid payload"
            )

        async def _spy_query_treasury(bot_id: str = ""):
            treasury_calls.append(bot_id)
            raise AssertionError(
                "_query_treasury_data must not run for cross-field invalid payload"
            )

        monkeypatch.setattr(engine, "evaluate", _spy_evaluate)
        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side=side,
            quantity=quantity,  # type: ignore[arg-type]
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            exchange="KRX",
            reason="cross-field quantity normalization regression",
        )
        await eventbus.publish(order)

        assert evaluate_calls == []
        assert treasury_calls == []
        assert len(validated) == 0
        assert len(rejected) == 1

        ev = rejected[0]
        # reason은 cross-field로 먼저 fire한 게이트의 reason을 그대로 유지한다.
        assert expected_reason in ev.reason
        # rejection payload의 quantity는 trades.quantity REAL NOT NULL 호환을
        # 위해 finite float (0.0)로 정규화된다.
        assert isinstance(ev.quantity, float)
        assert ev.quantity == 0.0

    async def test_rule_engine_safe_builder_handles_unrenderable_repr(
        self, engine, eventbus, monkeypatch
    ):
        """``__repr__``가 raise하는 input에서도 fail-closed reject 발행 잠금.

        회귀(#1302 메타 리뷰): preflight 게이트의 ``raise``가 EventBus 핸들러
        예외 swallow에 걸려 ``OrderRejectedEvent`` 미발행 → audit fail-open.
        catch-all ``except``와 ``_build_safe_rejected_event`` (raise하지 않는
        builder)가 receive하는지 검증한다.

        ``Unrenderable.__repr__``가 ``RuntimeError``를 던지는 ``side``를 넣어
        invalid-side 게이트의 ``f"...{_safe_str(event.side)}..."`` reason 조립
        자체가 raise해도 catch-all이 builder로 generic reject를 발행해야 한다.

        ``_safe_str``는 ``repr`` 실패 시 ``"<unrenderable {type}>"`` placeholder
        를 반환하므로 실제로 reason 조립은 raise하지 않는다 — 하지만 test의
        목적은 invariant 보호이므로, ``_safe_str`` 구현이 향후 약화되어도
        catch-all이 잡아내는지 정적으로 확인한다.
        """

        class Unrenderable:
            def __repr__(self) -> str:
                raise RuntimeError("repr deliberately fails")

            def __str__(self) -> str:
                raise RuntimeError("str deliberately fails")

            def __hash__(self) -> int:
                return 0

            def __eq__(self, other: object) -> bool:
                return False

        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        # 본 입력은 invalid-side 게이트에서 fire (frozenset membership에서
        # str 가드로 잠긴 후 reason 조립 단계로 진입).
        bad_side = Unrenderable()

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side=bad_side,  # type: ignore[arg-type]
            quantity=10.0,
            order_type="market",
            exchange="KRX",
            reason="unrenderable repr regression",
        )

        # publish가 정상 반환되는 것 자체가 catch-all 안전망 검증.
        await eventbus.publish(order)

        assert len(validated) == 0
        # 정확히 1건 발행되어야 한다 (게이트 발행 또는 catch-all 발행 중 하나).
        assert len(rejected) == 1
        ev = rejected[0]
        # quantity는 finite float (10.0 → 정규화된 동일 값) 호환.
        assert isinstance(ev.quantity, float)
        # symbol/side/order_type 모두 sqlite TEXT 호환을 위해 str 정규화.
        assert isinstance(ev.symbol, str)
        assert isinstance(ev.side, str)
        assert isinstance(ev.order_type, str)
        # reason은 typed message 또는 generic "preflight error" 어느 쪽이든 OK.
        assert isinstance(ev.reason, str)
        assert ev.reason  # non-empty

    async def test_rule_engine_catch_all_reject_for_synthetic_raise(
        self, engine, eventbus, monkeypatch
    ):
        """preflight 도중 helper가 강제로 raise해도 catch-all이 reject 발행.

        회귀(#1302 메타 리뷰): ``_query_treasury_data``를 monkeypatch로 raise
        하도록 만들어 preflight 게이트 통과 후 evaluate 진입 직전에 강제 예외를
        주입한다. catch-all ``except``가 잡아 ``_build_safe_rejected_event``로
        generic reject를 발행하는지 (audit trail이 fail-closed로 잠기는지)
        검증한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        async def _spy_query_treasury(bot_id: str = ""):
            raise RuntimeError("synthetic preflight failure")

        monkeypatch.setattr(engine, "_query_treasury_data", _spy_query_treasury)

        # 모든 preflight 게이트를 통과하는 정상 입력. evaluate 직전 단계인
        # _query_treasury_data에서 강제 raise → catch-all로 fail-closed.
        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=50000.0,
            exchange="KRX",
            reason="synthetic raise regression",
        )

        # catch-all 안전망이 동작하면 publish가 정상 반환된다.
        await eventbus.publish(order)

        assert len(validated) == 0
        assert len(rejected) == 1
        ev = rejected[0]
        # generic catch-all reason
        assert "preflight error" in ev.reason
        # 모든 sqlite TEXT 컬럼은 str로 정규화돼야 한다.
        assert isinstance(ev.symbol, str)
        assert isinstance(ev.side, str)
        assert isinstance(ev.order_type, str)
        assert isinstance(ev.bot_id, str)
        assert isinstance(ev.strategy_id, str)
        assert isinstance(ev.exchange, str)
        # quantity는 finite float
        assert isinstance(ev.quantity, float)
        assert ev.quantity == 10.0

    @pytest.mark.parametrize(
        ("price", "side", "order_type", "expected_reason"),
        [
            # quantity=NaN 게이트로 fire하면서 price=NaN을 함께 실어 보낸다.
            (float("nan"), "buy", "limit", "Invalid quantity"),
            # invalid-side 게이트로 fire하면서 price=inf를 함께 실어 보낸다.
            (float("inf"), "hold", "market", "Invalid signal side"),
        ],
    )
    async def test_rule_engine_normalizes_nan_price_in_rejected_event(
        self,
        engine,
        eventbus,
        price,
        side,
        order_type,
        expected_reason,
    ):
        """``OrderRejectedEvent.price``의 NaN/inf payload는 ``None``으로 정규화.

        회귀(#1302 P2 #4): 본 PR 이전에는 ``_build_safe_rejected_event``가
        ``price=getattr(event, "price", None)``으로 원본을 그대로 전파했다.
        ``price=float("nan")`` / ``inf``가 reject 이벤트에 그대로 실리면
        ``TradeRecorder``의 ``event.price or 0.0`` 처리(NaN은 truthy)에서
        sqlite ``trades.price REAL`` 컬럼에 NaN이 bind되어 PnL 계산이 깨지고
        본 PR이 보장하려는 reject audit trail도 깨진다.

        cross-field 케이스(quantity 게이트 + invalid price, invalid side +
        invalid price)에서 builder가 ``_coerce_finite_optional_price``로
        ``None`` 정규화를 강제하는지 잠근다. reason은 먼저 fire한 게이트의
        reason을 그대로 유지한다 (price-only 검증은 본 PR 범위 밖이므로
        새 게이트가 fire하면 안 됨).
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side=side,
            quantity=float("nan") if expected_reason == "Invalid quantity" else 10.0,
            order_type=order_type,
            price=price,
            exchange="KRX",
            reason="Codex P2 #4 NaN price regression",
        )
        await eventbus.publish(order)

        assert len(validated) == 0
        assert len(rejected) == 1
        ev = rejected[0]
        assert expected_reason in ev.reason
        # price는 trades.price REAL nullable 컬럼 호환 + TradeRecorder의
        # ``event.price or 0.0`` 처리 안전성을 위해 None으로 정규화돼야 한다.
        assert ev.price is None

    @pytest.mark.parametrize(
        "bad_price",
        [
            [],
            {},
            "100",
            True,
            False,
            object(),
        ],
    )
    async def test_rule_engine_normalizes_non_number_price_in_rejected_event(
        self,
        engine,
        eventbus,
        bad_price,
    ):
        """``OrderRejectedEvent.price``의 비-number payload는 ``None``으로 정규화.

        회귀(#1302 P2 #4): ``list`` (비빈), ``dict``, ``str``, ``bool`` 같은
        비-number truthy 값이 ``event.price``로 들어오면 builder가 그대로
        전파해 ``TradeRecorder``가 sqlite ``trades.price REAL`` 컬럼에 bind
        시도 시 ``InterfaceError``가 발생한다. ``False``/빈 컨테이너 같은
        falsy 비-number도 일관성을 위해 ``None``으로 떨어뜨린다.

        invalid-side 게이트로 fire시켜 reject 경로를 강제하고, builder의
        price 정규화만 단독 검증한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="hold",  # invalid-side 게이트 fire
            quantity=10.0,
            order_type="market",
            price=bad_price,  # type: ignore[arg-type]
            exchange="KRX",
            reason="Codex P2 #4 non-number price regression",
        )
        await eventbus.publish(order)

        assert len(validated) == 0
        assert len(rejected) == 1
        ev = rejected[0]
        assert "Invalid signal side" in ev.reason
        # 비-number는 모두 None으로 정규화돼야 한다.
        assert ev.price is None

    async def test_rule_engine_preserves_finite_price_in_rejected_event(
        self, engine, eventbus
    ):
        """정상 finite ``price`` payload는 ``float``로 보존된다.

        회귀(#1302 P2 #4): builder의 price 정규화가 정상 reject payload까지
        과도하게 ``None``으로 떨어뜨리면 audit trail의 가격 정보가 손실되어
        뒤따르는 PnL/보고 계산이 부정확해진다. quantity=NaN 게이트로 fire한
        cross-field 케이스에서 finite price (1000.0)는 그대로 보존되는지
        잠근다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=float("nan"),  # quantity 게이트 fire
            order_type="limit",
            price=1000.0,
            exchange="KRX",
            reason="Codex P2 #4 finite price preservation regression",
        )
        await eventbus.publish(order)

        assert len(validated) == 0
        assert len(rejected) == 1
        ev = rejected[0]
        assert "Invalid quantity" in ev.reason
        # 정상 finite price는 보존돼야 한다 (정규화의 false-positive 방지).
        assert ev.price == 1000.0
        assert isinstance(ev.price, float)

    async def test_rule_engine_normalizes_overflow_int_price(self, engine, eventbus):
        """``float`` 변환 시 ``OverflowError``를 유발하는 거대 ``int`` price 정규화.

        회귀(#1302 P2 #4): Python ``int``는 임의 정밀도라 ``10**400`` 같은
        거대 정수는 ``math.isfinite`` 호출 시 ``float(value)`` 변환에서
        ``OverflowError``를 던진다. ``_coerce_finite_optional_price`` helper
        가 ``OverflowError``/``ValueError``/``TypeError``를 가드해 ``None``
        으로 떨어뜨리는지 (builder가 절대 raise하지 않는 invariant 유지)
        잠근다. invalid-side 게이트로 fire시켜 reject 경로를 강제한다.
        """
        rejected: list[OrderRejectedEvent] = []
        validated: list[OrderValidatedEvent] = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderValidatedEvent, lambda e: validated.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="hold",  # invalid-side 게이트 fire
            quantity=10.0,
            order_type="market",
            price=10**400,  # type: ignore[arg-type]
            exchange="KRX",
            reason="Codex P2 #4 overflow int price regression",
        )

        # builder가 OverflowError를 leak하면 publish가 raise하므로,
        # 정상 반환되는 것 자체가 fail-closed 잠금 검증.
        await eventbus.publish(order)

        assert len(validated) == 0
        assert len(rejected) == 1
        ev = rejected[0]
        assert "Invalid signal side" in ev.reason
        assert ev.price is None


# ── RuleEngine.update_rules ──────────────────────


class TestRuleEngineUpdateRules:
    """RuleEngine.update_rules() 단위 테스트."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def bot_strategies(self):
        """bot_id → strategy_id 매핑."""
        return {"bot1": "momentum_v1", "bot2": "mean_revert_v1"}

    @pytest.fixture
    def engine(self, eventbus, mock_account_service, bot_strategies):
        return RuleEngine(
            eventbus=eventbus,
            account_id="domestic",
            account_service=mock_account_service,
            bot_strategy_resolver=lambda bid: bot_strategies.get(bid),
        )

    def test_update_rules_replaces_strategy_rules(self, engine):
        """update_rules는 해당 전략의 기존 룰을 교체한다."""
        # 기존 룰 설정
        engine.add_strategy_rule(
            "momentum_v1",
            PositionSizeRule("old_ps", {"max_position_percent": 0.10}),
        )
        assert len(engine._strategy_rules["momentum_v1"]) == 1

        # update_rules로 교체
        new_rules = [
            {
                "type": "position_size",
                "id": "new_ps",
                "max_position_percent": 0.20,
                "max_position_amount": 500000.0,
            },
            {
                "type": "trade_frequency",
                "id": "new_freq",
                "max_trades_per_hour": 10,
            },
        ]
        engine.update_rules("bot1", new_rules)

        assert len(engine._strategy_rules["momentum_v1"]) == 2
        rule_ids = [r.rule_id for r in engine._strategy_rules["momentum_v1"]]
        assert "new_ps" in rule_ids
        assert "new_freq" in rule_ids
        assert "old_ps" not in rule_ids

    def test_update_rules_no_resolver_raises(self, eventbus, mock_account_service):
        """resolver 미설정 시 RuleError."""
        from ante.rule.exceptions import RuleError

        engine = RuleEngine(
            eventbus=eventbus,
            account_id="domestic",
            account_service=mock_account_service,
        )
        with pytest.raises(RuleError, match="bot_strategy_resolver"):
            engine.update_rules("bot1", [])

    def test_update_rules_unknown_bot_raises(self, engine):
        """존재하지 않는 봇이면 RuleError."""
        from ante.rule.exceptions import RuleError

        with pytest.raises(RuleError, match="전략을 찾을 수 없습니다"):
            engine.update_rules("nonexistent", [])

    def test_update_rules_empty_list(self, engine):
        """빈 룰 리스트로 갱신하면 기존 룰이 모두 제거된다."""
        engine.add_strategy_rule(
            "momentum_v1",
            PositionSizeRule("ps", {"max_position_percent": 0.10}),
        )
        engine.update_rules("bot1", [])
        assert engine._strategy_rules["momentum_v1"] == []

    def test_update_rules_does_not_affect_other_strategies(self, engine):
        """다른 전략의 룰에 영향 없음."""
        engine.add_strategy_rule(
            "momentum_v1",
            PositionSizeRule("ps1", {"max_position_percent": 0.10}),
        )
        engine.add_strategy_rule(
            "mean_revert_v1",
            TradeFrequencyRule("freq1", {"max_trades_per_hour": 5}),
        )

        engine.update_rules(
            "bot1",
            [
                {
                    "type": "trade_frequency",
                    "id": "new_freq",
                    "max_trades_per_hour": 20,
                },
            ],
        )

        # bot1의 전략(momentum_v1) 룰은 교체됨
        assert len(engine._strategy_rules["momentum_v1"]) == 1
        assert engine._strategy_rules["momentum_v1"][0].rule_id == "new_freq"

        # bot2의 전략(mean_revert_v1) 룰은 그대로
        assert len(engine._strategy_rules["mean_revert_v1"]) == 1
        assert engine._strategy_rules["mean_revert_v1"][0].rule_id == "freq1"

    def test_set_bot_strategy_resolver(self, eventbus, mock_account_service):
        """set_bot_strategy_resolver로 resolver를 나중에 설정할 수 있다."""
        engine = RuleEngine(
            eventbus=eventbus,
            account_id="domestic",
            account_service=mock_account_service,
        )
        engine.set_bot_strategy_resolver(lambda bid: "strat_a" if bid == "b1" else None)

        engine.update_rules(
            "b1",
            [
                {"type": "position_size", "id": "ps", "max_position_percent": 0.15},
            ],
        )
        assert "strat_a" in engine._strategy_rules
        assert len(engine._strategy_rules["strat_a"]) == 1

    def test_update_rules_evaluate_with_new_rules(self, engine):
        """갱신된 룰이 실제 평가에 반영된다."""
        # 느슨한 룰
        engine.update_rules(
            "bot1",
            [
                {
                    "type": "position_size",
                    "id": "ps",
                    "max_position_percent": 1.0,
                    "max_position_amount": 10_000_000.0,
                },
            ],
        )

        context = RuleContext(
            bot_id="bot1",
            account_id="domestic",
            strategy_id="momentum_v1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            current_price=50000.0,
            available_balance=1_000_000.0,
            bot_allocated_budget=1_000_000.0,
            account_status="active",
        )
        result = engine.evaluate(context)
        assert result.overall_result == RuleResult.PASS

        # 타이트한 룰로 교체
        engine.update_rules(
            "bot1",
            [
                {
                    "type": "position_size",
                    "id": "ps_tight",
                    "max_position_percent": 0.01,
                    "max_position_amount": 10_000.0,
                },
            ],
        )
        result = engine.evaluate(context)
        assert result.overall_result == RuleResult.REJECT


class TestRuleEngineConfigReload:
    """RuleEngine._on_config_changed() 계좌/전략 룰 재로드 테스트."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    async def engine(self, eventbus, mock_account_service):
        engine = RuleEngine(
            eventbus=eventbus,
            account_id="domestic",
            account_service=mock_account_service,
        )
        engine.start()
        return engine

    async def test_global_rule_reload_on_config_changed(self, engine, eventbus):
        """category='global_rule' ConfigChangedEvent 발행 시 계좌 룰이 재로드된다."""
        import json

        from ante.eventbus.events import ConfigChangedEvent

        # 초기 계좌 룰 설정
        engine.load_rules_from_config(
            [{"type": "daily_loss_limit", "id": "dl", "max_daily_loss_percent": 0.05}]
        )
        assert len(engine._global_rules) == 1
        assert engine._global_rules[0].rule_id == "dl"

        # ConfigChangedEvent로 계좌 룰 교체
        new_rules = [
            {"type": "total_exposure_limit", "id": "exp", "max_exposure_percent": 0.20},
            {
                "type": "trading_hours",
                "id": "th",
                "start_time": "09:00",
                "end_time": "15:30",
            },
        ]
        await eventbus.publish(
            ConfigChangedEvent(
                category="global_rule",
                key="rules.global",
                new_value=json.dumps(new_rules),
            )
        )

        assert len(engine._global_rules) == 2
        rule_ids = {r.rule_id for r in engine._global_rules}
        assert rule_ids == {"exp", "th"}
        assert "dl" not in rule_ids

    async def test_rule_category_reload(self, engine, eventbus):
        """category='rule'도 계좌 룰 재로드를 트리거한다."""
        import json

        from ante.eventbus.events import ConfigChangedEvent

        engine.load_rules_from_config(
            [{"type": "daily_loss_limit", "id": "dl", "max_daily_loss_percent": 0.05}]
        )

        new_rules = [
            {
                "type": "total_exposure_limit",
                "id": "exp2",
                "max_exposure_percent": 0.30,
            },
        ]
        await eventbus.publish(
            ConfigChangedEvent(
                category="rule",
                key="rules.global",
                new_value=json.dumps(new_rules),
            )
        )

        assert len(engine._global_rules) == 1
        assert engine._global_rules[0].rule_id == "exp2"

    async def test_strategy_rule_reload_on_config_changed(self, engine, eventbus):
        """category='strategy_rule' ConfigChangedEvent로 전략 룰이 재로드된다."""
        import json

        from ante.eventbus.events import ConfigChangedEvent

        # 초기 전략 룰 설정
        engine.load_strategy_rules_from_config(
            "momentum_v1",
            [{"type": "position_size", "id": "ps", "max_position_percent": 0.10}],
        )
        assert len(engine._strategy_rules["momentum_v1"]) == 1

        # ConfigChangedEvent로 전략 룰 교체
        new_rules = [
            {"type": "trade_frequency", "id": "freq", "max_trades_per_hour": 10},
            {
                "type": "unrealized_loss_limit",
                "id": "ul",
                "max_unrealized_loss_percent": 0.03,
            },
        ]
        await eventbus.publish(
            ConfigChangedEvent(
                category="strategy_rule",
                key="rules.strategy.momentum_v1",
                new_value=json.dumps(new_rules),
            )
        )

        assert len(engine._strategy_rules["momentum_v1"]) == 2
        rule_ids = {r.rule_id for r in engine._strategy_rules["momentum_v1"]}
        assert rule_ids == {"freq", "ul"}

    async def test_config_changed_invalid_json_ignored(self, engine, eventbus):
        """잘못된 JSON new_value는 무시한다."""
        from ante.eventbus.events import ConfigChangedEvent

        engine.load_rules_from_config(
            [{"type": "daily_loss_limit", "id": "dl", "max_daily_loss_percent": 0.05}]
        )

        await eventbus.publish(
            ConfigChangedEvent(
                category="global_rule",
                key="rules.global",
                new_value="not-valid-json{{{",
            )
        )

        # 기존 룰이 유지되어야 한다
        assert len(engine._global_rules) == 1
        assert engine._global_rules[0].rule_id == "dl"

    async def test_config_changed_non_list_ignored(self, engine, eventbus):
        """new_value가 list가 아닌 경우 무시한다."""
        import json

        from ante.eventbus.events import ConfigChangedEvent

        engine.load_rules_from_config(
            [{"type": "daily_loss_limit", "id": "dl", "max_daily_loss_percent": 0.05}]
        )

        await eventbus.publish(
            ConfigChangedEvent(
                category="global_rule",
                key="rules.global",
                new_value=json.dumps({"not": "a list"}),
            )
        )

        # 기존 룰 유지
        assert len(engine._global_rules) == 1

    async def test_config_changed_unrelated_category_ignored(self, engine, eventbus):
        """rule 관련이 아닌 category는 무시한다."""
        import json

        from ante.eventbus.events import ConfigChangedEvent

        engine.load_rules_from_config(
            [{"type": "daily_loss_limit", "id": "dl", "max_daily_loss_percent": 0.05}]
        )

        await eventbus.publish(
            ConfigChangedEvent(
                category="broker",
                key="broker.commission_rate",
                new_value=json.dumps(0.0002),
            )
        )

        # 기존 룰 변경 없음
        assert len(engine._global_rules) == 1
        assert engine._global_rules[0].rule_id == "dl"


# ── RuleEngineManager ────────────────────────────


class TestRuleEngineManager:
    """RuleEngineManager 단위 테스트."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def manager(self, eventbus, mock_account_service):
        return RuleEngineManager(
            eventbus=eventbus, account_service=mock_account_service
        )

    def test_create_engine(self, manager):
        """계좌별 RuleEngine을 생성할 수 있다."""
        engine = manager.create_engine("domestic")
        assert engine.account_id == "domestic"

    def test_create_engine_with_rules(self, manager):
        """룰 설정과 함께 RuleEngine을 생성할 수 있다."""
        configs = [
            {"type": "daily_loss_limit", "id": "dl", "max_daily_loss_percent": 0.05},
        ]
        engine = manager.create_engine("domestic", configs)
        assert len(engine._global_rules) == 1

    def test_get_engine(self, manager):
        """생성된 RuleEngine을 account_id로 조회한다."""
        manager.create_engine("domestic")
        engine = manager.get("domestic")
        assert engine.account_id == "domestic"

    def test_get_engine_not_found(self, manager):
        """존재하지 않는 account_id 조회 시 KeyError."""
        with pytest.raises(KeyError, match="RuleEngine이 존재하지 않습니다"):
            manager.get("nonexistent")

    async def test_initialize_all(self, manager):
        """모든 계좌의 RuleEngine을 초기화한다."""
        accounts = [
            Account(
                account_id="domestic",
                name="국내주식",
                exchange="KRX",
                currency="KRW",
                broker_type="test",
            ),
            Account(
                account_id="us-stock",
                name="미국주식",
                exchange="NYSE",
                currency="USD",
                broker_type="test",
            ),
        ]
        await manager.initialize_all(accounts)

        assert len(manager.engines) == 2
        assert manager.get("domestic").account_id == "domestic"
        assert manager.get("us-stock").account_id == "us-stock"

    def test_multiple_engines_isolation(self, manager):
        """2개 계좌의 RuleEngine이 서로 간섭하지 않는다."""
        engine1 = manager.create_engine("domestic")
        engine2 = manager.create_engine("us-stock")

        engine1.add_account_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05})
        )

        assert len(engine1._global_rules) == 1
        assert len(engine2._global_rules) == 0


# ── RuleEngine Treasury 연동 ────────────────────


class TestRuleEngineTreasuryIntegration:
    """RuleEngine ↔ Treasury 연동 테스트."""

    @pytest.fixture
    def mock_treasury(self):
        """Treasury mock."""
        from unittest.mock import MagicMock

        treasury = MagicMock()
        treasury.get_summary.return_value = {
            "total_profit_loss": 500000.0,
            "total_evaluation": 100000000.0,
            "ante_eval_amount": 20000000.0,
        }
        treasury.get_daily_snapshot = AsyncMock(
            return_value={
                "total_asset": 99000000.0,
            }
        )
        treasury.get_latest_snapshot = AsyncMock(
            return_value={
                "daily_pnl": -300000.0,
            }
        )
        return treasury

    async def test_query_treasury_data(self, mock_treasury):
        """Treasury에서 자산/손익 데이터를 정상 조회."""
        engine = RuleEngine(
            eventbus=EventBus(), treasury=mock_treasury, account_id="acc-test"
        )
        data = await engine._query_treasury_data()
        assert data["total_pnl"] == 500000.0
        assert data["total_asset"] == 100000000.0
        assert data["total_exposure"] == 20000000.0
        assert data["prev_day_total_asset"] == 99000000.0
        assert data["daily_pnl"] == -300000.0

    async def test_query_treasury_data_none(self):
        """Treasury가 None이면 기본값 반환."""
        engine = RuleEngine(eventbus=EventBus(), treasury=None, account_id="acc-test")
        data = await engine._query_treasury_data()
        assert all(v == 0.0 for v in data.values())

    async def test_query_treasury_data_exception(self, mock_treasury):
        """Treasury 조회 실패 시 기본값 fallback."""
        mock_treasury.get_summary.side_effect = Exception("DB error")
        mock_treasury.get_daily_snapshot = AsyncMock(side_effect=Exception("DB error"))
        mock_treasury.get_latest_snapshot = AsyncMock(side_effect=Exception("DB error"))
        engine = RuleEngine(
            eventbus=EventBus(), treasury=mock_treasury, account_id="acc-test"
        )
        data = await engine._query_treasury_data()
        assert all(v == 0.0 for v in data.values())


# ── RuleEngine.start() 시그니처 회귀 테스트 ──────────────


class TestRuleEngineUnrealizedPnl:
    """RuleEngine 미실현 손익 주입 테스트. Refs #783."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def mock_trade_service(self):
        """TradeService 목 객체."""
        from dataclasses import dataclass

        @dataclass
        class FakePosition:
            bot_id: str
            symbol: str
            quantity: float
            avg_entry_price: float
            realized_pnl: float = 0.0

        service = AsyncMock()
        service.get_positions = AsyncMock(
            return_value=[
                FakePosition(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=10.0,
                    avg_entry_price=60000.0,
                ),
            ]
        )
        return service

    @pytest.fixture
    def engine(self, eventbus, mock_account_service, mock_trade_service):
        return RuleEngine(
            eventbus=eventbus,
            account_id="domestic",
            account_service=mock_account_service,
            trade_service=mock_trade_service,
        )

    @pytest.mark.asyncio
    async def test_calculate_unrealized_pnl_with_loss(self, engine, mock_trade_service):
        """보유 종목 현재가 < 평단가일 때 음수 미실현 손익."""
        result = await engine._calculate_bot_unrealized_pnl(
            bot_id="bot1",
            current_price=50000.0,  # 평단가 60000 대비 하락
            order_symbol="005930",
        )
        # (50000 - 60000) * 10 = -100000
        assert result == pytest.approx(-100000.0)

    @pytest.mark.asyncio
    async def test_calculate_unrealized_pnl_with_profit(
        self, engine, mock_trade_service
    ):
        """보유 종목 현재가 > 평단가일 때 양수 미실현 손익."""
        result = await engine._calculate_bot_unrealized_pnl(
            bot_id="bot1",
            current_price=70000.0,
            order_symbol="005930",
        )
        # (70000 - 60000) * 10 = 100000
        assert result == pytest.approx(100000.0)

    @pytest.mark.asyncio
    async def test_calculate_unrealized_pnl_different_symbol(
        self, engine, mock_trade_service
    ):
        """주문 대상과 다른 종목 보유 시 미실현 손익은 0으로 근사."""
        result = await engine._calculate_bot_unrealized_pnl(
            bot_id="bot1",
            current_price=50000.0,
            order_symbol="035720",  # 다른 종목
        )
        assert result == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_calculate_unrealized_pnl_no_trade_service(self, eventbus):
        """TradeService 없으면 0.0 반환."""
        engine = RuleEngine(eventbus=eventbus, account_id="domestic")
        result = await engine._calculate_bot_unrealized_pnl(
            bot_id="bot1",
            current_price=50000.0,
            order_symbol="005930",
        )
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_calculate_unrealized_pnl_exception(self, engine, mock_trade_service):
        """조회 실패 시 0.0 반환."""
        mock_trade_service.get_positions = AsyncMock(
            side_effect=RuntimeError("DB error")
        )
        result = await engine._calculate_bot_unrealized_pnl(
            bot_id="bot1",
            current_price=50000.0,
            order_symbol="005930",
        )
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_order_request_injects_unrealized_pnl(
        self, engine, eventbus, mock_trade_service
    ):
        """OrderRequestEvent 처리 시 context에 unrealized_pnl이 주입된다."""
        # UnrealizedLossLimitRule 추가
        engine.add_strategy_rule(
            "momentum_v1",
            UnrealizedLossLimitRule(
                "ul",
                {
                    "name": "UL",
                    "max_unrealized_loss_percent": 0.05,
                },
            ),
        )
        engine.start()

        # 이벤트 발행 후 결과 확인
        validated = []
        rejected = []

        async def on_validated(event):
            validated.append(event)

        async def on_rejected(event):
            rejected.append(event)

        from ante.eventbus.events import (
            OrderRejectedEvent,
            OrderRequestEvent,
            OrderValidatedEvent,
        )

        eventbus.subscribe(OrderValidatedEvent, on_validated)
        eventbus.subscribe(OrderRejectedEvent, on_rejected)

        # 현재가 50000, 평단가 60000 → 미실현 -100000
        # 봇 예산 조회를 위한 Treasury 설정 없음 → bot_allocated_budget=0
        # allocated_budget=0이면 룰 통과
        await eventbus.publish(
            OrderRequestEvent(
                account_id="domestic",
                bot_id="bot1",
                strategy_id="momentum_v1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50000.0,
                order_type="limit",
            )
        )

        # budget=0이므로 룰 통과
        assert len(validated) == 1


class TestRuleEngineStartSync:
    """RuleEngine.start()가 sync 메서드임을 보장하는 회귀 테스트. Refs #742."""

    def test_start_is_sync(self):
        """start()는 coroutine이 아닌 일반 동기 메서드여야 한다."""
        import asyncio
        import inspect

        assert not inspect.iscoroutinefunction(RuleEngine.start), (
            "RuleEngine.start()는 sync 메서드여야 합니다 (스펙 일치)"
        )

        # 실제 호출 시 coroutine을 반환하지 않음을 확인
        engine = RuleEngine(eventbus=EventBus(), account_id="acc-test")
        result = engine.start()
        assert not asyncio.iscoroutine(result), (
            "start() 호출 결과가 coroutine이면 안 됩니다"
        )

    def test_start_subscribes_events(self):
        """start() 호출 후 EventBus에 핸들러가 등록된다."""
        eventbus = EventBus()
        engine = RuleEngine(eventbus=eventbus, account_id="test")
        engine.start()

        # subscribe가 등록되었는지 간접 확인:
        # OrderRequestEvent 핸들러가 있어야 한다
        from ante.eventbus.events import OrderRequestEvent

        handlers = eventbus._handlers.get(OrderRequestEvent, [])
        assert len(handlers) >= 1, (
            "start() 후 OrderRequestEvent 핸들러가 등록되어야 합니다"
        )


# ── TradingHoursRule: 계좌별 거래시간 컨텍스트 주입 (#781) ────


class TestTradingHoursRuleContextFields:
    """TradingHoursRule이 RuleContext의 trading_hours 필드를 사용하는지 검증."""

    def test_context_fields_override_config(self, base_context):
        """context 필드가 config의 allowed_hours보다 우선한다."""
        rule = TradingHoursRule(
            "hours",
            {"name": "Trading Hours", "allowed_hours": "09:00-15:30"},
        )
        # 계좌가 08:00~16:00 거래 시간 설정
        base_context.trading_hours_start = "08:00"
        base_context.trading_hours_end = "16:00"
        base_context.metadata["current_time"] = time(8, 30)

        result = rule.evaluate(base_context)
        # config는 09:00-15:30이지만 context가 08:00-16:00이므로 통과
        assert result.result == RuleResult.PASS

    def test_context_fields_reject_outside(self, base_context):
        """context 필드의 거래시간 밖이면 차단."""
        rule = TradingHoursRule(
            "hours",
            {"name": "Trading Hours", "allowed_hours": "09:00-15:30"},
        )
        # 계좌가 10:00~14:00 으로 좁은 거래 시간 설정
        base_context.trading_hours_start = "10:00"
        base_context.trading_hours_end = "14:00"
        base_context.metadata["current_time"] = time(9, 30)

        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_default_context_fields_with_config_allowed_hours(self, base_context):
        """context가 기본값이면 config의 allowed_hours가 사용된다."""
        rule = TradingHoursRule(
            "hours",
            {"name": "Trading Hours", "allowed_hours": "10:00-14:00"},
        )
        # context 필드는 기본값 (09:00, 15:30)
        base_context.metadata["current_time"] = time(9, 30)

        result = rule.evaluate(base_context)
        # config의 10:00-14:00이 적용되어 09:30은 차단
        assert result.result == RuleResult.REJECT

    def test_different_accounts_different_hours(self, base_context):
        """서로 다른 계좌의 거래시간이 독립적으로 적용된다."""
        rule = TradingHoursRule("hours", {"name": "Trading Hours"})

        # 국내 계좌: 09:00-15:30
        base_context.trading_hours_start = "09:00"
        base_context.trading_hours_end = "15:30"
        base_context.metadata["current_time"] = time(10, 0)
        result_kr = rule.evaluate(base_context)
        assert result_kr.result == RuleResult.PASS

        # 미국 계좌: 22:30-05:00 (단순화하여 22:30-23:59 테스트)
        base_context.trading_hours_start = "22:30"
        base_context.trading_hours_end = "23:59"
        base_context.metadata["current_time"] = time(10, 0)
        result_us = rule.evaluate(base_context)
        assert result_us.result == RuleResult.REJECT

        base_context.metadata["current_time"] = time(23, 0)
        result_us2 = rule.evaluate(base_context)
        assert result_us2.result == RuleResult.PASS

    def test_rule_context_has_trading_hours_fields(self):
        """RuleContext에 trading_hours 필드가 존재하고 기본값이 올바르다."""
        ctx = RuleContext(account_id="acc-test")
        assert ctx.trading_hours_start == "09:00"
        assert ctx.trading_hours_end == "15:30"
        assert ctx.timezone == "Asia/Seoul"

    def test_context_timezone_field(self, base_context):
        """context의 timezone 필드가 TradingHoursRule에 전달된다."""
        rule = TradingHoursRule("hours", {"name": "Trading Hours"})
        base_context.trading_hours_start = "09:00"
        base_context.trading_hours_end = "15:30"
        base_context.timezone = "US/Eastern"
        base_context.metadata["current_time"] = time(10, 0)

        result = rule.evaluate(base_context)
        # current_time이 직접 주입되어 timezone은 실제 시각 조회에만 영향
        # 09:00-15:30 범위 내이므로 통과
        assert result.result == RuleResult.PASS


# ── WARN 경로 단위 테스트 (#806) ─────────────────────


class _WarnRule(Rule):
    """테스트용 WARN 반환 룰."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.WARN,
            action=RuleAction.NOTIFY,
            message="Warning threshold reached",
        )


class TestRuleEngineWarnPath:
    """RuleEngine WARN 결과 경로 테스트. Refs #806."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def engine(self, eventbus, mock_account_service):
        return RuleEngine(
            eventbus=eventbus,
            account_id="domestic",
            account_service=mock_account_service,
        )

    def test_warn_rule_returns_warn_evaluation(self, base_context):
        """_WarnRule이 WARN 결과를 반환한다."""
        rule = _WarnRule("warn_test", {"name": "Warn Test"})
        evaluation = rule.evaluate(base_context)
        assert evaluation.result == RuleResult.WARN
        assert evaluation.action == RuleAction.NOTIFY

    def test_engine_evaluate_warn_overall(self, engine, base_context):
        """WARN 룰만 있으면 overall_result가 WARN이다."""
        engine.add_account_rule(_WarnRule("w1", {"name": "Warn1"}))
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.WARN

    def test_warn_included_in_evaluations(self, engine, base_context):
        """WARN 결과가 EvaluationResult.evaluations에 포함된다."""
        engine.add_account_rule(_WarnRule("w1", {"name": "Warn1"}))
        result = engine.evaluate(base_context)
        assert len(result.evaluations) == 1
        assert result.evaluations[0].result == RuleResult.WARN
        assert result.evaluations[0].rule_id == "w1"

    def test_warn_no_rejection_reason(self, engine, base_context):
        """WARN은 rejection_reason을 설정하지 않는다."""
        engine.add_account_rule(_WarnRule("w1", {"name": "Warn1"}))
        result = engine.evaluate(base_context)
        assert result.rejection_reason == ""

    def test_warn_actions_collected(self, engine, base_context):
        """WARN 룰의 action(NOTIFY)이 actions 목록에 포함된다."""
        engine.add_account_rule(_WarnRule("w1", {"name": "Warn1"}))
        result = engine.evaluate(base_context)
        assert RuleAction.NOTIFY in result.actions

    def test_warn_with_pass_overall_warn(self, engine, base_context):
        """PASS + WARN 조합 시 overall은 WARN이다."""
        engine.add_account_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05})
        )
        engine.add_account_rule(_WarnRule("w1", {"name": "Warn1", "priority": 10}))
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.WARN
        assert len(result.evaluations) == 2

    def test_multiple_warns(self, engine, base_context):
        """다수 WARN 룰 시 overall은 WARN, 모든 evaluation 포함."""
        engine.add_account_rule(_WarnRule("w1", {"name": "Warn1"}))
        engine.add_account_rule(_WarnRule("w2", {"name": "Warn2", "priority": 5}))
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.WARN
        assert len(result.evaluations) == 2
        warn_ids = {e.rule_id for e in result.evaluations}
        assert warn_ids == {"w1", "w2"}


class TestRuleEngineWarnEventBus:
    """WARN 경로의 EventBus 이벤트 발행 테스트. Refs #806."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    async def engine(self, eventbus, mock_account_service):
        engine = RuleEngine(
            eventbus=eventbus,
            account_id="domestic",
            account_service=mock_account_service,
        )
        engine.add_account_rule(_WarnRule("w1", {"name": "Warn1"}))
        engine.start()
        return engine

    async def test_warn_publishes_order_validated(self, engine, eventbus):
        """WARN 시 OrderValidatedEvent가 발행된다."""
        received = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: received.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=50000.0,
        )
        await eventbus.publish(order)

        assert len(received) == 1
        assert received[0].bot_id == "bot1"
        assert received[0].account_id == "domestic"

    async def test_warn_does_not_publish_rejected(self, engine, eventbus):
        """WARN 시 OrderRejectedEvent는 발행되지 않는다."""
        rejected = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=50000.0,
        )
        await eventbus.publish(order)

        assert len(rejected) == 0

    async def test_warn_publishes_notification(self, engine, eventbus):
        """WARN 시 NotificationEvent(level='warning')가 발행된다."""
        from ante.eventbus.events import NotificationEvent

        notifications = []
        eventbus.subscribe(NotificationEvent, lambda e: notifications.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=50000.0,
        )
        await eventbus.publish(order)

        assert len(notifications) == 1
        assert notifications[0].level == "warning"
        assert "Warning threshold reached" in notifications[0].title

    async def test_warn_multiple_notifications(self, engine, eventbus):
        """다수 WARN 룰 시 각 WARN마다 NotificationEvent가 발행된다."""
        from ante.eventbus.events import NotificationEvent

        engine.add_account_rule(_WarnRule("w2", {"name": "Warn2", "priority": 10}))

        notifications = []
        eventbus.subscribe(NotificationEvent, lambda e: notifications.append(e))

        order = OrderRequestEvent(
            account_id="domestic",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            price=50000.0,
        )
        await eventbus.publish(order)

        assert len(notifications) == 2
