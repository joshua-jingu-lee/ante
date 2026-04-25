"""CLI에서 사용하는 랜덤 패스워드 생성 유틸리티."""

from __future__ import annotations

import secrets
import string

_ALPHABET = string.ascii_letters + string.digits + "-_"
_DEFAULT_LENGTH = 24


def generate_password(length: int = _DEFAULT_LENGTH) -> str:
    """URL-safe 문자집합 기반 랜덤 패스워드를 생성한다.

    - secrets 모듈 사용 (암호학적 안전)
    - shell-safe (따옴표·공백 없음)
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
