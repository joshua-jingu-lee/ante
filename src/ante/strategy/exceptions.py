"""Strategy 모듈 예외."""


class StrategyError(Exception):
    """Strategy 기본 예외."""

    pass


class StrategyNotFoundError(StrategyError):
    """전략을 찾을 수 없음 (#1796).

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``getattr(e, "code", "EXECUTION_ERROR")``로 안정 코드
    ``"STRATEGY_NOT_FOUND"`` 를 노출하도록 한다. ``StrategyRegistry.update_status``
    가 missing strategy 에 대해 raise 하면 CLI ``strategy set-status`` 가
    typed code envelope 으로 종료한다.
    """

    code: str = "STRATEGY_NOT_FOUND"


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
