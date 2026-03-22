"""credentials Fernet 암호화."""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet


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
