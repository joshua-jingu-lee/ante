"""Auth middleware error code 정책 회귀 lock (#1841 Family C).

``src/ante/cli/middleware.py`` 는 인증/권한 실패 시 ``_emit_auth_error`` 에
전달하는 envelope ``code`` 값으로 lowercase 토큰 3 종 (``auth_required``,
``auth_failed``, ``permission_denied``) 을 사용한다.

Taxonomy SSOT (``docs/specs/contracts/error-taxonomy.md``, #1839) 는
SCREAMING_SNAKE 를 normative 로 명시했지만, auth middleware 의 lowercase
값은 #1815 migration 시점까지 의도적으로 유지된다 (#1839 결정).

본 test 는 다음 두 가지를 회귀 lock 한다:

* lowercase 토큰 3 종이 source 에 그대로 존재한다.
* SCREAMING_SNAKE 변형 (``AUTH_REQUIRED`` 등) 이 ``_emit_auth_error``
  호출 인자로 도입되지 않았다 (=의도 없는 migration 회피).

migration 은 #1815 가 책임지며, 그 시점에 본 test 도 함께 갱신된다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIDDLEWARE = _REPO_ROOT / "src" / "ante" / "cli" / "middleware.py"

_LOWERCASE_CODES = ("auth_required", "auth_failed", "permission_denied")
_SCREAMING_VARIANTS = ("AUTH_REQUIRED", "AUTH_FAILED", "PERMISSION_DENIED")


@pytest.fixture(scope="module")
def middleware_source() -> str:
    """``middleware.py`` raw source 를 반환한다.

    AST 도 가능하지만 본 lock 은 literal 매치로 충분하다.
    """
    return _MIDDLEWARE.read_text(encoding="utf-8")


@pytest.mark.parametrize("code", _LOWERCASE_CODES)
def test_auth_middleware_lowercase_codes_preserved(
    middleware_source: str,
    code: str,
) -> None:
    """auth middleware lowercase 토큰이 source 에 그대로 존재해야 한다.

    실패 시 #1815 migration 이 의도와 다르게 본 epic (#1841) 범위에서
    선반영되었거나, 코드가 잘못 삭제되었음을 의미한다. #1815 가 정식으로
    SCREAMING_SNAKE 로 migration 할 때 본 test 도 함께 갱신해야 한다.
    """
    literal = f'"{code}"'
    assert literal in middleware_source, (
        f"middleware.py 에서 {literal} 회귀 — auth lowercase 토큰은 #1815 "
        "migration 시점까지 의도적으로 유지된다 (#1839 결정)."
    )


@pytest.mark.parametrize("variant", _SCREAMING_VARIANTS)
def test_auth_middleware_no_screaming_snake_variant(
    middleware_source: str,
    variant: str,
) -> None:
    """SCREAMING_SNAKE 변형이 의도 없이 도입되지 않아야 한다.

    #1815 가 migration 을 책임지므로 본 epic (#1841) 범위에서는 변형이
    source 에 등장해선 안 된다. 등장 시 #1815 와 본 test 갱신을 동기화해야
    한다.
    """
    literal = f'"{variant}"'
    assert literal not in middleware_source, (
        f"middleware.py 에 {literal} 도입 감지 — #1815 migration 이 본 epic "
        "(#1841) 보다 먼저 들어왔다면 본 test 도 함께 갱신해야 한다."
    )
