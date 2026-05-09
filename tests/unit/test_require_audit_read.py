"""``require_audit_read`` dependency 단위 테스트 (issue #1359 Codex P2 fix loop 2차).

dependency 자체의 동작(Bearer 우선, 쿠키 fallback, session_service None skip,
master OR ``audit:read`` scope 검증, ``request.state.member_id`` 갱신)을 라우트
통합 없이 검증한다. 라우트 통합 테스트는
``tests/unit/test_audit_routes_auth.py``에 있다.

배경:
    초기 패치는 ``GET /api/audit``에 ``require_master_caller``를 적용해 master
    role만 허용했다. 그러나 spec ``docs/specs/member/02-design-decisions.md:188-229``
    은 audit 도메인 read 권한을 ``master`` role 또는 ``audit:read`` scope 중
    하나로 정의하므로, 모니터링 전용 agent(default role + ``audit:read`` scope)
    가 차단되는 회귀가 발생했다. 본 dependency는 두 조건의 OR로 통과시킨다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ante.member.models import MemberRole
from ante.web.deps import require_audit_read


@dataclass
class _StubMember:
    member_id: str
    role: str
    scopes: list[str] = field(default_factory=list)


class _StubMemberService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._members: dict[str, _StubMember] = {}

    def add(
        self,
        member_id: str,
        role: str = "default",
        scopes: list[str] | None = None,
    ) -> None:
        self._members[member_id] = _StubMember(
            member_id=member_id,
            role=role,
            scopes=list(scopes) if scopes else [],
        )

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

    ``require_audit_read``는 ``request.state.member_id`` getattr와
    ``request.cookies.get`` 만 사용한다.
    """
    state = SimpleNamespace()
    if state_member_id is not None:
        state.member_id = state_member_id
    cookies_obj = cookies or {}
    return SimpleNamespace(state=state, cookies=cookies_obj)


# ── 200: 통과 케이스 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_caller_when_bearer_master() -> None:
    """master role → 통과 (scope와 무관)."""
    svc = _StubMemberService()
    svc.add("master-user", role=MemberRole.MASTER.value)
    request = _make_request(state_member_id="master-user")

    caller = await require_audit_read(request, svc, None)

    assert caller == "master-user"
    assert svc.calls == ["master-user"]


@pytest.mark.asyncio
async def test_returns_caller_when_default_with_audit_read_scope() -> None:
    """default role + ``audit:read`` scope → 통과 (모니터링 agent 시나리오).

    spec docs/specs/member/02-design-decisions.md:188-229 모니터링 agent.
    """
    svc = _StubMemberService()
    svc.add(
        "monitor-agent",
        role=MemberRole.DEFAULT.value,
        scopes=["bot:read", "trade:read", "audit:read"],
    )
    request = _make_request(state_member_id="monitor-agent")

    caller = await require_audit_read(request, svc, None)

    assert caller == "monitor-agent"
    assert svc.calls == ["monitor-agent"]


@pytest.mark.asyncio
async def test_returns_caller_when_admin_with_audit_read_scope() -> None:
    """admin role + ``audit:read`` scope → 통과."""
    svc = _StubMemberService()
    svc.add("admin-1", role=MemberRole.ADMIN.value, scopes=["audit:read"])
    request = _make_request(state_member_id="admin-1")

    caller = await require_audit_read(request, svc, None)

    assert caller == "admin-1"


@pytest.mark.asyncio
async def test_falls_back_to_session_cookie_when_bearer_missing() -> None:
    """Bearer 미설정 + 유효 세션 쿠키(audit:read 보유) → caller 결정 + state 갱신."""
    member_svc = _StubMemberService()
    member_svc.add(
        "cookie-monitor",
        role=MemberRole.DEFAULT.value,
        scopes=["audit:read"],
    )

    session_svc = _StubSessionService()
    session_svc.add_session("sid-1", "cookie-monitor")

    request = _make_request(cookies={"ante_session": "sid-1"})

    caller = await require_audit_read(request, member_svc, session_svc)

    assert caller == "cookie-monitor"
    assert session_svc.calls == ["sid-1"]
    # AuditMiddleware 일관성을 위해 request.state.member_id가 갱신돼야 한다.
    assert request.state.member_id == "cookie-monitor"


