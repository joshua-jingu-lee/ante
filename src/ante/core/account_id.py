"""Account ID scoping helper — fallback 금지, runtime/creation 정책 분리."""

from __future__ import annotations

import re


class AccountError(Exception):
    """Account 기본 예외."""

    pass


class InvalidAccountIdError(AccountError):
    """account_id 형식 위반 또는 RESTRICTED/INVALID_RUNTIME 예약어 사용.

    클래스 레벨 ``code`` 속성은 IPC 서버가 ``ipc_error_payload``로
    안정 코드 ``"VALIDATION_ERROR"``를 노출하도록 한다. 이 예외를 raise하는
    IPC 경로(treasury.allocate/deallocate의 봇 계좌 대조, approval 핸들러 등)가
    자동으로 ``VALIDATION_ERROR``로 매핑된다.
    """

    code: str = "VALIDATION_ERROR"


ACCOUNT_ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9\-]{3,30}$")

INVALID_RUNTIME_ACCOUNT_IDS: frozenset[str] = frozenset({"default"})

RESTRICTED_NEW_ACCOUNT_IDS: frozenset[str] = frozenset({"test"})


def is_invalid_account_id(account_id: str | None) -> bool:
    """runtime-invalid 판정.

    다음 중 하나면 ``True``:

    - ``None`` 또는 빈 문자열
    - ``INVALID_RUNTIME_ACCOUNT_IDS``에 포함 (``"default"``)
    - ``ACCOUNT_ID_PATTERN``과 불일치

    ``"test"``는 bootstrap 계좌로 runtime valid이므로 ``False``를 반환한다.
    """
    if account_id is None or account_id == "":
        return True
    if account_id in INVALID_RUNTIME_ACCOUNT_IDS:
        return True
    if not ACCOUNT_ID_PATTERN.fullmatch(account_id):
        return True
    return False


def require_account_id(account_id: str | None, *, context: str = "") -> str:
    """invalid면 :class:`InvalidAccountIdError` raise. valid면 그대로 반환.

    fallback 금지 정책의 진입점이다. account-scoped 명령/이벤트/캐시 키
    경로에서 호출하여 ``None``/``""``/``"default"``/패턴 위반 값이 도달
    하지 못하도록 한다.

    Raises:
        InvalidAccountIdError: ``is_invalid_account_id``가 ``True``일 때.
    """
    if is_invalid_account_id(account_id):
        prefix = f"({context}) " if context else ""
        raise InvalidAccountIdError(
            f"{prefix}유효한 account_id가 필요합니다: {account_id!r}. "
            "fallback (default, '', None) 또는 형식 위반 값은 사용할 수 없습니다."
        )
    return account_id  # type: ignore[return-value]


def validate_new_account_id(account_id: str | None, *, context: str = "") -> str:
    """신규 Account 생성 정책 검증.

    형식 검사(:data:`ACCOUNT_ID_PATTERN`)와 RESTRICTED 거부
    (:data:`RESTRICTED_NEW_ACCOUNT_IDS`, :data:`INVALID_RUNTIME_ACCOUNT_IDS`)
    를 모두 수행한다. bootstrap seed (``"test"``) 경로는 본 helper를 우회
    해야 한다 (``AccountService.create_default_test_account``).

    형식 위반 메시지는 기존 ``AccountService.create`` 메시지 형식을 보존한다
    (CLI ``str(e)`` contract: ``ante account create`` 표면 메시지).
    """
    prefix = f"({context}) " if context else ""
    if account_id is None or account_id == "":
        raise InvalidAccountIdError(
            f"{prefix}account_id 형식이 올바르지 않습니다: '{account_id}'. "
            "영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다."
        )
    if account_id in RESTRICTED_NEW_ACCOUNT_IDS:
        raise InvalidAccountIdError(
            f"{prefix}account_id '{account_id}'는 ante init이 생성하는 시드 계좌로 "
            "예약되어 있어 신규 생성이 불가합니다."
        )
    if account_id in INVALID_RUNTIME_ACCOUNT_IDS:
        raise InvalidAccountIdError(
            f"{prefix}account_id '{account_id}'는 fallback 예약어로 "
            "신규 생성이 불가합니다."
        )
    if not ACCOUNT_ID_PATTERN.fullmatch(account_id):
        raise InvalidAccountIdError(
            f"{prefix}account_id 형식이 올바르지 않습니다: '{account_id}'. "
            "영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다."
        )
    return account_id
