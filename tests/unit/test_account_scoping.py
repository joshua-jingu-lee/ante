"""Account ID scoping helper 단위 테스트.

검증 대상: ``ante.account.scoping``의 runtime/creation 정책 분리.
계약 SSOT: ``docs/specs/account/14-account-id-contract.md``.
"""

from __future__ import annotations

import pytest

from ante.account.errors import InvalidAccountIdError
from ante.account.scoping import (
    INVALID_RUNTIME_ACCOUNT_IDS,
    RESTRICTED_NEW_ACCOUNT_IDS,
    is_invalid_account_id,
    require_account_id,
    validate_new_account_id,
)

# ── is_invalid_account_id (runtime 판정) ────────────────────


def test_is_invalid_rejects_none() -> None:
    """``None``은 runtime invalid."""
    assert is_invalid_account_id(None) is True


def test_is_invalid_rejects_empty() -> None:
    """빈 문자열은 runtime invalid."""
    assert is_invalid_account_id("") is True


def test_is_invalid_rejects_default() -> None:
    """``"default"``는 fallback 예약어로 runtime invalid."""
    assert is_invalid_account_id("default") is True
    assert "default" in INVALID_RUNTIME_ACCOUNT_IDS


def test_is_invalid_accepts_test() -> None:
    """``"test"``는 bootstrap 계좌이므로 runtime valid."""
    assert is_invalid_account_id("test") is False


@pytest.mark.parametrize(
    "bad_id",
    [
        "ab",  # 너무 짧음
        "a" * 31,  # 너무 김
        "foo!bar",  # 허용되지 않은 특수문자
        "has space",  # 공백
        "has_under",  # 언더스코어 비허용
        "한글계좌",  # non-ASCII
    ],
)
def test_is_invalid_rejects_pattern_mismatch(bad_id: str) -> None:
    """``ACCOUNT_ID_PATTERN`` 위반은 runtime invalid."""
    assert is_invalid_account_id(bad_id) is True


@pytest.mark.parametrize(
    "good_id",
    [
        "test",  # bootstrap (runtime valid)
        "domestic",
        "foo-bar-2",
        "abc",
        "a" * 30,
        "ABC",
        "Test-123",
    ],
)
def test_is_invalid_accepts_normal(good_id: str) -> None:
    """형식 준수 + non-fallback ID는 runtime valid."""
    assert is_invalid_account_id(good_id) is False


# ── require_account_id (fallback 금지 진입점) ───────────────


def test_require_raises_with_context() -> None:
    """invalid면 ``InvalidAccountIdError``를 raise하고 context를 메시지에 포함."""
    with pytest.raises(InvalidAccountIdError) as exc_info:
        require_account_id(None, context="trade.submit_order")

    msg = str(exc_info.value)
    assert "trade.submit_order" in msg
    assert "유효한 account_id가 필요합니다" in msg
    assert "fallback" in msg


def test_require_raises_without_context() -> None:
    """context 미지정 시에도 invalid는 raise하며 prefix는 비어 있다."""
    with pytest.raises(InvalidAccountIdError) as exc_info:
        require_account_id("default")

    msg = str(exc_info.value)
    # context prefix가 없으므로 "() " 같은 빈 괄호도 없어야 한다.
    assert not msg.startswith("()")
    assert "유효한 account_id가 필요합니다" in msg


def test_require_returns_value() -> None:
    """valid한 account_id는 그대로 반환된다."""
    assert require_account_id("domestic") == "domestic"
    # bootstrap valid
    assert require_account_id("test") == "test"
    # context는 valid 경로에 영향 없음
    assert require_account_id("foo-bar-2", context="ctx") == "foo-bar-2"


# ── validate_new_account_id (creation 정책) ─────────────────


def test_validate_new_rejects_test() -> None:
    """``"test"``는 신규 생성 거부 — bootstrap seed로만 허용."""
    assert "test" in RESTRICTED_NEW_ACCOUNT_IDS
    with pytest.raises(InvalidAccountIdError) as exc_info:
        validate_new_account_id("test")
    assert "ante init" in str(exc_info.value)
    assert "시드 계좌" in str(exc_info.value)


def test_validate_new_accepts_normal() -> None:
    """형식 준수 + non-RESTRICTED ID는 신규 생성 가능."""
    assert validate_new_account_id("domestic") == "domestic"
    assert validate_new_account_id("foo-bar-2") == "foo-bar-2"
    assert validate_new_account_id("Test-123") == "Test-123"


def test_validate_new_rejects_default() -> None:
    """``"default"``는 fallback 예약어로 신규 생성 거부."""
    with pytest.raises(InvalidAccountIdError) as exc_info:
        validate_new_account_id("default")
    assert "fallback" in str(exc_info.value)


def test_validate_new_rejects_none_and_empty() -> None:
    """``None``과 빈 문자열은 신규 생성 거부 (CLI 형식 위반 메시지)."""
    for bad in (None, ""):
        with pytest.raises(InvalidAccountIdError) as exc_info:
            validate_new_account_id(bad)
        assert "account_id 형식이 올바르지 않습니다" in str(exc_info.value)


def test_validate_new_message_preserves_format_hint() -> None:
    """형식 위반 메시지는 기존 ``AccountService.create`` 형식을 보존한다.

    ``ante account create`` CLI 표면에서 ``str(e)``로 노출되므로 형식이
    바뀌면 사용자/Agent 에러 처리 표면이 깨진다.
    """
    with pytest.raises(InvalidAccountIdError) as exc_info:
        validate_new_account_id("ab")  # 너무 짧음

    msg = str(exc_info.value)
    assert "account_id 형식이 올바르지 않습니다: 'ab'." in msg
    assert "영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다." in msg


def test_validate_new_message_rejects_test_with_seed_hint() -> None:
    """``"test"`` 거부 메시지는 bootstrap seed 안내를 포함한다."""
    with pytest.raises(InvalidAccountIdError) as exc_info:
        validate_new_account_id("test")

    msg = str(exc_info.value)
    assert "'test'" in msg
    assert "ante init" in msg
    assert "시드 계좌" in msg
