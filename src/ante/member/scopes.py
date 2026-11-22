"""Member scope vocabulary SSOT."""

from __future__ import annotations

__all__ = [
    "SCOPE_VOCABULARY",
    "InvalidScopeError",
    "is_valid_scope",
]


SCOPE_VOCABULARY: frozenset[str] = frozenset(
    {
        "account:read",
        "account:write",
        "strategy:read",
        "strategy:write",
        "data:read",
        "data:write",
        "report:read",
        "report:write",
        "config:read",
        "config:write",
        "approval:read",
        "approval:write",
        "approval:admin",
        "bot:read",
        "bot:admin",
        "trade:read",
        "treasury:read",
        "treasury:admin",
        "member:read",
        "member:admin",
        "system:read",
        "system:admin",
        "rule:read",
        "rule:admin",
        "broker:read",
        "audit:read",
        "notification:read",
        "backtest:run",
    }
)


def is_valid_scope(scope: str) -> bool:
    """``scope`` 문자열이 SCOPE_VOCABULARY 에 포함되어 있는지 확인한다.

    구분자 변형(예: ``account.read``), 대소문자 변형(예: ``Account:Read``),
    공백/외부 prefix(``sample:invalid``, ``audit :read``) 는 모두 false 다.
    빈 문자열은 false 다.
    """
    return scope in SCOPE_VOCABULARY


class InvalidScopeError(ValueError):
    """SCOPE_VOCABULARY 에 없는 scope 문자열이 service 계층에 전달된 경우.

    CLI direct path 와 내부 caller (``MemberService.register`` /
    ``update_scopes`` 직접 호출) 가 invalid scope 를 넘기는 경우 본 예외가
    defense-in-depth 로 raise 된다.

    ``ValueError`` 의 서브클래스로 두어 기존 ``except ValueError`` 핸들러가
    그대로 동작하지만, 호출자가 vocabulary 위반과 다른 도메인 오류
    (예: 존재하지 않는 멤버) 를 구분하려면 본 클래스로 좁혀 catch 한다.
    """

    code: str = "MEMBER_INVALID_SCOPE"

    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(f"unsupported scope: {scope!r}")
