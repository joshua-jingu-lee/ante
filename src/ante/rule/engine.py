"""RuleEngine — 2계층 룰 평가 엔진."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeGuard

from ante.core.market_data_vocab import is_krx_symbol
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
    from ante.account.models import Account
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
#
# 형태 검증은 코드 레벨 SSOT(`ante.core.market_data_vocab.is_krx_symbol`)에
# 위임한다. `is_krx_symbol` 은 `\A[0-9]{6}\Z` + `fullmatch` + non-str
# 선검사로 구현되어 위임 전 `_KRX_NUMERIC_SYMBOL_PATTERN.fullmatch` 와
# 엄격도가 동일하다 — `123456\n`·leading/trailing whitespace·비문자열은
# 위임 전후 모두 fail-closed로 거부된다(#1613 narrow-scope: #1299 동작 불변).


def _is_finite_quantity(value: object) -> TypeGuard[int | float]:
    """``value``가 finite ``float``-호환 quantity인지 판정.

    비-number, ``bool``, ``NaN``, ``inf``는 모두 ``False``로 잠근다.
    Python ``int``는 임의 정밀도라 ``10**10000`` 같은 거대한 정수는
    ``math.isfinite`` 호출 시 ``float(value)`` 변환에서
    ``OverflowError`` (또는 ``ValueError``/``TypeError``)를 던진다 (#1302 P2).
    이때도 finite-호환이 아니므로 ``False``로 떨어뜨려 호출부가
    fail-closed reject 경로로 빠지게 한다. helper 자체가 절대 raise하지 않는
    invariant를 유지하여 outer try 유무와 관계없이 정상 동작을 보장한다.

    ``isinstance(True, int) == True`` 이므로 ``bool``을 명시적으로 제외한다.
    ``math.isfinite``는 numeric type 확인 뒤에만 호출한다 (가드 순서 중요).

    반환 타입은 ``TypeGuard[int | float]``로 선언하여 mypy가 호출부 ``True``
    분기에서 ``value``를 ``int | float``로 좁히게 한다 (#1302 P1 #5). 이를
    통해 ``_coerce_finite_quantity``의 ``float(value)``가 ``object`` 인자
    overload 미스매치 없이 통과한다.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError, TypeError):
        return False


def _coerce_finite_quantity(value: object) -> float:
    """``OrderRejectedEvent.quantity`` payload용 안전한 finite ``float`` 변환.

    비-number, ``bool``, ``NaN``, ``inf``, 그리고 ``float`` 변환 시
    ``OverflowError``를 유발하는 거대 ``int`` (#1302 P2)는 ``0.0``으로
    정규화한다. ``trades.quantity REAL NOT NULL`` 컬럼 호환을 보장하여,
    임의의 cross-field invalid payload (#1297/#1298/#1299/#1300/#1301)에서
    quantity 자리에 비-finite 값이 함께 실려도 audit trail이 깨지지 않는다.

    판정은 ``_is_finite_quantity``에 위임하여 단일 진입점을 유지한다.
    """
    if not _is_finite_quantity(value):
        return 0.0
    return float(value)


def _coerce_finite_optional_price(value: object) -> float | None:
    """``OrderRejectedEvent.price`` payload용 안전한 ``float | None`` 정규화.

    회귀(#1302 P2 #4): 본 PR 이전에는 ``_build_safe_rejected_event``가
    ``price=getattr(event, "price", None)``로 원본 값을 그대로 전파했다.
    ``price=float("nan")`` / ``inf``, 또는 ``list``/``dict``/``str``/``bool``
    같은 비-number truthy 값이 들어오면 ``TradeRecorder``의 ``event.price or
    0.0`` 처리(NaN과 비빈 list는 truthy)에서 그대로 sqlite ``trades.price
    REAL`` 컬럼에 bind 시도되어 ``InterfaceError`` 또는 NaN 저장을 유발해
    PnL 계산이 깨지고, 본 PR이 보장하려는 reject audit trail도 깨진다.

    ``None``은 그대로 통과시킨다 — market 주문 등 정상 흐름에서 ``price=None``
    이 유효하므로, invalid 케이스도 ``None``으로 떨어뜨려 ``trades.price``
    컬럼(nullable)과 호환을 유지한다. finite numeric은 ``float``로 보존하여
    정상 reject payload를 깨뜨리지 않는다.

    ``OrderRejectedEvent.stop_price`` 필드는 스키마에 존재하지 않고 builder도
    싣지 않으므로 본 helper의 cover 범위 밖이다 (#1301 plan 확인).
    """
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
    """sqlite ``TEXT`` 컬럼 바인딩용 안전한 ``str`` 정규화.

    Python 3.13의 ``int`` ↔ ``str`` 변환 4300자리 제한
    (``sys.set_int_max_str_digits``), 사용자 정의 ``__repr__``가 raise하는
    모든 경우, ``MemoryError``까지 포괄한다. builder가 절대 raise하지 않는
    invariant를 지키기 위한 단일 진입점.

    ``str``은 그대로 통과시켜 sqlite ``TEXT`` 컬럼 호환을 유지하고
    (``"hold"``→``"hold"``), 그 외 값은 ``repr()`` 시도 후 실패 시
    ``"<unrenderable {type}>"`` placeholder로 떨어뜨린다.

    ``reason`` 메시지 조립에는 quote 보존이 필요하므로 ``_safe_repr``를 사용한다
    (``"hold"``→``"'hold'"``).
    """
    if isinstance(value, str):
        return value
    try:
        return repr(value)
    except Exception:  # noqa: BLE001
        # 사용자 정의 ``__repr__``이 임의의 예외를 던질 수 있으므로
        # ``BaseException``을 제외한 모든 예외를 잡아 placeholder로 떨어뜨린다.
        # builder가 절대 raise하지 않는 invariant 유지.
        return f"<unrenderable {type(value).__name__}>"


def _safe_repr(value: object) -> str:
    """``reason`` 메시지 조립용 안전한 ``repr``-스타일 변환.

    ``_safe_str``과 달리 ``str``도 quote로 감싼 ``repr`` 형태로 반환하여
    ``"Invalid signal side: 'hold' (allowed: ...)"`` 같은 audit-friendly 포맷을
    유지한다. 사용자 정의 ``__repr__``이 임의의 예외를 던져도 잡아 placeholder
    로 떨어뜨린다 (``BaseException`` 제외). builder의 raise-free invariant와
    동일한 보호.

    builder에는 사용하지 않는다 (sqlite 컬럼 호환은 ``_safe_str`` 책임).
    """
    try:
        return repr(value)
    except Exception:  # noqa: BLE001
        return f"<unrenderable {type(value).__name__}>"


def _safe_order_id(value: object) -> str:
    """``OrderRejectedEvent.order_id`` 바인딩용 안전한 평문 ``str`` 변환.

    ``UUID`` 같은 ``__str__``이 안정적인 객체는 ``str()`` 결과를 그대로 사용
    (``UUID(...)`` 같은 ``repr`` 형식이 아닌 ``"058c026b-..."`` 평문). ``str``은
    그대로 통과시키고, ``__str__``이 raise하면 ``repr`` 시도 후 placeholder로
    떨어진다. builder가 절대 raise하지 않는 invariant 유지.
    """
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        try:
            return repr(value)
        except Exception:  # noqa: BLE001
            return f"<unrenderable {type(value).__name__}>"


def _build_safe_rejected_event(
    *,
    account_id: str,
    event: object,
    reason: str,
) -> Any:
    """모든 source 필드를 정규화한 fail-closed ``OrderRejectedEvent`` 빌더.

    builder 자체가 절대 raise하지 않는다 (#1302 메타 리뷰). 호출자는 catch-all
    ``except`` 안에서 안전하게 호출할 수 있다.

    - ``symbol`` / ``side`` / ``order_type`` / ``bot_id`` / ``strategy_id`` /
      ``exchange``: ``_safe_str``로 정규화 (sqlite ``TEXT`` 컬럼 호환).
    - ``quantity``: ``_coerce_finite_quantity``로 finite ``float`` 정규화
      (NaN/inf/비-number/large-int 모두 0.0).
    - ``price``: ``_coerce_finite_optional_price``로 finite ``float | None``
      정규화 (NaN/inf/비-number/large-int 모두 ``None``). ``trades.price``
      sqlite REAL 컬럼(nullable) 호환 + ``TradeRecorder``의 ``event.price
      or 0.0`` 처리에서도 NaN/비-number bind를 차단한다 (#1302 P2 #4).
    - ``order_id``: ``getattr``+``_safe_str`` (``event_id``가 없거나 raise하는
      pathological 상황 대응).
    - ``reason``: 호출자가 미리 만든 문자열. 호출자도 ``_safe_str`` 사용 권장.
    """
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
        account: Account | None = None,
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
        # Account snapshot — reload 경로(``_on_config_changed``)에서 broker_type별
        # default를 다시 merge할 때 참조한다. 생명주기 동안 broker_type 불변 가정.
        # 기존 호출자(테스트 fixture 등) 호환을 위해 ``None`` 허용 — None일 때
        # reload 경로는 helper를 우회하여 stored 그대로 적용한다 (#1296).
        self._account = account

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
            # account_id 스코핑(#2140): RuleEngine은 계좌별 인스턴스이므로,
            # 같은 bot_id를 공유하는 타 계좌 포지션이 미실현 손익에 혼입되어
            # UnrealizedLossLimitRule이 오판하지 않도록 자기 계좌로 한정한다.
            positions = await self._trade_service.get_positions(
                bot_id, account_id=self._account_id
            )
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
        """OrderRequestEvent 수신 시 룰 평가 후 결과 이벤트 발행.

        구조 invariant (#1302 메타 리뷰): isinstance/account_id 필터링 직후부터
        모든 preflight 게이트(#1297-#1302) + evaluate + Treasury 조회 + reject
        경로 전체를 단일 ``try`` 블록으로 감싼다. 게이트별 ``raise`` (예: f-string
        ``repr`` 시 ``OverflowError``, 사용자 정의 ``__repr__`` 예외 등)가 EventBus
        핸들러까지 leak되어 ``OrderRejectedEvent`` 발행이 swallow되면 audit
        trail이 끊겨 fail-open이 된다. catch-all ``except``가 잡아 ``_build_safe_
        rejected_event`` (절대 raise하지 않는 builder)로 generic reject를
        강제 발행하는 것이 본 함수의 핵심 invariant.

        Pathological large-int 등 strategy 코드가 정상적으로 만들 수 없는 입력은
        catch-all builder가 receive하며, 게이트별 typed reject reason은 강제하지
        않는다.
        """
        from ante.eventbus.events import (
            NotificationEvent,
            OrderRequestEvent,
            OrderValidatedEvent,
        )

        if not isinstance(event, OrderRequestEvent):
            return

        # account_id 필터링: 자기 계좌 이벤트만 처리
        if event.account_id != self._account_id:
            return

        try:
            # OrderRequestEvent 계약 preflight: Signal.side 허용값 검증.
            # docs/specs/strategy/03-02-signal-fields.md — side ∈ {"buy", "sell"}.
            # 룰 평가/Treasury 조회 이전에 거부하여 사이드이펙트(예약/주문) 차단.
            # `isinstance(..., str)` 가드로 list/dict 같은 unhashable 값이 들어와도
            # frozenset membership 검사가 TypeError를 raise하지 않도록 한다.
            if not isinstance(event.side, str) or event.side not in _VALID_ORDER_SIDES:
                # cross-field 보강(#1297/#1298/#1299): side만 invalid해도 동시에
                # order_type/symbol까지 비문자열이면 reject 이벤트가 broken되므로
                # builder가 모든 sqlite TEXT NOT NULL 필드를 _safe_str로 정규화.
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

            # OrderRequestEvent 계약 preflight: KRX numeric symbol 검증.
            # 회귀(#1299): A7 oracle이 검출한 버그 — Signal.symbol="INVALID",
            # exchange="KRX" 주문이 RuleEngine→Treasury→broker까지 진행되어
            # KIS 40070000(매매불가 종목)이 발생했다. 현재 Ante KIS-domestic 경로는
            # 6자리 숫자 PDNO(예: "005930", "069500")만 가정하므로, 그 형식을
            # 만족하지 않는 KRX symbol은 룰 평가/Treasury 조회 이전에 fail-closed로
            # 거부한다. 비-KRX exchange는 broker adapter에 위임한다.
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

            # OrderRequestEvent 계약 preflight: limit / stop_limit price 필수.
            # 회귀(#1300): A7 oracle이 검출한 버그 — order_type="limit", side="sell",
            # price=None 주문이 RuleEngine→Treasury→broker까지 진행되어 KIS 호출
            # 단계에서 HTTP 500이 발생했다. limit / stop_limit는 가격 지정이
            # invariant이므로, price=None이면 룰 평가/Treasury 조회 이전에
            # fail-closed로 거부한다.
            # market의 price=None은 스펙상 옵션이므로 통과시키며, 0/음수/NaN/비-number
            # price 검증은 본 PR 범위 밖(#1303)이다.
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

            # OrderRequestEvent 계약 preflight: stop / stop_limit stop_price 필수.
            # 회귀(#1301): A7 oracle이 검출한 버그 — order_type="stop", side="sell",
            # stop_price=None 주문이 RuleEngine→OrderApproved→StopOrderRegistered까지
            # 진행되어 terminal event(체결/거부)가 누락되었다. stop / stop_limit는
            # 트리거 가격(stop_price) 지정이 invariant이므로, stop_price=None이면
            # 룰 평가/Treasury 조회 이전에 fail-closed로 거부한다. OrderRejectedEvent
            # 스키마에 stop_price 필드가 없으므로 reason 문자열에만 명시한다.
            # 0/음수/NaN stop_price 검증은 본 PR 범위 밖(별도 후속 이슈)이다.
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

            # OrderRequestEvent 계약 preflight: stop_price 값이 있으면 finite number.
            # 회귀(#1319 #1321 #1324): A7 oracle이 검출한 버그 —
            # Signal.stop_price=NaN/inf 또는 음수가 RuleEngine→OrderValidatedEvent까지
            # 진행되어 broker terminal_event 누락 또는 Treasury 거부로 누적됐다.
            # NaN/inf/non-number stop_price는 Treasury/Gateway 호출 이전에
            # fail-closed로 거부한다.
            #
            # _is_finite_quantity는 비-number/bool/NaN/inf 및 거대 정수
            # (float 변환 시 OverflowError)를 모두 함께 잠근다. None은 정상 흐름이며
            # 위 #1301 게이트가 None을 별도 처리한다.
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

            # OrderRequestEvent 계약 preflight: stop_price는 양수여야 한다.
            # 회귀(#1319 #1322): A7 oracle 회귀 — 음수 stop_price가 Treasury 예약/주문
            # 호출 이전에 fail-closed로 거부되어야 한다. stop_price는 위 finite 게이트로
            # 잠금됐으므로 < 0 비교는 안전하다. 0 stop_price 검증은 #1320 별도 이슈.
            #
            # OrderRejectedEvent 스키마에 stop_price 필드가 없으므로 reason 문자열에만
            # 음수 stop_price가 등장한다 (audit trail). _build_safe_rejected_event는
            # stop_price를 싣지 않으므로 변경하지 않는다 (선례 #1301 docstring).
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

            # OrderRequestEvent 계약 preflight: stop_price는 0이 아니어야 한다.
            # 회귀(#1320 #1323): A7 oracle이 검출한 버그 — Signal.stop_price=0
            # 주문이 RuleEngine→OrderValidatedEvent까지 진행되어 broker terminal_event
            # 누락 또는 Treasury 거부로 누적됐다. 0 stop_price는 무의미한 트리거이므로
            # Treasury 예약/주문 호출 이전에 fail-closed로 거부한다.
            #
            # stop_price는 #1319 finite 게이트에서 finite int|float로 잠금됐고, #1319
            # negative 게이트에서 음수가 거부됐으므로 본 게이트의 비교 대상은
            # 0, 0.0, -0.0이다. Python에서 0 == 0.0 == -0.0이 True이므로 == 0으로
            # 모두 잠근다 (선례 #1305/#1318 패턴). reason은 f-string으로 부호 보존.
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

            # OrderRequestEvent 계약 preflight: quantity는 finite number여야 한다.
            # 회귀(#1302): A7 oracle이 검출한 버그 — Signal.quantity=NaN,
            # side='buy', order_type='limit', price=1000 주문이 RuleEngine→
            # OrderValidatedEvent→Treasury 진입 후 sqlite
            # `bot_budgets.available NOT NULL` 위반으로 실패했다.
            # NaN/inf/non-number quantity는 Treasury 예약/주문 호출 이전에 fail-closed
            # 로 거부한다. 0/음수 quantity, NaN price 검증은 본 PR 범위 밖
            # (#1304/#1305/#1303)이다.
            #
            # _is_finite_quantity는 비-number/bool/NaN/inf뿐 아니라 ``10**10000``
            # 같은 거대 정수 (float 변환 시 ``OverflowError``)도 함께 잠근다 (#1302 P2).
            # 본 게이트가 outer try 블록 안에 있으므로 reason 조립의 ``_safe_str``
            # 가 raise해도 catch-all이 receive해 generic reject를 발행한다.
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

            # OrderRequestEvent 계약 preflight: price 값이 있으면 finite number.
            # 회귀(#1303): A7 oracle이 검출한 버그 — Signal.price=NaN, side='buy',
            # order_type='limit', quantity=1 주문이 RuleEngine→OrderValidatedEvent→
            # Treasury 진입 후 sqlite NOT NULL 위반으로 실패했다. NaN/inf/non-number
            # price는 Treasury 예약/주문 호출 이전에 fail-closed로 거부한다.
            #
            # ``price=None``은 정상 흐름이다 — market 주문은 None이 옵션이며,
            # limit/stop_limit의 price=None은 #1300 게이트가 별도 처리한다. 본
            # 게이트는 price 값이 있을 때만 finite numeric을 강제한다.
            #
            # ``_is_finite_quantity``는 비-number/bool/NaN/inf 및 ``10**400`` 같은
            # 거대 정수 (float 변환 시 ``OverflowError``)를 모두 함께 잠근다.
            # 0/음수 price 검증, NaN stop_price, OrderModifyEvent price 검증은
            # 본 PR 범위 밖(별도 후속 이슈)이다.
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

            # OrderRequestEvent 계약 preflight: price 값이 있으면 양수여야 한다.
            # 회귀(#1316): A7 oracle이 검출한 버그 — Signal.price=-1000, side='buy',
            # order_type='limit', quantity=1 주문이 RuleEngine→OrderValidatedEvent→
            # Treasury까지 진행되어 ``reserve_amount_invalid`` 거부 + 음수 reserve
            # 시도가 발생했다. 음수 price는 Treasury 예약/주문 호출 이전에
            # fail-closed로 거부한다.
            #
            # price는 #1303 게이트에서 finite ``int|float``로 잠금됐으므로
            # ``< 0`` 비교는 안전하다. market 옵션의 ``price=None``은 본 게이트
            # 진입 전에 통과되어 영향 없다. limit/stop_limit ``price=None``은
            # #1300 게이트가 별도 처리한다. 0/NaN price 검증은 본 PR 범위 밖
            # (#1303 finite는 NaN을 잠그고, 0은 #1318 별도 이슈).
            #
            # _build_safe_rejected_event는 invalid finite price를 보존하므로
            # ev.price 페이로드에는 음수 그대로 실린다 (audit-trail invariant 동일,
            # 선례 #1304 negative quantity와 일관).
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

            # OrderRequestEvent 계약 preflight: price는 0이 아니어야 한다.
            # 회귀(#1318): A7 oracle이 검출한 버그 — Signal.price=0 주문이 RuleEngine→
            # OrderValidatedEvent→Treasury까지 진행되어 reserve_amount_invalid
            # (total_reserve=0) 거부가 발생했다. 0 price는 무의미한 주문이므로
            # Treasury 예약/주문 호출 이전에 fail-closed로 거부한다.
            #
            # price는 #1303 게이트에서 finite int|float로 잠금됐고, #1316 게이트에서
            # 음수가 거부됐으므로 본 게이트의 비교 대상은 0, 0.0, -0.0이다.
            # Python에서 0 == 0.0 == -0.0이 True이므로 ``== 0``으로 모두 잠근다
            # (선례 #1305 zero quantity). reason은 f-string으로 실제 값을 보존하여
            # audit trail에서 0/0.0/-0.0를 구분한다.
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

            # OrderRequestEvent 계약 preflight: quantity는 양수여야 한다.
            # 회귀(#1304): A7 oracle이 검출한 버그 — Signal.quantity=-1, side='buy',
            # order_type='limit', price=1000 주문이 RuleEngine→OrderValidatedEvent→
            # Treasury까지 진행되어 ``reserve_amount_invalid``(total_reserve=-1000.15)
            # 거부 + 음수 예약 시도가 발생했다. 음수 quantity는 Treasury 예약/주문
            # 호출 이전에 fail-closed로 거부한다.
            #
            # quantity는 #1302 게이트에서 finite ``int|float``로 잠금됐으므로
            # ``< 0`` 비교는 안전하다. 도메인 가드를 분리하여 NaN/inf/non-number
            # (#1302) 와 음수(#1304)의 책임 영역을 명확히 한다. 0 quantity는
            # #1305 별도 이슈에서 처리된다.
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

            # OrderRequestEvent 계약 preflight: quantity는 0이 아니어야 한다.
            # 회귀(#1305): A7 oracle이 검출한 버그 — Signal.quantity=0 주문이
            # RuleEngine→OrderValidatedEvent→Treasury까지 진행되어
            # ``reserve_amount_invalid``(total_reserve=0.0) 거부가 발생했다.
            # 0 quantity는 no-op 주문이므로 Treasury 예약/주문 호출 이전에
            # fail-closed로 거부한다.
            #
            # quantity는 #1302 게이트에서 finite ``int|float``로 잠금됐고,
            # #1304 게이트에서 ``< 0``이 거부됐으므로 본 게이트의 비교 대상은
            # ``0``, ``0.0``, ``-0.0`` 등이다. Python에서
            # ``0 == 0.0 == -0.0``이 True이므로 ``== 0``으로 모두 잠근다.
            # reason은 f-string으로 실제 값을 보존하여 audit trail에서
            # ``0``/``0.0``/``-0.0``를 구분할 수 있게 한다.
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
                # 정상 흐름의 OrderValidatedEvent는 RuleEngine 내부 검증을
                # 통과한 OrderRequest에서만 가므로 quantity는 이미 finite로
                # 보장되지만, defensive 차원에서 builder를 적용해 audit
                # trail의 finite-float 불변성을 일관되게 잠근다 (#1302).
                await self._eventbus.publish(
                    _build_safe_rejected_event(
                        account_id=self._account_id,
                        event=event,
                        reason=result.rejection_reason,
                    )
                )
                await self._execute_actions(result.actions, event)

        except Exception:  # noqa: BLE001
            # catch-all (#1302 메타 리뷰 invariant): preflight 게이트나 evaluate
            # 단계 어디에서든 raise가 일어나도 audit trail이 fail-closed로
            # 잠기도록 generic reject를 강제 발행한다. builder는 절대 raise하지
            # 않으며, 만약 publish 자체가 raise해도 안쪽 try가 다시 잡아
            # logger.exception으로만 남긴다.
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
            except Exception:  # noqa: BLE001
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
                # 거부 시 이벤트 소비 — 후속 핸들러(Gateway)가 추가 terminal
                # event를 발행하지 않도록 transient marker를 set한다 (#1331).
                # ``OrderModifyEvent``는 ``_consumed`` 필드를 정의하지 않은
                # frozen dataclass이므로 ``hasattr`` guard를 두면 항상 False가
                # 되어 marker가 전혀 set되지 않는다 (dead code). 가드를 제거하고
                # ``object.__setattr__``로 직접 주입한다. dataclass 필드가
                # 아니므로 영속 history 직렬화에는 노출되지 않는다.
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
            # 룰 평가 예외 경로도 후속 Gateway가 추가 terminal event를 발행하지
            # 못하도록 transient marker를 set한다 (#1331). reason은 이미
            # ``"Rule evaluation error"``로 강제됐으므로 Gateway의
            # ``"modify_not_implemented"``가 같은 정정 요청에 중첩 발행되면
            # audit trail이 깨진다.
            object.__setattr__(event, "_consumed", True)

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

        # 다중 계좌 환경에서 ConfigChangedEvent는 모든 RuleEngine subscriber에게
        # broadcast된다. category="rule"은 계좌별 룰(`accounts.{account_id}.rules`)
        # 변경을 의미하므로, 자기 계좌 키가 아니면 무시해야 한다. 그렇지 않으면
        # 다른 계좌의 stored rules가 자기 effective rules로 잘못 merge되어
        # 계좌간 default rule(예: trading_hours)이 cross-contamination 된다 (#1296).
        if event.category == "rule":
            expected_key = f"accounts.{self._account_id}.rules"
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

        if event.category in ("rule", "global_rule"):
            self._account_rules.clear()
            # account snapshot이 있으면 broker_type별 default를 다시 merge하여
            # reload 후에도 effective rule 집합이 유지되도록 한다 (#1296).
            # account가 없는 호출자(테스트 fixture 등)에서는 기존 동작 유지.
            if self._account is not None:
                from ante.rule.defaults import resolve_effective_rules

                effective = resolve_effective_rules(self._account, new_rules)
                self.load_rules_from_config(effective)
            else:
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
