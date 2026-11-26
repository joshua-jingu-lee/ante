"""RuleEngine — 2계층 룰 평가 엔진."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, TypeGuard

from ante.core import clock
from ante.core.market_data_vocab import is_krx_symbol
from ante.rule.base import (
    EvaluationResult,
    Rule,
    RuleAction,
    RuleContext,
    RuleEvaluation,
    RuleResult,
)
from ante.rule.config_update import account_rules_config_key
from ante.rule.exceptions import RuleConfigError
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
    from ante.account.models import Account
    from ante.account.readiness import RuntimeReadinessRegistry
    from ante.account.service import AccountService
    from ante.eventbus.bus import EventBus
    from ante.instrument.service import InstrumentService
    from ante.trade.order_tracker import OrderTracker
    from ante.trade.service import TradeService
    from ante.treasury.treasury import Treasury

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

_VALID_ORDER_SIDES: frozenset[str] = frozenset({"buy", "sell"})

_VALID_ORDER_TYPES: frozenset[str] = frozenset(
    {"market", "limit", "stop", "stop_limit"}
)


def _is_finite_quantity(value: object) -> TypeGuard[int | float]:
    """``value``가 finite ``float``-호환 quantity인지 판정."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError, TypeError):
        return False


def _coerce_finite_quantity(value: object) -> float:
    """``OrderRejectedEvent.quantity`` payload용 안전한 finite ``float`` 변환."""
    if not _is_finite_quantity(value):
        return 0.0
    return float(value)


def _coerce_finite_optional_price(value: object) -> float | None:
    """``OrderRejectedEvent.price`` payload용 안전한 ``float | None`` 정규화."""
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        if not math.isfinite(value):
            return None
    except (OverflowError, ValueError, TypeError):
        return None
    return float(value)


def _safe_str(value: object) -> str:
    """``TEXT`` 바인딩용 ``str`` 정규화(비-str은 ``repr()``, 실패 시 placeholder)."""
    if isinstance(value, str):
        return value
    try:
        return repr(value)
    except Exception:
        return f"<unrenderable {type(value).__name__}>"


def _safe_repr(value: object) -> str:
    """``reason`` 메시지 조립용 안전한 ``repr``-스타일 변환."""
    try:
        return repr(value)
    except Exception:
        return f"<unrenderable {type(value).__name__}>"


def _safe_order_id(value: object) -> str:
    """``OrderRejectedEvent.order_id`` 바인딩용 안전한 평문 ``str`` 변환."""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return f"<unrenderable {type(value).__name__}>"


