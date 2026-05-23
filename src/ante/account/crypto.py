"""credentials Fernet 암호화.

키 오류는 두 가지 root cause로 구분된다(`docs/specs/account/06-database-schema.md`
ANTE_DB_ENCRYPTION_KEY SSOT + `docs/specs/cli/02-design-decisions.md` CLI 에러
코드 명명 규칙):

- ``EncryptionKeyMissingError`` (``DB_ENCRYPTION_KEY_MISSING``): env가 미설정
  또는 빈 문자열이고, ``Config.load``가 ``secrets.env`` fallback에서도 export하지
  못한 경우.
- ``EncryptionKeyInvalidError`` (``DB_ENCRYPTION_KEY_INVALID``): env에 값은 있으나
  Fernet 형식(URL-safe base64, 44바이트, ``=``로 끝남)을 위반하거나, 형식은 맞으나
  실제 decrypt 시 ``cryptography.fernet.InvalidToken``으로 키 불일치가 드러난 경우.

기반 클래스 ``EncryptionKeyError``를 ``RuntimeError`` 서브로 두어 기존
``except RuntimeError`` 사용처와 behavior preserving을 유지한다.
"""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken


class EncryptionKeyError(RuntimeError):
    """크립토 키 오류 기반 클래스.

    ``RuntimeError`` 서브로 두어 기존 ``except RuntimeError`` 사용처와의
    behavior preserving을 유지한다. 호출자는 typed 서브클래스
    (``EncryptionKeyMissingError`` / ``EncryptionKeyInvalidError``)로 분기하거나
    ``getattr(e, "code", "EXECUTION_ERROR")``로 안정 코드를 읽을 수 있다.
    """

    code: str = "DB_ENCRYPTION_KEY_ERROR"


class EncryptionKeyMissingError(EncryptionKeyError):
    """ANTE_DB_ENCRYPTION_KEY env가 미설정/빈 + secrets.env fallback 실패."""

    code: str = "DB_ENCRYPTION_KEY_MISSING"


class EncryptionKeyInvalidError(EncryptionKeyError):
    """키가 설정되어 있으나 Fernet 형식 위반 또는 decrypt 실패(InvalidToken)."""

    code: str = "DB_ENCRYPTION_KEY_INVALID"


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
        EncryptionKeyMissingError: ANTE_DB_ENCRYPTION_KEY 환경변수가 미설정
            이거나 빈 문자열인 경우 (``secrets.env`` fallback에서도 키가 export
            되지 않은 상태). 메시지는 ``Config.load``의 fallback이 실패했음을
            함께 안내한다.
        EncryptionKeyInvalidError: 환경변수는 설정되어 있으나
            ``_validate_fernet_key`` 검증을 통과하지 못한 경우(형식 위반).
    """
    key = os.environ.get("ANTE_DB_ENCRYPTION_KEY")
    if not key:
        raise EncryptionKeyMissingError(
            "ANTE_DB_ENCRYPTION_KEY 환경변수가 설정되지 않았습니다."
        )
    if not _validate_fernet_key(key):
        raise EncryptionKeyInvalidError(
            "ANTE_DB_ENCRYPTION_KEY 형식이 유효하지 않습니다 "
            "(Fernet.generate_key() 출력 형식이어야 합니다)."
        )
    return Fernet(key.encode())


def encrypt_credentials(credentials: dict) -> str:
    """credentials dict를 Fernet 암호화된 문자열로 변환한다."""
    return _get_fernet().encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(encrypted: str) -> dict:
    """Fernet 암호화된 문자열을 credentials dict로 복호화한다.

    Raises:
        EncryptionKeyMissingError: ``_get_fernet()``이 키 미설정/빈으로 raise.
        EncryptionKeyInvalidError: ``_get_fernet()``이 형식 위반으로 raise하거나,
            형식은 맞으나 실제 ``Fernet.decrypt()``가 ``InvalidToken``을 raise한
            경우(다른 키로 암호화된 legacy row). 원본 예외는 ``__cause__``로
            보존된다.
    """
    fernet = _get_fernet()
    try:
        return json.loads(fernet.decrypt(encrypted.encode()).decode())
    except InvalidToken as e:
        raise EncryptionKeyInvalidError(
            "credentials decrypt 실패: 키가 일치하지 않습니다."
        ) from e
