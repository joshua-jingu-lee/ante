"""RuleEngine — 2계층 룰 평가 엔진."""

from __future__ import annotations

import logging
from collections.abc import Callable
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
        bot_strategy_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._eventbus = eventbus
        self._system_state = system_state
        self._bot_strategy_resolver = bot_strategy_resolver

        self._global_rules: list[Rule] = []
        self._strategy_rules: dict[str, list[Rule]] = {}

    def start(self) -> None:
        """EventBus 구독 등록."""
        from ante.eventbus.events import (
            ConfigChangedEvent,
            OrderModifyEvent,
            OrderRequestEvent,
        )

        self._eventbus.subscribe(
            OrderRequestEvent, self._on_order_request, priority=100
        )
        self._eventbus.subscribe(OrderModifyEvent, self._on_order_modify, priority=100)
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

    def set_bot_strategy_resolver(self, resolver: Callable[[str], str | None]) -> None:
        """봇 ID → 전략 ID 변환 콜백 설정 (초기화 후 BotManager 연결 시 호출)."""
        self._bot_strategy_resolver = resolver

    def update_rules(self, bot_id: str, rules: list[dict[str, Any]]) -> None:
        """봇의 거래 규칙을 갱신.

        bot_id에 연결된 strategy_id를 조회한 뒤
        load_strategy_rules_from_config(strategy_id, rules)로 기존 룰을 교체한다.

        Args:
            bot_id: 대상 봇 ID.
            rules: 새 룰 설정 리스트.

        Raises:
            RuleError: resolver 미설정 또는 strategy_id 조회 실패.
        """
        from ante.rule.exceptions import RuleError

        if not self._bot_strategy_resolver:
            raise RuleError(
                "bot_strategy_resolver가 설정되지 않았습니다. "
                "set_bot_strategy_resolver()를 먼저 호출하세요."
            )

        strategy_id = self._bot_strategy_resolver(bot_id)
        if not strategy_id:
            raise RuleError(f"봇 '{bot_id}'에 연결된 전략을 찾을 수 없습니다.")

        self.load_strategy_rules_from_config(strategy_id, rules)
        logger.info(
            "룰 갱신: bot=%s, strategy=%s, 룰 %d건",
            bot_id,
            strategy_id,
            len(rules),
        )

    def remove_strategy_rules(self, strategy_id: str) -> None:
        """특정 전략의 룰 제거."""
        removed = self._strategy_rules.pop(strategy_id, None)
        if removed:
            logger.info("전략별 룰 제거: strategy=%s (%d건)", strategy_id, len(removed))

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
                                    title=f"Rule warning: {ev.message}",
                                    category="system",
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

    async def _on_order_modify(self, event: object) -> None:
        """OrderModifyEvent 수신 시 룰 평가. 위반 시 거부 이벤트 발행."""
        from ante.eventbus.events import (
            OrderModifyEvent,
            OrderModifyRejectedEvent,
        )

        if not isinstance(event, OrderModifyEvent):
            return

        context = RuleContext(
            bot_id=event.bot_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            order_type="limit" if event.price else "market",
            price=event.price,
            current_price=event.price or 0.0,
            system_status=self._system_state.trading_state.value,
        )

        try:
            result = self.evaluate(context)

            if result.overall_result in (
                RuleResult.BLOCK,
                RuleResult.REJECT,
            ):
                logger.warning(
                    "주문 정정 거부: order=%s bot=%s — %s",
                    event.order_id,
                    event.bot_id,
                    result.rejection_reason,
                )
                await self._eventbus.publish(
                    OrderModifyRejectedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        reason=result.rejection_reason,
                    )
                )
                # 거부 시 이벤트 소비 — 후속 핸들러(Gateway)에 전달 방지
                if hasattr(event, "_consumed"):
                    object.__setattr__(event, "_consumed", True)

        except Exception:
            logger.exception("주문 정정 룰 평가 실패: %s", event.order_id)
            await self._eventbus.publish(
                OrderModifyRejectedEvent(
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=event.symbol,
                    side=event.side,
                    quantity=event.quantity,
                    price=event.price,
                    reason="Rule evaluation error",
                )
            )

    async def _on_config_changed(self, event: object) -> None:
        """설정 변경 시 룰 재로딩.

        category가 ``"rule"`` 또는 ``"global_rule"``이면 전역 룰을 재로드하고,
        ``"strategy_rule"``이면 해당 전략 룰을 재로드한다.

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.
        """
        import json

        from ante.eventbus.events import ConfigChangedEvent

        if not isinstance(event, ConfigChangedEvent):
            return
        if event.category not in ("rule", "global_rule", "strategy_rule"):
            return

        logger.info("룰 설정 변경 감지, 재로딩 시작: %s", event.key)

        try:
            new_rules: list[dict[str, Any]] = json.loads(event.new_value)
        except (json.JSONDecodeError, TypeError):
            logger.warning("룰 설정 파싱 실패 — 재로딩 건너뜀: %s", event.key)
            return

        if not isinstance(new_rules, list):
            logger.warning("룰 설정이 list가 아님 — 재로딩 건너뜀: %s", event.key)
            return

        if event.category in ("rule", "global_rule"):
            self._global_rules.clear()
            self.load_rules_from_config(new_rules)
            logger.info("전역 룰 재로드 완료: %d건", len(self._global_rules))
        elif event.category == "strategy_rule":
            # key 형식: "rules.strategy.<strategy_id>" 또는 strategy_id 직접
            parts = event.key.rsplit(".", 1)
            strategy_id = parts[-1] if len(parts) > 1 else event.key
            self.load_strategy_rules_from_config(strategy_id, new_rules)
            logger.info(
                "전략 룰 재로드 완료: strategy=%s, %d건",
                strategy_id,
                len(self._strategy_rules.get(strategy_id, [])),
            )
