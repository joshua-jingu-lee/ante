"""Rule Engine 모듈 단위 테스트."""

from datetime import time

import pytest

from ante.core import Database
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
        strategy_id="momentum_v1",
        symbol="005930",
        side="buy",
        quantity=10.0,
        order_type="market",
        current_price=50000.0,
        current_position=0.0,
        available_balance=1000000.0,
        system_status="active",
        daily_pnl=0.0,
        total_pnl=100000.0,
    )


# ── RuleResult / RuleEvaluation ──────────────────


class TestRuleDataModels:
    def test_rule_result_values(self):
        """RuleResult 값 확인."""
        assert RuleResult.PASS == "pass"
        assert RuleResult.WARN == "warn"
        assert RuleResult.BLOCK == "block"
        assert RuleResult.REJECT == "reject"

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
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
        )
        ctx.current_price = 50000.0
        assert ctx.current_price == 50000.0


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
        base_context.total_pnl = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS

    def test_block_exceeds_limit(self, rule, base_context):
        """손실이 한도 초과하면 BLOCK."""
        base_context.daily_pnl = -10000.0
        base_context.total_pnl = 100000.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.BLOCK
        assert result.action == RuleAction.HALT_SYSTEM

    def test_pass_zero_total_pnl(self, rule, base_context):
        """총 수익이 0이면 통과 (0으로 나누기 방지)."""
        base_context.daily_pnl = -1000.0
        base_context.total_pnl = 0.0
        result = rule.evaluate(base_context)
        assert result.result == RuleResult.PASS


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
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await database.close()

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    async def system_state(self, db, eventbus):
        from ante.config.system_state import SystemState

        state = SystemState(db=db, eventbus=eventbus)
        await state.initialize()
        return state

    @pytest.fixture
    def engine(self, eventbus, system_state):
        return RuleEngine(eventbus=eventbus, system_state=system_state)

    def test_evaluate_no_rules(self, engine, base_context):
        """룰이 없으면 PASS."""
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.PASS
        assert len(result.evaluations) == 0

    def test_evaluate_global_rule_pass(self, engine, base_context):
        """전역 룰 통과."""
        engine.add_global_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05})
        )
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.PASS

    def test_evaluate_global_rule_block(self, engine, base_context):
        """전역 룰 차단 시 전략별 룰은 평가하지 않음."""
        engine.add_global_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05})
        )
        engine.add_strategy_rule(
            "momentum_v1",
            PositionSizeRule("ps", {"max_position_percent": 0.10}),
        )

        base_context.daily_pnl = -10000.0
        base_context.total_pnl = 100000.0
        result = engine.evaluate(base_context)

        assert result.overall_result == RuleResult.BLOCK
        # 전역 룰만 평가됨
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
        engine.add_global_rule(rule_low)
        engine.add_global_rule(rule_high)

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
        engine.add_global_rule(
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
        engine.add_global_rule(rule)
        base_context.daily_pnl = -5000.0
        base_context.total_pnl = 100000.0
        result = engine.evaluate(base_context)
        assert result.overall_result == RuleResult.PASS
        assert len(result.evaluations) == 0


# ── RuleEngine EventBus 통합 ─────────────────────


class TestRuleEngineEventBus:
    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await database.close()

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    async def system_state(self, db, eventbus):
        from ante.config.system_state import SystemState

        state = SystemState(db=db, eventbus=eventbus)
        await state.initialize()
        return state

    @pytest.fixture
    async def engine(self, eventbus, system_state):
        engine = RuleEngine(eventbus=eventbus, system_state=system_state)
        engine.start()
        return engine

    async def test_order_validated_on_pass(self, engine, eventbus):
        """룰 통과 시 OrderValidatedEvent 발행."""
        received = []
        eventbus.subscribe(OrderValidatedEvent, lambda e: received.append(e))

        order = OrderRequestEvent(
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

    async def test_order_rejected_on_block(self, engine, eventbus):
        """룰 차단 시 OrderRejectedEvent 발행."""
        engine.add_global_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.001})
        )

        received = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: received.append(e))

        # 손실 상태를 context에 전달하기 위해 직접 evaluate 방식이 아닌,
        # _on_order_request에서는 기본 context가 생성되므로
        # 전역에서 항상 BLOCK하는 룰을 추가
        # DailyLossLimitRule은 pnl이 0이면 pass하므로, 다른 방식 사용
        # TradingHoursRule로 시간 외 거래 차단
        engine.clear_rules()
        engine.add_global_rule(
            TradingHoursRule(
                "hours",
                {"allowed_hours": "00:00-00:01"},  # 거의 항상 차단
            )
        )

        order = OrderRequestEvent(
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


# ── RuleEngine.update_rules ──────────────────────


class TestRuleEngineUpdateRules:
    """RuleEngine.update_rules() 단위 테스트."""

    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await database.close()

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    async def system_state(self, db, eventbus):
        from ante.config.system_state import SystemState

        state = SystemState(db=db, eventbus=eventbus)
        await state.initialize()
        return state

    @pytest.fixture
    def bot_strategies(self):
        """bot_id → strategy_id 매핑."""
        return {"bot1": "momentum_v1", "bot2": "mean_revert_v1"}

    @pytest.fixture
    def engine(self, eventbus, system_state, bot_strategies):
        return RuleEngine(
            eventbus=eventbus,
            system_state=system_state,
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

    def test_update_rules_no_resolver_raises(self, eventbus, system_state):
        """resolver 미설정 시 RuleError."""
        from ante.rule.exceptions import RuleError

        engine = RuleEngine(eventbus=eventbus, system_state=system_state)
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

    def test_set_bot_strategy_resolver(self, eventbus, system_state):
        """set_bot_strategy_resolver로 resolver를 나중에 설정할 수 있다."""
        engine = RuleEngine(eventbus=eventbus, system_state=system_state)
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
            strategy_id="momentum_v1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            current_price=50000.0,
            available_balance=1_000_000.0,
            system_status="active",
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
