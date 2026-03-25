"""Member 모듈 단위 테스트."""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    MemberAuthFailedEvent,
    MemberRegisteredEvent,
    MemberRevokedEvent,
    MemberSuspendedEvent,
)
from ante.member.auth import (
    generate_recovery_key,
    generate_token,
    get_token_type,
    hash_password,
    hash_token,
    verify_password,
    verify_recovery_key,
    verify_token,
)
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.member.service import ANIMAL_EMOJI_POOL, MemberService

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def service(db, eventbus):
    svc = MemberService(db, eventbus)
    await svc.initialize()
    return svc


# ── Models ───────────────────────────────────────────


class TestModels:
    def test_member_type_values(self):
        assert MemberType.HUMAN == "human"
        assert MemberType.AGENT == "agent"

    def test_member_role_values(self):
        assert MemberRole.MASTER == "master"
        assert MemberRole.ADMIN == "admin"
        assert MemberRole.DEFAULT == "default"

    def test_member_status_values(self):
        assert MemberStatus.ACTIVE == "active"
        assert MemberStatus.SUSPENDED == "suspended"
        assert MemberStatus.REVOKED == "revoked"

    def test_member_dataclass(self):
        m = Member(
            member_id="test-01",
            type=MemberType.AGENT,
            role=MemberRole.DEFAULT,
        )
        assert m.member_id == "test-01"
        assert m.org == "default"
        assert m.scopes == []
        assert m.status == MemberStatus.ACTIVE


# ── Auth Utilities ───────────────────────────────────


class TestAuth:
    def test_generate_token_human(self):
        token = generate_token(MemberType.HUMAN)
        assert token.startswith("ante_hk_")

    def test_generate_token_agent(self):
        token = generate_token(MemberType.AGENT)
        assert token.startswith("ante_ak_")

    def test_generate_token_invalid_type(self):
        with pytest.raises(ValueError, match="지원하지 않는 멤버 타입"):
            generate_token("unknown")

    def test_hash_and_verify_token(self):
        token = generate_token(MemberType.HUMAN)
        h = hash_token(token)
        assert verify_token(token, h)
        assert not verify_token("wrong_token", h)

    def test_get_token_type(self):
        assert get_token_type("ante_hk_abc") == MemberType.HUMAN
        assert get_token_type("ante_ak_abc") == MemberType.AGENT
        assert get_token_type("unknown_abc") is None

    def test_hash_and_verify_password(self):
        stored = hash_password("secret123")
        assert verify_password("secret123", stored)
        assert not verify_password("wrong", stored)

    def test_recovery_key_format(self):
        key = generate_recovery_key()
        assert key.startswith("ANTE-RK-")
        parts = key.replace("ANTE-RK-", "").split("-")
        assert len(parts) == 6
        assert all(len(p) == 4 for p in parts)

    def test_recovery_key_verify(self):
        from ante.member.auth import hash_recovery_key

        key = generate_recovery_key()
        h = hash_recovery_key(key)
        assert verify_recovery_key(key, h)
        assert not verify_recovery_key("ANTE-RK-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX", h)


# ── MemberService ────────────────────────────────────


class TestBootstrapMaster:
    async def test_bootstrap_creates_master(self, service):
        member, token, recovery_key = await service.bootstrap_master(
            member_id="owner", password="pass123", name="대표"
        )
        assert member.member_id == "owner"
        assert member.type == MemberType.HUMAN
        assert member.role == MemberRole.MASTER
        assert member.name == "대표"
        assert token.startswith("ante_hk_")
        assert recovery_key.startswith("ANTE-RK-")

    async def test_bootstrap_twice_fails(self, service):
        await service.bootstrap_master("owner", "pass123")
        with pytest.raises(ValueError, match="master가 이미 존재합니다"):
            await service.bootstrap_master("owner2", "pass456")

    async def test_bootstrap_publishes_event(self, service, eventbus):
        events = []
        eventbus.subscribe(MemberRegisteredEvent, events.append)
        await service.bootstrap_master("owner", "pass123")
        assert len(events) == 1
        assert events[0].member_id == "owner"
        assert events[0].role == "master"


