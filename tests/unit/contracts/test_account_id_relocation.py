"""계좌 ID 검증 정의의 자리를 옮겨도 동작이 그대로인지 잠그는 테스트.

계약 SSOT: ``docs/specs/account/14-account-id-contract.md``.
"""

from __future__ import annotations

import pytest

from ante.account import errors as account_errors
from ante.account.errors import AccountError, InvalidAccountIdError
from ante.account.scoping import (
    ACCOUNT_ID_PATTERN,
    INVALID_RUNTIME_ACCOUNT_IDS,
    RESTRICTED_NEW_ACCOUNT_IDS,
    is_invalid_account_id,
    require_account_id,
    validate_new_account_id,
)
from ante.contracts.error_registry import EXCEPTION_TO_SPEC

ACCOUNT_ERROR_SUBCLASSES = [
    "AccountActivateAllFailedError",
    "AccountAlreadyExistsError",
    "AccountAlreadySuspendedError",
    "AccountDeletedError",
    "AccountHasActiveBotsError",
    "AccountImmutableFieldError",
    "AccountNotFoundError",
    "AccountReconcileNotApplicableError",
    "AccountStructuralChangeRequiresStoppedServerError",
    "AccountSuspendAllFailedError",
    "AccountSuspendNotPersistedError",
    "AccountSuspendedError",
    "BrokerReconnectFailedError",
    "InvalidAccountIdError",
    "InvalidBrokerConfigError",
    "InvalidBrokerTypeError",
    "InvalidExchangeError",
    "MissingCredentialsError",
]

MOVED_FROM_SCOPING = [
    "ACCOUNT_ID_PATTERN",
    "INVALID_RUNTIME_ACCOUNT_IDS",
    "RESTRICTED_NEW_ACCOUNT_IDS",
    "is_invalid_account_id",
    "require_account_id",
    "validate_new_account_id",
    "InvalidAccountIdError",
]
MOVED_FROM_ERRORS = ["AccountError", "InvalidAccountIdError"]
MOVED_FROM_PACKAGE = [
    "ACCOUNT_ID_PATTERN",
    "INVALID_RUNTIME_ACCOUNT_IDS",
    "RESTRICTED_NEW_ACCOUNT_IDS",
    "is_invalid_account_id",
    "require_account_id",
    "validate_new_account_id",
    "AccountError",
    "InvalidAccountIdError",
]

FORMAT_TAIL = "영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다."
REQUIRE_TAIL = "fallback (default, '', None) 또는 형식 위반 값은 사용할 수 없습니다."


def _mro_names(cls: type) -> list[str]:
    """클래스의 MRO를 이름 목록으로 돌려준다."""
    return [c.__name__ for c in cls.__mro__]


def test_invalid_account_id_error_mro() -> None:
    """``InvalidAccountIdError`` 의 상속 사슬."""
    assert _mro_names(InvalidAccountIdError) == [
        "InvalidAccountIdError",
        "AccountError",
        "Exception",
        "BaseException",
        "object",
    ]


def test_account_error_mro() -> None:
    """``AccountError`` 의 상속 사슬."""
    assert _mro_names(AccountError) == [
        "AccountError",
        "Exception",
        "BaseException",
        "object",
    ]


def test_account_error_direct_subclasses() -> None:
    """``AccountError`` 를 바로 상속하는 계좌 예외의 이름 집합."""
    names = sorted(c.__name__ for c in AccountError.__subclasses__())
    assert names == ACCOUNT_ERROR_SUBCLASSES


@pytest.mark.parametrize("name", ACCOUNT_ERROR_SUBCLASSES)
def test_account_error_subclass_mro(name: str) -> None:
    """계좌 예외마다 상속 사슬이 ``AccountError`` 를 거친다."""
    cls = getattr(account_errors, name)
    assert _mro_names(cls) == [
        name,
        "AccountError",
        "Exception",
        "BaseException",
        "object",
    ]


@pytest.mark.parametrize(
    ("old_module", "name"),
    [("ante.account.scoping", n) for n in MOVED_FROM_SCOPING]
    + [("ante.account.errors", n) for n in MOVED_FROM_ERRORS]
    + [("ante.account", n) for n in MOVED_FROM_PACKAGE],
)
def test_old_path_reexports_same_object(old_module: str, name: str) -> None:
    """옛 경로의 이름이 새 경로의 객체와 같다."""
    import importlib

    from ante.core import account_id

    old = importlib.import_module(old_module)
    assert getattr(old, name) is getattr(account_id, name)


