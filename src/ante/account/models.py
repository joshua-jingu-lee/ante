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


class TradingMode(StrEnum):
    """거래 모드."""

    VIRTUAL = "virtual"
    LIVE = "live"


@dataclass
class Account:
    """계좌 엔티티.

    거래소, 통화, 브로커, 수수료, 인증 정보를 하나로 묶는 최상위 엔티티.
    """

    # --- 식별 ---
    account_id: str
    name: str

    # --- 시장 ---
    exchange: str
    currency: str
    timezone: str = "Asia/Seoul"
    trading_hours_start: str = "09:00"
    trading_hours_end: str = "15:30"

    # --- 거래 모드 ---
    trading_mode: TradingMode = TradingMode.VIRTUAL

    # --- 브로커 ---
    broker_type: str = "test"
    credentials: dict[str, str] = field(default_factory=dict)
    broker_config: dict[str, Any] = field(default_factory=dict)

    # --- 비용 ---
    buy_commission_rate: Decimal = Decimal("0")
    sell_commission_rate: Decimal = Decimal("0")
    # 시장가 매수 주문 reserve buffer 비율 (Account-level Treasury reserve policy).
    # 시장가 매수는 체결 가격이 보장되지 않으므로 현재가만으로 reserve하면 부족할
    # 수 있다. Treasury는 ``reserve_basis = quantity * quote * (1 + buffer)``
    # 식으로 자금을 보수적으로 잠근다. ``broker_config``에 들어가지 않으며,
    # 1.0에서는 cold-path 전용(structural) 필드다 (#1333).
    market_order_reserve_buffer_rate: Decimal = Decimal("0")

    # --- 상태 ---
    status: AccountStatus = AccountStatus.ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # --- 진단 플래그 (#1474) ---
    # DB row 의 ``timezone`` 컬럼이 invalid IANA 값으로 저장되어 있어
    # ``_row_to_account`` 가 fallback timezone (:data:`DEFAULT_FALLBACK_TIMEZONE`)
    # 으로 대체한 경우 ``True`` 다. ``False`` 가 default 이며, 정상 row 와
    # in-memory 신규 생성에는 영향이 없다.
    #
    # 의미론: ``True`` 일 때 ``timezone`` 필드는 fallback 값이고, 원본 DB row
    # 는 그대로 invalid 상태로 남아 있다. 운영자는 ``ante account repair-timezone``
    # 으로 명시적으로 row 값을 valid 로 교정해야 플래그가 재로드 시 다시
    # ``False`` 가 된다 (silent rewrite 금지).
    #
    # ``IMMUTABLE_FIELDS`` / ``STRUCTURAL_FIELDS`` / ``MUTABLE_FIELDS`` 어느
    # 분류에도 포함되지 않으며 PUT/CLI update 입력으로 받지 않는다 — 진단 전용
    # 필드라 외부에서 직접 변경하지 않는다.
    timezone_invalid: bool = False


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
    # 시장가 매수 reserve buffer 비율의 broker별 기본값. Account 생성 시 이
    # 값이 ``Account.market_order_reserve_buffer_rate``의 초기값으로 사용된다
    # (#1333).
    market_order_reserve_buffer_rate: Decimal
    default_account_id: str
    default_name: str
    required_credentials: list[str]
