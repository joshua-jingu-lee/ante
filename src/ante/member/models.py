"""Member 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MemberType(StrEnum):
    """멤버 타입."""

    HUMAN = "human"
    AGENT = "agent"


class MemberRole(StrEnum):
    """멤버 역할."""

    MASTER = "master"
    ADMIN = "admin"
    DEFAULT = "default"


class MemberStatus(StrEnum):
    """멤버 상태."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass
class Member:
    """시스템 행위 주체 (사람 또는 AI Agent)."""

    member_id: str
    type: str
    role: str
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = MemberStatus.ACTIVE
    scopes: list[str] = field(default_factory=list)
    token_hash: str = ""
    password_hash: str = ""
    recovery_key_hash: str = ""
    created_at: str = ""
    created_by: str = ""
    last_active_at: str = ""
    suspended_at: str = ""
    revoked_at: str = ""
    token_expires_at: str = ""
