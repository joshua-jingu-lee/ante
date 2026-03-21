"""RuleEngineManager — 계좌별 RuleEngine 인스턴스 관리."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.rule.engine import RuleEngine

if TYPE_CHECKING:
    from ante.account.models import Account
    from ante.account.service import AccountService
    from ante.eventbus.bus import EventBus
    from ante.treasury import TreasuryManager as TreasuryManagerType

logger = logging.getLogger(__name__)


class RuleEngineManager:
    """계좌별 RuleEngine 인스턴스를 관리하는 상위 계층."""

    def __init__(
        self,
        eventbus: EventBus,
        account_service: AccountService,
        treasury_manager: TreasuryManagerType | None = None,
    ) -> None:
        self._eventbus = eventbus
        self._account_service = account_service
        self._treasury_manager = treasury_manager
        self._engines: dict[str, RuleEngine] = {}

    def create_engine(
        self,
        account_id: str,
        rule_configs: list[dict[str, Any]] | None = None,
    ) -> RuleEngine:
        """계좌별 RuleEngine 생성. EventBus에 자동 구독.

        Args:
            account_id: 계좌 ID.
            rule_configs: 계좌 룰 설정 리스트. None이면 빈 룰.

        Returns:
            생성된 RuleEngine 인스턴스.
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

    async def initialize_all(
        self,
        accounts: list[Account],
        config: Any = None,
    ) -> None:
        """시스템 시작 시 모든 계좌의 RuleEngine 초기화.

        각 계좌에 대해 RuleEngine을 생성하고, 계좌별 룰 설정을 로드한다.

        Args:
            accounts: 초기화할 계좌 목록.
            config: 전체 설정 객체 (룰 설정 추출용). None이면 빈 룰.
        """
        for account in accounts:
            rule_configs: list[dict[str, Any]] = []

            # config에서 계좌별 룰 설정 추출
            if config is not None and hasattr(config, "get"):
                account_rules = config.get(f"accounts.{account.account_id}.rules", None)
                if isinstance(account_rules, list):
                    rule_configs = account_rules

            self.create_engine(account.account_id, rule_configs)

        logger.info("RuleEngineManager 초기화 완료: %d개 계좌", len(self._engines))

    @property
    def engines(self) -> dict[str, RuleEngine]:
        """모든 RuleEngine 인스턴스 (읽기 전용 접근)."""
        return dict(self._engines)
