"""MemberService — 멤버 등록·조회·상태 관리."""

from __future__ import annotations

import json
import logging
import re
import secrets
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

__all__ = ["MemberService", "ANIMAL_EMOJI_POOL", "MEMBER_SCHEMA", "_token_expires_at"]

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
        한다(#1439). 위반 시 ``InvalidScopeError`` 를 raise 한다. Web API
        ingress 는 Pydantic field validator 로 동일 invariant 를 검증하지만
        CLI direct path 와 내부 caller 가 본 메소드를 직접 호출할 수 있으므로
        service 계층에서 한 번 더 방어한다(defense-in-depth).

        ``role`` 은 ``MemberRole`` enum SSOT 멤버이어야 한다 (#1465 — split
        #1417/A). Web API ingress 는 Pydantic ``MemberRole`` 필드로 422 를
        강제하지만, CLI direct path 및 내부 caller 가 임의 문자열을 넘길 수
        있으므로 본 서비스 계층에서도 ``ValueError`` 로 재검증한다. 검증은
        ``_assert_master`` 직후, ``_assert_type_role`` 직전에 둬서 enum
        membership 위반이 type-role 분기보다 먼저 거부되도록 한다.
        """
        if registered_by:
            await self._assert_master(registered_by, "register")
        self._assert_role_enum(role)
        self._assert_type_role(member_type, role)

        # vocabulary 검증은 type/role 검증 이후, DB I/O 이전에 수행한다.
        # CLI direct path 회귀 (#1439).
        scopes = scopes or []
        self._assert_scopes_vocabulary(scopes)

        existing = await self.get(member_id)
        if existing:
            msg = f"이미 존재하는 member_id: {member_id}"
            raise ValueError(msg)

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
        """패스워드 인증 (human 대시보드 로그인)."""
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

    # ── 상태 변경 ──────────────────────────────────────

    async def suspend(self, member_id: str, suspended_by: str = "") -> Member:
        """멤버 일시 정지.

        ``suspended_by``는 master 권한 caller여야 한다(#1351 — 보안 회귀
        잠금). 빈 문자열을 포함한 non-master는 ``PermissionDeniedError``로
        거부된다. 라우트 인증 가드와 무관하게 service-layer 자체 invariant.
        """
        await self._assert_master(suspended_by, "suspend")
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
        """멤버 재활성화.

        ``reactivated_by``는 master 권한 caller여야 한다(#1351).
        """
        await self._assert_master(reactivated_by, "reactivate")
        member = await self._get_or_raise(member_id)
        self._assert_status(member, MemberStatus.SUSPENDED, "reactivate")

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

    # ── invalid-role cleanup (#1468 — split #1417/D) ───

    async def audit_invalid_roles(self) -> list[Member]:
        """``MemberRole`` enum SSOT 에 없는 ``role`` row 를 식별해 반환한다.

        #1465 (write path) 와 #1466 (auth read-path) 가 막힌 뒤에도, 그 이전에
        DB 에 남은 ``role="oracle_invalid_role"`` 같은 row 는 그대로 존재할 수
        있다. 본 메서드는 운영자가 cleanup 대상 row 를 식별할 수 있도록 enum
        membership 검증을 적용한 list 를 반환한다.

        검증은 read-only 이며 부작용이 없다. 정상 role row 는 결과에 포함되지
        않는다 (정상 role 영향 없음 회귀 SSOT).
        """
        valid = {member.value for member in MemberRole}
        rows = await self._db.fetch_all(
            "SELECT * FROM members ORDER BY created_at DESC"
        )
        invalid: list[Member] = []
        for row in rows:
            if row["role"] not in valid:
                invalid.append(_row_to_member(row))
        return invalid

    async def repair_role(
        self,
        member_id: str,
        new_role: str,
        repaired_by: str = "",
    ) -> Member:
        """invalid-role row 를 master-only 권한으로 valid role 로 교정한다.

        invariants (#1468):

        - caller 는 master 여야 한다 (``_assert_master``). 비-master 는
          ``PermissionDeniedError`` 로 거부된다.
        - ``new_role`` 은 ``MemberRole`` enum 멤버여야 한다 (``_assert_role_enum``).
          enum 위반은 ``ValueError`` 로 거부된다.
        - ``new_role`` 이 ``MemberRole.MASTER`` 인 cleanup 은 거부된다. master
          승격은 cleanup 의 의도가 아니며, 우발적인 권한 상승을 막기 위해
          ``ValueError`` 로 거부한다. (``ante init`` master 부트스트랩만 master
          를 생성한다.)
        - 대상 row 의 현재 ``role`` 은 enum SSOT 에 없어야 한다. 이미 valid 한
          row 를 본 메서드로 재교정하는 것은 의도된 cleanup 범위를 벗어나므로
          ``ValueError`` 로 거부한다 (정상 role row 영향 없음 회귀).
        - type-role 불변식 (``_assert_type_role``) 도 동일하게 적용된다. agent
          를 master/admin 으로 cleanup 하지 못한다.

        성공 시 ``MemberRoleRepairedEvent`` 를 발행해 audit/log 추적이 가능하게
        한다.
        """
        await self._assert_master(repaired_by, "repair_role")
        self._assert_role_enum(new_role)
        if new_role == MemberRole.MASTER:
            msg = "repair_role 로 master 역할로 변경할 수 없습니다"
            raise ValueError(msg)

        member = await self._get_or_raise(member_id)

        valid = {role.value for role in MemberRole}
        if member.role in valid:
            msg = (
                f"이미 valid role 입니다: {member.role!r}."
                " repair_role 은 invalid-role row 만 교정합니다."
            )
            raise ValueError(msg)

        self._assert_type_role(member.type, new_role)

        old_role = member.role
        await self._db.execute(
            "UPDATE members SET role = ? WHERE member_id = ?",
            (new_role, member_id),
        )

        from ante.eventbus.events import MemberRoleRepairedEvent

        await self._eventbus.publish(
            MemberRoleRepairedEvent(
                member_id=member_id,
                old_role=old_role,
                new_role=new_role,
                repaired_by=repaired_by,
            )
        )

        logger.info(
            "invalid-role 교정: %s (%s → %s, by %s)",
            member_id,
            old_role,
            new_role,
            repaired_by,
        )
        member.role = new_role
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
        return await self._token_manager.rotate_token(member, rotated_by)

    # ── 패스워드·복구키 관리 (RecoveryKeyManager 위임) ─

    async def change_password(
        self, member_id: str, old_password: str, new_password: str
    ) -> None:
        """패스워드 변경 (human만)."""
        member = await self._get_or_raise(member_id)
        await self._recovery_key_manager.change_password(
            member, old_password, new_password
        )

    async def reset_password(
        self, member_id: str, recovery_key: str, new_password: str
    ) -> None:
        """recovery key로 패스워드 리셋 (human만)."""
        member = await self._get_or_raise(member_id)
        await self._recovery_key_manager.reset_password(
            member, recovery_key, new_password
        )

    async def regenerate_recovery_key(self, member_id: str, password: str) -> str:
        """복구 키 재발급."""
        member = await self._get_or_raise(member_id)
        return await self._recovery_key_manager.regenerate_recovery_key(
            member, password
        )

    # ── 권한 관리 ──────────────────────────────────────

    async def update_scopes(
        self, member_id: str, scopes: list[str], updated_by: str = ""
    ) -> Member:
        """권한 범위 변경.

        ``updated_by``는 master 권한 caller여야 한다(#1351). 이전에는
        ``if updated_by:`` 가드 때문에 빈 caller가 master 검증을 우회했으나,
        본 가드를 제거해 빈 caller도 거부한다.

        ``scopes`` 의 각 원소는 ``SCOPE_VOCABULARY`` 에 등록된 문자열이어야
        한다(#1439). 위반 시 ``InvalidScopeError`` 를 raise 한다. Web API
        ingress 가 Pydantic field validator 로 422 차단하지만 CLI 직접 호출과
        내부 caller 를 위해 service 계층에서 한 번 더 방어한다.
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
        """멤버 조회. 없으면 ValueError."""
        member = await self.get(member_id)
        if not member:
            msg = f"존재하지 않는 멤버: {member_id}"
            raise ValueError(msg)
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

        Web API ingress 는 Pydantic ``MemberRole`` 필드로 422 를 강제하지만,
        CLI direct path 와 내부 caller 는 본 서비스 메소드를 직접 호출할 수
        있다. enum 위반이 token 발급/DB INSERT 까지 새지 않도록 service 계층
        에서 한 번 더 방어한다 (defense-in-depth — Plan Preflight narrow-scope
        SSOT: ``src/ante/member/models.py``).

        ``StrEnum`` 인스턴스는 곧 문자열이므로 ``MemberRole.DEFAULT`` 같은
        enum 직접 호출도 통과한다. 알 수 없는 문자열은 ``ValueError`` 로
        거부되며, Web API 라우터의 ``except ValueError`` 분기가 400 으로
        매핑한다 (현재 핸들러 시그니처 유지).
        """
        valid = {member.value for member in MemberRole}
        if role not in valid:
            msg = f"invalid role: {role!r}"
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
            msg = f"master는 {action}할 수 없습니다"
            raise PermissionError(msg)

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
