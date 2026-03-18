"""MemberService — 멤버 등록·인증·관리."""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ante.member.auth import (
    generate_recovery_key,
    generate_token,
    get_token_type,
    hash_password,
    hash_recovery_key,
    hash_token,
    verify_password,
    verify_recovery_key,
)
from ante.member.models import Member, MemberRole, MemberStatus, MemberType

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

MEMBER_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    member_id          TEXT PRIMARY KEY,
    type               TEXT NOT NULL,
    role               TEXT NOT NULL DEFAULT 'default',
    org                TEXT NOT NULL DEFAULT 'default',
    name               TEXT NOT NULL DEFAULT '',
    emoji              TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'active',
    scopes             TEXT NOT NULL DEFAULT '[]',
    token_hash         TEXT DEFAULT '',
    password_hash      TEXT DEFAULT '',
    recovery_key_hash  TEXT DEFAULT '',
    created_at         TEXT DEFAULT (datetime('now')),
    created_by         TEXT DEFAULT '',
    last_active_at     TEXT DEFAULT '',
    suspended_at       TEXT DEFAULT '',
    revoked_at         TEXT DEFAULT '',
    token_expires_at   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_members_type ON members(type);
CREATE INDEX IF NOT EXISTS idx_members_status ON members(status);
CREATE INDEX IF NOT EXISTS idx_members_org ON members(org);
"""

_EMOJI_MIGRATION = "ALTER TABLE members ADD COLUMN emoji TEXT NOT NULL DEFAULT ''"
_TOKEN_EXPIRES_MIGRATION = (
    "ALTER TABLE members ADD COLUMN token_expires_at TEXT DEFAULT ''"
)

# 단일 이모지(grapheme cluster) 검증 패턴
# 기본 이모지 1개 + 선택적 modifier/ZWJ sequence
_EMOJI_BASE = (
    r"[\U0001F600-\U0001F64F]"  # Emoticons
    r"|[\U0001F300-\U0001F5FF]"  # Misc Symbols & Pictographs
    r"|[\U0001F680-\U0001F6FF]"  # Transport & Map
    r"|[\U0001F900-\U0001F9FF]"  # Supplemental Symbols
    r"|[\U0001FA00-\U0001FA6F]"  # Chess Symbols
    r"|[\U0001FA70-\U0001FAFF]"  # Symbols Extended-A
    r"|[\U00002702-\U000027B0]"  # Dingbats
    r"|[\U0001F1E0-\U0001F1FF]{2}"  # Flags (2 regional indicators)
)
_EMOJI_MODIFIER = (
    r"[\U0000FE00-\U0000FE0F]"  # Variation Selectors
    r"|[\U0001F3FB-\U0001F3FF]"  # Skin tone modifiers
    r"|[\U000E0020-\U000E007F]"  # Tags
)
# 단일 이모지: base + optional ZWJ sequences
_EMOJI_RE = re.compile(
    r"^(?:" + _EMOJI_BASE + r")"
    r"(?:" + _EMOJI_MODIFIER + r")*"
    r"(?:\U0000200D(?:" + _EMOJI_BASE + r")(?:" + _EMOJI_MODIFIER + r")*)*$"
)

ANIMAL_EMOJI_POOL: list[str] = [
    "🐶",
    "🐱",
    "🐻",
    "🦊",
    "🐼",
    "🐨",
    "🦁",
    "🐯",
    "🐸",
    "🐵",
    "🦄",
    "🐳",
    "🐙",
    "🦉",
    "🦋",
    "🐧",
    "🐺",
    "🦈",
    "🐝",
    "🦜",
    "🐢",
    "🐬",
    "🦅",
    "🐲",
    "🐴",
    "🦩",
    "🐿",
    "🦔",
    "🦇",
    "🐞",
    "🦀",
    "🐘",
    "🦒",
    "🦘",
    "🐊",
]


def _is_single_emoji(value: str) -> bool:
    """단일 이모지인지 검증."""
    return bool(_EMOJI_RE.match(value))


def _row_to_member(row: dict) -> Member:
    """DB 행을 Member 객체로 변환."""
    return Member(
        member_id=row["member_id"],
        type=row["type"],
        role=row["role"],
        org=row.get("org", "default"),
        name=row.get("name", ""),
        emoji=row.get("emoji", ""),
        status=row.get("status", MemberStatus.ACTIVE),
        scopes=json.loads(row.get("scopes", "[]")),
        token_hash=row.get("token_hash", ""),
        password_hash=row.get("password_hash", ""),
        recovery_key_hash=row.get("recovery_key_hash", ""),
        created_at=row.get("created_at", ""),
        created_by=row.get("created_by", ""),
        last_active_at=row.get("last_active_at", ""),
        suspended_at=row.get("suspended_at", ""),
        revoked_at=row.get("revoked_at", ""),
        token_expires_at=row.get("token_expires_at", ""),
    )


def _now() -> str:
    """현재 UTC 시각 문자열."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _token_expires_at(ttl_days: int) -> str:
    """TTL 일수 기준 토큰 만료 시각."""
    from datetime import timedelta

    return (datetime.now(UTC) + timedelta(days=ttl_days)).strftime("%Y-%m-%d %H:%M:%S")


