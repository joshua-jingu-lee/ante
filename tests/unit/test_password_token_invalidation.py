"""패스워드 변경/리셋 시 토큰 무효화 테스트 (GAP-034, #772)."""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.member.service import MemberService


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


class TestChangePasswordTokenInvalidation:
    """change_password 후 토큰 무효화 검증."""

    async def test_token_invalidated_after_change_password(self, service, db):
        """패스워드 변경 후 token_hash, token_expires_at이 NULL이어야 한다."""
        member, token, _ = await service.bootstrap_master("owner", "pass123")

        # 변경 전: token_hash 존재
        row = await db.fetch_one(
            "SELECT token_hash, token_expires_at FROM members WHERE member_id = ?",
            ("owner",),
        )
        assert row["token_hash"] is not None
        assert row["token_hash"] != ""

        await service.change_password("owner", "pass123", "newpass")

        # 변경 후: token_hash가 NULL
        row = await db.fetch_one(
            "SELECT token_hash, token_expires_at FROM members WHERE member_id = ?",
            ("owner",),
        )
        assert row["token_hash"] is None
        assert row["token_expires_at"] is None

    async def test_old_token_fails_after_change_password(self, service):
        """패스워드 변경 후 기존 토큰으로 인증 실패."""
        _, token, _ = await service.bootstrap_master("owner", "pass123")

        # 변경 전: 토큰 인증 성공
        m = await service.authenticate(token)
        assert m.member_id == "owner"

        await service.change_password("owner", "pass123", "newpass")

        # 변경 후: 기존 토큰 인증 실패
        with pytest.raises(PermissionError):
            await service.authenticate(token)


class TestResetPasswordTokenInvalidation:
    """reset_password 후 토큰 무효화 검증."""

    async def test_token_invalidated_after_reset_password(self, service, db):
        """패스워드 리셋 후 token_hash, token_expires_at이 NULL이어야 한다."""
        _, token, recovery_key = await service.bootstrap_master("owner", "pass123")

        # 리셋 전: token_hash 존재
        row = await db.fetch_one(
            "SELECT token_hash, token_expires_at FROM members WHERE member_id = ?",
            ("owner",),
        )
        assert row["token_hash"] is not None
        assert row["token_hash"] != ""

        await service.reset_password("owner", recovery_key, "resetpass")

        # 리셋 후: token_hash가 NULL
        row = await db.fetch_one(
            "SELECT token_hash, token_expires_at FROM members WHERE member_id = ?",
            ("owner",),
        )
        assert row["token_hash"] is None
        assert row["token_expires_at"] is None

    async def test_old_token_fails_after_reset_password(self, service):
        """패스워드 리셋 후 기존 토큰으로 인증 실패."""
        _, token, recovery_key = await service.bootstrap_master("owner", "pass123")

        # 리셋 전: 토큰 인증 성공
        m = await service.authenticate(token)
        assert m.member_id == "owner"

        await service.reset_password("owner", recovery_key, "resetpass")

        # 리셋 후: 기존 토큰 인증 실패
        with pytest.raises(PermissionError):
            await service.authenticate(token)
