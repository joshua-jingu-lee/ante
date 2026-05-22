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
    from ante.audit.logger import AuditLogger
    from ante.bot.manager import BotManager
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

    Refs #1418 → #1472 SPLIT-D: ``audit_logger`` 필드는 administrative
    mutation IPC (``approval.cancel_invalid``) 가 정상 환경에서 audit_log 테이블에
    기록을 남기기 위해 추가되었다. 테스트/legacy 환경에서는 ``None`` 이 허용되며,
    핸들러는 ``getattr(svc, "audit_logger", None)`` 패턴으로 안전하게 처리한다.

    Refs #1712: ``trade_service`` 필드는 IPC ``bot.status`` handler 의
    positions 보강 (``enrich_bot_info``) 을 위해 optional 로 추가되었다.
    ``audit_logger`` 와 동형으로 ``None`` 허용 + ``getattr`` safe-access 가
    보장된다. legacy ServiceRegistry 호출자(``trade_service`` 인자 미전달)는
    그대로 동작하며, positions 키는 부재한다.
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
