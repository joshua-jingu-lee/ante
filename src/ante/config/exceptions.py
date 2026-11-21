"""Config 모듈 예외."""


class ConfigError(Exception):
    """Config 기본 예외."""

    pass


class ConfigValidationError(ValueError):
    """동적 설정 키-invariant 위반 (write 경계 입력 오류).

    ``validate_value`` 에서 ``system.log_level`` 처럼 enum SSOT가 정의된
    키가 invalid 값을 받았을 때 raise된다.

    ``ValueError`` 서브클래스 계약은 기존 service-boundary 테스트와 CLI/IPC
    입력 오류 처리 경로가 공유한다.
    """

    code = "CONFIG_VALIDATION_ERROR"
