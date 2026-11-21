"""Rule Engine 모듈 예외."""


class RuleError(Exception):
    """Rule Engine 기본 예외."""

    pass


class RuleConfigError(RuleError):
    """룰 설정 오류.

    클래스 레벨 ``code`` 는 IPC 서버 ``getattr(e, "code", ...)`` 와 helper
    registry-first lookup 이 동일 ``RULE_CONFIG_ERROR`` 안정 코드를 surface
    하도록 정렬한다. taxonomy 카테고리는 ``validation`` (룰 입력 invariant
    위반).
    """

    code: str = "RULE_CONFIG_ERROR"
