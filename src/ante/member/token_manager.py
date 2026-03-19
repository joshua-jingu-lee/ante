"""TokenManager — 토큰 생성·갱신·만료 관리."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ante.member.auth import generate_token, hash_token
from ante.member.models import Member, MemberStatus

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)


def _token_expires_at(ttl_days: int) -> str:
    """TTL 일수 기준 토큰 만료 시각."""
    return (datetime.now(UTC) + timedelta(days=ttl_days)).strftime("%Y-%m-%d %H:%M:%S")


class TokenManager:
    """토큰 생성·갱신·만료 관리."""

    def __init__(self, db: Database, token_ttl_days: int = 90) -> None:
        self._db = db
        self._token_ttl_days = token_ttl_days

    @property
    def token_ttl_days(self) -> int:
        """토큰 TTL 일수."""
        return self._token_ttl_days

    def create_token(self, member_type: str) -> tuple[str, str, str]:
        """새 토큰 생성. (raw_token, token_hash, expires_at) 반환."""
        token = generate_token(member_type)
        t_hash = hash_token(token)
        expires_at = _token_expires_at(self._token_ttl_days)
        return token, t_hash, expires_at

    async def rotate_token(
        self, member: Member, rotated_by: str = ""
    ) -> tuple[Member, str]:
        """토큰 재발급. 기존 토큰 즉시 무효화. 새 TTL 적용."""
        if member.status != MemberStatus.ACTIVE:
            msg = f"비활성 멤버는 rotate_token할 수 없습니다 (현재: {member.status})"
            raise PermissionError(msg)

        token, t_hash, expires_at = self.create_token(member.type)

        await self._db.execute(
            "UPDATE members SET token_hash = ?, token_expires_at = ? "
            "WHERE member_id = ?",
            (t_hash, expires_at, member.member_id),
        )

        logger.info("토큰 재발급: %s (by %s)", member.member_id, rotated_by)
        member.token_hash = t_hash
        member.token_expires_at = expires_at
        return member, token

    @staticmethod
    def check_token_expiry(member: Member) -> str | None:
        """토큰 만료 상태 확인.

        Returns:
            None — 정상
            "expired" — 만료됨
            "expiring_soon" — 7일 이내 만료 임박
        """
        if not member.token_expires_at:
            return None

        expires = datetime.strptime(  # noqa: DTZ007
            member.token_expires_at, "%Y-%m-%d %H:%M:%S"
        )
        now = datetime.now(UTC).replace(tzinfo=None)

        if now > expires:
            return "expired"
        if now > expires - timedelta(days=7):
            return "expiring_soon"
        return None
