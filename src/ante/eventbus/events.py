"""EventBus 이벤트 타입 정의.

모든 이벤트는 Event를 상속하는 frozen dataclass.
이벤트는 순수 데이터 구조로, 비즈니스 로직을 포함하지 않는다.

account-scoped 이벤트는 ``_requires_account_id: ClassVar[bool] = True``
마커를 추가하면, ``Event.__post_init__``이 ``account_id`` 필드 값을
:func:`ante.account.scoping.is_invalid_account_id` 로 검증한다. 검증
실패 시 :class:`ante.account.errors.InvalidAccountIdError` 가 raise되어
빈 문자열/``"default"``/None/형식 위반 값이 이벤트로 발행되지 못한다.
system-wide 이벤트(SystemStartedEvent, SystemShutdownEvent 등)는 marker
없이 default ``False`` 를 유지하므로 검증되지 않는다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID, uuid4

from ante.account.errors import InvalidAccountIdError
from ante.account.scoping import is_invalid_account_id


@dataclass(frozen=True)
class Event:
    """모든 이벤트의 기본 클래스.

    Attributes:
        _requires_account_id: 하위 클래스에서 ``True`` 로 override하면
            ``__post_init__`` 이 ``account_id`` 필드를 runtime 검증한다.
            system-wide 이벤트는 ``False`` (default).
    """

    _requires_account_id: ClassVar[bool] = False

    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )

    def __post_init__(self) -> None:
        if self._requires_account_id:
            account_id = getattr(self, "account_id", None)
            if is_invalid_account_id(account_id):
                raise InvalidAccountIdError(
                    f"AccountScopedEvent {type(self).__name__}는 valid account_id가 "
                    f"필수입니다: {account_id!r}. fallback ('', None, 'default') 또는 "
                    "형식 위반 값은 사용할 수 없습니다."
                )


# ── 주문 흐름 (Order Flow) ────────────────────────


@dataclass(frozen=True)
class OrderRequestEvent(Event):
    """봇 → EventBus: 신규 주문 요청."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
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

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    order_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class OrderModifyEvent(Event):
    """봇 → EventBus: 주문 정정 요청."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class OrderModifyRejectedEvent(Event):
    """RuleEngine → EventBus: 주문 정정 룰 위반으로 거부."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class OrderValidatedEvent(Event):
    """RuleEngine → EventBus: 룰 검증 통과."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
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

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
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

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
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

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
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

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
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

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
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

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    order_type: str = ""
    error_message: str = ""
    error_code: str = ""
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

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    bot_id: str = ""


@dataclass(frozen=True)
class BotStopEvent(Event):
    """RuleEngine/사용자 → EventBus: 봇 중지 요청."""

    bot_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class BotStoppedEvent(Event):
    """BotManager → EventBus: 봇 중지 완료."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    bot_id: str = ""


@dataclass(frozen=True)
class BotErrorEvent(Event):
    """BotManager → EventBus: 봇 에러 발생."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    bot_id: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class BotStepCompletedEvent(Event):
    """Bot → EventBus: 봇 실행 사이클 완료.

    매 on_step() 호출 후 결과를 기록한다.
    result 값: success, timeout, signal_overflow, error
    """

    _requires_account_id: ClassVar[bool] = True

    bot_id: str = ""
    account_id: str = ""
    result: str = ""
    message: str = ""


@dataclass(frozen=True)
class BotRestartExhaustedEvent(Event):
    """BotManager → EventBus: 봇 재시작 한도 소진."""

    _requires_account_id: ClassVar[bool] = True

    bot_id: str = ""
    account_id: str = ""
    restart_attempts: int = 0
    last_error: str = ""


@dataclass(frozen=True)
class SystemStartedEvent(Event):
    """Main → EventBus: 시스템 초기화 완료."""

    auto_started_bots: int = 0


@dataclass(frozen=True)
class SystemShutdownEvent(Event):
    """Main → EventBus: 시스템 종료 시작."""

    reason: str = ""


# ── 알림 (Notification) ──────────────────────────


@dataclass(frozen=True)
class NotificationEvent(Event):
    """각 모듈 → EventBus: 알림 발송 트리거."""

    level: str = "info"
    title: str = ""
    message: str = ""
    category: str = ""
    buttons: list | None = None  # type: ignore[assignment]


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
class PositionMismatchEvent(Event):
    """포지션 불일치 감지."""

    bot_id: str = ""
    symbol: str = ""
    internal_qty: float = 0.0
    broker_qty: float = 0.0
    reason: str = ""


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
    auto_approved: bool = False


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
class MemberReactivatedEvent(Event):
    """MemberService → EventBus: 멤버 재활성화."""

    member_id: str = ""
    reactivated_by: str = ""


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


# ── 일일 리포트 (DailyReport) ──────────────────────


@dataclass(frozen=True)
class DailyReportEvent(Event):
    """DailyReportScheduler → EventBus: 일일 성과 리포트 발행."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    report_date: str = ""  # YYYY-MM-DD
    trade_count: int = 0
    has_trades: bool = False
    daily_pnl: float = 0.0
    daily_return: float = 0.0
    net_trade_amount: float = 0.0
    unrealized_pnl: float = 0.0