class TestRegister:
    async def test_register_agent(self, service):
        await service.bootstrap_master("owner", "pass123")
        member, token = await service.register(
            member_id="agent-01",
            member_type=MemberType.AGENT,
            org="strategy-lab",
            name="전략봇 1호",
            scopes=["strategy:write", "data:read"],
            registered_by="owner",
        )
        assert member.member_id == "agent-01"
        assert member.type == MemberType.AGENT
        assert member.role == MemberRole.DEFAULT
        assert member.org == "strategy-lab"
        assert token.startswith("ante_ak_")
        assert member.scopes == ["strategy:write", "data:read"]

    async def test_register_duplicate_fails(self, service):
        await service.register("agent-01", MemberType.AGENT)
        with pytest.raises(ValueError, match="이미 존재하는"):
            await service.register("agent-01", MemberType.AGENT)

    async def test_register_agent_as_master_fails(self, service):
        with pytest.raises(PermissionError, match="agent 타입은 master"):
            await service.register(
                "bad-agent", MemberType.AGENT, role=MemberRole.MASTER
            )

    async def test_register_agent_as_admin_fails(self, service):
        with pytest.raises(PermissionError, match="agent 타입은 master 또는 admin"):
            await service.register("bad-agent", MemberType.AGENT, role=MemberRole.ADMIN)


class TestAuthenticate:
    async def test_authenticate_token(self, service):
        _, token = await service.register("agent-01", MemberType.AGENT)
        member = await service.authenticate(token)
        assert member.member_id == "agent-01"

    async def test_authenticate_invalid_prefix(self, service):
        with pytest.raises(PermissionError, match="유효하지 않은 토큰 형식"):
            await service.authenticate("invalid_token_xyz")

    async def test_authenticate_wrong_token(self, service):
        await service.register("agent-01", MemberType.AGENT)
        with pytest.raises(PermissionError, match="인증 실패"):
            await service.authenticate("ante_ak_nonexistent_token")

    async def test_authenticate_suspended_member(self, service):
        _, token = await service.register("agent-01", MemberType.AGENT)
        await service.suspend("agent-01", suspended_by="owner")
        with pytest.raises(PermissionError, match="비활성 멤버"):
            await service.authenticate(token)

    async def test_authenticate_type_mismatch(self, service, db):
        """agent 토큰으로 human 멤버를 인증할 수 없다."""
        await service.bootstrap_master("owner", "pass123")
        _, token = await service.register(
            "human-01", MemberType.HUMAN, registered_by="owner"
        )
        # 토큰은 ante_hk_ 이지만, DB를 직접 조작하여 type을 agent로 변경
        await db.execute(
            "UPDATE members SET type = ? WHERE member_id = ?",
            (MemberType.AGENT, "human-01"),
        )
        with pytest.raises(PermissionError, match="인증 불가"):
            await service.authenticate(token)


class TestAuthenticatePassword:
    async def test_password_auth(self, service):
        await service.bootstrap_master("owner", "pass123")
        member = await service.authenticate_password("owner", "pass123")
        assert member.member_id == "owner"

    async def test_wrong_password(self, service):
        await service.bootstrap_master("owner", "pass123")
        with pytest.raises(PermissionError, match="인증 실패"):
            await service.authenticate_password("owner", "wrong")

    async def test_agent_cannot_password_auth(self, service):
        await service.register("agent-01", MemberType.AGENT)
        with pytest.raises(PermissionError, match="human 멤버만"):
            await service.authenticate_password("agent-01", "anything")

    async def test_nonexistent_member(self, service):
        with pytest.raises(PermissionError, match="인증 실패"):
            await service.authenticate_password("ghost", "pass")


