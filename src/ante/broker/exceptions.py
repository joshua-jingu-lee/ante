"""Broker Adapter 모듈 예외."""


class BrokerError(Exception):
    """Broker 기본 예외."""

    pass


class AuthenticationError(BrokerError):
    """인증 실패."""

    pass


class APIError(BrokerError):
    """API 호출 실패."""

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
    """주문을 찾을 수 없음."""

    pass


class RateLimitError(BrokerError):
    """Rate limit 초과."""

    pass


class CircuitOpenError(BrokerError):
    """Circuit breaker가 OPEN 상태 — API 호출 차단."""

    pass
