"""TreasuryManager -- 계좌별 Treasury 인스턴스 관리."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.treasury.treasury import Treasury

if TYPE_CHECKING:
    from ante.account.models import Account
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


class TreasuryManager:
    """계좌별 Treasury 인스턴스를 생성하고 관리하는 상위 계층."""

    def __init__(self, db: Database, eventbus: EventBus) -> None:
        self._db = db
        self._eventbus = eventbus
        self._treasuries: dict[str, Treasury] = {}

    async def create_treasury(self, account: Account) -> Treasury:
        """Account 정보로 Treasury 인스턴스 생성 및 등록.

        Args:
            account: Account 엔티티. account_id, currency, commission 정보 사용.

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
        )
        await treasury.initialize()
        self._treasuries[account.account_id] = treasury
        logger.info("Treasury 생성: account_id=%s", account.account_id)
        return treasury

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
