"""MemberService — 멤버 등록·조회·상태 관리."""

from __future__ import annotations

import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ante.member.auth import (
    generate_recovery_key,
    hash_password,
    hash_recovery_key,
)
from ante.member.auth_service import AuthService
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.member.recovery_key_manager import RecoveryKeyManager
from ante.member.scopes import InvalidScopeError, is_valid_scope
from ante.member.token_manager import TokenManager, _token_expires_at

__all__ = [
    "MemberService",
    "InvalidRoleScan",
    "ANIMAL_EMOJI_POOL",
    "MEMBER_SCHEMA",
    "_token_expires_at",
]


@dataclass
class InvalidRoleScan:
    """``MemberService.find_invalid_role_members`` 결과 컨테이너 (#1468).

    ``MemberRole`` enum SSOT 에 없는 ``role`` 을 가진 member row 를 두 카테고리로
    분리한다. 운영자는 ``actionable`` 만 ``ante member revoke`` 로 cleanup 하고,
    ``legacy_revoked`` 는 이미 revoke 된 historical row 라 추가 조치가 필요 없다.

    Attributes:
        actionable: ``role`` invalid AND ``status != revoked`` 인 row 들. 운영자가
            ``ante member revoke <member_id>`` 로 revoke 해야 할 대상.
        legacy_revoked: ``role`` invalid AND ``status == revoked`` 인 row 들. 이미
            revoke 처리된 흔적이며, 운영자가 동일 row 를 반복 처리하지 않게 분리.
    """

    actionable: list[Member] = field(default_factory=list)
    legacy_revoked: list[Member] = field(default_factory=list)


if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

_DEFAULT_ORG = "default"

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
    "\U0001f436",
    "\U0001f431",
    "\U0001f43b",
    "\U0001f98a",
    "\U0001f43c",
    "\U0001f428",
    "\U0001f981",
    "\U0001f42f",
    "\U0001f438",
    "\U0001f435",
    "\U0001f984",
    "\U0001f433",
    "\U0001f419",
    "\U0001f989",
    "\U0001f98b",
    "\U0001f427",
    "\U0001f43a",
    "\U0001f988",
    "\U0001f41d",
    "\U0001f99c",
    "\U0001f422",
    "\U0001f42c",
    "\U0001f985",
    "\U0001f432",
    "\U0001f434",
    "\U0001f9a9",
    "\U0001f43f",
    "\U0001f994",
    "\U0001f987",
    "\U0001f41e",
    "\U0001f980",
    "\U0001f418",
    "\U0001f992",
    "\U0001f998",
    "\U0001f40a",
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
        org=row.get("org", _DEFAULT_ORG),
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