@pytest.mark.parametrize("name", ACCOUNT_ERROR_SUBCLASSES)
def test_account_error_subclass_base_is_core_object(name: str) -> None:
    """계좌 예외마다 상속 사슬의 ``AccountError`` 가 새 경로의 객체다."""
    from ante.core.account_id import AccountError as CoreAccountError

    cls = getattr(account_errors, name)
    assert cls.__mro__[1] is CoreAccountError


def test_invalid_account_id_error_code() -> None:
    """클래스 속성 ``code``."""
    assert InvalidAccountIdError.code == "VALIDATION_ERROR"


def test_registry_maps_invalid_account_id_error() -> None:
    """에러 레지스트리가 같은 클래스 객체로 코드를 찾는다."""
    assert EXCEPTION_TO_SPEC[InvalidAccountIdError].code == "VALIDATION_ERROR"


def test_constants() -> None:
    """상수 셋의 값."""
    assert ACCOUNT_ID_PATTERN.pattern == r"^[a-zA-Z0-9\-]{3,30}$"
    assert INVALID_RUNTIME_ACCOUNT_IDS == frozenset({"default"})
    assert RESTRICTED_NEW_ACCOUNT_IDS == frozenset({"test"})


@pytest.mark.parametrize(
    ("account_id", "expected"),
    [
        ("abc", False),
        ("ab", True),
        ("a" * 30, False),
        ("a" * 31, True),
        ("test", False),
        ("default", True),
        (None, True),
        ("", True),
        ("a_b", True),
    ],
)
def test_is_invalid_account_id(account_id: str | None, expected: bool) -> None:
    """runtime 판정의 경계 안팎."""
    assert is_invalid_account_id(account_id) is expected


@pytest.mark.parametrize("account_id", ["abc", "test", "a" * 30])
def test_require_account_id_returns_valid(account_id: str) -> None:
    """runtime valid면 받은 값을 그대로 돌려준다."""
    assert require_account_id(account_id) == account_id


@pytest.mark.parametrize(
    ("account_id", "context", "message"),
    [
        ("ab", "", f"유효한 account_id가 필요합니다: 'ab'. {REQUIRE_TAIL}"),
        ("default", "", f"유효한 account_id가 필요합니다: 'default'. {REQUIRE_TAIL}"),
        (None, "", f"유효한 account_id가 필요합니다: None. {REQUIRE_TAIL}"),
        ("", "", f"유효한 account_id가 필요합니다: ''. {REQUIRE_TAIL}"),
        ("", "ctx", f"(ctx) 유효한 account_id가 필요합니다: ''. {REQUIRE_TAIL}"),
    ],
)
def test_require_account_id_message(
    account_id: str | None, context: str, message: str
) -> None:
    """runtime invalid면 메시지 전체가 그대로다."""
    with pytest.raises(InvalidAccountIdError) as exc_info:
        require_account_id(account_id, context=context)
    assert str(exc_info.value) == message


@pytest.mark.parametrize("account_id", ["abc", "a" * 30])
def test_validate_new_account_id_returns_valid(account_id: str) -> None:
    """creation valid면 받은 값을 그대로 돌려준다."""
    assert validate_new_account_id(account_id) == account_id


@pytest.mark.parametrize(
    ("account_id", "context", "message"),
    [
        ("ab", "", f"account_id 형식이 올바르지 않습니다: 'ab'. {FORMAT_TAIL}"),
        (None, "", f"account_id 형식이 올바르지 않습니다: 'None'. {FORMAT_TAIL}"),
        ("", "", f"account_id 형식이 올바르지 않습니다: ''. {FORMAT_TAIL}"),
        (
            "test",
            "",
            "account_id 'test'는 ante init이 생성하는 시드 계좌로 "
            "예약되어 있어 신규 생성이 불가합니다.",
        ),
        (
            "default",
            "",
            "account_id 'default'는 fallback 예약어로 신규 생성이 불가합니다.",
        ),
        (
            "ab",
            "ctx",
            f"(ctx) account_id 형식이 올바르지 않습니다: 'ab'. {FORMAT_TAIL}",
        ),
    ],
)
def test_validate_new_account_id_message(
    account_id: str | None, context: str, message: str
) -> None:
    """creation invalid면 메시지 전체가 그대로다."""
    with pytest.raises(InvalidAccountIdError) as exc_info:
        validate_new_account_id(account_id, context=context)
    assert str(exc_info.value) == message
