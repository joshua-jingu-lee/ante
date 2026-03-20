"""Strategy 모듈 예외."""


class StrategyError(Exception):
    """Strategy 기본 예외."""

    pass


class StrategyLoadError(StrategyError):
    """전략 파일 로드 실패."""

    pass


class StrategyValidationError(StrategyError):
    """전략 검증 실패."""

    pass


class StrategyFileAccessError(StrategyError):
    """전략 파일 접근 오류."""

    pass


class IncompatibleExchangeError(StrategyError):
    """전략의 exchange와 계좌의 exchange가 호환되지 않음."""

    pass
