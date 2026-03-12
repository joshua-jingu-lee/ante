"""RuleEngine — 2계층 룰 평가 엔진."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.rule.base import (
    EvaluationResult,
    Rule,
    RuleAction,
    RuleContext,
    RuleEvaluation,
    RuleResult,
)
from ante.rule.global_rules import (
    DailyLossLimitRule,
    TotalExposureLimitRule,
    TradingHoursRule,
)
from ante.rule.strategy_rules import (
    PositionSizeRule,
    TradeFrequencyRule,
    UnrealizedLossLimitRule,
)

if TYPE_CHECKING:
    from ante.config.system_state import SystemState
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

# 룰 타입 → 클래스 매핑
RULE_REGISTRY: dict[str, type[Rule]] = {
    "daily_loss_limit": DailyLossLimitRule,
    "total_exposure_limit": TotalExposureLimitRule,
    "trading_hours": TradingHoursRule,
    "position_size": PositionSizeRule,
    "unrealized_loss_limit": UnrealizedLossLimitRule,
    "trade_frequency": TradeFrequencyRule,
}


class RuleEngine:
    """2계층 룰 평가 엔진.

    전역 룰(모든 봇)과 전략별 룰을 순차 평가하여
    OrderRequestEvent를 승인/거부한다.
    """

    def __init__(
        self,
        eventbus: EventBus,
        system_state: SystemState,
    ) -> None:
        self._eventbus = eventbus
        self._system_state = system_state

        self._global_rules: list[Rule] = []
        self._strategy_rules: dict[str, list[Rule]] = {}

    async def start(self) -> None:
        """EventBus 구독 등록."""
        from ante.eventbus.events import ConfigChangedEvent, OrderRequestEvent

        self._eventbus.subscribe(
            OrderRequestEvent, self._on_order_request, priority=100
        )
        self._eventbus.subscribe(ConfigChangedEvent, self._on_config_changed)
        logger.info("RuleEngine 시작")

    # ── 룰 관리 ─────────────────────────────────────

    def add_global_rule(self, rule: Rule) -> None:
        """전역 룰 추가."""
        self._global_rules.append(rule)
        self._global_rules.sort(key=lambda r: r.priority)

    def add_strategy_rule(self, strategy_id: str, rule: Rule) -> None:
        """전략별 룰 추가."""
        if strategy_id not in self._strategy_rules:
            self._strategy_rules[strategy_id] = []
        self._strategy_rules[strategy_id].append(rule)
        self._strategy_rules[strategy_id].sort(key=lambda r: r.priority)

    def clear_rules(self) -> None:
        """모든 룰 제거."""
        self._global_rules.clear()
        self._strategy_rules.clear()

    def load_rules_from_config(self, rule_configs: list[dict[str, Any]]) -> None:
        """룰 설정 리스트에서 전역 룰 인스턴스 생성."""
        for cfg in rule_configs:
            rule = self._create_rule(cfg)
            if rule is not None:
                self._global_rules.append(rule)
        self._global_rules.sort(key=lambda r: r.priority)

    def load_strategy_rules_from_config(
        self,
        strategy_id: str,
        rule_configs: list[dict[str, Any]],
    ) -> None:
        """룰 설정 리스트에서 전략별 룰 인스턴스 생성."""
        rules: list[Rule] = []
        for cfg in rule_configs:
            rule = self._create_rule(cfg)
            if rule is not None:
                rules.append(rule)
        rules.sort(key=lambda r: r.priority)
        self._strategy_rules[strategy_id] = rules

    @staticmethod
    def _create_rule(config: dict[str, Any]) -> Rule | None:
        """룰 설정에서 룰 인스턴스 생성."""
        rule_type = config.get("type")
        rule_class = RULE_REGISTRY.get(rule_type)  # type: ignore[arg-type]
        if rule_class is None:
            logger.warning("알 수 없는 룰 타입: %s", rule_type)
            return None
        rule_id = config.get("id", rule_type)
        return rule_class(rule_id, config)

    # ── 룰 평가 ─────────────────────────────────────

    def evaluate(self, context: RuleContext) -> EvaluationResult:
        """주문에 대한 룰 평가. 전역 → 전략별 순서로 평가."""
        all_evaluations: list[RuleEvaluation] = []

        # 전역 룰 평가
        for rule in self._global_rules:
            if rule.is_applicable(context):
                evaluation = rule.evaluate(context)
                all_evaluations.append(evaluation)
                # BLOCK/REJECT 시 즉시 중단
                if evaluation.result in (RuleResult.BLOCK, RuleResult.REJECT):
                    break

        # 전역 룰에서 차단되지 않았으면 전략별 룰 평가
        if not any(
            e.result in (RuleResult.BLOCK, RuleResult.REJECT) for e in all_evaluations
        ):
            strategy_rules = self._strategy_rules.get(context.strategy_id, [])
            for rule in strategy_rules:
                if rule.is_applicable(context):
                    evaluation = rule.evaluate(context)
                    all_evaluations.append(evaluation)
                    if evaluation.result in (
                        RuleResult.BLOCK,
                        RuleResult.REJECT,
                    ):
                        break

        # 결과 종합
        overall, reason, actions = self._aggregate_results(all_evaluations)

        return EvaluationResult(
            overall_result=overall,
            evaluations=all_evaluations,
            rejection_reason=reason,
            actions=actions,
        )

    @staticmethod
    def _aggregate_results(
        evaluations: list[RuleEvaluation],
    ) -> tuple[RuleResult, str, list[RuleAction]]:
        """평가 결과들을 종합."""
        overall = RuleResult.PASS
        reason = ""
        actions: list[RuleAction] = []

        for evaluation in evaluations:
            if evaluation.result == RuleResult.BLOCK:
                overall = RuleResult.BLOCK
                reason = evaluation.message
                if evaluation.action != RuleAction.LOG:
                    actions.append(evaluation.action)
                break
            elif evaluation.result == RuleResult.REJECT:
                overall = RuleResult.REJECT
                reason = evaluation.message
                if evaluation.action != RuleAction.LOG:
                    actions.append(evaluation.action)
                break
            elif evaluation.result == RuleResult.WARN and overall == RuleResult.PASS:
                overall = RuleResult.WARN

            if evaluation.action != RuleAction.LOG:
                actions.append(evaluation.action)

        return overall, reason, actions

    # ── EventBus 핸들러 ──────────────────────────────

    async def _on_order_request(self, event: object) -> None:
        """OrderRequestEvent 수신 시 룰 평가 후 결과 이벤트 발행."""
        from ante.eventbus.events import (
            NotificationEvent,
            OrderRejectedEvent,
            OrderRequestEvent,
            OrderValidatedEvent,
        )

        if not isinstance(event, OrderRequestEvent):
            return

        context = RuleContext(
            bot_id=event.bot_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            order_type=event.order_type,
            price=event.price,
            current_price=event.price or 0.0,
            system_status=self._system_state.trading_state.value,
        )

        try:
            result = self.evaluate(context)

            if result.overall_result in (RuleResult.PASS, RuleResult.WARN):
                await self._eventbus.publish(
                    OrderValidatedEvent(
                        order_id=str(event.event_id),
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        stop_price=event.stop_price,
                        reason=event.reason,
                    )
                )
                if result.overall_result == RuleResult.WARN:
                    for ev in result.evaluations:
                        if ev.result == RuleResult.WARN:
                            await self._eventbus.publish(
                                NotificationEvent(
                                    level="warning",
                                    message=f"Rule warning: {ev.message}",
                                    metadata=ev.metadata,
                                )
                            )
            else:
                await self._eventbus.publish(
                    OrderRejectedEvent(
                        order_id=str(event.event_id),
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        reason=result.rejection_reason,
                    )
                )
                await self._execute_actions(result.actions, event)

        except Exception:
            logger.exception("룰 평가 실패: %s", event.event_id)
            await self._eventbus.publish(
                OrderRejectedEvent(
                    order_id=str(event.event_id),
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=event.symbol,
                    side=event.side,
                    quantity=event.quantity,
                    price=event.price,
                    order_type=event.order_type,
                    reason="Rule evaluation error",
                )
            )

    async def _execute_actions(self, actions: list[RuleAction], event: object) -> None:
        """룰 위반 조치 실행."""
        from ante.config.system_state import TradingState
        from ante.eventbus.events import (
            BotStopEvent,
            NotificationEvent,
            OrderRequestEvent,
        )

        if not isinstance(event, OrderRequestEvent):
            return

        for action in actions:
            if action == RuleAction.NOTIFY:
                await self._eventbus.publish(
                    NotificationEvent(
                        level="error",
                        message=(
                            f"Rule violation for bot {event.bot_id}: {event.symbol}"
                        ),
                    )
                )
            elif action == RuleAction.STOP_BOT:
                await self._eventbus.publish(
                    BotStopEvent(
                        bot_id=event.bot_id,
                        reason="Rule violation",
                    )
                )
            elif action == RuleAction.HALT_SYSTEM:
                await self._system_state.set_state(
                    TradingState.HALTED,
                    reason="Critical rule violation",
                    changed_by="rule_engine",
                )

    async def _on_config_changed(self, event: object) -> None:
        """설정 변경 시 룰 재로딩 트리거."""
        from ante.eventbus.events import ConfigChangedEvent

        if not isinstance(event, ConfigChangedEvent):
            return
        if event.category in ("rule", "global_rule", "strategy_rule"):
            logger.info("룰 설정 변경 감지, 룰 재로딩 필요: %s", event.key)
