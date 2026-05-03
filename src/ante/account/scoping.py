"""Account ID scoping helper — fallback 금지, runtime/creation 정책 분리.

이 모듈은 Account ID 계약(`docs/specs/account/14-account-id-contract.md`)의
SSOT 진입점이다. account-scoped 데이터/이벤트/명령에서 fallback (None,
빈 문자열, ``"default"``) 사용을 차단하고, 신규 계좌 생성에서는 bootstrap
seed 예약어(``"test"``)도 추가로 거부한다.

핵심 함수
~~~~~~~~~

- :func:`is_invalid_account_id` — runtime 시점 빠른 판정. ``"test"``는
  bootstrap 계좌이므로 runtime valid이다.
- :func:`require_account_id` — invalid면 :class:`InvalidAccountIdError`
  raise. fallback 금지 정책의 진입점이다.
- :func:`validate_new_account_id` — 신규 계좌 생성 정책 (요구 형식 +
  RESTRICTED 거부). bootstrap seed 경로(``create_default_test_account``)는
  helper를 우회한다.

상세 계약은 ``docs/specs/account/14-account-id-contract.md``를 참조한다.
"""

from __future__ import annotations

import re

from ante.account.errors import InvalidAccountIdError

# Account ID 형식: 영문/숫자/하이픈, 3~30자.
ACCOUNT_ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9\-]{3,30}$")

# Runtime invalid: account-scoped 데이터/이벤트는 절대 가질 수 없는 값.
# ``"default"``는 fallback 예약어로 어떤 시점에도 유효하지 않다.
INVALID_RUNTIME_ACCOUNT_IDS: frozenset[str] = frozenset({"default"})

# 신규 계좌 생성에서만 거부: bootstrap seed로만 허용한다.
# ``"test"``는 ``ante init`` → ``create_default_test_account`` 경로로만
# 생성되며, 사용자/Agent가 명시적으로 새로 만들 수는 없다.
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

    Args:
        account_id: 검증할 account_id.
        context: 에러 메시지에 부착할 호출 위치 식별자.
            예: ``"trade.submit_order"``, ``"treasury.deposit"``.

    Returns:
        검증된 account_id. type narrow를 위해 ``str``로 반환된다.

    Raises:
        InvalidAccountIdError: ``is_invalid_account_id``가 ``True``일 때.
    """
    if is_invalid_account_id(account_id):
        prefix = f"({context}) " if context else ""
        raise InvalidAccountIdError(
            f"{prefix}유효한 account_id가 필요합니다: {account_id!r}. "
            "fallback (default, '', None, 'test')은 사용할 수 없습니다."
        )
    return account_id  # type: ignore[return-value]


def validate_new_account_id(account_id: str | None) -> str:
    """신규 Account 생성 정책 검증.

    형식 검사(:data:`ACCOUNT_ID_PATTERN`)와 RESTRICTED 거부
    (:data:`RESTRICTED_NEW_ACCOUNT_IDS`, :data:`INVALID_RUNTIME_ACCOUNT_IDS`)
    를 모두 수행한다. bootstrap seed (``"test"``) 경로는 본 helper를 우회
    해야 한다 (``AccountService.create_default_test_account``).

    형식 위반 메시지는 기존 ``AccountService.create`` 메시지 형식을 보존한다
    (CLI ``str(e)`` contract: ``ante account create`` 표면 메시지).

    Args:
        account_id: 검증할 account_id.

    Returns:
        검증된 account_id.

    Raises:
        InvalidAccountIdError: 형식 위반, 또는 RESTRICTED/INVALID_RUNTIME
            예약어와 일치할 때.
    """
    if account_id is None or account_id == "":
        raise InvalidAccountIdError(
            f"account_id 형식이 올바르지 않습니다: '{account_id}'. "
            "영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다."
        )
    if account_id in RESTRICTED_NEW_ACCOUNT_IDS:
        raise InvalidAccountIdError(
            f"account_id '{account_id}'는 ante init이 생성하는 시드 계좌로 "
            "예약되어 있어 신규 생성이 불가합니다."
        )
    if account_id in INVALID_RUNTIME_ACCOUNT_IDS:
        raise InvalidAccountIdError(
            f"account_id '{account_id}'는 fallback 예약어로 신규 생성이 불가합니다."
        )
    if not ACCOUNT_ID_PATTERN.fullmatch(account_id):
        raise InvalidAccountIdError(
            f"account_id 형식이 올바르지 않습니다: '{account_id}'. "
            "영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다."
        )
    return account_id
