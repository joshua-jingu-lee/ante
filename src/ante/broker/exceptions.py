"""Broker Adapter 모듈 예외.

#1843 sub-PR 5 — 본 모듈의 ``*Error`` sub-class 5건에 class-level ``.code``
속성을 신규 부여한다. helper(``ante.contracts.error_spec_for_exception``)
의 registry MRO lookup 과 IPC server.py:322 의 ``getattr(e, "code",
"EXECUTION_ERROR")`` fallback 양쪽에서 동일한 안정 코드가 envelope 으로
surface 되도록 정렬한다 (#1842 account 12 sub-class / #1843 sub-PR 1~4
member/approval/bot/treasury 동형).

원천 code 분리 정책 (#1843 sub-PR 5 Codex Plan Review v1 condition):

- ``APIError`` 가 보존하는 ``error_code`` (KIS msg_cd 등 원천
  external broker code) 는 **log-only / 디버깅 보조** 용도다.
- public envelope (CLI ``OutputFormatter.error`` / IPC envelope ``{code,
  message}``) 에는 ante taxonomy 의 안정 코드(``BROKER_API_ERROR``)만
  노출한다 — envelope SSOT 갱신 필요한 ``details.broker_code`` 필드 도입은
  본 PR 범위 밖이며 후속 spec PR 에서 책임진다.
- 보존 채널: ``APIError.error_code`` 인스턴스 필드 (log / debug message /
  EventBus ``OrderFailedEvent.error_code`` payload). public envelope 변환
  경로는 본 필드를 surface 하지 않는다.
"""


class BrokerError(Exception):
    """Broker 기본 예외.

    ``BrokerError`` base 자체는 의도적으로 ``EXCEPTION_TO_SPEC`` 에 등록하지
    않는다 — sub-class 5건이 모두 안정 코드를 보유하므로 base class 가
    fallback 으로 자체 raise 되는 사용 사례가 없다 (account/member/approval/
    bot/treasury sweep 의 base class 처리 동형 — ``pending_migration``
    allowlist 에 baseline 으로 유지).
    """

    pass


class AuthenticationError(BrokerError):
    """인증 실패.

    KIS OAuth 토큰 발급/갱신 실패 (HTTP 401/403, 잘못된 app_key/app_secret
    등). taxonomy ``auth`` 카테고리.
    """

    code: str = "BROKER_AUTH_FAILED"


class APIError(BrokerError):
    """API 호출 실패.

    KIS API 호출 시 broker side business / HTTP error. ``status_code`` 에
    HTTP status, ``error_code`` 에 원천 KIS ``msg_cd`` (예: ``APBK0501``) 가
    log-only 채널로 보존된다.

    public envelope code:
        ``BROKER_API_ERROR`` (taxonomy ``external`` 카테고리).

    원천 KIS ``msg_cd`` 노출 정책:
        public envelope (CLI ``OutputFormatter.error`` / IPC envelope
        ``{code, message}``) 에는 ante taxonomy 안정 코드만 노출한다.
        원천 ``msg_cd`` 는 ``self.error_code`` 필드 + log message
        (``KIS API Error [{msg_cd}]: {msg1}`` 형태) 에 보존되며, public
        surface 로 변환되지 않는다 (#1843 sub-PR 5 Codex Plan Review v1
        condition).
    """

    code: str = "BROKER_API_ERROR"

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        error_code: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.retryable = retryable


class OrderNotFoundError(BrokerError):
    """주문을 찾을 수 없음.

    broker side 에서 조회/취소 대상 주문이 존재하지 않을 때. taxonomy
    ``not_found`` 카테고리.
    """

    code: str = "BROKER_ORDER_NOT_FOUND"


class RateLimitError(BrokerError):
    """Rate limit 초과.

    KIS API per-minute rate limit 초과. retryable backoff 정책의 신호로 쓰인다.
    taxonomy ``external`` 카테고리 (외부 시스템 throttling).
    """

    code: str = "BROKER_RATE_LIMITED"


class CircuitOpenError(BrokerError):
    """Circuit breaker가 OPEN 상태 — API 호출 차단.

    연속 실패 임계 도달 시 circuit breaker 가 OPEN 으로 전이해 API 호출을
    차단한다. taxonomy ``service_unavailable`` 카테고리 (broker 가용성
    임시 차단).
    """

    code: str = "BROKER_CIRCUIT_OPEN"
