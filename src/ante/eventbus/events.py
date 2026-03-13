"""EventBus 이벤트 타입 정의.

모든 이벤트는 Event를 상속하는 frozen dataclass.
이벤트는 순수 데이터 구조로, 비즈니스 로직을 포함하지 않는다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Event:
    """모든 이벤트의 기본 클래스."""

    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )


# ── 주문 흐름 (Order Flow) ────────────────────────


@dataclass(frozen=True)
class OrderRequestEvent(Event):
    """봇 → EventBus: 신규 주문 요청."""

    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    order_type: str = ""
    price: float | None = None
    stop_price: float | None = None
    reason: str = ""
    exchange: str = "KRX"


@dataclass(frozen=True)
class OrderCancelEvent(Event):
    """봇 → EventBus: 주문 취소 요청."""

    bot_id: str = ""
    strategy_id: str = ""
    order_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class OrderModifyEvent(Event):
    """봇 → EventBus: 주문 정정 요청."""

    bot_id: str = ""
    strategy_id: str = ""
    order_id: str = ""
    quantity: float = 0.0
    price: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class OrderValidatedEvent(Event):
    """RuleEngine → EventBus: 룰 검증 통과."""

    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float | None = None
    order_type: str = ""
    stop_price: float | None = None
    reason: str = ""
    exchange: str = "KRX"


@dataclass(frozen=True)
class OrderRejectedEvent(Event):
    """RuleEngine/Treasury → EventBus: 주문 거부."""

    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float | None = None
    order_type: str = ""
    reason: str = ""
    exchange: str = "KRX"


@dataclass(frozen=True)
class OrderApprovedEvent(Event):
    """Treasury → EventBus: 자금 확보 완료, 주문 실행 허가."""

    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float | None = None
    order_type: str = ""
    stop_price: float | None = None
    reserved_amount: float = 0.0
    exchange: str = "KRX"


@dataclass(frozen=True)
class OrderSubmittedEvent(Event):
    """APIGateway → EventBus: 증권사에 주문 전송됨."""

    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    broker_order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    order_type: str = ""
    exchange: str = "KRX"


@dataclass(frozen=True)
class OrderFilledEvent(Event):
    """BrokerAdapter → EventBus: 체결 완료."""

    order_id: str = ""
    broker_order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    requested_quantity: float = 0.0
    remaining_quantity: float = 0.0
    commission: float = 0.0
    order_type: str = ""
    reason: str = ""
    exchange: str = "KRX"


@dataclass(frozen=True)
class OrderCancelledEvent(Event):
    """BrokerAdapter → EventBus: 취소 완료."""

    order_id: str = ""
    broker_order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    reason: str = ""
    exchange: str = "KRX"


@dataclass(frozen=True)
class OrderFailedEvent(Event):
    """BrokerAdapter → EventBus: 주문 실패."""

    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    order_type: str = ""
    error_message: str = ""
    exchange: str = "KRX"


@dataclass(frozen=True)
class OrderUpdateEvent(Event):
    """주문 상태 변경 통합 (전략 전달용, EventBus 발행 대상 아님).

    Bot이 세부 이벤트를 수신 후, 전략의 on_order_update()에
    통합 형태로 전달하기 위한 내부 변환용 데이터 클래스.
    """

    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    status: str = ""
    symbol: str = ""
    side: str = ""
    order_type: str = ""
    quantity: float = 0.0
    reason: str = ""
    exchange: str = "KRX"


# ── 시스템 이벤트 (System) ────────────────────────


@dataclass(frozen=True)
class BotStartedEvent(Event):
    """BotManager → EventBus: 봇 시작."""

    bot_id: str = ""


@dataclass(frozen=True)
class BotStopEvent(Event):
    """RuleEngine/사용자 → EventBus: 봇 중지 요청."""

    bot_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class BotStoppedEvent(Event):
    """BotManager → EventBus: 봇 중지 완료."""

    bot_id: str = ""


@dataclass(frozen=True)
class BotErrorEvent(Event):
    """BotManager → EventBus: 봇 에러 발생."""

    bot_id: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class BotRestartExhaustedEvent(Event):
    """BotManager → EventBus: 봇 재시작 한도 소진."""

    bot_id: str = ""
    restart_attempts: int = 0
    last_error: str = ""


@dataclass(frozen=True)
class TradingStateChangedEvent(Event):
    """SystemState → EventBus: 거래 상태(킬 스위치) 변경."""

    old_state: str = ""
    new_state: str = ""
    reason: str = ""
    changed_by: str = ""


@dataclass(frozen=True)
class SystemShutdownEvent(Event):
    """Main → EventBus: 시스템 종료 시작."""

    reason: str = ""


# ── 알림 (Notification) ──────────────────────────


@dataclass(frozen=True)
class NotificationEvent(Event):
    """각 모듈 → EventBus: 알림 발송 트리거."""

    level: str = "info"
    message: str = ""
    detail: str = ""
    metadata: dict = field(default_factory=dict)  # type: ignore[assignment]


# ── 백테스트 (Backtest) ──────────────────────────


@dataclass(frozen=True)
class BacktestCompleteEvent(Event):
    """BacktestEngine → EventBus: 백테스트 완료."""

    backtest_id: str = ""
    strategy_id: str = ""
    status: str = ""
    result_path: str = ""
    error_message: str = ""


# ── 대사 (Reconciliation) ────────────────────────


@dataclass(frozen=True)
class ReconcileEvent(Event):
    """Reconciler → EventBus: 대사 보정 완료."""

    bot_id: str = ""
    discrepancy_count: int = 0
    corrections: list = field(default_factory=list)  # type: ignore[assignment]


# ── 외부 시그널 (External Signal) ─────────────────


@dataclass(frozen=True)
class ExternalSignalEvent(Event):
    """REST API → EventBus: 외부 AI Agent 시그널."""

    bot_id: str = ""
    signal_id: str = ""
    symbol: str = ""
    action: str = ""
    reason: str = ""
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)  # type: ignore[assignment]
    exchange: str = "KRX"


# ── 설정 변경 (Config) ───────────────────────────


@dataclass(frozen=True)
class ConfigChangedEvent(Event):
    """WebAPI/CLI → EventBus: 동적 설정 변경 알림."""

    category: str = ""
    key: str = ""
    old_value: str = ""
    new_value: str = ""
    changed_by: str = ""


# ── 결재 (Approval) ───────────────────────────


@dataclass(frozen=True)
class ApprovalCreatedEvent(Event):
    """ApprovalService → EventBus: 결재 요청 생성."""

    approval_id: str = ""
    approval_type: str = ""
    requester: str = ""
    title: str = ""


@dataclass(frozen=True)
class ApprovalResolvedEvent(Event):
    """ApprovalService → EventBus: 결재 처리 완료 (승인/거절/철회/만료)."""

    approval_id: str = ""
    approval_type: str = ""
    resolution: str = ""
    resolved_by: str = ""


# ── 멤버 (Member) ───────────────────────────────


@dataclass(frozen=True)
class MemberRegisteredEvent(Event):
    """MemberService → EventBus: 멤버 등록 완료."""

    member_id: str = ""
    member_type: str = ""
    role: str = ""
    registered_by: str = ""


@dataclass(frozen=True)
class MemberSuspendedEvent(Event):
    """MemberService → EventBus: 멤버 정지."""

    member_id: str = ""
    suspended_by: str = ""


@dataclass(frozen=True)
class MemberRevokedEvent(Event):
    """MemberService → EventBus: 멤버 폐기."""

    member_id: str = ""
    revoked_by: str = ""


@dataclass(frozen=True)
class MemberAuthFailedEvent(Event):
    """MemberService → EventBus: 인증 실패."""

    member_id: str = ""
    reason: str = ""


# ── 잔고 동기화 (Treasury) ──────────────────────


@dataclass(frozen=True)
class BalanceSyncedEvent(Event):
    """Treasury → EventBus: 계좌 잔고 동기화 완료."""

    account_balance: float = 0.0
    purchasable_amount: float = 0.0
    total_evaluation: float = 0.0
    external_purchase_amount: float = 0.0
    external_eval_amount: float = 0.0


# ── Circuit Breaker ──────────────────────────────


@dataclass(frozen=True)
class CircuitBreakerEvent(Event):
    """KIS API circuit breaker 상태 변경."""

    broker: str = ""
    old_state: str = ""
    new_state: str = ""
    failure_count: int = 0
    reason: str = ""


# ── 주문 취소 실패 ──────────────────────────────


@dataclass(frozen=True)
class OrderCancelFailedEvent(Event):
    """주문 취소 실패."""

    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    error_message: str = ""
