"""RuleEngineManager — 계좌별 RuleEngine 인스턴스 관리."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ante.rule.config_update import account_rules_config_key
from ante.rule.defaults import resolve_effective_rules
from ante.rule.engine import RuleEngine

if TYPE_CHECKING:
    from ante.account.models import Account
    from ante.account.readiness import RuntimeReadinessRegistry
    from ante.account.service import AccountService
    from ante.eventbus.bus import EventBus
    from ante.instrument.service import InstrumentService
    from ante.trade.order_tracker import OrderTracker
    from ante.trade.service import TradeService
    from ante.treasury import TreasuryManager as TreasuryManagerType

logger = logging.getLogger(__name__)

_ABSENT = object()


class RuleEngineManager:
    """계좌별 RuleEngine 인스턴스를 관리하는 상위 계층."""

    def __init__(
        self,
        eventbus: EventBus,
        account_service: AccountService,
        treasury_manager: TreasuryManagerType | None = None,
        trade_service: TradeService | None = None,
        order_tracker: OrderTracker | None = None,
        unrecovered_buy_guard_min_age: float = 60.0,
        allow_unrecovered_buy_overlap: bool = False,
        instrument_service: InstrumentService | None = None,
        runtime_readiness: RuntimeReadinessRegistry | None = None,
    ) -> None:
        self._eventbus = eventbus
        self._account_service = account_service
        self._treasury_manager = treasury_manager
        self._trade_service = trade_service
        self._order_tracker = order_tracker
        self._unrecovered_buy_guard_min_age = unrecovered_buy_guard_min_age
        self._allow_unrecovered_buy_overlap = allow_unrecovered_buy_overlap
        self._instrument_service = instrument_service
        self._runtime_readiness = runtime_readiness
        self._engines: dict[str, RuleEngine] = {}

    def create_engine(
        self,
        account_id: str,
        rule_configs: list[dict[str, Any]] | None = None,
        *,
        account: Account | None = None,
    ) -> RuleEngine:
        """계좌별 RuleEngine 생성. EventBus에 자동 구독.

        Args:
            account: 계좌 snapshot. 전달되면 RuleEngine에 캐시되어 reload
                경로(``_on_config_changed``)에서 broker_type별 default를 다시
                merge할 때 사용된다. ``None``이면 reload 경로는 stored 그대로
                적용 (하위 호환).
        """
        treasury = None
        if self._treasury_manager is not None:
            try:
                treasury = self._treasury_manager.get(account_id)
            except KeyError:
                logger.warning("Treasury 없음: account=%s", account_id)

        engine = RuleEngine(
            eventbus=self._eventbus,
            account_id=account_id,
            account_service=self._account_service,
            treasury=treasury,
            trade_service=self._trade_service,
            account=account,
            order_tracker=self._order_tracker,
            unrecovered_buy_guard_min_age=self._unrecovered_buy_guard_min_age,
            allow_unrecovered_buy_overlap=self._allow_unrecovered_buy_overlap,
            instrument_service=self._instrument_service,
            runtime_readiness=self._runtime_readiness,
        )

        if rule_configs:
            engine.load_rules_from_config(rule_configs)

        engine.start()
        self._engines[account_id] = engine

        logger.info(
            "RuleEngine 생성: account=%s, 룰 %d건",
            account_id,
            len(rule_configs) if rule_configs else 0,
        )
        return engine

    def get(self, account_id: str) -> RuleEngine:
        """계좌의 RuleEngine 인스턴스 반환.

        Raises:
            KeyError: 해당 계좌의 RuleEngine이 없음.
        """
        if account_id not in self._engines:
            raise KeyError(f"account '{account_id}'의 RuleEngine이 존재하지 않습니다.")
        return self._engines[account_id]

    def set_market_price_resolver(
        self, account_id: str, resolver: Callable[[str], Awaitable[float]]
    ) -> None:
        """계좌의 RuleEngine에 시장가 매수 평가용 현재가 조회를 주입한다.

        Raises:
            KeyError: 해당 계좌의 RuleEngine이 없음.
        """
        self.get(account_id).set_market_price_resolver(resolver)

    async def aclose(self) -> None:
        """모든 RuleEngine의 진행 중인 시세 조회를 정리한다."""
        for engine in list(self._engines.values()):
            await engine.aclose()

    async def initialize_all(
        self,
        accounts: list[Account],
        config: Any = None,
        dynamic_config: Any = None,
    ) -> None:
        """시스템 시작 시 모든 계좌의 RuleEngine 초기화.

        Stored rules 우선순위: ``dynamic_config`` 행(사용자가 명시적으로 비활성화한
        룰이 default 재주입으로 되살아나지 않도록 static보다 우선) → 정적 ``config``
        seed → broker_type별 default. ``dynamic_config`` 행의 값이 리스트가 아니거나
        조회가 예외를 내거나, 항목으로 룰을 만들지 못하면 그 계좌만 계좌 룰 없이
        ``rules_unavailable`` 엔진으로 둔다.
        """
        for account in accounts:
            key = account_rules_config_key(account.account_id)
            stored_rules: list[dict[str, Any]] | None = None

            if dynamic_config is not None:
                cause: str | None = None
                try:
                    dyn_rules = await dynamic_config.get(key, default=_ABSENT)
                except Exception as exc:
                    cause = f"read_error:{type(exc).__name__}"
                else:
                    if isinstance(dyn_rules, list):
                        stored_rules = dyn_rules
                    elif dyn_rules is not _ABSENT:
                        cause = f"not_list:{type(dyn_rules).__name__}"
                if cause is not None:
                    logger.error(
                        "계좌 룰을 로드하지 못해 주문 차단: account=%s, cause=%s",
                        account.account_id,
                        cause,
                    )
                    self._create_blocked_engine(account, cause)
                    continue

            if stored_rules is None and config is not None and hasattr(config, "get"):
                account_rules = config.get(key, None)
                if isinstance(account_rules, list):
                    stored_rules = account_rules

            self._create_engine_or_block(account, stored_rules)

        logger.info("RuleEngineManager 초기화 완료: %d개 계좌", len(self._engines))

    def _create_engine_or_block(
        self, account: Account, stored_rules: list[dict[str, Any]] | None
    ) -> None:
        """룰을 만들 수 없으면 그 계좌만 ``invalid_item`` 차단 엔진으로 둔다."""
        try:
            rule_configs = resolve_effective_rules(account, stored_rules)
            self.create_engine(account.account_id, rule_configs, account=account)
        except Exception as exc:
            cause = f"invalid_item:{type(exc).__name__}"
            logger.error(
                "계좌 룰을 로드하지 못해 주문 차단: account=%s, cause=%s",
                account.account_id,
                cause,
                exc_info=True,
            )
            self._create_blocked_engine(account, cause)

    def _create_blocked_engine(self, account: Account, cause: str) -> None:
        """계좌 룰 없이 ``rules_unavailable`` 엔진을 만든다(``cause``는 원인:상세)."""
        engine = self.create_engine(account.account_id, None, account=account)
        engine.mark_rules_unavailable(cause.split(":", 1)[0])

    def rules_unavailable_accounts(self) -> dict[str, str]:
        """막힌 계좌 ID → 원인(``not_list`` | ``read_error`` | ``invalid_item``)."""
        return {
            account_id: engine.rules_unavailable_cause
            for account_id, engine in self._engines.items()
            if engine.rules_unavailable_cause is not None
        }

    @property
    def engines(self) -> dict[str, RuleEngine]:
        """모든 RuleEngine 인스턴스 (읽기 전용 접근)."""
        return dict(self._engines)
