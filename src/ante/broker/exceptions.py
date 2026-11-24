"""Broker Adapter 모듈 예외."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


ORDER_OUTCOME_UNKNOWN = "order_outcome_unknown"
"""접수 여부를 알 수 없어 다시 보내지 않은 매수·매도 주문의 ``error_code``."""


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

    ``error_code``: KIS 원천 ``msg_cd`` (예: ``EGW00133``)를 **구조적으로**
    보존한다. ``main`` 의 startup / self-healing connect 실패 경로가 reason 에
    ``EGW00133`` 을 문자열 grep 이 아니라 ``getattr(e, "error_code", None)`` /
    isinstance 로 추출하기 위함이다(D-ACC-09 readiness reason 연동). 기본값은 빈
    문자열이라 기존 호출부(코드 미지정)는 영향이 없다.
    """

    code: str = "BROKER_AUTH_FAILED"

    def __init__(self, message: str, *, error_code: str = "") -> None:
        super().__init__(message)
        self.error_code = error_code


class TokenRateLimitError(AuthenticationError):
    """토큰 발급 빈도 제한 (KIS ``EGW00133``).

    KIS 는 접근토큰 발급을 1분당 1회만 허용한다. ``_authenticate`` 가 발급 응답에서
    ``EGW00133`` 을 감지하면 **즉시** 본 예외를 raise 하고 **내부 sleep/retry 루프를
    절대 두지 않는다**(곱셈 원천 제거). ~60s backoff cadence 는 단일 레이어
    (``main`` startup 의 bounded retry **또는** self-healing loop 의 burst interval)
    에서만 적용된다(spec 07 OAuth2 §(4)(5)(6) 단일 cadence).
    """

    code: str = "BROKER_AUTH_FAILED"

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "",
        cooldown_until: datetime | None = None,
    ) -> None:
        super().__init__(message, error_code=error_code)
        self.cooldown_until = cooldown_until


class APIError(BrokerError):
    """API 호출 실패.

    원천 KIS ``msg_cd`` 노출 정책:
        public envelope (CLI ``OutputFormatter.error`` / IPC envelope
        ``{code, message}``) 에는 ante taxonomy 안정 코드만 노출한다.
        원천 ``msg_cd`` 는 ``self.error_code`` 필드 + log message
        (``KIS API Error [{msg_cd}]: {msg1}`` 형태) 에 보존되며, public
        surface 로 변환되지 않는다.
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


class ModifyOrgnoUnavailableError(BrokerError):
    """주문 정정 KRX_FWDG_ORD_ORGNO 미상 — 정정 요청 전송 불가.

    KIS 국내주식 정정(order-rvsecncl)은 원주문별 ``KRX_FWDG_ORD_ORGNO``
    (한국거래소전송주문조직번호)를 요구한다. 이 값은 place_order(order-cash) 성공
    응답에서 캡처해 둔 인메모리 캐시(``_krx_fwdg_orgno_cache``)에서만 가져오며,
    캐시 miss(재기동 등으로 소실) 또는 제출 영업일 불일치(odno 재사용) 시에는
    오값 전송을 막기 위해 본 예외를 raise 한다(전송 금지, fail-closed). Gateway 는
    이를 ``modify_orgno_unavailable`` 거부 사유로 매핑한다. taxonomy
    ``state_conflict`` 카테고리 (정정 전송 전제조건 미충족).
    """

    code: str = "BROKER_MODIFY_ORGNO_UNAVAILABLE"
