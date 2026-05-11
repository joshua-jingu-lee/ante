"""``require_audit_read`` dependency 단위 테스트 (issues #1359 / #1408).

#1408 단순화 후 본 dep 은 ``RequireAuthMiddleware`` (#1403) 가 채운
``request.state.member_id`` 를 신뢰하고 다음만 수행한다:

    - ``member_service.get(caller)``
    - ``MemberStatus.ACTIVE`` re-check (TOCTOU race guard)
    - ``require_scope`` predicate (master / human bypass / scope ∈ scopes)

spec ``docs/specs/member/02-design-decisions.md:210-221`` 의 ``require_scope``
predicate 와 동일:

    - master role → 통과
    - human 멤버 → 통과 (scope 무관)
    - ``audit:read`` ∈ scopes → 통과 (agent 정상 경로)
    - 그 외 (agent without scope) → 403

Bearer 헤더 / ``ante_session`` 쿠키 해석은 미들웨어 책임으로 이전되었으므로
본 파일은 더 이상 mock Bearer/cookie 분기를 검증하지 않는다 (#1408). 통합
경로는 ``tests/unit/test_audit_routes_auth.py`` / ``tests/unit/test_runtime_
mutation_auth.py`` 가 ``TestClient`` 를 통해 미들웨어 + dep 합산을 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ante.member.models import MemberRole, MemberStatus, MemberType
from ante.web.deps import require_audit_read


@dataclass
class _StubMember:
    member_id: str
    role: str
    type: str = MemberType.AGENT.value
    scopes: list[str] = field(default_factory=list)
    status: str = MemberStatus.ACTIVE.value


class _StubMemberService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._members: dict[str, _StubMember] = {}

    def add(
        self,
        member_id: str,
        role: str = "default",
        member_type: str = MemberType.AGENT.value,
        scopes: list[str] | None = None,
        status: str = MemberStatus.ACTIVE.value,
    ) -> None:
        self._members[member_id] = _StubMember(
            member_id=member_id,
            role=role,
            type=member_type,
            scopes=list(scopes) if scopes else [],
            status=status,
        )

    async def get(self, member_id: str) -> _StubMember | None:
        self.calls.append(member_id)
        return self._members.get(member_id)


def _make_request(*, state_member_id: str | None = None) -> SimpleNamespace:
    """FastAPI Request 의 최소 stub.

    #1408 단순화 후 dep 은 ``request.state.member_id`` 만 참조한다. 미들웨어가
    이미 채운 상태를 흉내내기 위해 ``state_member_id`` 만 받는다.
    """
    state = SimpleNamespace()
    if state_member_id is not None:
        state.member_id = state_member_id
    return SimpleNamespace(state=state)


# ── 200: 통과 케이스 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_caller_when_master() -> None:
    """master role → 통과 (scope 와 무관)."""
    svc = _StubMemberService()
    svc.add(
        "master-user",
        role=MemberRole.MASTER.value,
        member_type=MemberType.HUMAN.value,
    )
    request = _make_request(state_member_id="master-user")

    caller = await require_audit_read(request, svc)

    assert caller == "master-user"
    assert svc.calls == ["master-user"]


@pytest.mark.asyncio
async def test_returns_caller_when_human_admin_without_scope() -> None:
    """human admin 멤버 → 통과 (scope 미보유여도 human bypass).

    spec docs/specs/member/02-design-decisions.md:210-221 ``require_scope``
    predicate: ``member.type == "human"`` 이면 scope 검증 자동 통과.
    """
    svc = _StubMemberService()
    svc.add(
        "human-admin",
        role=MemberRole.ADMIN.value,
        member_type=MemberType.HUMAN.value,
        scopes=[],
    )
    request = _make_request(state_member_id="human-admin")

    caller = await require_audit_read(request, svc)

    assert caller == "human-admin"
    assert svc.calls == ["human-admin"]


@pytest.mark.asyncio
async def test_returns_caller_when_human_default_without_scope() -> None:
    """human default 멤버 → 통과 (scope 미보유여도 human bypass).

    spec ``require_scope`` predicate 는 type 만 보고 scope 비검사.
    """
    svc = _StubMemberService()
    svc.add(
        "human-default",
        role=MemberRole.DEFAULT.value,
        member_type=MemberType.HUMAN.value,
        scopes=[],
    )
    request = _make_request(state_member_id="human-default")

    caller = await require_audit_read(request, svc)

    assert caller == "human-default"
    assert svc.calls == ["human-default"]


@pytest.mark.asyncio
async def test_returns_caller_when_default_with_audit_read_scope() -> None:
    """agent default role + ``audit:read`` scope → 통과 (모니터링 agent 시나리오).

    spec docs/specs/member/02-design-decisions.md:188-229 모니터링 agent.
    """
    svc = _StubMemberService()
    svc.add(
        "monitor-agent",
        role=MemberRole.DEFAULT.value,
        member_type=MemberType.AGENT.value,
        scopes=["bot:read", "trade:read", "audit:read"],
    )
    request = _make_request(state_member_id="monitor-agent")

    caller = await require_audit_read(request, svc)

    assert caller == "monitor-agent"
    assert svc.calls == ["monitor-agent"]


@pytest.mark.asyncio
async def test_returns_caller_when_admin_with_audit_read_scope() -> None:
    """agent admin role + ``audit:read`` scope → 통과."""
    svc = _StubMemberService()
    svc.add(
        "admin-1",
        role=MemberRole.ADMIN.value,
        member_type=MemberType.AGENT.value,
        scopes=["audit:read"],
    )
    request = _make_request(state_member_id="admin-1")

    caller = await require_audit_read(request, svc)

    assert caller == "admin-1"


# ── 500: 미들웨어 invariant 위반 (#1408) ─────────────────────────────────


@pytest.mark.asyncio
async def test_raises_500_when_state_member_id_missing() -> None:
    """``request.state.member_id`` 미설정 → 500 invariant violation.

    #1408: ``RequireAuthMiddleware`` 가 보호 라우트 진입 전에
    ``request.state.member_id`` 를 반드시 채우므로, 비어 있다면 client 인증
    실패 (401) 가 아니라 미들웨어 설치 누락/순서 오류 같은 서버 내부 invariant
    위반이다.
    """
    svc = _StubMemberService()
    request = _make_request()  # state.member_id 미설정

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_raises_500_when_state_member_id_empty_string() -> None:
    """``request.state.member_id == ""`` → 500 (빈 문자열도 invariant 위반)."""
    svc = _StubMemberService()
    request = _make_request(state_member_id="")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 500


# ── 503: member_service 미주입 (cold-path) ──────────────────────────────


@pytest.mark.asyncio
async def test_raises_503_when_member_service_missing() -> None:
    """``member_service is None`` (cold-path invariant) → 503.

    정상 배포에서는 항상 주입되며 미들웨어 통과 시점에도 검증되었으므로
    도달하지 않는다.
    """
    request = _make_request(state_member_id="some-caller")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, None)

    assert exc.value.status_code == 503


# ── 403: 권한 실패 케이스 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raises_403_when_agent_default_without_audit_read_scope() -> None:
    """agent default role + ``audit:read`` 미보유 → 403."""
    svc = _StubMemberService()
    svc.add(
        "plain-agent",
        role=MemberRole.DEFAULT.value,
        member_type=MemberType.AGENT.value,
        scopes=["bot:read"],
    )
    request = _make_request(state_member_id="plain-agent")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_agent_default_with_empty_scopes() -> None:
    """agent default role + scopes 비어있음 → 403."""
    svc = _StubMemberService()
    svc.add(
        "plain-agent",
        role=MemberRole.DEFAULT.value,
        member_type=MemberType.AGENT.value,
        scopes=[],
    )
    request = _make_request(state_member_id="plain-agent")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_agent_admin_without_audit_read_scope() -> None:
    """agent admin role + ``audit:read`` 미보유 → 403 (agent admin 은 자동 통과 아님).

    agent 는 type bypass 대상이 아니므로 scope 검증을 받는다.
    """
    svc = _StubMemberService()
    svc.add(
        "admin-no-scope",
        role=MemberRole.ADMIN.value,
        member_type=MemberType.AGENT.value,
        scopes=["bot:admin", "approval:write"],
    )
    request = _make_request(state_member_id="admin-no-scope")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_caller_id_unknown_to_member_service() -> None:
    """미들웨어가 ``request.state.member_id`` 를 채웠으나 멤버 서비스에 해당
    id 가 없는 경우 → 403 (ghost caller invariant 보호).
    """
    svc = _StubMemberService()
    request = _make_request(state_member_id="ghost-id")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 403


# ── 403: 비활성 멤버 차단 (TOCTOU race guard, #1359 fix loop 4차 / #1408) ─


@pytest.mark.asyncio
async def test_raises_403_when_master_suspended() -> None:
    """master role 이지만 ``status == SUSPENDED`` → 403.

    미들웨어가 ACTIVE 1차 검증을 했어도 권한 분기 전 race window 에서
    ``SUSPENDED`` 로 전환된 경우 본 dep 이 차단해야 한다 (#1408 TOCTOU guard).
    """
    svc = _StubMemberService()
    svc.add(
        "master-suspended",
        role=MemberRole.MASTER.value,
        member_type=MemberType.HUMAN.value,
        status=MemberStatus.SUSPENDED.value,
    )
    request = _make_request(state_member_id="master-suspended")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_master_revoked() -> None:
    """master role 이지만 ``status == REVOKED`` → 403."""
    svc = _StubMemberService()
    svc.add(
        "master-revoked",
        role=MemberRole.MASTER.value,
        member_type=MemberType.HUMAN.value,
        status=MemberStatus.REVOKED.value,
    )
    request = _make_request(state_member_id="master-revoked")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_human_admin_suspended() -> None:
    """human admin (type bypass 대상) 이라도 ``status == SUSPENDED`` → 403.

    type bypass 가 status 검사보다 우선해서는 안 된다.
    """
    svc = _StubMemberService()
    svc.add(
        "human-admin-suspended",
        role=MemberRole.ADMIN.value,
        member_type=MemberType.HUMAN.value,
        status=MemberStatus.SUSPENDED.value,
    )
    request = _make_request(state_member_id="human-admin-suspended")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_agent_with_audit_read_scope_suspended() -> None:
    """agent + ``audit:read`` scope 보유라도 ``status == SUSPENDED`` → 403.

    scope 보유가 status 검사보다 우선해서는 안 된다.
    """
    svc = _StubMemberService()
    svc.add(
        "monitor-agent-suspended",
        role=MemberRole.DEFAULT.value,
        member_type=MemberType.AGENT.value,
        scopes=["audit:read"],
        status=MemberStatus.SUSPENDED.value,
    )
    request = _make_request(state_member_id="monitor-agent-suspended")

    with pytest.raises(HTTPException) as exc:
        await require_audit_read(request, svc)

    assert exc.value.status_code == 403
