"""MemberService master 권한 검증 회귀 (issue #1351).

5개 mutation 메서드(``suspend``, ``reactivate``, ``revoke``, ``rotate_token``,
``update_scopes``)는 caller가 master가 아니면 ``PermissionDeniedError``를 raise
해야 한다. 빈 caller도 거부 대상이다.

이 모듈은 service-layer가 라우트 인증 가드와 무관하게 자체 invariant를
유지하도록 잠근다. 라우트 인증을 우회하는 모든 경로(미래의 다른 라우터,
내부 호출 등)에서 보안 회귀가 일어나지 않게 잠그는 두 번째 방어선이다.
"""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.member.errors import PermissionDeniedError
from ante.member.models import MemberStatus, MemberType
from ante.member.service import MemberService


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
async def service(db, eventbus):
    svc = MemberService(db, eventbus)
    await svc.initialize()
    return svc


@pytest.fixture
async def populated_service(service: MemberService) -> MemberService:
    """master(``owner``) + non-master(``agent-caller``) + 대상 멤버들 고정."""
    await service.bootstrap_master("owner", "pass123")
    await service.register("agent-caller", MemberType.AGENT, registered_by="owner")
    await service.register("agent-active", MemberType.AGENT, registered_by="owner")
    await service.register("agent-suspended", MemberType.AGENT, registered_by="owner")
    # suspended 상태 셋업
    await service.suspend("agent-suspended", suspended_by="owner")
    return service


# ── suspend ────────────────────────────────────────────────────────────────


class TestSuspendMasterGuard:
    async def test_suspend_with_empty_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.suspend("agent-active", suspended_by="")

    async def test_suspend_with_non_master_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.suspend("agent-active", suspended_by="agent-caller")

    async def test_suspend_with_unknown_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.suspend("agent-active", suspended_by="ghost")

    async def test_suspend_with_master_caller_succeeds(
        self, populated_service: MemberService
    ) -> None:
        member = await populated_service.suspend("agent-active", suspended_by="owner")
        assert member.status == MemberStatus.SUSPENDED


# ── reactivate ─────────────────────────────────────────────────────────────


class TestReactivateMasterGuard:
    async def test_reactivate_with_empty_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.reactivate("agent-suspended", reactivated_by="")

    async def test_reactivate_with_non_master_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.reactivate(
                "agent-suspended", reactivated_by="agent-caller"
            )

    async def test_reactivate_with_master_caller_succeeds(
        self, populated_service: MemberService
    ) -> None:
        member = await populated_service.reactivate(
            "agent-suspended", reactivated_by="owner"
        )
        assert member.status == MemberStatus.ACTIVE


# ── revoke ─────────────────────────────────────────────────────────────────


class TestRevokeMasterGuard:
    async def test_revoke_with_empty_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.revoke("agent-active", revoked_by="")

    async def test_revoke_with_non_master_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.revoke("agent-active", revoked_by="agent-caller")

    async def test_revoke_with_master_caller_succeeds(
        self, populated_service: MemberService
    ) -> None:
        member = await populated_service.revoke("agent-active", revoked_by="owner")
        assert member.status == MemberStatus.REVOKED


# ── rotate_token ──────────────────────────────────────────────────────────


class TestRotateTokenMasterGuard:
    async def test_rotate_token_with_empty_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.rotate_token("agent-active", rotated_by="")

    async def test_rotate_token_with_non_master_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.rotate_token(
                "agent-active", rotated_by="agent-caller"
            )

    async def test_rotate_token_with_master_caller_succeeds(
        self, populated_service: MemberService
    ) -> None:
        member, token = await populated_service.rotate_token(
            "agent-active", rotated_by="owner"
        )
        assert member.member_id == "agent-active"
        assert token.startswith("ante_ak_")


# ── update_scopes ─────────────────────────────────────────────────────────


class TestUpdateScopesMasterGuard:
    async def test_update_scopes_with_empty_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        """빈 caller가 더 이상 master 검증을 우회하면 안 된다 (#1351 — 회귀 잠금).

        이전에는 ``if updated_by:`` 가드 때문에 빈 caller가 검증을 건너뛰었다.
        이슈 #1351에서 이 분기를 제거하고 caller가 항상 master여야 한다는
        invariant를 강제한다.
        """
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.update_scopes(
                "agent-active", ["data:read"], updated_by=""
            )

    async def test_update_scopes_with_non_master_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.update_scopes(
                "agent-active", ["data:read"], updated_by="agent-caller"
            )

    async def test_update_scopes_with_master_caller_succeeds(
        self, populated_service: MemberService
    ) -> None:
        member = await populated_service.update_scopes(
            "agent-active", ["data:read"], updated_by="owner"
        )
        assert member.scopes == ["data:read"]


# ── master 우선순위 회귀 ───────────────────────────────────────────────────


class TestMasterCheckHappensBeforeStatusCheck:
    """master 검증이 status/role 검증보다 먼저 실행되어야 한다.

    그렇지 않으면 non-master가 missing member id로 ``ValueError``를 받아
    ``PermissionDeniedError``를 우회하는 분기가 생길 수 있다. 보안적으로는
    "이 caller는 어떤 결과도 받지 못한다"는 정책을 우선시한다.
    """

    async def test_suspend_non_master_on_unknown_member_raises_permission(
        self, populated_service: MemberService
    ) -> None:
        # 존재하지 않는 멤버여도 caller가 master가 아니면 PermissionDenied가
        # 먼저 raise 되어야 한다(존재 여부 정보 누설 방지).
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.suspend(
                "no-such-member", suspended_by="agent-caller"
            )

    async def test_update_scopes_non_master_on_unknown_member_raises_permission(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.update_scopes(
                "no-such-member", ["data:read"], updated_by="agent-caller"
            )


# ── master 보호와 충돌 시 우선순위 ────────────────────────────────────────


class TestMasterCallerOnMasterTarget:
    """master 본인을 대상으로 mutation 호출 시 기존 invariant 유지.

    master 보호 규칙(``master는 suspend할 수 없다``)은 그대로 동작해야 한다.
    """

    async def test_master_cannot_suspend_master(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionError, match="master는 suspend"):
            await populated_service.suspend("owner", suspended_by="owner")

    async def test_master_cannot_revoke_master(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionError, match="master는 revoke"):
            await populated_service.revoke("owner", revoked_by="owner")
