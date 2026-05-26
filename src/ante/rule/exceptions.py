"""Rule Engine 모듈 예외.

class-level ``code`` 정책 (#1843 sub-PR 6, 실측 mirror):

- ``RuleConfigError`` → ``RULE_CONFIG_ERROR`` (validation; 본 PR 신규 부여)
  — 룰 설정 입력 invariant 위반 (rule_type/params 등).

``RuleError`` base 는 의도적으로 ``.code`` 를 부여하지 않는다 — 사용 사례가
없으며 allowlist 의 ``pending_migration`` baseline 으로 보존된다 (#1842
``AccountError`` 와 동일 패턴).
"""


class RuleError(Exception):
    """Rule Engine 기본 예외."""

    pass


class RuleConfigError(RuleError):
    """룰 설정 오류 (#1843 sub-PR 6).

    클래스 레벨 ``code`` 는 IPC 서버 ``getattr(e, "code", ...)`` 와 helper
    registry-first lookup 이 동일 ``RULE_CONFIG_ERROR`` 안정 코드를 surface
    하도록 정렬한다. taxonomy 카테고리는 ``validation`` (룰 입력 invariant
    위반).
    """

    code: str = "RULE_CONFIG_ERROR"
