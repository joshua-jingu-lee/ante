"""#2398 active-order readiness gate 테스트 공유 빌더.

3계층(+G9) gate 테스트와, gate 도입으로 account 메타·ready registry 가 필요해진
기존 테스트가 공유하는 헬퍼다.
"""

from __future__ import annotations

from decimal import Decimal

from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.readiness import (
    ALL_FLAGS,
    ReadinessFlag,
    RuntimeReadinessRegistry,
    is_flag_exempt,
)


def make_account(
    account_id: str = "acc-001",
    *,
    broker_type: str = "kis-domestic",
    trading_mode: TradingMode = TradingMode.LIVE,
    status: AccountStatus = AccountStatus.ACTIVE,
) -> Account:
    """gate 테스트용 최소 Account 빌더."""
    return Account(
        account_id=account_id,
        name=account_id,
        exchange="KRX",
        currency="KRW",
        trading_mode=trading_mode,
        broker_type=broker_type,
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        status=status,
    )


def ready_registry(
    account_id: str = "acc-001",
    *,
    broker_type: str = "kis-domestic",
    trading_mode: TradingMode = TradingMode.LIVE,
) -> RuntimeReadinessRegistry:
    """주어진 account 의 비면제 플래그를 전부 ready 로 mark 한 registry.

    ``active_trading_ready`` 가 ``True`` 를 반환하도록(통과) 구성한다(G5).
    """
    reg = RuntimeReadinessRegistry()
    for flag in ALL_FLAGS:
        if is_flag_exempt(flag, broker_type=broker_type, trading_mode=trading_mode):
            continue
        reg.mark_ready(account_id, flag)
    return reg


def not_ready_registry(
    account_id: str = "acc-001",
    *,
    flag: ReadinessFlag = ReadinessFlag.FILL_RECONCILE,
    broker_type: str = "kis-domestic",
    trading_mode: TradingMode = TradingMode.LIVE,
    reason: str = "test_not_ready",
) -> RuntimeReadinessRegistry:
    """한 비면제 플래그만 not_ready 인 registry(나머지 비면제는 ready).

    ``active_trading_ready`` 가 ``False`` 를 반환하도록(차단) 구성한다.
    """
    reg = ready_registry(account_id, broker_type=broker_type, trading_mode=trading_mode)
    reg.mark_not_ready(account_id, flag, reason)
    return reg