class MemberService:
    """멤버 등록·조회·상태 관리 서비스.

    인증은 AuthService, 토큰은 TokenManager,
    복구키·패스워드는 RecoveryKeyManager에 위임한다.
    """

    def __init__(
        self,
        db: Database,
        eventbus: EventBus,
        token_ttl_days: int = 90,
    ) -> None:
        self._db = db
        self._eventbus = eventbus
        self._token_ttl_days = token_ttl_days

        # 하위 매니저 조립
        self._token_manager = TokenManager(db, token_ttl_days)
        self._auth_service = AuthService(
            db=db,
            eventbus=eventbus,
            token_manager=self._token_manager,
            get_member=self.get,
        )
        self._recovery_key_manager = RecoveryKeyManager(db=db, eventbus=eventbus)

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
        return secrets.choice(available)

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
            # #1915: emoji 형식 거부는 typed ``MemberInvalidEmojiError``
            # (.code=MEMBER_INVALID_EMOJI) 로 raise 해 CLI envelope 에 안정
            # 코드 surface. ``ValueError`` 다중상속이라 기존 ``except
            # ValueError`` (CLI ``set-emoji`` generic fallback, ``test_member.
            # py:602/606`` 의 ``pytest.raises(ValueError, match=...)``) 가
            # 회귀 없이 동일하게 잡힌다.
            from ante.member.errors import MemberInvalidEmojiError

            msg = "emoji는 단일 이모지만 허용됩니다"
            raise MemberInvalidEmojiError(msg)

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
    ) -> tuple[Member, str, str]:
        """master 생성 + (token, recovery_key) 반환. 최초 1회만 가능."""
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

        token, t_hash, expires_at = self._token_manager.create_token(MemberType.HUMAN)
        recovery_key = generate_recovery_key()
        now = _now()

        member = Member(
            member_id=member_id,
            type=MemberType.HUMAN,
            role=MemberRole.MASTER,
            org=_DEFAULT_ORG,
            name=name or member_id,
            emoji=emoji,
            status=MemberStatus.ACTIVE,
            scopes=[],
            token_hash=t_hash,
            password_hash=hash_password(password),
            recovery_key_hash=hash_recovery_key(recovery_key),
            created_at=now,
            created_by="system",
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
                registered_by="system",
            )
        )

        logger.info("Master 멤버 생성 완료: %s", member.member_id)
        return member, token, recovery_key

    # ── 멤버 등록 ──────────────────────────────────────

    async def register(
        self,
        member_id: str,
        member_type: str,
        role: str = MemberRole.DEFAULT,
        org: str = _DEFAULT_ORG,
        name: str = "",
        emoji: str | None = None,
        scopes: list[str] | None = None,
        registered_by: str = "",
    ) -> tuple[Member, str]:
        """멤버 등록 + 토큰 반환.

        ``scopes`` 의 각 원소는 ``SCOPE_VOCABULARY`` 에 등록된 문자열이어야
        한다(#1439). 위반 시 ``InvalidScopeError`` 를 raise 한다. CLI direct
        path 와 내부 caller 가 본 메소드를 직접 호출할 수 있으므로 service
        계층에서 방어한다(defense-in-depth).

        ``role`` 은 ``MemberRole`` enum SSOT 멤버이어야 한다 (#1465 — split
        #1417/A). ``member_type`` 은 ``MemberType`` enum SSOT 멤버이어야 한다
        (#1628 — ``role`` 동형 미러). CLI direct path 및 내부 caller 가 임의
        문자열을 넘길 수 있으므로 본 서비스 계층에서도 ``ValueError`` 로
        재검증한다. 검증은 ``_assert_master``
        직후, ``_assert_type_role`` 직전에 둬서 enum membership 위반이
        type-role 분기보다 먼저 거부되도록 한다.
        """
        if registered_by:
            await self._assert_master(registered_by, "register")
        self._assert_role_enum(role)
        self._assert_type_enum(member_type)
        self._assert_type_role(member_type, role)

        # vocabulary 검증은 type/role 검증 이후, DB I/O 이전에 수행한다.
        # CLI direct path 회귀 (#1439).
        scopes = scopes or []
        self._assert_scopes_vocabulary(scopes)

        existing = await self.get(member_id)
        if existing:
            # #1807 (Group R sweep): duplicate member_id 는 typed
            # ``MemberAlreadyExistsError`` (.code=MEMBER_ALREADY_EXISTS) 로
            # raise 해 CLI envelope 에 안정 코드 surface. ValueError 다중상속
            # 으로 기존 ``except (ValueError, PermissionError)`` 회귀 없음.
            from ante.member.errors import MemberAlreadyExistsError

            raise MemberAlreadyExistsError(member_id)

        if emoji is None:
            emoji = await self._auto_assign_emoji()
        elif emoji:
            self._validate_emoji_format(emoji)
            await self._validate_emoji_unique(emoji)

        token, t_hash, expires_at = self._token_manager.create_token(member_type)
        now = _now()

        member = Member(
            member_id=member_id,
            type=member_type,
            role=role,
            org=org,
            name=name or member_id,
            emoji=emoji,
            status=MemberStatus.ACTIVE,
            scopes=scopes,
            token_hash=t_hash,
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

    # ── 인증 (AuthService 위임) ────────────────────────

    async def authenticate(self, token: str) -> Member:
        """토큰으로 멤버 인증."""
        return await self._auth_service.authenticate(token)

    async def authenticate_password(self, member_id: str, password: str) -> Member:
        """패스워드 인증 (human 복구/maintenance)."""
        return await self._auth_service.authenticate_password(member_id, password)

    # ── 조회 ───────────────────────────────────────────

    async def get(self, member_id: str) -> Member | None:
        """단건 조회."""
        row = await self._db.fetch_one(
            "SELECT * FROM members WHERE member_id = ?",
            (member_id,),
        )
        return _row_to_member(row) if row else None

    async def list_members(
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

    async def count(
        self,
        member_type: str | None = None,
        org: str | None = None,
        status: str | None = None,
    ) -> int:
        """필터 조건에 맞는 전체 건수를 반환한다."""
        conditions: list[str] = []
        params: list[str] = []

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
        row = await self._db.fetch_one(
            f"SELECT COUNT(*) AS cnt FROM members{where}",  # noqa: S608
            tuple(params),
        )
        return row["cnt"] if row else 0

    async def find_invalid_role_members(self) -> InvalidRoleScan:
        """``MemberRole`` enum SSOT 에 없는 ``role`` 을 가진 member row 를 식별한다.

        #1465(write path 차단), #1466(auth read-path guard)으로 invalid-role row
        는 더 이상 새로 생성되지 않지만, 이전에 생성된 legacy row 는 DB 에 남아
        있을 수 있다. 본 메소드는 그런 row 를 운영자가 cleanup 할 수 있도록 두
        카테고리로 분리해 반환한다.

        반환된 ``Member`` 객체는 ``token_hash`` 등 민감 필드도 포함하지만
        CLI 출력 계층에서 마스킹/생략한다 (본 메소드는 service-layer SSOT 이므로
        column projection 을 의도적으로 하지 않는다 — caller 가 보안 결정을 진다).

        정렬: ``created_at ASC, member_id ASC`` (legacy row 정렬 안정성).

        Returns:
            ``InvalidRoleScan(actionable=[...], legacy_revoked=[...])``. 두 리스트는
            중복되지 않으며, ``status`` 분기로 정확히 한 쪽에만 속한다.
        """
        valid = tuple(member.value for member in MemberRole)
        placeholders = ",".join("?" for _ in valid)
        rows = await self._db.fetch_all(
            "SELECT * FROM members "  # noqa: S608
            f"WHERE role NOT IN ({placeholders}) "
            "ORDER BY created_at ASC, member_id ASC",
            valid,
        )
        actionable: list[Member] = []
        legacy_revoked: list[Member] = []
        for row in rows:
            member = _row_to_member(row)
            if member.status == MemberStatus.REVOKED:
                legacy_revoked.append(member)
            else:
                actionable.append(member)
        return InvalidRoleScan(actionable=actionable, legacy_revoked=legacy_revoked)

    # ── 상태 변경 ──────────────────────────────────────

    async def suspend(self, member_id: str, suspended_by: str = "") -> Member:
        """멤버 일시 정지.

        ``suspended_by``는 master 권한 caller여야 한다(#1351 — 보안 회귀
        잠금). 빈 문자열을 포함한 non-master는 ``PermissionDeniedError``로
        거부된다. 라우트 인증 가드와 무관하게 service-layer 자체 invariant.

        state 위반 (이미 SUSPENDED 등) 은 #1814 Group Q sweep 에 따라
        typed ``MemberStateConflictError`` 로 raise 한다 (이전 ``PermissionError``
        의미를 좁힘). ``ValueError`` 다중상속이므로 기존 ``except (ValueError,
        PermissionError)`` caller (CLI member suspend line 657 generic
        fallback) 가 회귀 없이 동일하게 잡힌다. ``revoke`` 는 plan scope 외
        라 기존 ``_assert_status`` ``PermissionError`` 경로를 유지한다.
        """
        from ante.member.errors import MemberStateConflictError

        await self._assert_master(suspended_by, "suspend")
        member = await self._get_or_raise(member_id)
        self._assert_not_master(member, "suspend")
        if member.status != MemberStatus.ACTIVE:
            raise MemberStateConflictError(
                member_id,
                current_status=str(member.status),
                requested_action="suspend",
            )

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
        """멤버 재활성화.

        ``reactivated_by``는 master 권한 caller여야 한다(#1351).

        state 위반 (이미 ACTIVE 등) 은 #1814 Group Q sweep 에 따라 typed
        ``MemberStateConflictError`` 로 raise 한다 (``suspend`` 1:1 미러).
        """
        from ante.member.errors import MemberStateConflictError

        await self._assert_master(reactivated_by, "reactivate")
        member = await self._get_or_raise(member_id)
        if member.status != MemberStatus.SUSPENDED:
            raise MemberStateConflictError(
                member_id,
                current_status=str(member.status),
                requested_action="reactivate",
            )

        await self._db.execute(
            "UPDATE members SET status = ? WHERE member_id = ?",
            (MemberStatus.ACTIVE, member_id),
        )

        from ante.eventbus.events import MemberReactivatedEvent

        await self._eventbus.publish(
            MemberReactivatedEvent(
                member_id=member_id,
                reactivated_by=reactivated_by,
            )
        )

        logger.info("멤버 재활성화: %s (by %s)", member_id, reactivated_by)
        member.status = MemberStatus.ACTIVE
        return member

    async def revoke(self, member_id: str, revoked_by: str = "") -> Member:
        """멤버 영구 폐기. 토큰 해시 삭제.

        ``revoked_by``는 master 권한 caller여야 한다(#1351).
        """
        await self._assert_master(revoked_by, "revoke")
        member = await self._get_or_raise(member_id)
        self._assert_not_master(member, "revoke")
        self._assert_status(
            member, (MemberStatus.ACTIVE, MemberStatus.SUSPENDED), "revoke"
        )

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

    # ── 토큰 관리 (TokenManager 위임) ──────────────────

    async def rotate_token(
        self, member_id: str, rotated_by: str = ""
    ) -> tuple[Member, str]:
        """토큰 재발급. 기존 토큰 즉시 무효화.

        ``rotated_by``는 master 권한 caller여야 한다(#1351). 인증 없는 token
        재발급 표면을 제거한다.
        """
        await self._assert_master(rotated_by, "rotate_token")
        member = await self._get_or_raise(member_id)
        result = await self._token_manager.rotate_token(member, rotated_by)

        from ante.eventbus.events import MemberTokenRotatedEvent

        await self._eventbus.publish(
            MemberTokenRotatedEvent(member_id=member_id, rotated_by=rotated_by)
        )
        return result

    # ── 패스워드·복구키 관리 (RecoveryKeyManager 위임) ─

    async def change_password(
        self, member_id: str, old_password: str, new_password: str
    ) -> None:
        """패스워드 변경 (human만)."""
        member = await self._get_or_raise(member_id)
        await self._recovery_key_manager.change_password(
            member, old_password, new_password
        )

        from ante.eventbus.events import MemberPasswordChangedEvent

        await self._eventbus.publish(
            MemberPasswordChangedEvent(
                member_id=member_id, changed_by=member_id, reason="change"
            )
        )

    async def reset_password(
        self, member_id: str, recovery_key: str, new_password: str
    ) -> None:
        """recovery key로 패스워드 리셋 (human만)."""
        member = await self._get_or_raise(member_id)
        await self._recovery_key_manager.reset_password(
            member, recovery_key, new_password
        )

        from ante.eventbus.events import MemberPasswordChangedEvent

        await self._eventbus.publish(
            MemberPasswordChangedEvent(
                member_id=member_id, changed_by=member_id, reason="reset"
            )
        )

    async def regenerate_recovery_key(self, member_id: str, password: str) -> str:
        """복구 키 재발급."""
        member = await self._get_or_raise(member_id)
        recovery_key = await self._recovery_key_manager.regenerate_recovery_key(
            member, password
        )

        from ante.eventbus.events import MemberRecoveryKeyRegeneratedEvent

        await self._eventbus.publish(
            MemberRecoveryKeyRegeneratedEvent(
                member_id=member_id, regenerated_by=member_id
            )
        )
        return recovery_key

    # ── 권한 관리 ──────────────────────────────────────

    async def update_scopes(
        self, member_id: str, scopes: list[str], updated_by: str = ""
    ) -> Member:
        """권한 범위 변경.

        ``updated_by``는 master 권한 caller여야 한다(#1351). 이전에는
        ``if updated_by:`` 가드 때문에 빈 caller가 master 검증을 우회했으나,
        본 가드를 제거해 빈 caller도 거부한다.

        ``scopes`` 의 각 원소는 ``SCOPE_VOCABULARY`` 에 등록된 문자열이어야
        한다(#1439). 위반 시 ``InvalidScopeError`` 를 raise 한다. CLI 직접
        호출과 내부 caller 를 위해 service 계층에서 방어한다.
        """
        await self._assert_master(updated_by, "update_scopes")
        # vocabulary 검증은 master 검증 직후, 멤버 조회 / DB write 이전에 수행한다.
        self._assert_scopes_vocabulary(scopes)
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

    async def _assert_master(self, caller_id: str, action: str) -> None:
        """호출자가 master인지 검증."""
        from ante.member.errors import PermissionDeniedError

        caller = await self.get(caller_id)
        if not caller or caller.role != MemberRole.MASTER:
            raise PermissionDeniedError(
                f"'{action}'은(는) master만 수행할 수 있습니다."
            )

    async def _get_or_raise(self, member_id: str) -> Member:
        """멤버 조회. 없으면 ``MemberNotFoundError`` (#1805).

        이전에는 ``ValueError("존재하지 않는 멤버: ...")`` 를 raise 했으나,
        CLI/IPC envelope 이 안정 코드 ``"MEMBER_NOT_FOUND"`` 를 surface
        하도록 typed exception (``MemberError`` 서브) 으로 변경한다. 메시지
        시그니처와 회귀 케이스(``test_member.py:582`` 등) 호환을 위해
        문자열은 동일하게 유지한다. ``ApprovalNotFoundError`` (#1798) 와
        동형 패턴.
        """
        from ante.member.errors import MemberNotFoundError

        member = await self.get(member_id)
        if not member:
            raise MemberNotFoundError(member_id)
        return member

    @staticmethod
    def _assert_scopes_vocabulary(scopes: list[str]) -> None:
        """``scopes`` 의 각 원소가 ``SCOPE_VOCABULARY`` 에 포함되는지 검증한다.

        위반 시 첫 invalid scope 를 인자로 ``InvalidScopeError`` 를 raise 한다.
        ``InvalidScopeError`` 는 ``ValueError`` 서브클래스이므로 기존
        ``except ValueError`` 핸들러도 동일하게 처리된다(#1439).

        빈 리스트는 통과시킨다. ``None`` 은 caller(``register`` /
        ``update_scopes``) 에서 빈 리스트로 정규화한 뒤 본 헬퍼를 호출한다.
        """
        for scope in scopes:
            if not is_valid_scope(scope):
                raise InvalidScopeError(scope)

    @staticmethod
    def _assert_role_enum(role: str) -> None:
        """``role`` 이 ``MemberRole`` enum SSOT 의 멤버인지 검증한다 (#1465).

        CLI direct path 와 내부 caller 는 본 서비스 메소드를 직접 호출할 수
        있다. enum 위반이 token 발급/DB INSERT 까지 새지 않도록 service 계층
        에서 한 번 더 방어한다 (defense-in-depth — Plan Preflight narrow-scope
        SSOT: ``src/ante/member/models.py``).

        ``StrEnum`` 인스턴스는 곧 문자열이므로 ``MemberRole.DEFAULT`` 같은
        enum 직접 호출도 통과한다. 알 수 없는 문자열은 ``ValueError`` 로
        거부된다.
        """
        valid = {member.value for member in MemberRole}
        if role not in valid:
            msg = f"invalid role: {role!r}"
            raise ValueError(msg)

    @staticmethod
    def _assert_type_enum(member_type: str) -> None:
        """``member_type`` 이 ``MemberType`` enum SSOT 의 멤버인지 검증한다 (#1628).

        CLI direct path 와 내부 caller 는 본 서비스 메소드를 직접 호출할 수
        있다. enum 위반이 token 발급/DB INSERT 까지 새지 않도록 service 계층
        에서 한 번 더 방어한다 (defense-in-depth — #1465 ``role`` enum 강제
        패턴 1:1 미러, SSOT: ``src/ante/member/models.py``).

        ``StrEnum`` 인스턴스는 곧 문자열이므로 ``MemberType.AGENT`` 같은
        enum 직접 호출도 통과한다. 알 수 없는 문자열은 ``ValueError`` 로
        거부된다.
        """
        valid = {member.value for member in MemberType}
        if member_type not in valid:
            msg = f"invalid member_type: {member_type!r}"
            raise ValueError(msg)

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
            # #1915: master 보호 위반은 typed ``MemberMasterProtectedError``
            # (.code=MEMBER_MASTER_PROTECTED) 로 raise 해 CLI envelope 에
            # 안정 코드 surface. ``PermissionError`` 다중상속이라 기존
            # ``except PermissionError`` (CLI ``suspend``/``revoke`` generic
            # fallback, ``test_member_service_master_guard.py:239/245`` 의
            # ``pytest.raises(PermissionError, match="master는 ...")``) 가
            # 회귀 없이 동일하게 잡힌다.
            from ante.member.errors import MemberMasterProtectedError

            msg = f"master는 {action}할 수 없습니다"
            raise MemberMasterProtectedError(msg)

    @staticmethod
    def _assert_active(member: Member, action: str) -> None:
        """활성 상태 검증."""
        if member.status != MemberStatus.ACTIVE:
            msg = f"비활성 멤버는 {action}할 수 없습니다 (현재: {member.status})"
            raise PermissionError(msg)

    @staticmethod
    def _assert_status(
        member: Member, expected: str | tuple[str, ...], action: str
    ) -> None:
        """특정 상태 검증. 단일 또는 복수 상태를 허용한다."""
        statuses = (expected,) if isinstance(expected, str) else expected
        if member.status not in statuses:
            allowed = ", ".join(statuses)
            msg = (
                f"{action}은(는) {allowed} 상태에서만 "
                f"가능합니다 (현재: {member.status})"
            )
            raise PermissionError(msg)
