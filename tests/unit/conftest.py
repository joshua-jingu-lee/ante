"""tests/unit 공통 fixture.

``RequireAuthMiddleware`` (#1403) 도입 후 default-deny 가 모든 보호 라우트에
적용된다. 라우트의 비즈니스 로직만 검증하는 테스트들이 익명 호출로 401 회귀를
일으키지 않도록, 본 모듈에서 공용 ``master_member_service`` /
``master_auth_headers`` / ``authed_test_client`` 헬퍼를 제공한다.

설계 의도:

* 미들웨어 게이트 자체의 매트릭스는 ``test_require_auth_middleware.py`` /
  ``test_runtime_mutation_auth.py`` 가 별도로 보호한다. 본 헬퍼는 그 외의
  "라우트 동작 검증" 테스트가 인증 게이트를 깔끔하게 통과하도록 돕는
  공통 stub 일 뿐, 인증 매트릭스를 대체하지 않는다.
* ``_MasterOnlyMemberService`` 는 단일 master 토큰 ``master-test-token`` 만
  인증한다. ``TokenAuthMiddleware`` 가 ``authenticate(token)`` 을,
  ``RequireAuthMiddleware`` 가 세션 fallback 경로에서 ``get(member_id)`` 를
  호출한다.
* ``make_authed_client(app)`` 는 master Bearer 토큰을 디폴트 헤더로 부착한
  ``TestClient`` 를 돌려준다. 라우트 동작 테스트의 표준 진입점이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient


@dataclass
class _MasterMember:
    """tests/unit 공용 master 멤버 stub.

    필드는 ``ante.member.models.Member`` 의 직렬화 가능한 부분 집합과
    동일한 모양을 가진다. RequireAuthMiddleware 세션 fallback 의
    ``status`` 검사를 통과하기 위해 ``status="active"`` 를 유지한다.
    """

    member_id: str = "master-test"
    type: str = "human"
    role: str = "master"
    org: str = "default"
    name: str = "Test Master"
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = dc_field(default_factory=list)


class _MasterOnlyMemberService:
    """master 토큰 ``master-test-token`` 만 인증하는 최소 stub.

    ``TokenAuthMiddleware`` 가 ``authenticate(token)`` 을, ``RequireAuthMiddleware``
    가 ``get(member_id)`` 를 호출한다. ``update_last_active`` 는 no-op.
    """

    def __init__(self) -> None:
        self._master = _MasterMember()

    async def authenticate(self, token: str) -> _MasterMember:
        if token != "master-test-token":
            raise PermissionError("invalid token")
        return self._master

    async def get(self, member_id: str) -> _MasterMember | None:
        if member_id == self._master.member_id:
            return self._master
        return None

    async def update_last_active(self, member_id: str) -> None:
        return None


# tests/unit 표준 master Bearer 헤더. 공통 helper 가 자동 부착하지만,
# 인증 없는 동일 라우트 검증 등에서 명시 사용할 수 있도록 노출한다.
MASTER_AUTH_HEADERS: dict[str, str] = {"Authorization": "Bearer master-test-token"}


def make_master_member_service() -> _MasterOnlyMemberService:
    """라우트 동작 테스트용 master-only ``MemberService`` 인스턴스 생성."""
    return _MasterOnlyMemberService()


def make_authed_client(app: FastAPI) -> TestClient:
    """master Bearer 토큰을 디폴트 헤더로 부착한 ``TestClient``.

    호출 측은 ``create_app(..., member_service=make_master_member_service())``
    로 app 을 만든 뒤 본 함수로 client 를 받는다. default-deny 가 적용된 보호
    라우트가 자동으로 인증을 통과한다.
    """
    from fastapi.testclient import TestClient

    test_client = TestClient(app)
    test_client.headers.update(MASTER_AUTH_HEADERS)
    return test_client


@pytest.fixture
def master_member_service() -> _MasterOnlyMemberService:
    """라우트 동작 테스트용 master-only ``MemberService`` fixture."""
    return make_master_member_service()


@pytest.fixture
def master_auth_headers() -> dict[str, str]:
    """master Bearer 디폴트 헤더 fixture (인증 없는 client 와 함께 쓸 때 명시 사용)."""
    return dict(MASTER_AUTH_HEADERS)
