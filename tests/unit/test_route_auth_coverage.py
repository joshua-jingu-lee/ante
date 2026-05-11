"""라우트 인증 dependency 정적 회귀 검증 (#1405).

본 테스트는 두 invariant 를 정적으로 잠근다.

CASE 1 — ``ATTACHED_ROUTE_ALLOWLIST`` marker 회귀:
    현재 ``src/ante/web/routes/`` 에서 ``Depends(require_*)`` 로 인증 가드가
    부착된 17개 mutation 라우트가, 본 PR 시점의 SSOT(11-route-scope-table.md
    "결정 scope" 컬럼) 와 정합한 상태로 ``src/ante/web/deps.py`` 의
    ``_is_authentication_dependency = True`` marker 가 붙은 dependency 에 의해
    보호되고 있음을 확인한다.

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

본 테스트는 SSOT 와 직접 비교하지 않고 (CASE 1 의 ALLOWLIST 는 #1407 마이그
레이션 전까지 부착이 narrow 한 상태이므로) "현재 부착된 라우트가 marker 로
이어지는지" 만 검증한다. #1407 이후 narrow allowlist 가 제거되고 모든
``/api/*`` 라우트가 enforce 되면, 본 파일을 제거하고 통합 검증으로 교체한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.dependencies.models import Dependant


# ── CASE 1 SSOT ────────────────────────────────────────────────────────────
#
# 본 시점 (#1405) 에 ``Depends(require_*)`` 로 인증 가드가 실제 부착된
# (method, path) 17개. 11-route-scope-table.md "결정 scope" 컬럼과 정합 확인.
# scope 문자열은 documentation purpose (가독성) 만이며, 본 테스트는
# marker 부착 여부만 검증한다 (#1407 이 scope 기반 마이그레이션을 담당).
ATTACHED_ROUTE_ALLOWLIST: dict[tuple[str, str], str] = {
    # config
    ("PUT", "/api/config/{key:path}"): "config:write",
    # system (master-only)
    ("POST", "/api/system/halt"): "system:admin",
    ("POST", "/api/system/clear-halt"): "system:admin",
    # audit
    ("GET", "/api/audit"): "audit:read",
    # members (master-only)
    ("PATCH", "/api/members/{member_id}/password"): "member:admin",
    # strategies
    ("PATCH", "/api/strategies/{strategy_id}/status"): "strategy:write",
    # accounts (master-only)
    ("PUT", "/api/accounts/{account_id}"): "account:admin",
    ("POST", "/api/accounts/{account_id}/suspend"): "account:admin",
    ("POST", "/api/accounts/{account_id}/activate"): "account:admin",
    ("PUT", "/api/accounts/{account_id}/rules/{rule_type}"): "rule:admin",
    # bots (master-only)
    ("POST", "/api/bots"): "bot:admin",
    ("DELETE", "/api/bots/{bot_id}"): "bot:admin",
    ("PUT", "/api/bots/{bot_id}"): "bot:admin",
    # reports
    ("POST", "/api/reports"): "report:write",
    # treasury (master-only)
    ("POST", "/api/treasury/bots/{bot_id}/allocate"): "treasury:write",
    ("POST", "/api/treasury/bots/{bot_id}/deallocate"): "treasury:write",
    ("POST", "/api/treasury/balance"): "treasury:write",
}


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


# ── CASE 1 ─────────────────────────────────────────────────────────────────


def test_attached_routes_have_auth_marker(app_routes: list[object]) -> None:
    """ALLOWLIST 의 17개 (method, path) 가 모두 marker 부착 dependency 로
    보호되어 있다."""
    # ``app.routes`` 에서 (method, path) → route 객체로 인덱싱.
    index: dict[tuple[str, str], object] = {}
    for route in app_routes:
        for key in _route_keys(route):
            index[key] = route

    missing_routes: list[tuple[str, str]] = []
    missing_marker: list[tuple[str, str]] = []
    for key in ATTACHED_ROUTE_ALLOWLIST:
        route = index.get(key)
        if route is None:
            missing_routes.append(key)
            continue
        if not _has_auth_marker(route):
            missing_marker.append(key)

    if missing_routes:
        pytest.fail(
            "ATTACHED_ROUTE_ALLOWLIST 에 등록된 라우트가 app.routes 에서 "
            f"발견되지 않음 (spec/code drift): {missing_routes}"
        )
    if missing_marker:
        pytest.fail(
            "ATTACHED_ROUTE_ALLOWLIST 에 등록된 라우트가 "
            "_is_authentication_dependency marker 가 부착된 dependency 로 "
            f"보호되지 않음 (marker 회귀): {missing_marker}"
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