class TestSuspendReactivateRevoke:
    async def test_suspend_and_reactivate(self, service):
        await service.register("agent-01", MemberType.AGENT)
        m = await service.suspend("agent-01", suspended_by="owner")
        assert m.status == MemberStatus.SUSPENDED

        m = await service.reactivate("agent-01", reactivated_by="owner")
        assert m.status == MemberStatus.ACTIVE

    async def test_suspend_master_fails(self, service):
        await service.bootstrap_master("owner", "pass123")
        with pytest.raises(PermissionError, match="master는 suspend"):
            await service.suspend("owner")

    async def test_revoke(self, service):
        await service.register("agent-01", MemberType.AGENT)
        m = await service.revoke("agent-01", revoked_by="owner")
        assert m.status == MemberStatus.REVOKED
        assert m.token_hash == ""

    async def test_revoke_suspended_member(self, service):
        await service.register("agent-01", MemberType.AGENT)
        await service.suspend("agent-01", suspended_by="owner")
        m = await service.revoke("agent-01", revoked_by="owner")
        assert m.status == MemberStatus.REVOKED
        assert m.token_hash == ""

    async def test_revoke_already_revoked_fails(self, service):
        await service.register("agent-01", MemberType.AGENT)
        await service.revoke("agent-01", revoked_by="owner")
        with pytest.raises(PermissionError, match="active, suspended 상태에서만"):
            await service.revoke("agent-01", revoked_by="owner")

    async def test_revoke_master_fails(self, service):
        await service.bootstrap_master("owner", "pass123")
        with pytest.raises(PermissionError, match="master는 revoke"):
            await service.revoke("owner")

    async def test_reactivate_active_fails(self, service):
        await service.register("agent-01", MemberType.AGENT)
        with pytest.raises(PermissionError, match="suspended 상태에서만"):
            await service.reactivate("agent-01")

    async def test_suspend_publishes_event(self, service, eventbus):
        events = []
        eventbus.subscribe(MemberSuspendedEvent, events.append)
        await service.register("agent-01", MemberType.AGENT)
        await service.suspend("agent-01", suspended_by="owner")
        assert len(events) == 1
        assert events[0].member_id == "agent-01"

    async def test_reactivate_publishes_event(self, service, eventbus):
        from ante.eventbus.events import MemberReactivatedEvent

        events: list = []
        eventbus.subscribe(MemberReactivatedEvent, events.append)
        await service.register("agent-01", MemberType.AGENT)
        await service.suspend("agent-01", suspended_by="owner")
        await service.reactivate("agent-01", reactivated_by="owner")
        assert len(events) == 1
        assert events[0].member_id == "agent-01"
        assert events[0].reactivated_by == "owner"

    async def test_revoke_publishes_event(self, service, eventbus):
        events = []
        eventbus.subscribe(MemberRevokedEvent, events.append)
        await service.register("agent-01", MemberType.AGENT)
        await service.revoke("agent-01", revoked_by="owner")
        assert len(events) == 1


class TestRotateToken:
    async def test_rotate_token(self, service):
        _, old_token = await service.register("agent-01", MemberType.AGENT)
        _, new_token = await service.rotate_token("agent-01", rotated_by="owner")
        assert old_token != new_token
        # 새 토큰으로 인증 성공
        m = await service.authenticate(new_token)
        assert m.member_id == "agent-01"
        # 기존 토큰으로 인증 실패
        with pytest.raises(PermissionError):
            await service.authenticate(old_token)


class TestPasswordManagement:
    async def test_change_password(self, service):
        await service.bootstrap_master("owner", "pass123")
        await service.change_password("owner", "pass123", "newpass")
        m = await service.authenticate_password("owner", "newpass")
        assert m.member_id == "owner"

    async def test_change_password_wrong_old(self, service):
        await service.bootstrap_master("owner", "pass123")
        with pytest.raises(PermissionError, match="패스워드가 일치하지"):
            await service.change_password("owner", "wrong", "newpass")

    async def test_reset_password_with_recovery_key(self, service):
        _, _, recovery_key = await service.bootstrap_master("owner", "pass123")
        await service.reset_password("owner", recovery_key, "resetpass")
        m = await service.authenticate_password("owner", "resetpass")
        assert m.member_id == "owner"

    async def test_reset_password_wrong_key(self, service):
        await service.bootstrap_master("owner", "pass123")
        with pytest.raises(PermissionError, match="유효하지 않은 recovery key"):
            await service.reset_password(
                "owner", "ANTE-RK-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX", "newpass"
            )

    async def test_regenerate_recovery_key(self, service):
        _, _, old_key = await service.bootstrap_master("owner", "pass123")
        new_key = await service.regenerate_recovery_key("owner", "pass123")
        assert new_key != old_key
        assert new_key.startswith("ANTE-RK-")
        # 새 키로 패스워드 리셋 가능
        await service.reset_password("owner", new_key, "resetpass2")
        # 기존 키로 리셋 불가
        with pytest.raises(PermissionError):
            await service.reset_password("owner", old_key, "hack")


class TestScopes:
    async def test_update_scopes(self, service):
        await service.bootstrap_master("owner", "pass123")
        await service.register("agent-01", MemberType.AGENT)
        m = await service.update_scopes(
            "agent-01", ["strategy:write", "data:read"], updated_by="owner"
        )
        assert m.scopes == ["strategy:write", "data:read"]
        # DB에 반영 확인
        fetched = await service.get("agent-01")
        assert fetched.scopes == ["strategy:write", "data:read"]


