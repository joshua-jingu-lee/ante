"""Account 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class AccountStatus(StrEnum):
    """계좌 상태."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


ACCOUNT_STATUS_TRANSITIONS: dict[AccountStatus, set[AccountStatus]] = {
    AccountStatus.ACTIVE: {AccountStatus.SUSPENDED, AccountStatus.DELETED},
    AccountStatus.SUSPENDED: {AccountStatus.ACTIVE, AccountStatus.DELETED},
    AccountStatus.DELETED: set(),
}


class TradingMode(StrEnum):
    """거래 모드."""

    VIRTUAL = "virtual"
    LIVE = "live"


@dataclass
class Account:
    """계좌 엔티티.

    거래소, 통화, 브로커, 수수료, 인증 정보를 하나로 묶는 최상위 엔티티.
    """

    account_id: str
    name: str

    exchange: str
    currency: str
    timezone: str = "Asia/Seoul"
    timezone_invalid: bool = False
    trading_hours_start: str = "09:00"
    trading_hours_end: str = "15:30"

    trading_mode: TradingMode = TradingMode.VIRTUAL

    broker_type: str = "test"
    credentials: dict[str, str] = field(default_factory=dict)
    broker_config: dict[str, Any] = field(default_factory=dict)

    buy_commission_rate: Decimal = Decimal("0")
    sell_commission_rate: Decimal = Decimal("0")
    market_order_reserve_buffer_rate: Decimal = Decimal("0")

    status: AccountStatus = AccountStatus.ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class BrokerPreset:
    """브로커별 기본값 프리셋.

    계좌 생성 시 브로커 선택만으로 나머지 필드를 자동으로 채운다.
    """

    exchange: str
    currency: str
    timezone: str
    trading_hours_start: str
    trading_hours_end: str
    buy_commission_rate: Decimal
    sell_commission_rate: Decimal
    market_order_reserve_buffer_rate: Decimal
    default_account_id: str
    default_name: str
    required_credentials: list[str]
