"""ServiceRegistry — 런타임 서비스 인스턴스를 보관하는 데이터 컨테이너.

IPC 핸들러가 필요한 서비스에 접근할 때 사용한다.
순환 임포트를 방지하기 위해 타입 힌트는 TYPE_CHECKING 블록에서만 임포트한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.account.service import AccountService
    from ante.approval.service import ApprovalService
    from ante.bot.manager import BotManager
    from ante.config.dynamic import DynamicConfigService
    from ante.eventbus import EventBus
    from ante.strategy.registry import StrategyRegistry
    from ante.trade.reconciler import PositionReconciler
    from ante.treasury.manager import TreasuryManager


@dataclass
class ServiceRegistry:
    """IPC 핸들러가 참조하는 서비스 레지스트리."""

    account: AccountService | Any
    bot_manager: BotManager | Any
    treasury_manager: TreasuryManager | Any
    dynamic_config: DynamicConfigService | Any
    approval: ApprovalService | Any
    reconciler: PositionReconciler | Any
    eventbus: EventBus | Any
    strategy_registry: StrategyRegistry | Any = field(default=None)
