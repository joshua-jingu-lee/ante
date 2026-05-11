"""``require_master_caller`` dependency 단위 테스트 (issues #1352 / #1408).

#1408 단순화 후 본 dep 은 ``RequireAuthMiddleware`` (#1403) 가 채운
``request.state.member_id`` 를 신뢰하고 다음만 수행한다:

    - ``member_service.get(caller)``
    - ``MemberStatus.ACTIVE`` re-check (TOCTOU race guard)
    - ``MemberRole.MASTER`` 강제

Bearer 헤더 / ``ante_session`` 쿠키 해석은 미들웨어 책임으로 이전되었으므로
본 파일은 더 이상 mock Bearer/cookie 분기를 검증하지 않는다. 라우트 통합
경로는 ``tests/unit/test_runtime_mutation_auth.py`` 가 ``TestClient`` 를
통해 미들웨어 + dep 합산을 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ante.member.models import MemberRole, MemberStatus
from ante.web.deps import require_master_caller


@dataclass
class _StubMember:
    member_id: str
    role: str
    status: str = MemberStatus.ACTIVE.value


class _StubMemberService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._members: dict[str, _StubMember] = {}

    def add(
        self,
        member_id: str,
        role: str = "default",
        status: str = MemberStatus.ACTIVE.value,
    ) -> None:
        self._members[member_id] = _StubMember(
            member_id=member_id, role=role, status=status
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
    """``request.state.member_id`` 가 master 면 caller 반환."""
    svc = _StubMemberService()
    svc.add("master-user", role=MemberRole.MASTER.value)
    request = _make_request(state_member_id="master-user")

    caller = await require_master_caller(request, svc)

    assert caller == "master-user"
    assert svc.calls == ["master-user"]


# ── 500: 미들웨어 invariant 위반 (#1408) ─────────────────────────────────


@pytest.mark.asyncio
async def test_raises_500_when_state_member_id_missing() -> None:
    """``request.state.member_id`` 미설정 → 500 invariant violation.

    #1408: ``RequireAuthMiddleware`` 가 보호 라우트 진입 전에
    ``request.state.member_id`` 를 반드시 채우므로, 비어 있다면 client 인증
    실패 (401) 가 아니라 서버 내부 invariant 위반이다.
    """
    svc = _StubMemberService()
    request = _make_request()

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc)

    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_raises_500_when_state_member_id_empty_string() -> None:
    """``request.state.member_id == ""`` → 500 (빈 문자열도 invariant 위반)."""
    svc = _StubMemberService()
    request = _make_request(state_member_id="")

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc)

    assert exc.value.status_code == 500


# ── 503: member_service 미주입 (cold-path) ──────────────────────────────


@pytest.mark.asyncio
async def test_raises_503_when_member_service_missing() -> None:
    """``member_service is None`` (cold-path invariant) → 503."""
    request = _make_request(state_member_id="some-caller")

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, None)

    assert exc.value.status_code == 503


# ── 403: 권한 / 비활성 케이스 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_raises_403_when_caller_is_not_master() -> None:
    """인증된 non-master → 403."""
    svc = _StubMemberService()
    svc.add("agent-01", role=MemberRole.DEFAULT.value)
    request = _make_request(state_member_id="agent-01")

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_caller_id_unknown_to_member_service() -> None:
    """미들웨어가 ``request.state.member_id`` 를 채웠으나 멤버 서비스에 해당
    id 가 없는 경우 → 403 (ghost caller invariant 보호).
    """
    svc = _StubMemberService()
    request = _make_request(state_member_id="ghost-id")

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_master_suspended() -> None:
    """master role 이지만 ``status == SUSPENDED`` → 403 (#1408 TOCTOU race guard).

    미들웨어가 ACTIVE 1차 검증을 했어도 권한 분기 전 race window 에서
    ``SUSPENDED`` 로 전환된 경우 본 dep 이 차단해야 한다.
    """
    svc = _StubMemberService()
    svc.add(
        "master-suspended",
        role=MemberRole.MASTER.value,
        status=MemberStatus.SUSPENDED.value,
    )
    request = _make_request(state_member_id="master-suspended")

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_raises_403_when_master_revoked() -> None:
    """master role 이지만 ``status == REVOKED`` → 403 (TOCTOU race guard)."""
    svc = _StubMemberService()
    svc.add(
        "master-revoked",
        role=MemberRole.MASTER.value,
        status=MemberStatus.REVOKED.value,
    )
    request = _make_request(state_member_id="master-revoked")

    with pytest.raises(HTTPException) as exc:
        await require_master_caller(request, svc)

    assert exc.value.status_code == 403
