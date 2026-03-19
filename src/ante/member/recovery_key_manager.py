"""RecoveryKeyManager — 복구 키·패스워드 관리."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ante.member.auth import (
    generate_recovery_key,
    hash_password,
    hash_recovery_key,
    verify_password,
    verify_recovery_key,
)
from ante.member.models import Member, MemberStatus, MemberType

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


class RecoveryKeyManager:
    """복구 키 생성·검증·폐기 및 패스워드 관리."""

    def __init__(
        self,
        db: Database,
        eventbus: EventBus,
    ) -> None:
        self._db = db
        self._eventbus = eventbus

    async def change_password(
        self, member: Member, old_password: str, new_password: str
    ) -> None:
        """패스워드 변경 (human만)."""
        self._assert_human(member, "change_password")
        self._assert_active(member, "change_password")

        if not member.password_hash or not verify_password(
            old_password, member.password_hash
        ):
            msg = "현재 패스워드가 일치하지 않습니다"
            raise PermissionError(msg)

        await self._db.execute(
            "UPDATE members SET password_hash = ? WHERE member_id = ?",
            (hash_password(new_password), member.member_id),
        )
        logger.info("패스워드 변경 완료: %s", member.member_id)

    async def reset_password(
        self, member: Member, recovery_key: str, new_password: str
    ) -> None:
        """recovery key로 패스워드 리셋 (human만)."""
        self._assert_human(member, "reset_password")

        if not member.recovery_key_hash or not verify_recovery_key(
            recovery_key, member.recovery_key_hash
        ):
            await self._publish_auth_failed(member.member_id, "recovery key 불일치")
            msg = "유효하지 않은 recovery key"
            raise PermissionError(msg)

        await self._db.execute(
            "UPDATE members SET password_hash = ? WHERE member_id = ?",
            (hash_password(new_password), member.member_id),
        )
        logger.info("패스워드 리셋 완료 (recovery key): %s", member.member_id)

    async def regenerate_recovery_key(self, member: Member, password: str) -> str:
        """복구 키 재발급. 현재 패스워드 확인 필수."""
        self._assert_human(member, "regenerate_recovery_key")
        self._assert_active(member, "regenerate_recovery_key")

        if not member.password_hash or not verify_password(
            password, member.password_hash
        ):
            msg = "현재 패스워드가 일치하지 않습니다"
            raise PermissionError(msg)

        recovery_key = generate_recovery_key()
        await self._db.execute(
            "UPDATE members SET recovery_key_hash = ? WHERE member_id = ?",
            (hash_recovery_key(recovery_key), member.member_id),
        )
        logger.info("Recovery key 재발급 완료: %s", member.member_id)
        return recovery_key

    async def _publish_auth_failed(self, member_id: str, reason: str) -> None:
        """인증 실패 이벤트 발행."""
        from ante.eventbus.events import MemberAuthFailedEvent

        await self._eventbus.publish(
            MemberAuthFailedEvent(member_id=member_id, reason=reason)
        )

    @staticmethod
    def _assert_human(member: Member, action: str) -> None:
        """human 전용 검증."""
        if member.type != MemberType.HUMAN:
            msg = f"{action}은(는) human 멤버만 가능합니다"
            raise PermissionError(msg)

    @staticmethod
    def _assert_active(member: Member, action: str) -> None:
        """활성 상태 검증."""
        if member.status != MemberStatus.ACTIVE:
            msg = f"비활성 멤버는 {action}할 수 없습니다 (현재: {member.status})"
            raise PermissionError(msg)
