"""credentials Fernet 암호화."""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet


def _validate_fernet_key(value: str | None) -> bool:
    """주어진 문자열이 Ante canonical Fernet 키인지 검증한다.

    Ante는 ``cryptography.fernet.Fernet.generate_key()`` 의 출력 형식만
    canonical key로 인정한다. 해당 출력은 URL-safe base64로 인코딩된
    32바이트 키이므로 항상 길이 44이고 ``"="`` 한 글자로 끝나는 문자열이다.
    그 외 형식(빈 값/공백/길이 불일치/패딩 불일치/Fernet 생성자 실패)은
    invalid로 분류된다.

    Args:
        value: 검사 대상 문자열. ``None`` 또는 빈 문자열은 invalid.

    Returns:
        True iff `value`가 Fernet 생성자에 전달 가능한 canonical key이다.
    """
    if not value:
        return False
    if len(value) != 44 or not value.endswith("="):
        return False
    try:
        Fernet(value.encode())
    except Exception:  # noqa: BLE001
        return False
    return True


def _get_fernet() -> Fernet:
    """환경변수에서 Fernet 키를 읽어 인스턴스를 반환한다.

    Raises:
        RuntimeError: ANTE_DB_ENCRYPTION_KEY 환경변수가 설정되지 않은 경우.
    """
    key = os.environ.get("ANTE_DB_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ANTE_DB_ENCRYPTION_KEY 환경변수가 설정되지 않았습니다.")
    return Fernet(key.encode())


def encrypt_credentials(credentials: dict) -> str:
    """credentials dict를 Fernet 암호화된 문자열로 변환한다."""
    return _get_fernet().encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(encrypted: str) -> dict:
    """Fernet 암호화된 문자열을 credentials dict로 복호화한다."""
    return json.loads(_get_fernet().decrypt(encrypted.encode()).decode())
