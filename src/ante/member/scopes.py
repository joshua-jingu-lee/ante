"""Member scope vocabulary SSOT (#1439).

본 모듈은 Ante 시스템 전반에서 사용하는 scope 문자열 vocabulary 의 단일 진실
저장소(SSOT)다. 인증 후 권한 판정에 사용되는 모든 scope 토큰은 본 모듈의
``SCOPE_VOCABULARY`` 에 등록되어 있어야 하며, 등록되지 않은 scope 문자열은
서비스 계층과 CLI 입력 단계에서 모두 거부된다.

설계 결정 (#1439 — Codex Plan Review r1):
- SSOT 위치를 ``src/ante/member`` 패키지로 둔다. Member 모듈이
  principal/credential/scope vocabulary 전체의 SSOT 라는 spec 결정
  (``docs/specs/member/02-design-decisions.md`` "Authorization SSOT")과
  일관성을 맞춘다.
- vocabulary 정의는 ``docs/specs/member/02-design-decisions.md`` 의 "권한 범위
  (Scope)" 매트릭스(read / write / admin / run 컬럼, "—" 셀 제외)에서 직접
  파생된다. spec doc 매트릭스의 모든 valid cell 은 본 frozenset 의 원소로
  존재해야 하며, drift 는 ``tests/unit/test_member_scope_drift.py`` 가 정적으로
  검증한다.

NOTE: ``signal`` 도메인은 봇별 signal key(``sk_``) 인증으로 동작하며 member
scope 체계 밖이다(spec doc L196). 본 vocabulary 에 포함되지 않는다.
"""

from __future__ import annotations

__all__ = [
    "SCOPE_VOCABULARY",
    "InvalidScopeError",
    "is_valid_scope",
]


# spec ``docs/specs/member/02-design-decisions.md`` 권한 범위 매트릭스(L177-194)
# 의 "—" 가 아닌 모든 cell. 도메인 가나다순(매트릭스 순서)으로 나열하고 같은
# 도메인 안에서는 read → write → admin → run 순서로 정렬한다.
SCOPE_VOCABULARY: frozenset[str] = frozenset(
    {
        # account
        "account:read",
        "account:write",
        # strategy
        "strategy:read",
        "strategy:write",
        # data
        "data:read",
        "data:write",
        # report
        "report:read",
        "report:write",
        # config
        "config:read",
        "config:write",
        # approval
        "approval:read",
        "approval:write",
        "approval:admin",
        # bot
        "bot:read",
        "bot:admin",
        # trade
        "trade:read",
        # treasury
        "treasury:read",
        "treasury:admin",
        # member
        "member:read",
        "member:admin",
        # system
        "system:read",
        "system:admin",
        # rule
        "rule:read",
        "rule:admin",
        # broker
        "broker:read",
        # audit
        "audit:read",
        # notification
        "notification:read",
        # backtest
        "backtest:run",
    }
)


def is_valid_scope(scope: str) -> bool:
    """``scope`` 문자열이 SCOPE_VOCABULARY 에 포함되어 있는지 확인한다.

    구분자 변형(예: ``account.read``), 대소문자 변형(예: ``Account:Read``),
    공백/외부 prefix(``oracle:invalid``, ``audit :read``) 는 모두 false 다.
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

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``getattr(e, "code", "EXECUTION_ERROR")``로 안정 코드
    ``"MEMBER_INVALID_SCOPE"`` 를 노출하도록 한다 (#1797). CLI 표면은 이미
    ``code="MEMBER_INVALID_SCOPE"`` 로 명시 매핑하고 있어 envelope 일관성
    회귀가 없다.
    """

    code: str = "MEMBER_INVALID_SCOPE"

    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(f"unsupported scope: {scope!r}")
