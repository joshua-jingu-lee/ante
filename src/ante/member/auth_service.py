"""AuthService — 멤버 인증 (토큰·패스워드)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ante.member.auth import get_token_type, hash_token, verify_password
from ante.member.models import Member, MemberStatus, MemberType
from ante.member.token_manager import TokenManager

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


class AuthService:
    """토큰·패스워드 기반 멤버 인증."""

    def __init__(
        self,
        db: Database,
        eventbus: EventBus,
        token_manager: TokenManager,
        get_member: object,
    ) -> None:
        self._db = db
        self._eventbus = eventbus
        self._token_manager = token_manager
        # get_member는 MemberService.get을 주입받음
        self._get_member = get_member

    async def authenticate(self, token: str) -> Member:
        """토큰으로 멤버 인증. 접두어 기반 타입 강제."""
        token_type = get_token_type(token)
        if token_type is None:
            await self._publish_auth_failed("", "유효하지 않은 토큰 형식")
            msg = "유효하지 않은 토큰 형식"
            raise PermissionError(msg)

        t_hash = hash_token(token)
        row = await self._db.fetch_one(
            "SELECT * FROM members WHERE token_hash = ?",
            (t_hash,),
        )
        if not row:
            await self._publish_auth_failed("", "토큰과 일치하는 멤버 없음")
            msg = "인증 실패"
            raise PermissionError(msg)

        from ante.member.service import _row_to_member

        member = _row_to_member(row)

        if member.type != token_type:
            await self._publish_auth_failed(
                member.member_id, "토큰 접두어와 멤버 타입 불일치"
            )
            msg = f"{token_type} key로 {member.type} 멤버 인증 불가"
            raise PermissionError(msg)

        if member.status != MemberStatus.ACTIVE:
            await self._publish_auth_failed(
                member.member_id, f"비활성 멤버: {member.status}"
            )
            msg = f"비활성 멤버: {member.status}"
            raise PermissionError(msg)

        # 토큰 만료 체크
        expiry_status = TokenManager.check_token_expiry(member)
        if expiry_status == "expired":
            await self._publish_auth_failed(member.member_id, "토큰 만료")
            msg = "토큰이 만료되었습니다. 'ante member rotate-token'으로 갱신하세요."
            raise PermissionError(msg)
        if expiry_status == "expiring_soon":
            logger.warning(
                "토큰 만료 임박: %s (만료: %s)",
                member.member_id,
                member.token_expires_at,
            )

        return member

    async def authenticate_password(self, member_id: str, password: str) -> Member:
        """패스워드 인증 (human 대시보드 로그인)."""
        member = await self._get_member(member_id)
        if not member:
            await self._publish_auth_failed(member_id, "존재하지 않는 멤버")
            msg = "인증 실패"
            raise PermissionError(msg)

        if member.type != MemberType.HUMAN:
            await self._publish_auth_failed(member_id, "human 전용 인증")
            msg = "패스워드 인증은 human 멤버만 가능합니다"
            raise PermissionError(msg)

        if member.status != MemberStatus.ACTIVE:
            await self._publish_auth_failed(member_id, f"비활성 멤버: {member.status}")
            msg = f"비활성 멤버: {member.status}"
            raise PermissionError(msg)

        if not member.password_hash or not verify_password(
            password, member.password_hash
        ):
            await self._publish_auth_failed(member_id, "패스워드 불일치")
            msg = "인증 실패"
            raise PermissionError(msg)

        return member

    async def _publish_auth_failed(self, member_id: str, reason: str) -> None:
        """인증 실패 이벤트 + 알림 발행."""
        from ante.eventbus.events import MemberAuthFailedEvent, NotificationEvent

        await self._eventbus.publish(
            MemberAuthFailedEvent(member_id=member_id, reason=reason)
        )
        target = f"멤버 `{member_id}`" if member_id else "알 수 없는 멤버"
        await self._eventbus.publish(
            NotificationEvent(
                level="warning",
                title="인증 실패",
                message=f"{target}\n사유: {reason}",
                category="member",
            )
        )
