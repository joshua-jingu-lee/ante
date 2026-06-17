"""TreasuryManager -- 계좌별 Treasury 인스턴스 관리."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ante.treasury.treasury import Treasury

if TYPE_CHECKING:
    from ante.account.models import Account
    from ante.account.readiness import RuntimeReadinessRegistry
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.trade.order_tracker import OrderTracker

logger = logging.getLogger(__name__)


class TreasuryManager:
    """계좌별 Treasury 인스턴스를 생성하고 관리하는 상위 계층."""

    def __init__(
        self,
        db: Database,
        eventbus: EventBus,
        *,
        order_tracker: OrderTracker | None = None,
        runtime_readiness: RuntimeReadinessRegistry | None = None,
    ) -> None:
        self._db = db
        self._eventbus = eventbus
        # #1947: 부분체결 비례 정산용 OrderTracker 를 각 Treasury 에 주입한다.
        # 단일 인스턴스(account-agnostic — PK 가 전역 유일 order_id)를 공유한다.
        self._order_tracker = order_tracker
        # #2398 D-ACC-09 축 ii: active-order readiness gate(계층2) reader 를 각
        # Treasury 에 pass-through 한다. broker_type/trading_mode 는 account 메타
        # (immutable)에서 per-Treasury 주입한다. main(s.runtime_readiness) 경유.
        self._runtime_readiness = runtime_readiness
        self._treasuries: dict[str, Treasury] = {}

    async def create_treasury(self, account: Account) -> Treasury:
        """Account 정보로 Treasury 인스턴스 생성 및 등록.

        Args:
            account: Account 엔티티. account_id, currency, commission, market
                buy reserve buffer 정보 사용.

        Returns:
            생성된 Treasury 인스턴스.
        """
        treasury = Treasury(
            db=self._db,
            eventbus=self._eventbus,
            account_id=account.account_id,
            currency=account.currency,
            buy_commission_rate=float(account.buy_commission_rate),
            sell_commission_rate=float(account.sell_commission_rate),
            market_order_reserve_buffer_rate=account.market_order_reserve_buffer_rate,
            order_tracker=self._order_tracker,
            # #2398: 계층2 gate reader + 면제 매트릭스 판정용 account 메타(immutable).
            runtime_readiness=self._runtime_readiness,
            broker_type=account.broker_type,
            trading_mode=account.trading_mode,
        )
        await treasury.initialize()
        self._treasuries[account.account_id] = treasury
        logger.info("Treasury 생성: account_id=%s", account.account_id)
        return treasury

    def set_order_reserve_price_resolver(
        self,
        account_id: str,
        resolver: Callable[[str], Awaitable[float]],
    ) -> None:
        """특정 계좌의 Treasury 에 시장가 매수 reserve estimate 용 resolver 주입.

        ``main._init_gateway()`` 끝에서 account-scoped wrapper 로 호출된다 — 부팅
        순서상 ``initialize_all`` 직후에는 APIGateway 가 아직 준비되지 않았기
        때문이다 (#1333). resolver 미주입 상태에서 시장가 매수 + price=None
        시도가 들어오면 Treasury 가 terminal ``market_buy_quote_unavailable`` 로
        거부한다.

        Raises:
            KeyError: 해당 계좌의 Treasury 가 등록돼 있지 않을 때.
        """
        if account_id not in self._treasuries:
            raise KeyError(f"Treasury not found: account_id={account_id}")
        self._treasuries[account_id].set_order_reserve_price_resolver(resolver)
        logger.info(
            "TreasuryManager: order_reserve_price_resolver 주입 완료 (account=%s)",
            account_id,
        )

    def get(self, account_id: str) -> Treasury:
        """계좌의 Treasury 인스턴스 반환.

        Args:
            account_id: 계좌 ID.

        Returns:
            Treasury 인스턴스.

        Raises:
            KeyError: 해당 계좌의 Treasury가 없을 때.
        """
        if account_id not in self._treasuries:
            raise KeyError(f"Treasury not found: account_id={account_id}")
        return self._treasuries[account_id]

    def list_all(self) -> list[Treasury]:
        """전체 Treasury 인스턴스 목록."""
        return list(self._treasuries.values())

    async def initialize_all(self, accounts: list[Account]) -> None:
        """각 계좌에 대해 Treasury 인스턴스 생성 및 초기화.

        Args:
            accounts: Account 엔티티 목록.
        """
        for account in accounts:
            await self.create_treasury(account)
        logger.info("전체 Treasury 초기화 완료: %d개 계좌", len(accounts))

    async def get_total_summary(self) -> dict[str, Any]:
        """전 계좌 합산 요약.

        Returns:
            각 계좌의 요약 정보를 포함하는 딕셔너리.
        """
        accounts_summary = []
        for treasury in self._treasuries.values():
            summary = treasury.get_summary()
            accounts_summary.append(
                {
                    "account_id": treasury.account_id,
                    "currency": treasury.currency,
                    "total_evaluation": summary["total_evaluation"],
                }
            )

        return {"accounts": accounts_summary}
