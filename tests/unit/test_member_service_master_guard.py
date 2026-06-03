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
from ante.member.errors import (
    MemberAlreadyExistsError,
    MemberInvalidEmojiError,
    MemberMasterProtectedError,
    PermissionDeniedError,
    ReservedMemberIdError,
)
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


# ── register (#2294 — 무조건 master 게이트) ────────────────────────────────


class TestRegisterMasterGuard:
    """#2294: ``register`` 의 master 검증이 **무조건** 수행되어야 한다.

    이전에는 ``if registered_by:`` 가드로 빈 actor 가 master 검증을
    우회했다. #2294 (#2113 메타리뷰 후속) 가 이 분기를 제거하고, 형제
    mutation (suspend/reactivate/revoke/rotate_token/update_scopes) 과 동일
    하게 caller 가 항상 master 여야 한다는 invariant 를 강제한다.
    """

    async def test_register_with_empty_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        """빈 actor("") 가 더 이상 master 검증을 우회하면 안 된다 (회귀 잠금).

        ``_assert_master("")`` → ``get("")`` 가 ``None`` 을 반환해
        ``PermissionDeniedError`` 로 거부된다 (의도된 defense-in-depth).
        """
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.register(
                "agent-new", MemberType.AGENT, registered_by=""
            )

    async def test_register_with_non_master_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.register(
                "agent-new", MemberType.AGENT, registered_by="agent-caller"
            )

    async def test_register_with_unknown_caller_raises(
        self, populated_service: MemberService
    ) -> None:
        """CLI 미인증 actor("unknown") 도 존재하지 않으므로 거부된다."""
        with pytest.raises(PermissionDeniedError, match="master만"):
            await populated_service.register(
                "agent-new", MemberType.AGENT, registered_by="unknown"
            )

    async def test_register_with_master_caller_succeeds(
        self, populated_service: MemberService
    ) -> None:
        member, token = await populated_service.register(
            "agent-new", MemberType.AGENT, registered_by="owner"
        )
        assert member.member_id == "agent-new"
        assert token.startswith("ante_ak_")


# ── register reserved-prefix guard (#2295) ─────────────────────────────────


