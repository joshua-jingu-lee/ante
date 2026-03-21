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
        account_status="active",
        daily_pnl=0.0,
        total_pnl=100000.0,
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
        ctx = RuleContext()
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
        """손실이 한도 내면 통과 (분모: 전일 총 자산)."""
        base_context.daily_pnl = -3000.0
        base_context.prev_day_total_asset = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_block_exceeds_limit(self, rule, base_context):
        """손실이 한도 초과하면 BLOCK + HALT_ACCOUNT (분모: 전일 총 자산)."""
        base_context.daily_pnl = -10000.0
        base_context.prev_day_total_asset = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.BLOCK
        assert result.action == RuleAction.HALT_ACCOUNT

    def test_pass_zero_prev_day_total_asset(self, rule, base_context):
        """전일 총 자산이 0이면 통과 (0으로 나누기 방지)."""
        base_context.daily_pnl = -1000.0
        base_context.prev_day_total_asset = 0.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_pass_large_asset_small_loss(self, rule, base_context):
        """자산 1억, 손실 50만 -> 0.5% < 5% -> PASS (기존 구현 오탐 검증)."""
        base_context.daily_pnl = -500000.0
        base_context.prev_day_total_asset = 100000000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_block_small_asset_large_loss(self, rule, base_context):
        """자산 100만, 손실 10만 -> 10% > 5% -> BLOCK."""
        base_context.daily_pnl = -100000.0
        base_context.prev_day_total_asset = 1000000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.BLOCK
        assert result.action == RuleAction.HALT_ACCOUNT


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
        """노출이 한도 내면 통과."""
        base_context.quantity = 1.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_exceeds_amount(self, rule, base_context):
        """금액 한도 초과 시 REJECT."""
        base_context.quantity = 20.0  # 20 * 50000 = 1,000,000 > 200,000
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT
        assert result.action == RuleAction.NOTIFY

    def test_reject_exceeds_percent(self, rule, base_context):
        """비율 한도 초과 시 REJECT."""
        base_context.available_balance = 100000.0  # 20% = 20,000
        base_context.quantity = 1.0  # 50,000 > 20,000
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT


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
        base_context.metadata["unrealized_pnl"] = 5000.0
        base_context.metadata["allocated_budget"] = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_reject_buy_exceeds_loss(self, rule, base_context):
        """미실현 손실 한도 초과 + 매수 시 REJECT."""
        base_context.side = "buy"
        base_context.metadata["unrealized_pnl"] = -15000.0
        base_context.metadata["allocated_budget"] = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.REJECT

    def test_pass_sell_exceeds_loss(self, rule, base_context):
        """미실현 손실 한도 초과 + 매도 시 통과 (포지션 정리 허용)."""
        base_context.side = "sell"
        base_context.metadata["unrealized_pnl"] = -15000.0
        base_context.metadata["allocated_budget"] = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS


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

        assert result.overall_result == RuleResult.BLOCK
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
        base_context.total_pnl = 100000.0
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
