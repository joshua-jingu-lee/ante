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
    from ante.account.service import AccountService
    from ante.eventbus.bus import EventBus
    from ante.treasury.treasury import Treasury

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

    계좌 룰(계좌 레벨)과 전략별 룰을 순차 평가하여
    OrderRequestEvent를 승인/거부한다.
    각 RuleEngine은 특정 account_id에 바인딩되며,
    해당 계좌의 이벤트만 처리한다.
    """

    def __init__(
        self,
        eventbus: EventBus,
        account_id: str = "default",
        account_service: AccountService | None = None,
        bot_strategy_resolver: Callable[[str], str | None] | None = None,
        treasury: Treasury | None = None,
    ) -> None:
        self._eventbus = eventbus
        self._account_id = account_id
        self._account_service = account_service
        self._bot_strategy_resolver = bot_strategy_resolver
        self._treasury = treasury

        self._account_rules: list[Rule] = []
        self._strategy_rules: dict[str, list[Rule]] = {}

    @property
    def account_id(self) -> str:
        """바인딩된 계좌 ID."""
        return self._account_id

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
        logger.info("RuleEngine 시작: account=%s", self._account_id)

    # ── 룰 관리 ─────────────────────────────────────

    def add_account_rule(self, rule: Rule) -> None:
        """계좌 룰 추가."""
        self._account_rules.append(rule)
        self._account_rules.sort(key=lambda r: r.priority)

    def add_global_rule(self, rule: Rule) -> None:
        """전역 룰 추가. add_account_rule의 별칭 (하위 호환)."""
        self.add_account_rule(rule)

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
        self._account_rules.clear()
        self._strategy_rules.clear()

    def load_rules_from_config(self, rule_configs: list[dict[str, Any]]) -> None:
        """룰 설정 리스트에서 계좌 룰 인스턴스 생성."""
        for cfg in rule_configs:
            rule = self._create_rule(cfg)
            if rule is not None:
                self._account_rules.append(rule)
        self._account_rules.sort(key=lambda r: r.priority)

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

    # ── 하위 호환 프로퍼티 ──────────────────────────────

    @property
    def _global_rules(self) -> list[Rule]:
        """하위 호환: _global_rules → _account_rules."""
        return self._account_rules

    # ── 룰 평가 ─────────────────────────────────────

    def evaluate(self, context: RuleContext) -> EvaluationResult:
        """주문에 대한 룰 평가. 계좌 룰 → 전략별 순서로 평가."""
        all_evaluations: list[RuleEvaluation] = []

        # 계좌 룰 평가
        for rule in self._account_rules:
            if rule.is_applicable(context):
                evaluation = rule.evaluate(context)
                all_evaluations.append(evaluation)
                # BLOCK/REJECT 시 즉시 중단
                if evaluation.result in (RuleResult.BLOCK, RuleResult.REJECT):
                    break

        # 계좌 룰에서 차단되지 않았으면 전략별 룰 평가
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

    # ── Treasury 조회 ──────────────────────────────

    async def _query_treasury_data(self, bot_id: str = "") -> dict[str, float]:
        """Treasury에서 자산/손익 데이터를 조회한다.

        Args:
            bot_id: 봇 할당 예산 조회를 위한 봇 ID.

        Returns:
            daily_pnl, total_pnl, prev_day_total_asset,
            total_asset, total_exposure, bot_allocated_budget 딕셔너리.
            조회 실패 시 각 값은 0.0.
        """
        result = {
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "prev_day_total_asset": 0.0,
            "total_asset": 0.0,
            "total_exposure": 0.0,
            "bot_allocated_budget": 0.0,
        }
        if self._treasury is None:
            return result

        # get_summary()는 동기 메서드
        try:
            summary = self._treasury.get_summary()
            result["total_pnl"] = summary.get("total_profit_loss", 0.0)
            result["total_asset"] = summary.get("total_evaluation", 0.0)
            result["total_exposure"] = summary.get("ante_eval_amount", 0.0)
        except Exception:
            logger.warning("Treasury summary 조회 실패: %s", self._account_id)

        # 봇 할당 예산 조회
        if bot_id:
            try:
                budget = self._treasury.get_budget(bot_id)
                if budget is not None:
                    result["bot_allocated_budget"] = budget.allocated
            except Exception:
                logger.warning("Treasury 봇 예산 조회 실패: bot=%s", bot_id)

        # get_daily_snapshot()은 비동기 메서드
        try:
            from datetime import date, timedelta

            yesterday = (date.today() - timedelta(days=1)).isoformat()
            snapshot = await self._treasury.get_daily_snapshot(yesterday)
            if snapshot is not None:
                result["prev_day_total_asset"] = snapshot.get("total_asset", 0.0)
        except Exception:
            logger.warning("Treasury 전일 스냅샷 조회 실패: %s", self._account_id)

        # daily_pnl: 최신 스냅샷에서 조회
        try:
            latest = await self._treasury.get_latest_snapshot()
            if latest is not None:
                result["daily_pnl"] = latest.get("daily_pnl", 0.0)
        except Exception:
            logger.warning("Treasury 최신 스냅샷 조회 실패: %s", self._account_id)

        return result

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

        # account_id 필터링: 자기 계좌 이벤트만 처리
        if event.account_id != self._account_id:
            return

        # 계좌 상태 조회
        account_status = "active"
        currency = "KRW"
        if self._account_service is not None:
            try:
                account = await self._account_service.get(self._account_id)
                account_status = account.status.value
                currency = account.currency
            except Exception:
                logger.warning(
                    "계좌 상태 조회 실패: %s — 기본값 사용", self._account_id
                )

        # Treasury 데이터 조회
        treasury_data = await self._query_treasury_data(bot_id=event.bot_id)

        context = RuleContext(
            bot_id=event.bot_id,
            account_id=self._account_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            order_type=event.order_type,
            price=event.price,
            current_price=event.price or 0.0,
            account_status=account_status,
            currency=currency,
            daily_pnl=treasury_data["daily_pnl"],
            total_pnl=treasury_data["total_pnl"],
            prev_day_total_asset=treasury_data["prev_day_total_asset"],
            total_asset=treasury_data["total_asset"],
            total_exposure=treasury_data["total_exposure"],
            bot_allocated_budget=treasury_data["bot_allocated_budget"],
        )

        try:
            result = self.evaluate(context)

            if result.overall_result in (RuleResult.PASS, RuleResult.WARN):
                await self._eventbus.publish(
                    OrderValidatedEvent(
                        account_id=self._account_id,
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
                        account_id=self._account_id,
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
                    account_id=self._account_id,
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
            elif action == RuleAction.HALT_ACCOUNT:
                if self._account_service is not None:
                    await self._account_service.suspend(
                        self._account_id,
                        reason="Critical rule violation",
                        suspended_by="rule_engine",
                    )
                else:
                    logger.warning(
                        "HALT_ACCOUNT 액션이지만 AccountService가 없어 실행 불가: %s",
                        self._account_id,
                    )

    async def _on_order_modify(self, event: object) -> None:
        """OrderModifyEvent 수신 시 룰 평가. 위반 시 거부 이벤트 발행."""
        from ante.eventbus.events import (
            OrderModifyEvent,
            OrderModifyRejectedEvent,
        )

        if not isinstance(event, OrderModifyEvent):
            return

        # account_id 필터링
        if event.account_id != self._account_id:
            return

        # 계좌 상태 조회
        account_status = "active"
        currency = "KRW"
        if self._account_service is not None:
            try:
                account = await self._account_service.get(self._account_id)
                account_status = account.status.value
                currency = account.currency
            except Exception:
                logger.warning(
                    "계좌 상태 조회 실패: %s — 기본값 사용", self._account_id
                )

        # Treasury 데이터 조회
        treasury_data = await self._query_treasury_data(bot_id=event.bot_id)

        context = RuleContext(
            bot_id=event.bot_id,
            account_id=self._account_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            order_type="limit" if event.price else "market",
            price=event.price,
            current_price=event.price or 0.0,
            account_status=account_status,
            currency=currency,
            daily_pnl=treasury_data["daily_pnl"],
            total_pnl=treasury_data["total_pnl"],
            prev_day_total_asset=treasury_data["prev_day_total_asset"],
            total_asset=treasury_data["total_asset"],
            total_exposure=treasury_data["total_exposure"],
            bot_allocated_budget=treasury_data["bot_allocated_budget"],
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

        category가 ``"rule"`` 또는 ``"global_rule"``이면 계좌 룰을 재로드하고,
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
            self._account_rules.clear()
            self.load_rules_from_config(new_rules)
            logger.info("계좌 룰 재로드 완료: %d건", len(self._account_rules))
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