class TestMasterPermissionCheck:
    """register/update_scopes에서 master 권한 검증 테스트."""

    async def test_register_by_agent_fails(self, service):
        """agent 역할의 멤버가 register 호출 시 PermissionDeniedError."""
        from ante.member.errors import PermissionDeniedError

        await service.register("agent-caller", MemberType.AGENT)
        with pytest.raises(PermissionDeniedError, match="master만"):
            await service.register(
                "new-agent", MemberType.AGENT, registered_by="agent-caller"
            )

    async def test_register_by_default_human_fails(self, service):
        """default 역할의 human이 register 호출 시 PermissionDeniedError."""
        from ante.member.errors import PermissionDeniedError

        await service.bootstrap_master("owner", "pass123")
        await service.register(
            "human-default",
            MemberType.HUMAN,
            role=MemberRole.DEFAULT,
            registered_by="owner",
        )
        with pytest.raises(PermissionDeniedError, match="master만"):
            await service.register(
                "new-agent", MemberType.AGENT, registered_by="human-default"
            )

    async def test_register_by_master_succeeds(self, service):
        """master 역할이면 register 정상 수행."""
        await service.bootstrap_master("owner", "pass123")
        member, token = await service.register(
            "agent-01", MemberType.AGENT, registered_by="owner"
        )
        assert member.member_id == "agent-01"

    async def test_register_by_nonexistent_caller_fails(self, service):
        """존재하지 않는 호출자로 register 호출 시 PermissionDeniedError."""
        from ante.member.errors import PermissionDeniedError

        with pytest.raises(PermissionDeniedError, match="master만"):
            await service.register("new-agent", MemberType.AGENT, registered_by="ghost")

    async def test_register_without_caller_succeeds(self, service):
        """registered_by가 빈 문자열(내부 호출)이면 검증 스킵."""
        member, token = await service.register("agent-01", MemberType.AGENT)
        assert member.member_id == "agent-01"

    async def test_update_scopes_by_agent_fails(self, service):
        """agent 역할의 멤버가 update_scopes 호출 시 PermissionDeniedError."""
        from ante.member.errors import PermissionDeniedError

        await service.register("agent-01", MemberType.AGENT)
        await service.register("agent-caller", MemberType.AGENT)
        with pytest.raises(PermissionDeniedError, match="master만"):
            await service.update_scopes(
                "agent-01", ["strategy:write"], updated_by="agent-caller"
            )

    async def test_update_scopes_by_master_succeeds(self, service):
        """master 역할이면 update_scopes 정상 수행."""
        await service.bootstrap_master("owner", "pass123")
        await service.register("agent-01", MemberType.AGENT)
        m = await service.update_scopes(
            "agent-01", ["strategy:write"], updated_by="owner"
        )
        assert m.scopes == ["strategy:write"]

    async def test_update_scopes_without_caller_succeeds(self, service):
        """updated_by가 빈 문자열(내부 호출)이면 검증 스킵."""
        await service.register("agent-01", MemberType.AGENT)
        m = await service.update_scopes("agent-01", ["data:read"])
        assert m.scopes == ["data:read"]


class TestList:
    async def test_list_all(self, service):
        await service.register("agent-01", MemberType.AGENT)
        await service.register("agent-02", MemberType.AGENT, org="risk")
        members = await service.list_members()
        assert len(members) == 2

    async def test_list_by_type(self, service):
        await service.bootstrap_master("owner", "pass123")
        await service.register("agent-01", MemberType.AGENT)
        humans = await service.list_members(member_type=MemberType.HUMAN)
        assert len(humans) == 1
        assert humans[0].type == MemberType.HUMAN

    async def test_list_by_org(self, service):
        await service.register("a1", MemberType.AGENT, org="strategy-lab")
        await service.register("a2", MemberType.AGENT, org="risk")
        result = await service.list_members(org="risk")
        assert len(result) == 1
        assert result[0].member_id == "a2"


class TestAuthFailedEvent:
    async def test_auth_failed_publishes_event(self, service, eventbus):
        events = []
        eventbus.subscribe(MemberAuthFailedEvent, events.append)
        with pytest.raises(PermissionError):
            await service.authenticate("invalid_token")
        assert len(events) == 1
        assert events[0].reason == "유효하지 않은 토큰 형식"


# ── Emoji ───────────────────────────────────────────