def _build_safe_rejected_event(
    *,
    account_id: str,
    event: object,
    reason: str,
) -> Any:
    """모든 source 필드를 정규화한 fail-closed ``OrderRejectedEvent`` 빌더."""
    from ante.eventbus.events import OrderRejectedEvent

    return OrderRejectedEvent(
        account_id=account_id,
        order_id=_safe_order_id(getattr(event, "event_id", "")),
        bot_id=_safe_str(getattr(event, "bot_id", "")),
        strategy_id=_safe_str(getattr(event, "strategy_id", "")),
        symbol=_safe_str(getattr(event, "symbol", "")),
        side=_safe_str(getattr(event, "side", "")),
        quantity=_coerce_finite_quantity(getattr(event, "quantity", 0.0)),
        price=_coerce_finite_optional_price(getattr(event, "price", None)),
        order_type=_safe_str(getattr(event, "order_type", "")),
        reason=reason,
        exchange=_safe_str(getattr(event, "exchange", "KRX")),
    )


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
        account: Account | None = None,
        order_tracker: OrderTracker | None = None,
        unrecovered_buy_guard_min_age: float = 60.0,
        allow_unrecovered_buy_overlap: bool = False,
        instrument_service: InstrumentService | None = None,
        runtime_readiness: RuntimeReadinessRegistry | None = None,
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
        self._order_tracker = order_tracker
        self._account = account
        self._instrument_service = instrument_service
        self._runtime_readiness = runtime_readiness

        self._unrecovered_buy_guard_min_age = unrecovered_buy_guard_min_age
        self._allow_unrecovered_buy_overlap_default = allow_unrecovered_buy_overlap
        self._allow_unrecovered_buy_overlap_by_bot: dict[str, bool] = {}

        self._account_rules: list[Rule] = []
        self._strategy_rules: dict[str, list[Rule]] = {}
        self._rules_unavailable_cause: str | None = None

    @property
    def account_id(self) -> str:
        """바인딩된 계좌 ID."""
        return self._account_id

    @property
    def rules_unavailable(self) -> bool:
        """저장된 계좌 룰을 읽지 못해 주문·정정을 막는 상태인지."""
        return self._rules_unavailable_cause is not None

    @property
    def rules_unavailable_cause(self) -> str | None:
        """막힌 원인(``not_list``|``read_error``|``invalid_item``). 아니면 ``None``."""
        return self._rules_unavailable_cause

    def mark_rules_unavailable(self, cause: str) -> None:
        """저장된 계좌 룰을 읽지 못한 상태로 둔다."""
        self._rules_unavailable_cause = cause

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

    def set_unrecovered_buy_overlap(self, bot_id: str, allow: bool) -> None:
        """봇 단위 ``allow_unrecovered_buy_overlap`` opt-out 등록.

        의도적으로 미복구 outstanding self-buy와 중첩되는 다중 주문을 내는 전략은
        ``allow=True``로 등록하여 미복구 매수 가드를 면제받는다. 미등록 봇은 계좌
        기본값(``allow_unrecovered_buy_overlap`` 생성자 인자, 기본 ``False``)을
        따른다.
        """
        self._allow_unrecovered_buy_overlap_by_bot[bot_id] = allow

    def update_rules(self, bot_id: str, rules: list[dict[str, Any]]) -> None:
        """봇의 거래 규칙을 갱신.

        bot_id에 연결된 strategy_id를 조회한 뒤
        load_strategy_rules_from_config(strategy_id, rules)로 기존 룰을 교체한다.

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
        """룰 설정 리스트로 계좌 룰을 만들어 더한다. 실패하면 기존 룰을 그대로 둔다."""
        merged = self._account_rules + self._build_rules(rule_configs)
        self._account_rules = self._sorted_rules(merged)

    def load_strategy_rules_from_config(
        self,
        strategy_id: str,
        rule_configs: list[dict[str, Any]],
    ) -> None:
        """룰 설정 리스트에서 전략별 룰 인스턴스 생성."""
        self._strategy_rules[strategy_id] = self._build_rules(rule_configs)

    def _build_rules(self, rule_configs: list[dict[str, Any]]) -> list[Rule]:
        """설정 리스트로 룰을 끝까지 만들고 정렬한다. 도중의 예외는 그대로 낸다."""
        rules: list[Rule] = []
        for index, cfg in enumerate(rule_configs):
            try:
                rule = self._create_rule(cfg)
            except Exception as exc:
                rule_type = cfg.get("type") if isinstance(cfg, dict) else None
                logger.error(
                    "룰 항목을 만들지 못함: account=%s, "
                    "effective_index=%d(기본 룰 병합 뒤 위치), item=%s, type=%s, "
                    "error=%s",
                    self._account_id,
                    index,
                    type(cfg).__name__,
                    rule_type if isinstance(rule_type, str) else None,
                    type(exc).__name__,
                )
                raise
            rules.append(rule)
        return self._sorted_rules(rules)

    def _sorted_rules(self, rules: list[Rule]) -> list[Rule]:
        """priority로 정렬한 새 리스트. 비교할 수 없으면 priority 타입을 남기고 낸다."""
        try:
            return sorted(rules, key=lambda r: r.priority)
        except Exception as exc:
            logger.error(
                "룰 priority로 정렬하지 못함: account=%s, priorities=%s, error=%s",
                self._account_id,
                [(r.config.get("type"), type(r.priority).__name__) for r in rules],
                type(exc).__name__,
            )
            raise

    @staticmethod
    def _create_rule(config: dict[str, Any]) -> Rule:
        """룰 설정에서 룰 인스턴스 생성. 쓸 수 없는 config면 ``RuleConfigError``."""
        rule_type = config.get("type")
        if not isinstance(rule_type, str):
            raise RuleConfigError(
                f"룰 type이 문자열이 아님: {type(rule_type).__name__}"
            )
        rule_class = RULE_REGISTRY.get(rule_type)
        if rule_class is None:
            raise RuleConfigError(f"알 수 없는 룰 타입: {rule_type!r}")
        errors = rule_class.config_errors(config)
        if errors:
            raise RuleConfigError(f"룰 config 검증 실패: {'; '.join(errors)}")
        rule_id: str = config.get("id", rule_type)
        return rule_class(rule_id, config)

    @property
    def _global_rules(self) -> list[Rule]:
        """하위 호환: _global_rules → _account_rules."""
        return self._account_rules

    def evaluate(self, context: RuleContext) -> EvaluationResult:
        """주문에 대한 룰 평가. 계좌 룰 → 전략별 순서로 평가."""
        all_evaluations: list[RuleEvaluation] = []

        for rule in self._account_rules:
            if rule.is_applicable(context):
                evaluation = rule.evaluate(context)
                all_evaluations.append(evaluation)
                if evaluation.result in (RuleResult.BLOCK, RuleResult.REJECT):
                    break

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

    async def _query_treasury_data(
        self, bot_id: str = ""
    ) -> tuple[dict[str, float], str | None]:
        """Treasury 값과, 미주입·조회 예외면 ``treasury_unavailable``을 돌려준다."""
        failure: str | None = None
        result = {
            "total_pnl": 0.0,
            "prev_day_total_asset": 0.0,
            "total_asset": 0.0,
            "total_exposure": 0.0,
            "bot_allocated_budget": 0.0,
        }
        if self._treasury is None:
            return result, "treasury_unavailable"

        try:
            summary = self._treasury.get_summary()
            result["total_pnl"] = summary.get("total_profit_loss", 0.0)
            result["total_asset"] = summary.get("total_evaluation", 0.0)
            result["total_exposure"] = summary.get("ante_eval_amount", 0.0)
        except Exception:
            failure = "treasury_unavailable"
            logger.warning("Treasury summary 조회 실패: %s", self._account_id)

        if bot_id:
            try:
                budget = self._treasury.get_budget(bot_id)
                if budget is not None:
                    result["bot_allocated_budget"] = budget.allocated
            except Exception:
                failure = "treasury_unavailable"
                logger.warning("Treasury 봇 예산 조회 실패: bot=%s", bot_id)

        try:
            today = clock.now(_KST).date().isoformat()
            snapshot = await self._treasury.get_prev_day_snapshot(today)
        except Exception:
            failure = "treasury_unavailable"
            logger.warning("Treasury 전일 스냅샷 조회 실패: %s", self._account_id)
        else:
            if snapshot is not None:
                result["prev_day_total_asset"] = snapshot.get("total_asset", 0.0)
            self._warn_if_daily_loss_skipped(snapshot)

        return result, failure

    def _warn_if_daily_loss_skipped(self, snapshot: dict[str, Any] | None) -> None:
        """분모가 없거나 비양수·비유한이면, 켜진 일일 손실 규칙이 있을 때만 경고한다."""
        value = None if snapshot is None else snapshot.get("total_asset")
        if _is_finite_quantity(value) and value > 0:
            return
        if not any(
            isinstance(rule, DailyLossLimitRule) and rule.enabled
            for rule in self._account_rules
        ):
            return
        logger.warning(
            "일일 손실 판정 건너뜀 — 전일 총 자산 없음: account=%s snapshot_date=%s "
            "total_asset=%s",
            self._account_id,
            None if snapshot is None else snapshot.get("snapshot_date"),
            value,
        )

    async def _query_daily_realized_pnl(self) -> float | None:
        """KST 오늘의 계좌 실현 손익을, 조회 예외면 ``None``을 돌려준다."""
        if self._trade_service is None:
            return 0.0
        start = datetime.combine(clock.now(_KST).date(), time(), tzinfo=_KST)
        try:
            return await self._trade_service.get_realized_pnl(
                account_id=self._account_id,
                start=start,
                end=start + timedelta(days=1),
            )
        except Exception:
            logger.warning("당일 실현 손익 조회 실패: %s", self._account_id)
            return None

    async def _calculate_bot_unrealized_pnl(
        self, bot_id: str, current_price: float, order_symbol: str
    ) -> float | None:
        """미실현 손익 합계를, 포지션 조회 예외면 ``None``을 돌려준다."""
        if self._trade_service is None:
            return 0.0

        try:
            positions = await self._trade_service.get_positions(
                bot_id, account_id=self._account_id
            )
            total = 0.0
            for pos in positions:
                if pos.symbol == order_symbol:
                    total += (current_price - pos.avg_entry_price) * pos.quantity
            return total
        except Exception:
            logger.warning("미실현 손익 계산 실패: bot=%s", bot_id)
            return None

    @staticmethod
    def _unrecovered_buy_age_seconds(submitted_at: str | None) -> float | None:
        """``submitted_at`` ISO 문자열의 age(초)를 계산. 산정 불가면 ``None``."""
        from datetime import UTC, datetime

        if not isinstance(submitted_at, str) or not submitted_at:
            return None
        try:
            parsed = datetime.fromisoformat(submitted_at)
        except (ValueError, TypeError):
            return None
        if parsed.tzinfo is None:
            return None
        age = (clock.now(UTC) - parsed).total_seconds()
        if age < 0:
            logger.warning(
                "미회수 매수 가드: submitted_at=%s 이 현재보다 %.1f초 앞섬 "
                "— 벽시계 역행으로 보고 age 0 처리",
                submitted_at,
                -age,
            )
        return max(age, 0.0)

    async def _check_unrecovered_buy_guard(self, event: object) -> str | None:
        """미복구 self-order 반복 매수 가드 (캐스케이드 방어)."""
        if self._order_tracker is None or self._trade_service is None:
            return None
        if getattr(event, "side", None) != "buy":
            return None

        bot_id = getattr(event, "bot_id", "")
        symbol = getattr(event, "symbol", "")

        allow_overlap = self._allow_unrecovered_buy_overlap_by_bot.get(
            bot_id, self._allow_unrecovered_buy_overlap_default
        )
        if allow_overlap:
            return None

        open_orders = await self._order_tracker.get_open_orders_for(
            account_id=self._account_id,
            bot_id=bot_id,
            symbol=symbol,
            side="buy",
        )
        unrecovered = [
            o for o in open_orders if (o.ordered_qty - o.recorded_filled_qty) > 0
        ]
        if not unrecovered:
            return None

        threshold = self._unrecovered_buy_guard_min_age
        aged = [
            o
            for o in unrecovered
            if (age := self._unrecovered_buy_age_seconds(o.submitted_at)) is not None
            and age >= threshold
        ]
        if not aged:
            return None

        positions = await self._trade_service.get_positions(
            bot_id, account_id=self._account_id
        )
        held_qty = sum(p.quantity for p in positions if p.symbol == symbol)
        if held_qty != 0:
            return None

        oldest = aged[0]
        remaining = oldest.ordered_qty - oldest.recorded_filled_qty
        return (
            f"Unrecovered buy guard: outstanding self-buy order "
            f"{_safe_str(oldest.order_id)} on {_safe_str(symbol)} "
            f"(remaining={remaining}, status={_safe_str(oldest.status)}) "
            f"is unrecovered (age ≥ {threshold}s) while internal position is 0 "
            f"— blocking duplicate buy to prevent #2314 cascade "
            f"(set allow_unrecovered_buy_overlap to opt out)"
        )

    async def _resolve_account_meta(self) -> tuple[str, Any] | None:
        """gate 용 ``(broker_type, trading_mode)`` 취득 — fail-closed."""
        from ante.account.models import TradingMode

        account = self._account
        if account is not None:
            broker_type = getattr(account, "broker_type", None)
            trading_mode = getattr(account, "trading_mode", None)
            if isinstance(broker_type, str) and trading_mode is not None:
                return broker_type, trading_mode
        if self._account_service is None:
            return None
        try:
            fetched = await self._account_service.get(self._account_id)
        except Exception:
            return None
        broker_type = getattr(fetched, "broker_type", None)
        trading_mode = getattr(fetched, "trading_mode", None)
        if not isinstance(broker_type, str) or trading_mode is None:
            return None
        _ = TradingMode
        return broker_type, trading_mode

    async def _resolve_account_status(self) -> Any | None:
        """G7 — live ``AccountStatus`` 3-state 조회(``resolve_account_status`` 위임)."""
        from ante.account.gate import resolve_account_status

        return await resolve_account_status(self._account_service, self._account_id)

    async def _on_order_request(self, event: object) -> None:
        """OrderRequestEvent 수신 시 룰 평가 후 결과 이벤트 발행."""
        from ante.eventbus.events import (
            NotificationEvent,
            OrderRequestEvent,
            OrderValidatedEvent,
        )

        if not isinstance(event, OrderRequestEvent):
            return

        if event.account_id != self._account_id:
            return

        try:
            from ante.account.gate import (
                ACCOUNT_NOT_READY_REASON,
                ACCOUNT_STATUS_UNAVAILABLE_REASON,
                ACCOUNT_SUSPENDED_REASON,
                STATUS_UNAVAILABLE,
                active_trading_blocked,
                build_not_ready_notification,
                is_liquidation_reason,
                not_ready_reason,
            )
            from ante.account.models import AccountStatus

            is_liquidation = is_liquidation_reason(getattr(event, "reason", ""))

            account_status = await self._resolve_account_status()
            status_reason: str | None = None
            if account_status == AccountStatus.SUSPENDED:
                status_reason = ACCOUNT_SUSPENDED_REASON
            elif account_status is STATUS_UNAVAILABLE:
                status_reason = ACCOUNT_STATUS_UNAVAILABLE_REASON
            if status_reason is not None:
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=status_reason,
                    )
                )
                await self._eventbus.publish(
                    build_not_ready_notification(
                        account_id=self._account_id,
                        reason=status_reason,
                        side=getattr(event, "side", ""),
                        is_liquidation=is_liquidation,
                    )
                )
                return

            meta = await self._resolve_account_meta()
            if meta is None:
                meta_blocked, meta_reason = (
                    True,
                    f"{ACCOUNT_NOT_READY_REASON}: account_metadata_unavailable",
                )
            else:
                meta_blocked = active_trading_blocked(
                    self._runtime_readiness,
                    self._account_id,
                    broker_type=meta[0],
                    trading_mode=meta[1],
                )
                meta_reason = not_ready_reason(
                    self._runtime_readiness,
                    self._account_id,
                    broker_type=meta[0],
                    trading_mode=meta[1],
                )
            if meta_blocked:
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=meta_reason,
                    )
                )
                await self._eventbus.publish(
                    build_not_ready_notification(
                        account_id=self._account_id,
                        reason=meta_reason,
                        side=getattr(event, "side", ""),
                        is_liquidation=is_liquidation,
                    )
                )
                return

            if self.rules_unavailable:
                rules_reason = f"{ACCOUNT_NOT_READY_REASON}: rules_unavailable"
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=rules_reason,
                    )
                )
                await self._eventbus.publish(
                    build_not_ready_notification(
                        account_id=self._account_id,
                        reason=rules_reason,
                        side=getattr(event, "side", ""),
                        is_liquidation=is_liquidation,
                    )
                )
                return

            if not isinstance(event.side, str) or event.side not in _VALID_ORDER_SIDES:
                reason = (
                    f"Invalid signal side: {_safe_repr(event.side)} "
                    f"(allowed: buy, sell)"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if (
                not isinstance(event.order_type, str)
                or event.order_type not in _VALID_ORDER_TYPES
            ):
                reason = (
                    f"Invalid order type: {_safe_repr(event.order_type)} "
                    f"(allowed: market, limit, stop, stop_limit)"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.exchange == "KRX" and not is_krx_symbol(event.symbol):
                reason = (
                    f"Invalid KRX numeric symbol: {_safe_repr(event.symbol)} "
                    f"(expected 6-digit numeric per current Ante "
                    f"KIS-domestic contract)"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.order_type in ("limit", "stop_limit") and event.price is None:
                reason = (
                    f"Missing price for {_safe_str(event.order_type)} order: "
                    f"price is required for limit and stop_limit orders"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.order_type in ("stop", "stop_limit") and event.stop_price is None:
                reason = (
                    f"Missing stop_price for {_safe_str(event.order_type)} order: "
                    f"stop_price is required for stop and stop_limit orders"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.stop_price is not None and not _is_finite_quantity(
                event.stop_price
            ):
                reason = (
                    f"Invalid stop_price: {_safe_repr(event.stop_price)} "
                    f"(stop_price must be a finite number when provided)"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.stop_price is not None and event.stop_price < 0:
                reason = (
                    f"Negative stop_price: {event.stop_price} "
                    f"(stop_price must be positive)"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.stop_price is not None and event.stop_price == 0:
                reason = (
                    f"Zero stop_price: {event.stop_price} (stop_price must be positive)"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if not _is_finite_quantity(event.quantity):
                reason = (
                    f"Invalid quantity: {_safe_repr(event.quantity)} "
                    f"(quantity must be a finite number)"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.price is not None and not _is_finite_quantity(event.price):
                reason = (
                    f"Invalid price: {_safe_repr(event.price)} "
                    f"(price must be a finite number when provided)"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.price is not None and event.price < 0:
                reason = f"Negative price: {event.price} (price must be positive)"
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.price is not None and event.price == 0:
                reason = f"Zero price: {event.price} (price must be positive)"
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.quantity < 0:
                reason = (
                    f"Negative quantity: {event.quantity} (quantity must be positive)"
                )
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            if event.quantity == 0:
                reason = f"Zero quantity: {event.quantity} (quantity must be positive)"
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=reason,
                    )
                )
                return

            guard_reason = await self._check_unrecovered_buy_guard(event)
            if guard_reason is not None:
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=guard_reason,
                    )
                )
                return

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

            treasury_data, input_failure = await self._query_treasury_data(
                bot_id=event.bot_id
            )

            current_price = event.price or 0.0
            unrealized_pnl = await self._calculate_bot_unrealized_pnl(
                bot_id=event.bot_id,
                current_price=current_price,
                order_symbol=event.symbol,
            )
            if unrealized_pnl is None:
                unrealized_pnl = 0.0
                input_failure = input_failure or "positions_unavailable"
            daily_pnl = await self._query_daily_realized_pnl()
            if daily_pnl is None:
                daily_pnl = 0.0
                input_failure = input_failure or "positions_unavailable"
            if input_failure is not None and event.side == "buy":
                input_reason = f"{ACCOUNT_NOT_READY_REASON}: {input_failure}"
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=input_reason,
                    )
                )
                await self._eventbus.publish(
                    build_not_ready_notification(
                        account_id=self._account_id,
                        reason=input_reason,
                        side=event.side,
                        is_liquidation=is_liquidation,
                    )
                )
                return

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
                daily_pnl=daily_pnl,
                total_pnl=treasury_data["total_pnl"],
                prev_day_total_asset=treasury_data["prev_day_total_asset"],
                total_asset=treasury_data["total_asset"],
                total_exposure=treasury_data["total_exposure"],
                bot_allocated_budget=treasury_data["bot_allocated_budget"],
                trading_hours_start=trading_hours_start,
                trading_hours_end=trading_hours_end,
                timezone=timezone,
            )

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
                        exchange=event.exchange,
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
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=result.rejection_reason,
                    )
                )
                await self._execute_actions(result.actions, event)

        except Exception:
            logger.exception(
                "OrderRequest preflight unexpected failure: event_id=%s",
                getattr(event, "event_id", "<unknown>"),
            )
            try:
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason="OrderRequest preflight error (see logs)",
                    )
                )
            except Exception:
                logger.exception(
                    "Failed to publish safe-fallback OrderRejectedEvent: event_id=%s",
                    getattr(event, "event_id", "<unknown>"),
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
                symbol_label = (
                    self._instrument_service.format_label(event.symbol, event.exchange)
                    if self._instrument_service is not None
                    else event.symbol
                )
                await self._eventbus.publish(
                    NotificationEvent(
                        level="error",
                        message=(
                            f"Rule violation for bot {event.bot_id}: {symbol_label}"
                        ),
                    )
                )
            elif action == RuleAction.STOP_BOT:
                await self._eventbus.publish(
                    BotStopEvent(
                        account_id=self._account_id,
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

        if event.account_id != self._account_id:
            return

        if self.rules_unavailable:
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
                    reason="account_not_ready: rules_unavailable",
                )
            )
            object.__setattr__(event, "_consumed", True)
            return

        if self._order_tracker is not None and not event.symbol and not event.side:
            try:
                record = await self._order_tracker.get(event.order_id)
            except Exception:
                logger.warning(
                    "주문 정정 메타 조회 실패: order=%s — symbol/side 미보강",
                    event.order_id,
                )
                record = None
            if record is not None and record.account_id == event.account_id:
                object.__setattr__(event, "symbol", record.symbol)
                object.__setattr__(event, "side", record.side)

        if not _is_finite_quantity(event.price) or event.price <= 0:
            logger.warning(
                "주문 정정 거부(무효 가격): order=%s — %s",
                event.order_id,
                _safe_repr(event.price),
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
                    reason="modify_invalid_args",
                )
            )
            object.__setattr__(event, "_consumed", True)
            return

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

        treasury_data, _ = await self._query_treasury_data(bot_id=event.bot_id)

        modify_price = float(event.price)
        unrealized_pnl = (
            await self._calculate_bot_unrealized_pnl(
                bot_id=event.bot_id,
                current_price=modify_price,
                order_symbol=event.symbol,
            )
            or 0.0
        )
        daily_pnl = await self._query_daily_realized_pnl() or 0.0

        context = RuleContext(
            bot_id=event.bot_id,
            account_id=self._account_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            order_type="limit",
            price=event.price,
            current_price=modify_price,
            account_status=account_status,
            currency=currency,
            unrealized_pnl=unrealized_pnl,
            daily_pnl=daily_pnl,
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
            object.__setattr__(event, "_consumed", True)

    def _release_rules_unavailable(self, category: str) -> None:
        """``rule`` category 재로드가 성공했으면 룰 로드 실패 상태를 푼다."""
        if category != "rule" or not self.rules_unavailable:
            return
        self._rules_unavailable_cause = None
        logger.info(
            "계좌 룰 로드 실패 상태 해제: account=%s, rules=%s",
            self._account_id,
            [rule.config.get("type") for rule in self._account_rules],
        )

    def _swap_account_rules(self, new_rules: list[dict[str, Any]]) -> str | None:
        """새 계좌 룰을 다 만든 뒤에만 바꿔 끼운다. 실패하면 예외 타입 이름을 낸다."""
        try:
            effective = new_rules
            if self._account is not None:
                from ante.rule.defaults import resolve_effective_rules

                effective = resolve_effective_rules(self._account, new_rules)
            rules = self._build_rules(effective)
        except Exception as exc:
            logger.error(
                "계좌 룰 재로드 실패 — 이전 룰 유지: account=%s",
                self._account_id,
                exc_info=True,
            )
            return type(exc).__name__
        self._account_rules = rules
        logger.info("계좌 룰 재로드 완료: %d건", len(self._account_rules))
        return None

    def _reload_failed_message(self, error: str) -> str:
        """실행 중 계좌 룰 재로드 실패 알림 본문(저장값 원문 없음)."""
        state = (
            "이 계좌는 계속 주문이 막혀 있습니다."
            if self.rules_unavailable
            else "이전 규칙으로 계속 검증하며, 저장값을 고치지 않고 재기동하면 "
            "이 계좌의 주문이 막힙니다."
        )
        return (
            f"계좌 {self._account_id} 의 새 거래 규칙 저장값으로 규칙을 만들지 못해 "
            f"({error}) 바꾸지 않았습니다. {state} 오류 로그에서 문제의 항목을 "
            "확인하세요."
        )

    async def _on_config_changed(self, event: object) -> None:
        """설정 변경 시 룰 재로딩."""
        import json

        from ante.eventbus.events import ConfigChangedEvent, NotificationEvent

        if not isinstance(event, ConfigChangedEvent):
            return
        if event.category not in ("rule", "strategy_rule"):
            return

        if event.category == "rule":
            expected_key = account_rules_config_key(self._account_id)
            if event.key != expected_key:
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

        if event.category == "rule":
            error = self._swap_account_rules(new_rules)
            if error is not None:
                await self._eventbus.publish(
                    NotificationEvent(
                        level="error",
                        title="계좌 규칙을 다시 읽지 못함 — 이전 규칙 유지",
                        message=self._reload_failed_message(error),
                        category="system",
                    )
                )
                return
            self._release_rules_unavailable(event.category)
        elif event.category == "strategy_rule":
            parts = event.key.rsplit(".", 1)
            strategy_id = parts[-1] if len(parts) > 1 else event.key
            self.load_strategy_rules_from_config(strategy_id, new_rules)
            logger.info(
                "전략 룰 재로드 완료: strategy=%s, %d건",
                strategy_id,
                len(self._strategy_rules.get(strategy_id, [])),
            )
