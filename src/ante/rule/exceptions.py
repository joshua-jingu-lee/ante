"""Rule Engine 모듈 예외."""


class RuleError(Exception):
    """Rule Engine 기본 예외."""

    pass


class RuleConfigError(RuleError):
    """룰 설정 오류."""

    pass
