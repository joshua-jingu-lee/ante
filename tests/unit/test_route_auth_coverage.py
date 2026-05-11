"""라우트 인증 dependency 정적 회귀 검증 (#1405 + #1407 enforce mode).

본 테스트는 두 invariant 를 정적으로 잠근다.

CASE 1 — enforce mode (#1407):
    ``src/ante/web/routes/`` 의 모든 ``APIRoute`` 가 다음 둘 중 하나에 해당해야
    한다:

    - PUBLIC_PATHS / PUBLIC_PREFIXES / GATE_EXEMPT_SELF_AUTH_PATHS 일치 → 인증
      게이트 면제 (라우트 자체에 인증 dependency 없음을 허용).
    - 그 외 ``/api/*`` 라우트 → ``src/ante/web/deps.py`` 의
      ``_is_authentication_dependency = True`` marker 가 부착된 dependency 에
      의해 보호되어야 한다.

    #1407 마이그레이션으로 모든 70 라우트가 SSOT
    (``docs/specs/web-api/11-route-scope-table.md``) 결정과 일관되게 부착되었다.
    본 테스트는 이후 새 라우트 추가 시 부착 누락을 즉시 차단한다.

    회귀 시 nightmare 시나리오:
        - 라우트에서 ``Depends(require_*)`` 인자가 사라져도 ``app.routes`` 에는
          여전히 등록돼 있어, 통합 테스트가 happy-path 만 검사하면 인증
          누락이 발견되지 않을 수 있다.
        - dependency 함수가 ``_is_authentication_dependency`` marker 없이
          rename / refactor 되면 본 정적 회귀가 marker 부재로 즉시 실패한다.

CASE 2 — ``PUBLIC_PATHS`` ∪ ``GATE_EXEMPT_SELF_AUTH_PATHS`` 의 ``/api/*``
   항목이 실제로 ``app.routes`` 에 등록되어 있는지 sanity 검증:
    ``/api/*`` 면제 경로는 라우트가 응답을 만들어야 의미가 있다. 코드 상
    경로 오타(예: ``/api/auht/me``)나 라우트 삭제가 spec/code drift 로
    이어지면 본 sanity 가 실패해 즉시 차단한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.dependencies.models import Dependant


# ── helpers ────────────────────────────────────────────────────────────────


def _walk_dependants(dep: Dependant) -> Iterator[Dependant]:
    """FastAPI Dependant 트리 (루트 + sub-dependants) 를 깊이 우선 walk."""
    yield dep
    for sub in dep.dependencies:
        yield from _walk_dependants(sub)


def _has_auth_marker(route: object) -> bool:
    """라우트의 Dependant 트리에 ``_is_authentication_dependency = True``
    marker 가 부착된 callable 이 하나라도 존재하면 True.

    인증 dependency 가 ``functools.wraps`` / decorator 로 한 단계 wrap 된 경우도
    ``__wrapped__`` 를 따라 marker 를 탐색한다.
    """
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    for dep in _walk_dependants(dependant):
        call = getattr(dep, "call", None)
        if call is None:
            continue
        if getattr(call, "_is_authentication_dependency", False):
            return True
        wrapped = getattr(call, "__wrapped__", None)
        while wrapped is not None:
            if getattr(wrapped, "_is_authentication_dependency", False):
                return True
            wrapped = getattr(wrapped, "__wrapped__", None)
    return False


def _route_keys(route: object) -> Iterator[tuple[str, str]]:
    """FastAPI ``APIRoute`` 의 ``(method, path)`` 키 시퀀스를 yield.

    ``methods`` 가 여러 개면 각 method 마다 한 번씩 yield 한다.
    """
    path = getattr(route, "path", None)
    methods = getattr(route, "methods", None) or set()
    if path is None:
        return
    for method in methods:
        yield method.upper(), path


def _is_exempt_path(
    path: str,
    public_paths: frozenset[str],
    public_prefixes: tuple[str, ...],
    gate_exempt_paths: frozenset[str],
) -> bool:
    """``path`` 가 PUBLIC_PATHS / PUBLIC_PREFIXES / GATE_EXEMPT_SELF_AUTH_PATHS
    의 어느 한 카테고리에 속하면 True."""
    if path in public_paths:
        return True
    if path in gate_exempt_paths:
        return True
    for prefix in public_prefixes:
        if path.startswith(prefix):
            return True
    return False


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app_routes() -> list[object]:
    """services 없이 ``create_app`` 으로 만든 빈 앱의 라우트 리스트.

    인증 dependency 는 ``app.state`` 의 ``member_service`` / ``session_service``
    가 없어도 Dependant 트리 자체는 그대로 구성되므로 marker 정적 검증에는
    충분하다.
    """
    from fastapi.routing import APIRoute

    from ante.web.app import create_app

    app = create_app()
    return [r for r in app.routes if isinstance(r, APIRoute)]


# ── CASE 1: enforce mode (#1407) ───────────────────────────────────────────


def test_all_api_routes_have_auth_marker_or_exempt(app_routes: list[object]) -> None:
    """모든 ``/api/*`` 라우트는 인증 dependency marker 부착 또는 면제 카테고리
    (PUBLIC_PATHS / PUBLIC_PREFIXES / GATE_EXEMPT_SELF_AUTH_PATHS) 에 속해야
    한다. #1407 enforce mode — 70 라우트 일관 부착 보장.
    """
    from ante.web.middleware.require_auth import (
        GATE_EXEMPT_SELF_AUTH_PATHS,
        PUBLIC_PATHS,
        PUBLIC_PREFIXES,
    )

    missing_auth: list[tuple[str, str]] = []
    for route in app_routes:
        path = getattr(route, "path", "")
        # /api/* 외 (정적/SPA fallback 등) 는 본 정적 검증 대상이 아님.
        if not path.startswith("/api/"):
            continue
        # 면제 경로는 통과.
        if _is_exempt_path(
            path, PUBLIC_PATHS, PUBLIC_PREFIXES, GATE_EXEMPT_SELF_AUTH_PATHS
        ):
            continue
        if not _has_auth_marker(route):
            for key in _route_keys(route):
                missing_auth.append(key)

    if missing_auth:
        pytest.fail(
            "다음 /api/* 라우트가 _is_authentication_dependency marker 부착 "
            "dependency 로 보호되지 않음 (#1407 enforce mode — SSOT "
            "docs/specs/web-api/11-route-scope-table.md 결정에 따라 부착 필요):\n"
            + "\n".join(f"  - {method} {path}" for method, path in sorted(missing_auth))
        )


# ── CASE 2 ─────────────────────────────────────────────────────────────────


def test_public_and_gate_exempt_api_paths_are_registered(
    app_routes: list[object],
) -> None:
    """``PUBLIC_PATHS`` ∪ ``GATE_EXEMPT_SELF_AUTH_PATHS`` 중 ``/api/*`` 항목이
    실제 ``app.routes`` 에 라우트로 등록되어 있다.

    비-``/api`` 항목 (``/``, ``/index.html``, ``/openapi.json``, ``/docs``,
    ``/redoc``, ``/assets/*``) 은 FastAPI 가 동적으로 제공하거나 정적 마운트로
    처리되어 ``APIRoute`` 에 나타나지 않으므로 검증 대상에서 제외한다.
    """
    from ante.web.middleware.require_auth import (
        GATE_EXEMPT_SELF_AUTH_PATHS,
        PUBLIC_PATHS,
    )

    registered_paths: set[str] = {
        getattr(route, "path")
        for route in app_routes  # noqa: B009
    }

    api_paths_to_check: set[str] = {
        p for p in (PUBLIC_PATHS | GATE_EXEMPT_SELF_AUTH_PATHS) if p.startswith("/api/")
    }

    missing = sorted(p for p in api_paths_to_check if p not in registered_paths)
    if missing:
        pytest.fail(
            "PUBLIC_PATHS / GATE_EXEMPT_SELF_AUTH_PATHS 의 /api/* 항목이 "
            f"app.routes 에 등록되어 있지 않음 (spec/code drift): {missing}"
        )