class MemberService:
    """멤버 등록·인증·관리 서비스."""

    def __init__(
        self,
        db: Database,
        eventbus: EventBus,
        token_ttl_days: int = 90,
    ) -> None:
        self._db = db
        self._eventbus = eventbus
        self._token_ttl_days = token_ttl_days

    async def initialize(self) -> None:
        """스키마 생성 + 컬럼 마이그레이션."""
        await self._db.execute_script(MEMBER_SCHEMA)
        for migration in (_EMOJI_MIGRATION, _TOKEN_EXPIRES_MIGRATION):
            try:
                await self._db.execute(migration)
            except Exception:  # noqa: BLE001
                pass  # 컬럼이 이미 존재하면 무시
        logger.info("MemberService 초기화 완료")

    # ── emoji 관리 ──────────────────────────────────────

    async def _get_used_emojis(self) -> set[str]:
        """사용 중인 emoji 집합 반환."""
        rows = await self._db.fetch_all("SELECT emoji FROM members WHERE emoji != ''")
        return {row["emoji"] for row in rows}

    async def _auto_assign_emoji(self) -> str:
        """미사용 동물 emoji 중 랜덤 선택. 소진 시 빈 문자열."""
        used = await self._get_used_emojis()
        available = [e for e in ANIMAL_EMOJI_POOL if e not in used]
        if not available:
            return ""
        return random.choice(available)  # noqa: S311

    async def _validate_emoji_unique(
        self, emoji: str, exclude_member_id: str = ""
    ) -> None:
        """emoji 중복 검증. 빈 문자열은 중복 허용."""
        if not emoji:
            return
        row = await self._db.fetch_one(
            "SELECT member_id FROM members WHERE emoji = ?",
            (emoji,),
        )
        if row and row["member_id"] != exclude_member_id:
            msg = f"emoji '{emoji}'는 이미 {row['member_id']}가 사용 중입니다"
            raise ValueError(msg)

    @staticmethod
    def _validate_emoji_format(emoji: str) -> None:
        """emoji 형식 검증. 빈 문자열 허용, 그 외 단일 이모지만."""
        if not emoji:
            return
        if not _is_single_emoji(emoji):
            msg = "emoji는 단일 이모지만 허용됩니다"
            raise ValueError(msg)

    async def update_emoji(
        self, member_id: str, emoji: str, updated_by: str = ""
    ) -> Member:
        """멤버 emoji 변경."""
        member = await self._get_or_raise(member_id)
        self._validate_emoji_format(emoji)
        await self._validate_emoji_unique(emoji, exclude_member_id=member_id)

        await self._db.execute(
            "UPDATE members SET emoji = ? WHERE member_id = ?",
            (emoji, member_id),
        )
        logger.info("emoji 변경: %s → %s (by %s)", member_id, emoji, updated_by)
        member.emoji = emoji
        return member

    # ── Master 부트스트랩 ──────────────────────────────

    async def bootstrap_master(
        self,
        member_id: str,
        password: str,
        name: str = "",
        emoji: str | None = None,
    ) -> tuple[Member, str]:
        """master 생성 + recovery key 반환. 최초 1회만 가능."""
        existing = await self._db.fetch_one(
            "SELECT member_id FROM members WHERE role = ?",
            (MemberRole.MASTER,),
        )
        if existing:
            msg = "master가 이미 존재합니다"
            raise ValueError(msg)

        if emoji is None:
            emoji = await self._auto_assign_emoji()
        elif emoji:
            self._validate_emoji_format(emoji)
            await self._validate_emoji_unique(emoji)

        recovery_key = generate_recovery_key()
        now = _now()

        member = Member(
            member_id=member_id,
            type=MemberType.HUMAN,
            role=MemberRole.MASTER,
            org="default",
            name=name or member_id,
            emoji=emoji,
            status=MemberStatus.ACTIVE,
            scopes=[],
            token_hash="",
            password_hash=hash_password(password),
            recovery_key_hash=hash_recovery_key(recovery_key),
            created_at=now,
            created_by="system",
        )

        await self._db.execute(
            """INSERT INTO members
               (member_id, type, role, org, name, emoji, status, scopes,
                token_hash, password_hash, recovery_key_hash,
                created_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                member.member_id,
                member.type,
                member.role,
                member.org,
                member.name,
                member.emoji,
                member.status,
                json.dumps(member.scopes),
                member.token_hash,
                member.password_hash,
                member.recovery_key_hash,
                member.created_at,
                member.created_by,
            ),
        )

        from ante.eventbus.events import MemberRegisteredEvent

        await self._eventbus.publish(
            MemberRegisteredEvent(
                member_id=member.member_id,
                member_type=member.type,
                role=member.role,
                registered_by="system",
            )
        )

        logger.info("Master 멤버 생성 완료: %s", member.member_id)
        return member, recovery_key

    # ── 멤버 등록 ──────────────────────────────────────

    async def register(
        self,
        member_id: str,
        member_type: str,
        role: str = MemberRole.DEFAULT,
        org: str = "default",
        name: str = "",
        emoji: str | None = None,
        scopes: list[str] | None = None,
        registered_by: str = "",
    ) -> tuple[Member, str]:
        """멤버 등록 + 토큰 반환."""
        self._assert_type_role(member_type, role)

        existing = await self.get(member_id)
        if existing:
            msg = f"이미 존재하는 member_id: {member_id}"
            raise ValueError(msg)

        if emoji is None:
            emoji = await self._auto_assign_emoji()
        elif emoji:
            self._validate_emoji_format(emoji)
            await self._validate_emoji_unique(emoji)

        token = generate_token(member_type)
        now = _now()
        expires_at = _token_expires_at(self._token_ttl_days)
        scopes = scopes or []

        member = Member(
            member_id=member_id,
            type=member_type,
            role=role,
            org=org,
            name=name or member_id,
            emoji=emoji,
            status=MemberStatus.ACTIVE,
            scopes=scopes,
            token_hash=hash_token(token),
            created_at=now,
            created_by=registered_by,
            token_expires_at=expires_at,
        )

        await self._db.execute(
            """INSERT INTO members
               (member_id, type, role, org, name, emoji, status, scopes,
                token_hash, password_hash, recovery_key_hash,
                created_at, created_by, token_expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                member.member_id,
                member.type,
                member.role,
                member.org,
                member.name,
                member.emoji,
                member.status,
                json.dumps(member.scopes),
                member.token_hash,
                member.password_hash,
                member.recovery_key_hash,
                member.created_at,
                member.created_by,
                member.token_expires_at,
            ),
        )

        from ante.eventbus.events import MemberRegisteredEvent

        await self._eventbus.publish(
            MemberRegisteredEvent(
                member_id=member.member_id,
                member_type=member.type,
                role=member.role,
                registered_by=registered_by,
            )
        )

        logger.info("멤버 등록 완료: %s (type=%s)", member.member_id, member.type)
        return member, token

    # ── 인증 ───────────────────────────────────────────

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
        if member.token_expires_at:
            expires = datetime.strptime(  # noqa: DTZ007
                member.token_expires_at, "%Y-%m-%d %H:%M:%S"
            )
            now = datetime.now(UTC).replace(tzinfo=None)
            if now > expires:
                await self._publish_auth_failed(member.member_id, "토큰 만료")
                msg = (
                    "토큰이 만료되었습니다. 'ante member rotate-token'으로 갱신하세요."
                )
                raise PermissionError(msg)

            from datetime import timedelta

            if now > expires - timedelta(days=7):
                logger.warning(
                    "토큰 만료 임박: %s (만료: %s)",
                    member.member_id,
                    member.token_expires_at,
                )

        return member

    async def authenticate_password(self, member_id: str, password: str) -> Member:
        """패스워드 인증 (human 대시보드 로그인)."""
        member = await self.get(member_id)
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

    # ── 조회 ───────────────────────────────────────────

    async def get(self, member_id: str) -> Member | None:
        """단건 조회."""
        row = await self._db.fetch_one(
            "SELECT * FROM members WHERE member_id = ?",
            (member_id,),
        )
        return _row_to_member(row) if row else None

    async def list(
        self,
        member_type: str | None = None,
        org: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Member]:
        """필터 조회."""
        conditions: list[str] = []
        params: list[str | int] = []

        if member_type:
            conditions.append("type = ?")
            params.append(member_type)
        if org:
            conditions.append("org = ?")
            params.append(org)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        rows = await self._db.fetch_all(
            f"SELECT * FROM members{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",  # noqa: S608
            tuple(params),
        )
        return [_row_to_member(row) for row in rows]

    # ── 상태 변경 ──────────────────────────────────────

    async def suspend(self, member_id: str, suspended_by: str = "") -> Member:
        """멤버 일시 정지."""
        member = await self._get_or_raise(member_id)
        self._assert_not_master(member, "suspend")
        self._assert_status(member, MemberStatus.ACTIVE, "suspend")

        now = _now()
        await self._db.execute(
            "UPDATE members SET status = ?, suspended_at = ? WHERE member_id = ?",
            (MemberStatus.SUSPENDED, now, member_id),
        )

        from ante.eventbus.events import MemberSuspendedEvent

        await self._eventbus.publish(
            MemberSuspendedEvent(
                member_id=member_id,
                suspended_by=suspended_by,
            )
        )

        logger.info("멤버 정지: %s (by %s)", member_id, suspended_by)
        member.status = MemberStatus.SUSPENDED
        member.suspended_at = now
        return member

    async def reactivate(self, member_id: str, reactivated_by: str = "") -> Member:
        """멤버 재활성화."""
        member = await self._get_or_raise(member_id)
        self._assert_status(member, MemberStatus.SUSPENDED, "reactivate")

        await self._db.execute(
            "UPDATE members SET status = ? WHERE member_id = ?",
            (MemberStatus.ACTIVE, member_id),
        )

        logger.info("멤버 재활성화: %s (by %s)", member_id, reactivated_by)
        member.status = MemberStatus.ACTIVE
        return member

    async def revoke(self, member_id: str, revoked_by: str = "") -> Member:
        """멤버 영구 폐기. 토큰 해시 삭제."""
        member = await self._get_or_raise(member_id)
        self._assert_not_master(member, "revoke")

        now = _now()
        await self._db.execute(
            """UPDATE members
               SET status = ?, token_hash = '', revoked_at = ?
               WHERE member_id = ?""",
            (MemberStatus.REVOKED, now, member_id),
        )

        from ante.eventbus.events import MemberRevokedEvent

        await self._eventbus.publish(
            MemberRevokedEvent(
                member_id=member_id,
                revoked_by=revoked_by,
            )
        )

        logger.info("멤버 폐기: %s (by %s)", member_id, revoked_by)
        member.status = MemberStatus.REVOKED
        member.token_hash = ""
        member.revoked_at = now
        return member

    # ── 토큰 관리 ──────────────────────────────────────

    async def rotate_token(
        self, member_id: str, rotated_by: str = ""
    ) -> tuple[Member, str]:
        """토큰 재발급. 기존 토큰 즉시 무효화. 새 TTL 적용."""
        member = await self._get_or_raise(member_id)
        self._assert_active(member, "rotate_token")

        token = generate_token(member.type)
        t_hash = hash_token(token)
        expires_at = _token_expires_at(self._token_ttl_days)

        await self._db.execute(
            "UPDATE members SET token_hash = ?, token_expires_at = ? "
            "WHERE member_id = ?",
            (t_hash, expires_at, member_id),
        )

        logger.info("토큰 재발급: %s (by %s)", member_id, rotated_by)
        member.token_hash = t_hash
        member.token_expires_at = expires_at
        return member, token

    # ── 패스워드 관리 ──────────────────────────────────

    async def change_password(
        self, member_id: str, old_password: str, new_password: str
    ) -> None:
        """패스워드 변경 (human만)."""
        member = await self._get_or_raise(member_id)
        self._assert_human(member, "change_password")
        self._assert_active(member, "change_password")

        if not member.password_hash or not verify_password(
            old_password, member.password_hash
        ):
            msg = "현재 패스워드가 일치하지 않습니다"
            raise PermissionError(msg)

        await self._db.execute(
            "UPDATE members SET password_hash = ? WHERE member_id = ?",
            (hash_password(new_password), member_id),
        )
        logger.info("패스워드 변경 완료: %s", member_id)

    async def reset_password(
        self, member_id: str, recovery_key: str, new_password: str
    ) -> None:
        """recovery key로 패스워드 리셋 (human만)."""
        member = await self._get_or_raise(member_id)
        self._assert_human(member, "reset_password")

        if not member.recovery_key_hash or not verify_recovery_key(
            recovery_key, member.recovery_key_hash
        ):
            await self._publish_auth_failed(member_id, "recovery key 불일치")
            msg = "유효하지 않은 recovery key"
            raise PermissionError(msg)

        await self._db.execute(
            "UPDATE members SET password_hash = ? WHERE member_id = ?",
            (hash_password(new_password), member_id),
        )
        logger.info("패스워드 리셋 완료 (recovery key): %s", member_id)

    async def regenerate_recovery_key(self, member_id: str, password: str) -> str:
        """복구 키 재발급. 현재 패스워드 확인 필수."""
        member = await self._get_or_raise(member_id)
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
            (hash_recovery_key(recovery_key), member_id),
        )
        logger.info("Recovery key 재발급 완료: %s", member_id)
        return recovery_key

    # ── 권한 관리 ──────────────────────────────────────

    async def update_scopes(
        self, member_id: str, scopes: list[str], updated_by: str = ""
    ) -> Member:
        """권한 범위 변경."""
        member = await self._get_or_raise(member_id)
        self._assert_active(member, "update_scopes")

        await self._db.execute(
            "UPDATE members SET scopes = ? WHERE member_id = ?",
            (json.dumps(scopes), member_id),
        )

        logger.info("권한 변경: %s → %s (by %s)", member_id, scopes, updated_by)
        member.scopes = scopes
        return member

    # ── 활동 추적 ──────────────────────────────────────

    async def update_last_active(self, member_id: str) -> None:
        """마지막 활동 시각 갱신."""
        await self._db.execute(
            "UPDATE members SET last_active_at = ? WHERE member_id = ?",
            (_now(), member_id),
        )

    # ── 내부 헬퍼 ──────────────────────────────────────

    async def _get_or_raise(self, member_id: str) -> Member:
        """멤버 조회. 없으면 ValueError."""
        member = await self.get(member_id)
        if not member:
            msg = f"존재하지 않는 멤버: {member_id}"
            raise ValueError(msg)
        return member

    async def _publish_auth_failed(self, member_id: str, reason: str) -> None:
        """인증 실패 이벤트 발행."""
        from ante.eventbus.events import MemberAuthFailedEvent

        await self._eventbus.publish(
            MemberAuthFailedEvent(member_id=member_id, reason=reason)
        )

    @staticmethod
    def _assert_type_role(member_type: str, role: str) -> None:
        """타입-역할 불변식 검증."""
        if member_type == MemberType.AGENT and role in (
            MemberRole.MASTER,
            MemberRole.ADMIN,
        ):
            msg = "agent 타입은 master 또는 admin 역할을 가질 수 없습니다"
            raise PermissionError(msg)

    @staticmethod
    def _assert_not_master(member: Member, action: str) -> None:
        """master 보호."""
        if member.role == MemberRole.MASTER:
            msg = f"master는 {action}할 수 없습니다"
            raise PermissionError(msg)

    @staticmethod
    def _assert_active(member: Member, action: str) -> None:
        """활성 상태 검증."""
        if member.status != MemberStatus.ACTIVE:
            msg = f"비활성 멤버는 {action}할 수 없습니다 (현재: {member.status})"
            raise PermissionError(msg)

    @staticmethod
    def _assert_human(member: Member, action: str) -> None:
        """human 전용 검증."""
        if member.type != MemberType.HUMAN:
            msg = f"{action}은(는) human 멤버만 가능합니다"
            raise PermissionError(msg)

    @staticmethod
    def _assert_status(member: Member, expected: str, action: str) -> None:
        """특정 상태 검증."""
        if member.status != expected:
            msg = (
                f"{action}은(는) {expected} 상태에서만 "
                f"가능합니다 (현재: {member.status})"
            )
            raise PermissionError(msg)
