"""``require_master_caller`` dependency 단위 테스트 (issue #1352).

dependency 자체의 동작(Bearer 우선, 쿠키 fallback, session_service None skip,
master 검증, ``request.state.member_id`` 갱신)을 라우트 통합 없이 검증한다.
실 통합 테스트는 ``tests/unit/test_runtime_mutation_auth.py``에 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ante.member.models import MemberRole
from ante.web.deps import require_master_caller


@dataclass
class _StubMember:
    member_id: str
    role: str


class _StubMemberService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._members: dict[str, _StubMember] = {}

    def add(self, member_id: str, role: str = "default") -> None:
        self._members[member_id] = _StubMember(member_id=member_id, role=role)

    async def get(self, member_id: str) -> _StubMember | None:
        self.calls.append(member_id)
        return self._members.get(member_id)


class _StubSessionService:
    def __init__(self, raise_on_validate: bool = False) -> None:
        self.calls: list[str] = []
        self._sessions: dict[str, str] = {}
        self.raise_on_validate = raise_on_validate

    def add_session(self, session_id: str, member_id: str) -> None:
        self._sessions[session_id] = member_id

    async def validate(self, session_id: str) -> dict | None:
        self.calls.append(session_id)
        if self.raise_on_validate:
            raise RuntimeError("session backend offline")
        member_id = self._sessions.get(session_id)
        if member_id is None:
            return None
        return {"member_id": member_id}


def _make_request(
    *,
    state_member_id: str | None = None,
    cookies: dict[str, str] | None = None,
) -> SimpleNamespace:
    """FastAPI Request 인터페이스를 흉내내는 최소 stub.

    ``require_master_caller``는 ``request.state.member_id`` getattr와
    ``request.cookies.get`` 만 사용한다.
    """
    state = SimpleNamespace()
    if state_member_id is not None:
        state.member_id = state_member_id
    cookies_obj = cookies or {}
    return SimpleNamespace(state=state, cookies=cookies_obj)


@pytest.mark.asyncio
async def test_returns_caller_when_bearer_master() -> None:
    """``request.state.member_id`` (Bearer 경로)가 master면 caller 반환."""
    svc = _StubMemberService()
    svc.add("master-user", role=MemberRole.MASTER.value)
    request = _make_request(state_member_id="master-user")

    caller = await require_master_caller(request, svc, None)

    assert caller == "master-user"
    assert svc.calls == ["master-user"]


@pytest.mark.asyncio
async def test_falls_back_to_session_cookie_when_bearer_missing() -> None:
    """Bearer 미설정 + 유효 세션 쿠키 → caller 결정 + state 갱신."""
    member_svc = _StubMemberService()
    member_svc.add("master-cookie-user", role=MemberRole.MASTER.value)

    session_svc = _StubSessionService()
    session_svc.add_session("sid-1", "master-cookie-user")

    request = _make_request(cookies={"ante_session": "sid-1"})

    caller = await require_master_caller(request, member_svc, session_svc)

    assert caller == "master-cookie-user"
    assert session_svc.calls == ["sid-1"]
    # AuditMiddleware 일관성을 위해 request.state.member_id가 갱신돼야 한다.
    assert request.state.member_id == "master-cookie-user"


@pytest.mark.asyncio
async def test_raises_401_when_no_bearer_and_no_cookie() -> None:
    """Bearer 없음 + 쿠키 없음 → 401."""
    svc = _StubMemberService()
    request = _make_request()

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc, _StubSessionService())

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_raises_401_when_session_service_none_and_only_cookie() -> None:
    """``session_service is None`` + Bearer 없음 → 쿠키 fallback skip → 401."""
    svc = _StubMemberService()
    request = _make_request(cookies={"ante_session": "sid-1"})

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc, None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_raises_401_when_invalid_cookie() -> None:
    """유효하지 않은 세션 쿠키 → 401."""
    svc = _StubMemberService()
    session_svc = _StubSessionService()
    request = _make_request(cookies={"ante_session": "unknown-sid"})

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc, session_svc)

    assert exc.value.status_code == 401
    assert session_svc.calls == ["unknown-sid"]


@pytest.mark.asyncio
async def test_session_validate_exception_is_absorbed_as_401() -> None:
    """``session_service.validate`` 예외는 401로 흡수돼야 한다 (#1351 패턴)."""
    svc = _StubMemberService()
    session_svc = _StubSessionService(raise_on_validate=True)
    request = _make_request(cookies={"ante_session": "sid-1"})

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc, session_svc)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_raises_403_when_caller_is_not_master() -> None:
    """인증된 non-master → 403, 메시지 톤은 한국어."""
    svc = _StubMemberService()
    svc.add("agent-01", role=MemberRole.DEFAULT.value)
    request = _make_request(state_member_id="agent-01")

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc, None)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_caller_id_unknown_to_member_service() -> None:
    """인증 미들웨어가 ``request.state.member_id``를 채웠으나 멤버 서비스에
    해당 id가 없는 경우 → 403 (ghost caller invariant 보호).
    """
    svc = _StubMemberService()
    request = _make_request(state_member_id="ghost-id")

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc, None)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_bearer_caller_takes_precedence_over_cookie() -> None:
    """Bearer 토큰이 caller를 결정하면 쿠키 검증을 다시 호출하지 않는다."""
    member_svc = _StubMemberService()
    member_svc.add("master-bearer", role=MemberRole.MASTER.value)
    session_svc = _StubSessionService()
    session_svc.add_session("sid-1", "master-cookie-user")

    request = _make_request(
        state_member_id="master-bearer",
        cookies={"ante_session": "sid-1"},
    )

    caller = await require_master_caller(request, member_svc, session_svc)

    assert caller == "master-bearer"
    assert session_svc.calls == [], (
        "Bearer 결정 시 session_service.validate가 호출되어선 안 된다"
    )
