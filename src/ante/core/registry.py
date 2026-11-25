"""ServiceRegistry — 런타임 서비스 인스턴스를 보관하는 데이터 컨테이너."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.account.service import AccountService
    from ante.approval.service import ApprovalService
    from ante.audit.logger import AuditLogger
    from ante.bot.manager import BotManager
    from ante.bot.signal_channel_registry import SignalChannelRegistry
    from ante.config.config import Config
    from ante.config.dynamic import DynamicConfigService
    from ante.eventbus import EventBus
    from ante.member.service import MemberService
    from ante.strategy.registry import StrategyRegistry
    from ante.trade.reconciler import PositionReconciler
    from ante.trade.service import TradeService
    from ante.treasury.manager import TreasuryManager


@dataclass
class ServiceRegistry:
    """IPC 핸들러가 참조하는 서비스 레지스트리.

    ``audit_logger`` 필드는 administrative
    mutation IPC (``approval.cancel_invalid``) 가 정상 환경에서 audit_log 테이블에
    기록을 남기기 위한 필드다. 테스트/legacy 환경에서는 ``None`` 이 허용되며,
    핸들러는 ``getattr(svc, "audit_logger", None)`` 패턴으로 안전하게 처리한다.
    """

    account: AccountService | Any
    bot_manager: BotManager | Any
    treasury_manager: TreasuryManager | Any
    dynamic_config: DynamicConfigService | Any
    approval: ApprovalService | Any
    reconciler: PositionReconciler | Any
    eventbus: EventBus | Any
    strategy_registry: StrategyRegistry | Any = field(default=None)
    audit_logger: AuditLogger | Any = field(default=None)
    trade_service: TradeService | Any = field(default=None)
    member_service: MemberService | Any = field(default=None)
    signal_channel_registry: SignalChannelRegistry | Any = field(default=None)
    config: Config | Any = field(default=None)