@pytest.mark.asyncio
async def test_bearer_caller_takes_precedence_over_cookie() -> None:
    """Bearer 토큰이 caller를 결정하면 쿠키 검증을 다시 호출하지 않는다."""
    member_svc = _StubMemberService()
    member_svc.add("bearer-master", role=MemberRole.MASTER.value)
    session_svc = _StubSessionService()
    session_svc.add_session("sid-1", "cookie-user")

    request = _make_request(
        state_member_id="bearer-master",
        cookies={"ante_session": "sid-1"},
    )

    caller = await require_audit_read(request, member_svc, session_svc)

    assert caller == "bearer-master"
    assert session_svc.calls == [], (
        "Bearer 결정 시 session_service.validate가 호출되어선 안 된다"
    )


# ── 401: 인증 실패 케이스 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raises_401_when_no_bearer_and_no_cookie() -> None:
    """Bearer 없음 + 쿠키 없음 → 401."""
    svc = _StubMemberService()
    request = _make_request()

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc, _StubSessionService())

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_raises_401_when_session_service_none_and_only_cookie() -> None:
    """``session_service is None`` + Bearer 없음 → 쿠키 fallback skip → 401."""
    svc = _StubMemberService()
    request = _make_request(cookies={"ante_session": "sid-1"})

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc, None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_raises_401_when_invalid_cookie() -> None:
    """유효하지 않은 세션 쿠키 → 401."""
    svc = _StubMemberService()
    session_svc = _StubSessionService()
    request = _make_request(cookies={"ante_session": "unknown-sid"})

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc, session_svc)

    assert exc.value.status_code == 401
    assert session_svc.calls == ["unknown-sid"]


@pytest.mark.asyncio
async def test_session_validate_exception_is_absorbed_as_401() -> None:
    """``session_service.validate`` 예외는 401로 흡수돼야 한다 (#1351 패턴)."""
    svc = _StubMemberService()
    session_svc = _StubSessionService(raise_on_validate=True)
    request = _make_request(cookies={"ante_session": "sid-1"})

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc, session_svc)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_raises_401_when_member_service_missing() -> None:
    """``member_service is None`` 분기는 cold-path invariant I1을 깨지 않게
    401로 떨어진다 (``require_master_caller``와 동일 정책).
    """
    request = _make_request(state_member_id="some-caller")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, None, None)

    assert exc.value.status_code == 401


# ── 403: 권한 실패 케이스 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raises_403_when_default_without_audit_read_scope() -> None:
    """default role + ``audit:read`` 미보유 → 403."""
    svc = _StubMemberService()
    svc.add("plain-agent", role=MemberRole.DEFAULT.value, scopes=["bot:read"])
    request = _make_request(state_member_id="plain-agent")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc, None)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_default_with_empty_scopes() -> None:
    """default role + scopes 비어있음 → 403."""
    svc = _StubMemberService()
    svc.add("plain-agent", role=MemberRole.DEFAULT.value, scopes=[])
    request = _make_request(state_member_id="plain-agent")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc, None)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_admin_without_audit_read_scope() -> None:
    """admin role + ``audit:read`` 미보유 → 403 (admin도 자동 통과 아님)."""
    svc = _StubMemberService()
    svc.add(
        "admin-no-scope",
        role=MemberRole.ADMIN.value,
        scopes=["bot:admin", "approval:write"],
    )
    request = _make_request(state_member_id="admin-no-scope")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc, None)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_caller_id_unknown_to_member_service() -> None:
    """인증 미들웨어가 ``request.state.member_id``를 채웠으나 멤버 서비스에
    해당 id가 없는 경우 → 403 (ghost caller invariant 보호).
    """
    svc = _StubMemberService()
    request = _make_request(state_member_id="ghost-id")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc, None)

    assert exc.value.status_code == 403
