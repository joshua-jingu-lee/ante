"""Auth middleware error code 정책 회귀 lock (#1841 Family C, #2738 ⑧-3).

인증/권한 실패의 envelope ``code`` 는 lowercase 토큰 3 종 (``auth_required``,
``auth_failed``, ``permission_denied``) 이다.

Taxonomy SSOT (``docs/specs/contracts/error-taxonomy.md``, #1839) 는
SCREAMING_SNAKE 를 normative 로 명시했지만, auth middleware 의 lowercase
값은 #1815 migration 시점까지 legacy alias 로 의도적으로 유지된다 (#1839 결정).

#2738 ⑧-3 뒤로 middleware 는 코드를 직접 쓰지 않고 ``ante.contracts.cli_errors``
의 예외를 던지며, 진입점 훅이 에러 레지스트리로 코드를 정한다. 본 test 는 같은
두 성질을 그 모양에서 lock 한다:

* lowercase 토큰 3 종이 middleware 가 던지는 예외의 코드이고, 레지스트리가 그
  값을 그대로 낸다.
* SCREAMING_SNAKE 변형 (``AUTH_REQUIRED`` 등) 이 middleware·
  예외 정의 source 에 도입되지 않았다 (=의도 없는 migration 회피). 레지스트리의
  ``PERMISSION_DENIED`` 는 member 도메인 코드라 대상이 아니다 — 세 예외의 등록
  값은 첫 test 가 lock 한다.

migration 은 #1815 가 책임지며, 그 시점에 본 test 도 함께 갱신된다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ante.contracts.cli_errors import (
    CliAuthFailedError,
    CliAuthRequiredError,
    CliPermissionDeniedError,
)
from ante.contracts.helpers import error_spec_for_exception

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIDDLEWARE = _REPO_ROOT / "src" / "ante" / "cli" / "middleware.py"
_SOURCES = (
    _MIDDLEWARE,
    _REPO_ROOT / "src" / "ante" / "contracts" / "cli_errors.py",
)

_AUTH_CLASSES = {
    "auth_required": CliAuthRequiredError,
    "auth_failed": CliAuthFailedError,
    "permission_denied": CliPermissionDeniedError,
}
_SCREAMING_VARIANTS = ("AUTH_REQUIRED", "AUTH_FAILED", "PERMISSION_DENIED")


def _raised_names() -> set[str]:
    tree = ast.parse(_MIDDLEWARE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            func = node.exc.func
            if isinstance(func, ast.Name):
                names.add(func.id)
    return names


@pytest.mark.parametrize("code", sorted(_AUTH_CLASSES))
def test_auth_middleware_lowercase_codes_preserved(code: str) -> None:
    """middleware 가 던지는 auth 예외의 코드가 lowercase 그대로다.

    실패 시 #1815 migration 이 의도와 다르게 선반영되었거나, 예외가 middleware
    에서 빠졌음을 의미한다.
    """
    cls = _AUTH_CLASSES[code]
    assert cls.__name__ in _raised_names(), (
        f"middleware.py 가 {cls.__name__} 를 던지지 않는다 — "
        f"{code!r} 의 출구가 사라졌다."
    )
    assert cls.code == code
    assert error_spec_for_exception(cls("m")).code == code


@pytest.mark.parametrize("variant", _SCREAMING_VARIANTS)
@pytest.mark.parametrize("source", _SOURCES, ids=lambda p: p.name)
def test_auth_middleware_no_screaming_snake_variant(variant: str, source: Path) -> None:
    """SCREAMING_SNAKE 변형이 의도 없이 도입되지 않아야 한다.

    #1815 가 migration 을 책임지므로 변형이 source 에 등장해선 안 된다. 등장 시
    #1815 와 본 test 갱신을 동기화해야 한다.
    """
    literal = f'"{variant}"'
    assert literal not in source.read_text(encoding="utf-8"), (
        f"{source.name} 에 {literal} 도입 감지 — #1815 migration 이 먼저 들어왔다면 "
        "본 test 도 함께 갱신해야 한다."
    )