class TestRegisterReservedMemberIdGuard:
    """#2295: ``register`` 가 reserved ``system:`` prefix member_id 를 거부.

    ``system:`` 는 system audit sentinel 네임스페이스
    (``system:kill_switch`` / ``system:recovery``) 전용 reserved prefix 다.
    사용자/agent member_id 가 이를 점유하면 audit 행위자 식별이 오염되므로
    ``ReservedMemberIdError`` (.code=MEMBER_ID_RESERVED) 로 거부한다.
    """

    async def test_register_system_recovery_rejected(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(ReservedMemberIdError):
            await populated_service.register(
                "system:recovery", MemberType.AGENT, registered_by="owner"
            )

    async def test_register_system_colon_arbitrary_rejected(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(ReservedMemberIdError):
            await populated_service.register(
                "system:abc", MemberType.AGENT, registered_by="owner"
            )

    async def test_reserved_error_has_stable_code(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(ReservedMemberIdError) as excinfo:
            await populated_service.register(
                "system:kill_switch", MemberType.AGENT, registered_by="owner"
            )
        assert excinfo.value.code == "MEMBER_ID_RESERVED"

    async def test_reserved_error_is_valueerror(
        self, populated_service: MemberService
    ) -> None:
        """``ValueError`` 다중상속으로 기존 generic fallback 회귀 없음."""
        with pytest.raises(ValueError):
            await populated_service.register(
                "system:x", MemberType.AGENT, registered_by="owner"
            )

    async def test_register_plain_system_allowed(
        self, populated_service: MemberService
    ) -> None:
        """콜론 없는 ``system`` 단독 member_id 는 오거부하지 않는다."""
        member, _ = await populated_service.register(
            "system", MemberType.AGENT, registered_by="owner"
        )
        assert member.member_id == "system"

    async def test_register_systemic_allowed(
        self, populated_service: MemberService
    ) -> None:
        """``systemic`` 등 ``system:`` 으로 시작하지 않는 member_id 는 허용."""
        member, _ = await populated_service.register(
            "systemic", MemberType.AGENT, registered_by="owner"
        )
        assert member.member_id == "systemic"

    async def test_register_normal_id_allowed(
        self, populated_service: MemberService
    ) -> None:
        member, _ = await populated_service.register(
            "agent-normal", MemberType.AGENT, registered_by="owner"
        )
        assert member.member_id == "agent-normal"

    async def test_reserved_guard_precedes_existing_member_lookup(
        self, populated_service: MemberService
    ) -> None:
        """reserved guard 는 existing-member 조회 *이전* 에 배치되어야 한다.

        legacy ``system:*`` 행이 DB 에 있어도 ``MEMBER_ALREADY_EXISTS`` 가
        아니라 ``MEMBER_ID_RESERVED`` 가 surface 되어야 한다 (Codex v2).
        guard 가 정상이면 DB 에 row 가 없으므로 INSERT 우회 자체로
        reserved 코드만 raise 된다 — 별도 row 주입 없이 reserved 가 항상
        먼저 매칭됨을 단언한다.
        """
        with pytest.raises(ReservedMemberIdError):
            await populated_service.register(
                "system:recovery", MemberType.AGENT, registered_by="owner"
            )
        # reserved guard 통과 후에도 일반 member_id duplicate 는 여전히
        # MemberAlreadyExistsError 로 별개 surface 됨 (분리된 fault 확인).
        await populated_service.register(
            "agent-dup", MemberType.AGENT, registered_by="owner"
        )
        with pytest.raises(MemberAlreadyExistsError):
            await populated_service.register(
                "agent-dup", MemberType.AGENT, registered_by="owner"
            )


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


# ── #1915 typed exception lock ────────────────────────────────────────────


class TestMemberMasterProtectedTypedException:
    """#1915: master 보호 위반은 typed ``MemberMasterProtectedError`` raise.

    이전 (#1915 이전): ``_assert_not_master`` 가 단순 ``PermissionError`` 를
    raise → CLI envelope 이 ``EXECUTION_ERROR`` 로 fallback.
    #1915 가 typed exception 으로 좁혀 안정 코드
    ``MEMBER_MASTER_PROTECTED`` 를 surface 한다.

    ``PermissionError`` 다중상속이라 기존 ``pytest.raises(PermissionError)``
    회귀 lock (상기 ``TestMasterCallerOnMasterTarget``) 은 그대로 통과한다.
    """

    async def test_suspend_master_raises_typed_exception(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(MemberMasterProtectedError, match="master는 suspend"):
            await populated_service.suspend("owner", suspended_by="owner")

    async def test_revoke_master_raises_typed_exception(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(MemberMasterProtectedError, match="master는 revoke"):
            await populated_service.revoke("owner", revoked_by="owner")

    async def test_typed_exception_has_stable_code(
        self, populated_service: MemberService
    ) -> None:
        """typed exception 의 class-level ``.code`` 는 안정 코드 그대로."""
        with pytest.raises(MemberMasterProtectedError) as excinfo:
            await populated_service.suspend("owner", suspended_by="owner")
        assert excinfo.value.code == "MEMBER_MASTER_PROTECTED"


class TestMemberInvalidEmojiTypedException:
    """#1915: emoji 형식 검증 거부는 typed ``MemberInvalidEmojiError`` raise.

    이전 (#1915 이전): ``_validate_emoji_format`` 이 단순 ``ValueError`` 를
    raise → CLI envelope 이 ``EXECUTION_ERROR`` fallback.
    #1915 가 typed exception 으로 좁혀 안정 코드 ``MEMBER_INVALID_EMOJI``
    를 surface 한다.

    ``ValueError`` 다중상속이라 기존 ``pytest.raises(ValueError, match=...)``
    회귀 lock (``test_member.py::TestEmojiValidation``) 은 그대로 통과한다.
    """

    async def test_update_emoji_invalid_format_raises_typed_exception(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(MemberInvalidEmojiError, match="단일 이모지만"):
            await populated_service.update_emoji(
                "agent-active", "abc", updated_by="owner"
            )

    async def test_typed_exception_has_stable_code(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(MemberInvalidEmojiError) as excinfo:
            await populated_service.update_emoji(
                "agent-active", "xyz", updated_by="owner"
            )
        assert excinfo.value.code == "MEMBER_INVALID_EMOJI"