# ── 잔고 동기화 (Treasury) ──────────────────────


@dataclass(frozen=True)
class BalanceSyncedEvent(Event):
    """Treasury → EventBus: 계좌 잔고 동기화 완료."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
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

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    error_message: str = ""


# ── Stop Order 이벤트 ──────────────────────────────


@dataclass(frozen=True)
class StopOrderRegisteredEvent(Event):
    """StopOrderManager → EventBus: 스탑 주문 등록.

    Refs #1336: 본 이벤트는 ``BotManager`` / ``Bot.on_order_update`` /
    ``SignalChannel._on_order_update`` 가 구독하여 전략 ``on_order_update``
    콜백 ``status="stop_registered"`` 로 변환한다. 다른 account-scoped
    주문 이벤트와 같은 컨벤션으로 ``account_id`` 를 첫 데이터 필드로
    배치하고, ``_requires_account_id`` 마커로 invalid fallback (``""``,
    ``"default"``, 형식 위반) 을 ``Event.__post_init__`` 에서 차단한다.
    """

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    stop_order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    order_type: str = ""
    stop_price: float = 0.0
    limit_price: float | None = None


@dataclass(frozen=True)
class StopOrderTriggeredEvent(Event):
    """StopOrderManager → EventBus: 스탑 주문 트리거.

    Refs #1336: 변환된 일반 주문(``OrderRequestEvent``)이 자체 라이프사이클
    이벤트를 발행하지만, stop_order_id 등 stop 식별 단위가 다르므로 본
    이벤트를 별도로 발행하여 전략 ``on_order_update``
    (``status="stop_triggered"``) 로 통보한다. ``account_id`` 는 다른
    account-scoped 이벤트와 동일하게 ``__post_init__`` 에서 검증된다.
    """

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    stop_order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    trigger_price: float = 0.0
    converted_order_type: str = ""


@dataclass(frozen=True)
class StopOrderExpiredEvent(Event):
    """StopOrderManager → EventBus: 스탑 주문 만료.

    Refs #1336: 등록된 stop 주문이 트리거되지 않은 채 자동 해제될 때
    발행된다. ``reason`` 허용 값 (현재 코드 기준):

    - ``"session_ended"``: ``check_session_expiry()`` 가 거래 세션 종료를
      감지하고 미트리거 주문을 만료시킬 때.
    - ``"manager_stopped"``: ``StopOrderManager.stop()`` 이 매니저를
      중지시키며 활성 주문을 일괄 만료시킬 때.

    추후 ``manual_cancel`` 등 다른 reason 도입은 별도 이슈로 분리한다
    (현재 ``cancel()`` 은 expired event 를 발행하지 않음).

    ``account_id`` 는 다른 account-scoped 이벤트와 동일하게
    ``__post_init__`` 에서 검증된다.
    """

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    stop_order_id: str = ""
    bot_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    reason: str = ""


# ── 실시간 스트림 이벤트 ─────────────────────────────


@dataclass(frozen=True)
class StreamConnectedEvent(Event):
    """KISStreamClient → EventBus: WebSocket 연결 성공.

    SPLIT-3 (#1242): KIS multi-account 환경에서 각 계좌마다 별도의
    ``KISStreamClient`` 인스턴스가 생성되며, 발행자는 자신의
    ``account_id`` 를 명시 전달해야 한다. ``StreamIntegration`` 의
    fallback toggle 이 다른 계좌 stream 의 disconnect 로 잘못 켜지지
    않도록 한다.
    """

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    broker: str = ""
    url: str = ""


@dataclass(frozen=True)
class StreamDisconnectedEvent(Event):
    """KISStreamClient → EventBus: WebSocket 연결 해제.

    SPLIT-3 (#1242): account-scoped marker 적용. 자세한 내용은
    :class:`StreamConnectedEvent` 를 참조한다.
    """

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    broker: str = ""
    reason: str = ""


# ── 계좌 (Account) ──────────────────────────────


@dataclass(frozen=True)
class AccountSuspendedEvent(Event):
    """AccountService → EventBus: 계좌 정지."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    reason: str = ""
    suspended_by: str = ""


@dataclass(frozen=True)
class AccountActivatedEvent(Event):
    """AccountService → EventBus: 계좌 활성화."""

    _requires_account_id: ClassVar[bool] = True

    account_id: str = ""
    activated_by: str = ""


# AccountDeletedEvent는 1.0 EventBus 계약에서 제거되었다 (#1139).
# 계좌 삭제는 cold-path structural operation이며, 서버 실행 중 consumer
# topology를 hot wiring하지 않는다. 정합 SSOT는
# docs/specs/eventbus/eventbus.md 119-127줄과
# docs/specs/account/05-eventbus-integration.md 8-17줄.
