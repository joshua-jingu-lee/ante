"""인증 유틸리티 — 토큰 생성·검증, 패스워드 해싱, Recovery Key."""

from __future__ import annotations

import hashlib
import secrets
import string

# ── 토큰 ─────────────────────────────────────────────

TOKEN_PREFIX_HUMAN = "ante_hk_"
TOKEN_PREFIX_AGENT = "ante_ak_"
TOKEN_LENGTH = 32  # 접두어 제외 랜덤 부분 길이


def generate_token(member_type: str) -> str:
    """멤버 타입에 따른 API 토큰 생성."""
    from ante.member.models import MemberType

    if member_type == MemberType.HUMAN:
        prefix = TOKEN_PREFIX_HUMAN
    elif member_type == MemberType.AGENT:
        prefix = TOKEN_PREFIX_AGENT
    else:
        msg = f"지원하지 않는 멤버 타입: {member_type}"
        raise ValueError(msg)

    random_part = secrets.token_urlsafe(TOKEN_LENGTH)
    return f"{prefix}{random_part}"


def hash_token(token: str) -> str:
    """토큰을 SHA-256 해시로 변환. 빠른 조회를 위해 SHA-256 사용."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    """토큰과 해시 일치 확인."""
    return secrets.compare_digest(hash_token(token), token_hash)


def get_token_type(token: str) -> str | None:
    """토큰 접두어로 멤버 타입 판별."""
    from ante.member.models import MemberType

    if token.startswith(TOKEN_PREFIX_HUMAN):
        return MemberType.HUMAN
    if token.startswith(TOKEN_PREFIX_AGENT):
        return MemberType.AGENT
    return None


# ── 패스워드 ─────────────────────────────────────────

SALT_LENGTH = 32
HASH_ITERATIONS = 600_000  # OWASP 2023 권장


def hash_password(password: str) -> str:
    """패스워드를 PBKDF2-SHA256으로 해싱. salt:hash 형식으로 반환."""
    salt = secrets.token_hex(SALT_LENGTH)
    pw_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        HASH_ITERATIONS,
    ).hex()
    return f"{salt}:{pw_hash}"


def verify_password(password: str, stored: str) -> bool:
    """패스워드 검증."""
    salt, expected_hash = stored.split(":", 1)
    actual_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        HASH_ITERATIONS,
    ).hex()
    return secrets.compare_digest(actual_hash, expected_hash)


# ── Recovery Key ─────────────────────────────────────

RECOVERY_KEY_GROUPS = 6
RECOVERY_KEY_GROUP_LEN = 4
RECOVERY_KEY_PREFIX = "ANTE-RK-"


def generate_recovery_key() -> str:
    """Recovery Key 생성. 형식: ANTE-RK-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX."""
    chars = string.ascii_uppercase + string.digits
    groups = [
        "".join(secrets.choice(chars) for _ in range(RECOVERY_KEY_GROUP_LEN))
        for _ in range(RECOVERY_KEY_GROUPS)
    ]
    return RECOVERY_KEY_PREFIX + "-".join(groups)


def hash_recovery_key(key: str) -> str:
    """Recovery Key 해싱 (패스워드와 동일한 방식)."""
    return hash_password(key)


def verify_recovery_key(key: str, stored: str) -> bool:
    """Recovery Key 검증."""
    return verify_password(key, stored)
