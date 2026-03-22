"""토큰 만료 정책 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.member.auth import generate_token, hash_token
from ante.member.models import MemberStatus, MemberType
from ante.member.service import MemberService, _token_expires_at


def _make_member_row(
    *,
    member_id: str = "test-agent",
    member_type: str = MemberType.AGENT,
    token: str | None = None,
    status: str = MemberStatus.ACTIVE,
    token_expires_at: str = "",
) -> dict:
    if token is None:
        token = generate_token(member_type)
    return {
        "member_id": member_id,
        "type": member_type,
        "role": "default",
        "org": "default",
        "name": "Test",
        "emoji": "",
        "status": status,
        "scopes": "[]",
        "token_hash": hash_token(token),
        "password_hash": "",
        "recovery_key_hash": "",
        "created_at": "2025-01-01 00:00:00",
        "created_by": "system",
        "last_active_at": "",
        "suspended_at": "",
        "revoked_at": "",
        "token_expires_at": token_expires_at,
    }


class TestTokenExpiresAtHelper:
    def test_returns_future_date(self):
        """만료 시각이 미래."""
        result = _token_expires_at(90)
        expires = datetime.strptime(result, "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007
        now = datetime.now(UTC).replace(tzinfo=None)
        assert expires > now

    def test_ttl_days_applied(self):
        """TTL 일수가 반영됨."""
        result = _token_expires_at(30)
        expires = datetime.strptime(result, "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007
        now = datetime.now(UTC).replace(tzinfo=None)
        diff = expires - now
        assert 29 <= diff.days <= 30


class TestTokenExpiryOnAuth:
    @pytest.mark.asyncio
    async def test_valid_token_not_expired(self):
        """만료되지 않은 토큰은 인증 성공."""
        token = generate_token(MemberType.AGENT)
        future = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        row = _make_member_row(token=token, token_expires_at=future)

        db = AsyncMock()
        db.fetch_one = AsyncMock(return_value=row)
        eventbus = MagicMock()
        eventbus.publish = AsyncMock()

        svc = MemberService(db, eventbus)
        member = await svc.authenticate(token)
        assert member.member_id == "test-agent"

    @pytest.mark.asyncio
    async def test_expired_token_raises(self):
        """만료된 토큰은 PermissionError."""
        token = generate_token(MemberType.AGENT)
        past = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        row = _make_member_row(token=token, token_expires_at=past)

        db = AsyncMock()
        db.fetch_one = AsyncMock(return_value=row)
        eventbus = MagicMock()
        eventbus.publish = AsyncMock()

        svc = MemberService(db, eventbus)
        with pytest.raises(PermissionError, match="만료"):
            await svc.authenticate(token)

    @pytest.mark.asyncio
    async def test_no_expiry_field_ok(self):
        """token_expires_at이 빈 문자열이면 만료 체크 스킵."""
        token = generate_token(MemberType.AGENT)
        row = _make_member_row(token=token, token_expires_at="")

        db = AsyncMock()
        db.fetch_one = AsyncMock(return_value=row)
        eventbus = MagicMock()
        eventbus.publish = AsyncMock()

        svc = MemberService(db, eventbus)
        member = await svc.authenticate(token)
        assert member.member_id == "test-agent"

    @pytest.mark.asyncio
    async def test_warning_logged_near_expiry(self, caplog):
        """만료 7일 전 경고 로그."""
        import logging

        token = generate_token(MemberType.AGENT)
        near = (datetime.now(UTC) + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        row = _make_member_row(token=token, token_expires_at=near)

        db = AsyncMock()
        db.fetch_one = AsyncMock(return_value=row)
        eventbus = MagicMock()
        eventbus.publish = AsyncMock()

        svc = MemberService(db, eventbus)
        with caplog.at_level(logging.WARNING, logger="ante.member.service"):
            member = await svc.authenticate(token)
            assert member is not None
            assert "만료 임박" in caplog.text


class TestTokenExpiryOnRotate:
    @pytest.mark.asyncio
    async def test_rotate_sets_new_expiry(self):
        """토큰 재발급 시 새 만료 시각 설정."""
        row = _make_member_row()

        db = AsyncMock()
        db.fetch_one = AsyncMock(return_value=row)
        db.execute = AsyncMock()
        eventbus = MagicMock()
        eventbus.publish = AsyncMock()

        svc = MemberService(db, eventbus, token_ttl_days=30)
        member, new_token = await svc.rotate_token("test-agent", "admin")

        assert member.token_expires_at != ""
        expires = datetime.strptime(  # noqa: DTZ007
            member.token_expires_at, "%Y-%m-%d %H:%M:%S"
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        diff = expires - now
        assert 29 <= diff.days <= 30


class TestTokenExpiryOnRegister:
    @pytest.mark.asyncio
    async def test_register_sets_expiry(self):
        """멤버 등록 시 토큰 만료 시각 설정."""
        master_row = _make_member_row(
            member_id="admin",
            member_type=MemberType.HUMAN,
        )
        master_row["role"] = "master"

        db = AsyncMock()
        db.fetch_one = AsyncMock(side_effect=[master_row, None])
        db.fetch_all = AsyncMock(return_value=[])
        db.execute = AsyncMock()
        eventbus = MagicMock()
        eventbus.publish = AsyncMock()

        svc = MemberService(db, eventbus, token_ttl_days=60)
        member, token = await svc.register(
            member_id="new-agent",
            member_type=MemberType.AGENT,
            registered_by="admin",
        )

        assert member.token_expires_at != ""
        expires = datetime.strptime(  # noqa: DTZ007
            member.token_expires_at, "%Y-%m-%d %H:%M:%S"
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        diff = expires - now
        assert 59 <= diff.days <= 60


class TestDefaultTTL:
    def test_default_ttl_90_days(self):
        """기본 TTL은 90일."""
        db = AsyncMock()
        eventbus = MagicMock()
        svc = MemberService(db, eventbus)
        assert svc._token_ttl_days == 90

    def test_custom_ttl(self):
        """커스텀 TTL 설정."""
        db = AsyncMock()
        eventbus = MagicMock()
        svc = MemberService(db, eventbus, token_ttl_days=30)
        assert svc._token_ttl_days == 30