class TestEmojiField:
    async def test_member_has_emoji_field(self):
        m = Member(member_id="t", type=MemberType.AGENT, role=MemberRole.DEFAULT)
        assert m.emoji == ""

    async def test_register_auto_assigns_emoji(self, service):
        member, _ = await service.register("a1", MemberType.AGENT)
        assert member.emoji != ""
        assert member.emoji in ANIMAL_EMOJI_POOL

    async def test_register_with_explicit_emoji(self, service):
        member, _ = await service.register("a1", MemberType.AGENT, emoji="🎸")
        assert member.emoji == "🎸"

    async def test_bootstrap_auto_assigns_emoji(self, service):
        member, _, _ = await service.bootstrap_master("owner", "pass123")
        assert member.emoji != ""
        assert member.emoji in ANIMAL_EMOJI_POOL

    async def test_bootstrap_with_explicit_emoji(self, service):
        member, _, _ = await service.bootstrap_master("owner", "pass123", emoji="👑")
        assert member.emoji == "👑"

    async def test_emoji_persisted_in_db(self, service):
        await service.register("a1", MemberType.AGENT, emoji="🐶")
        fetched = await service.get("a1")
        assert fetched.emoji == "🐶"


class TestUpdateEmoji:
    async def test_update_emoji(self, service):
        await service.register("a1", MemberType.AGENT, emoji="🐶")
        m = await service.update_emoji("a1", "🐱", updated_by="owner")
        assert m.emoji == "🐱"
        fetched = await service.get("a1")
        assert fetched.emoji == "🐱"

    async def test_update_emoji_to_empty(self, service):
        await service.register("a1", MemberType.AGENT, emoji="🐶")
        m = await service.update_emoji("a1", "", updated_by="owner")
        assert m.emoji == ""

    async def test_update_emoji_nonexistent_member(self, service):
        with pytest.raises(ValueError, match="존재하지 않는 멤버"):
            await service.update_emoji("ghost", "🐶")


class TestEmojiValidation:
    async def test_invalid_emoji_text(self, service):
        with pytest.raises(ValueError, match="단일 이모지만"):
            await service.register("a1", MemberType.AGENT, emoji="abc")

    async def test_invalid_emoji_multiple(self, service):
        with pytest.raises(ValueError, match="단일 이모지만"):
            await service.register("a1", MemberType.AGENT, emoji="🐶🐱")

    async def test_duplicate_emoji_fails(self, service):
        await service.register("a1", MemberType.AGENT, emoji="🐶")
        with pytest.raises(ValueError, match="이미.*사용 중"):
            await service.register("a2", MemberType.AGENT, emoji="🐶")

    async def test_duplicate_emoji_message_includes_owner(self, service):
        await service.register("a1", MemberType.AGENT, emoji="🐶")
        with pytest.raises(ValueError, match="a1"):
            await service.register("a2", MemberType.AGENT, emoji="🐶")

    async def test_empty_emoji_allows_duplicates(self, service):
        # emoji=""는 빈 문자열 명시 (자동 배정 안 함)
        m1, _ = await service.register("a1", MemberType.AGENT, emoji="")
        m2, _ = await service.register("a2", MemberType.AGENT, emoji="")
        assert m1.emoji == ""
        assert m2.emoji == ""

    async def test_update_emoji_duplicate_fails(self, service):
        await service.register("a1", MemberType.AGENT, emoji="🐶")
        await service.register("a2", MemberType.AGENT, emoji="🐱")
        with pytest.raises(ValueError, match="이미.*사용 중"):
            await service.update_emoji("a2", "🐶")

    async def test_update_emoji_same_value_ok(self, service):
        await service.register("a1", MemberType.AGENT, emoji="🐶")
        m = await service.update_emoji("a1", "🐶")
        assert m.emoji == "🐶"


class TestAutoAssignEmoji:
    async def test_auto_assign_unique(self, service):
        m1, _ = await service.register("a1", MemberType.AGENT)
        m2, _ = await service.register("a2", MemberType.AGENT)
        assert m1.emoji != m2.emoji

    async def test_auto_assign_exhausted_pool(self, service):
        for i in range(len(ANIMAL_EMOJI_POOL)):
            await service.register(
                f"a{i}", MemberType.AGENT, emoji=ANIMAL_EMOJI_POOL[i]
            )
        # 풀 소진 후 등록 — 에러 없이 빈 문자열
        member, _ = await service.register("overflow", MemberType.AGENT)
        assert member.emoji == ""

    async def test_auto_assigned_can_be_changed(self, service):
        member, _ = await service.register("a1", MemberType.AGENT)
        original = member.emoji
        m = await service.update_emoji("a1", "🎸")
        assert m.emoji == "🎸"
        assert m.emoji != original
