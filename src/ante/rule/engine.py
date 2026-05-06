"""RuleEngine — 2계층 룰 평가 엔진."""

from __future__ import annotations

import logging
import re
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
    from ante.trade.service import TradeService
    from ante.treasury.treasury import Treasury

logger = logging.getLogger(__name__)

# Signal.side 허용값 — docs/specs/strategy/03-02-signal-fields.md 기준
_VALID_ORDER_SIDES: frozenset[str] = frozenset({"buy", "sell"})

# Signal.order_type 허용값 — docs/specs/strategy/03-02-signal-fields.md 기준.
# "trail" 등 미지원 order_type은 broker adapter 단계에서 4건 누적 실패를
# 일으킨 회귀이므로(#1298), 룰 평가 이전에 fail-closed로 거부한다.
_VALID_ORDER_TYPES: frozenset[str] = frozenset(
    {"market", "limit", "stop", "stop_limit"}
)

# 현재 Ante KIS-domestic contract: 6자리 숫자 PDNO. KRX 전체 단축코드 SSOT 아님.
# docs/specs/data-feed/04-schema.md 와
# docs/specs/broker-adapter/08-kis-domestic-adapter.md 기준으로 KRX 주문 경로는
# 6자리 numeric 단축코드를 가정한다. "INVALID" 같은 비수치 symbol이 RuleEngine을
# 통과하면 KIS 40070000(매매불가 종목)을 유발하므로(#1299 A7 oracle 회귀), 룰 평가
# 이전에 fail-closed로 거부한다.
_KRX_NUMERIC_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}$")

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
        *,
        account_id: str,
        account_service: AccountService | None = None,
        bot_strategy_resolver: Callable[[str], str | None] | None = None,
        treasury: Treasury | None = None,
        trade_service: TradeService | None = None,
    ) -> None:
        from ante.account.scoping import require_account_id

        self._eventbus = eventbus
        self._account_id = require_account_id(
            account_id, context="rule_engine.__init__"
        )
        self._account_service = account_service
        self._bot_strategy_resolver = bot_strategy_resolver
        self._treasury = treasury
        self._trade_service = trade_service

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
        if not isinstance(rule_type, str):
            logger.warning("알 수 없는 룰 타입: %s", rule_type)
            return None
        rule_class = RULE_REGISTRY.get(rule_type)
        if rule_class is None:
            logger.warning("알 수 없는 룰 타입: %s", rule_type)
            return None
        rule_id: str = config.get("id", rule_type)  # type: ignore[assignment]
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

    # ── Trade 조회 ─────────────────────────────────

    async def _calculate_bot_unrealized_pnl(
        self, bot_id: str, current_price: float, order_symbol: str
    ) -> float:
        """봇의 전체 미실현 손익을 계산한다.

        현재 주문 대상 종목은 current_price를 사용하고,
        그 외 종목은 avg_entry_price를 현재가로 간주한다 (미실현=0 근사).

        Args:
            bot_id: 봇 ID.
            current_price: 주문 대상 종목의 현재 가격.
            order_symbol: 주문 대상 종목 코드.

        Returns:
            미실현 손익 합계.
        """
        if self._trade_service is None:
            return 0.0

        try:
            positions = await self._trade_service.get_positions(bot_id)
            total = 0.0
            for pos in positions:
                if pos.symbol == order_symbol:
                    # 주문 대상 종목: current_price로 미실현 손익 계산
                    total += (current_price - pos.avg_entry_price) * pos.quantity
                # 그 외 종목: 시세 정보 없으므로 미실현 손익 0으로 근사
            return total
        except Exception:
            logger.warning("미실현 손익 계산 실패: bot=%s", bot_id)
            return 0.0

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

        # OrderRequestEvent 계약 preflight: Signal.side 허용값 검증.
        # docs/specs/strategy/03-02-signal-fields.md — side ∈ {"buy", "sell"}.
        # 룰 평가/Treasury 조회 이전에 거부하여 사이드이펙트(예약/주문) 차단.
        # `isinstance(..., str)` 가드로 list/dict 같은 unhashable 값이 들어와도
        # frozenset membership 검사가 TypeError를 raise하지 않도록 한다.
        if not isinstance(event.side, str) or event.side not in _VALID_ORDER_SIDES:
            reason = f"Invalid signal side: {event.side!r} (allowed: buy, sell)"
            # OrderRejectedEvent.side / .order_type / .symbol은 TradeRecorder가
            # sqlite TEXT NOT NULL 컬럼에 바인딩하므로, 비문자열(list/dict/set/None
            # 등)이 들어올 경우 InterfaceError/NOT NULL 위반으로 거부 audit trail이
            # 깨진다. repr()로 강제 정규화하여 텍스트 호환성을 보장한다.
            # cross-field 보강(#1298/#1299): side만 invalid해도 동시에 order_type
            # 또는 symbol까지 비문자열이면 reject 이벤트가 broken되므로 세 필드
            # 모두 정규화한다.
            safe_side = event.side if isinstance(event.side, str) else repr(event.side)
            safe_order_type = (
                event.order_type
                if isinstance(event.order_type, str)
                else repr(event.order_type)
            )
            safe_symbol = (
                event.symbol if isinstance(event.symbol, str) else repr(event.symbol)
            )
            await self._eventbus.publish(
                OrderRejectedEvent(
                    account_id=self._account_id,
                    order_id=str(event.event_id),
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=safe_symbol,
                    side=safe_side,
                    quantity=event.quantity,
                    price=event.price,
                    order_type=safe_order_type,
                    reason=reason,
                    exchange=event.exchange,
                )
            )
            return

        # OrderRequestEvent 계약 preflight: Signal.order_type 허용값 검증.
        # docs/specs/strategy/03-02-signal-fields.md —
        # order_type ∈ {"market", "limit", "stop", "stop_limit"}.
        # 회귀(#1298): order_type="trail" 등 미지원 값이 RuleEngine을 통과해
        # Treasury 예약 → broker adapter 호출까지 진행되어 broker 실패 4건이
        # 누적되었다. 룰 평가/Treasury 조회 이전에 fail-closed로 거부한다.
        if (
            not isinstance(event.order_type, str)
            or event.order_type not in _VALID_ORDER_TYPES
        ):
            safe_order_type = (
                event.order_type
                if isinstance(event.order_type, str)
                else repr(event.order_type)
            )
            # cross-field 보강(#1299): symbol도 sqlite TEXT 컬럼에 바인딩되므로
            # 비문자열이면 repr()로 정규화한다.
            safe_symbol = (
                event.symbol if isinstance(event.symbol, str) else repr(event.symbol)
            )
            reason = (
                f"Invalid order type: {event.order_type!r} "
                f"(allowed: market, limit, stop, stop_limit)"
            )
            await self._eventbus.publish(
                OrderRejectedEvent(
                    account_id=self._account_id,
                    order_id=str(event.event_id),
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=safe_symbol,
                    side=event.side,
                    quantity=event.quantity,
                    price=event.price,
                    order_type=safe_order_type,
                    reason=reason,
                    exchange=event.exchange,
                )
            )
            return

        # OrderRequestEvent 계약 preflight: KRX numeric symbol 검증.
        # 회귀(#1299): A7 oracle이 검출한 버그 — Signal.symbol="INVALID",
        # exchange="KRX" 주문이 RuleEngine→Treasury→broker까지 진행되어
        # KIS 40070000(매매불가 종목)이 발생했다. 현재 Ante KIS-domestic 경로는
        # 6자리 숫자 PDNO(예: "005930", "069500")만 가정하므로, 그 형식을
        # 만족하지 않는 KRX symbol은 룰 평가/Treasury 조회 이전에 fail-closed로
        # 거부한다. 비-KRX exchange는 broker adapter에 위임한다.
        if event.exchange == "KRX" and (
            not isinstance(event.symbol, str)
            or not _KRX_NUMERIC_SYMBOL_PATTERN.fullmatch(event.symbol)
        ):
            safe_symbol = (
                event.symbol if isinstance(event.symbol, str) else repr(event.symbol)
            )
            reason = (
                f"Invalid KRX numeric symbol: {event.symbol!r} "
                f"(expected 6-digit numeric per current Ante KIS-domestic contract)"
            )
            await self._eventbus.publish(
                OrderRejectedEvent(
                    account_id=self._account_id,
                    order_id=str(event.event_id),
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=safe_symbol,
                    side=event.side,
                    quantity=event.quantity,
                    price=event.price,
                    order_type=event.order_type,
                    reason=reason,
                    exchange=event.exchange,
                )
            )
            return

        # OrderRequestEvent 계약 preflight: limit / stop_limit price 필수.
        # 회귀(#1300): A7 oracle이 검출한 버그 — order_type="limit", side="sell",
        # price=None 주문이 RuleEngine→Treasury→broker까지 진행되어 KIS 호출
        # 단계에서 HTTP 500이 발생했다. limit / stop_limit는 가격 지정이 invariant
        # 이므로, price=None이면 룰 평가/Treasury 조회 이전에 fail-closed로 거부한다.
        # market의 price=None은 스펙상 옵션이므로 통과시키며, 0/음수/NaN/비-number
        # price 검증은 본 PR 범위 밖(#1303)이다.
        if event.order_type in ("limit", "stop_limit") and event.price is None:
            reason = (
                f"Missing price for {event.order_type} order: "
                f"price is required for limit and stop_limit orders"
            )
            # cross-field 보강(#1297/#1298/#1299): symbol은 sqlite TEXT 컬럼에
            # 바인딩되므로 비문자열이면 repr()로 정규화한다. side / order_type은
            # 본 게이트 도달 시점에 위 게이트들에서 이미 문자열로 잠겼다.
            safe_symbol = (
                event.symbol if isinstance(event.symbol, str) else repr(event.symbol)
            )
            await self._eventbus.publish(
                OrderRejectedEvent(
                    account_id=self._account_id,
                    order_id=str(event.event_id),
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=safe_symbol,
                    side=event.side,
                    quantity=event.quantity,
                    price=event.price,
                    order_type=event.order_type,
                    reason=reason,
                    exchange=event.exchange,
                )
            )
            return

        # 계좌 상태 조회
        account_status = "active"
        currency = "KRW"
        trading_hours_start = "09:00"
        trading_hours_end = "15:30"
        timezone = "Asia/Seoul"
        if self._account_service is not None:
            try:
                account = await self._account_service.get(self._account_id)
                account_status = account.status.value
                currency = account.currency
                trading_hours_start = account.trading_hours_start
                trading_hours_end = account.trading_hours_end
                timezone = account.timezone
            except Exception:
                logger.warning(
                    "계좌 상태 조회 실패: %s — 기본값 사용", self._account_id
                )

        # Treasury 데이터 조회
        treasury_data = await self._query_treasury_data(bot_id=event.bot_id)

        # 미실현 손익 조회
        current_price = event.price or 0.0
        unrealized_pnl = await self._calculate_bot_unrealized_pnl(
            bot_id=event.bot_id,
            current_price=current_price,
            order_symbol=event.symbol,
        )

        context = RuleContext(
            bot_id=event.bot_id,
            account_id=self._account_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            order_type=event.order_type,
            price=event.price,
            current_price=current_price,
            account_status=account_status,
            currency=currency,
            unrealized_pnl=unrealized_pnl,
            daily_pnl=treasury_data["daily_pnl"],
            total_pnl=treasury_data["total_pnl"],
            prev_day_total_asset=treasury_data["prev_day_total_asset"],
            total_asset=treasury_data["total_asset"],
            total_exposure=treasury_data["total_exposure"],
            bot_allocated_budget=treasury_data["bot_allocated_budget"],
            trading_hours_start=trading_hours_start,
            trading_hours_end=trading_hours_end,
            timezone=timezone,
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
        trading_hours_start = "09:00"
        trading_hours_end = "15:30"
        timezone = "Asia/Seoul"
        if self._account_service is not None:
            try:
                account = await self._account_service.get(self._account_id)
                account_status = account.status.value
                currency = account.currency
                trading_hours_start = account.trading_hours_start
                trading_hours_end = account.trading_hours_end
                timezone = account.timezone
            except Exception:
                logger.warning(
                    "계좌 상태 조회 실패: %s — 기본값 사용", self._account_id
                )

        # Treasury 데이터 조회
        treasury_data = await self._query_treasury_data(bot_id=event.bot_id)

        # 미실현 손익 조회
        modify_price = event.price or 0.0
        unrealized_pnl = await self._calculate_bot_unrealized_pnl(
            bot_id=event.bot_id,
            current_price=modify_price,
            order_symbol=event.symbol,
        )

        context = RuleContext(
            bot_id=event.bot_id,
            account_id=self._account_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            order_type="limit" if event.price else "market",
            price=event.price,
            current_price=modify_price,
            account_status=account_status,
            currency=currency,
            unrealized_pnl=unrealized_pnl,
            daily_pnl=treasury_data["daily_pnl"],
            total_pnl=treasury_data["total_pnl"],
            prev_day_total_asset=treasury_data["prev_day_total_asset"],
            total_asset=treasury_data["total_asset"],
            total_exposure=treasury_data["total_exposure"],
            bot_allocated_budget=treasury_data["bot_allocated_budget"],
            trading_hours_start=trading_hours_start,
            trading_hours_end=trading_hours_end,
            timezone=timezone,
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
                        account_id=event.account_id,
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
                    account_id=event.account_id,
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
