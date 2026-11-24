"""``ante.contracts`` error helper unit tests (#1840).

본 테스트 모듈은 helper 자체 동작만 검증한다. repository-wide drift assertion
(예: 모든 ``*Error`` class 가 ``EXCEPTION_TO_SPEC`` 에 등록되어야 한다는
검증) 은 의도적으로 추가하지 않는다 — drift test guard 는 #1841 책임이며
본 PR 범위 밖이다.
"""

from __future__ import annotations

import json

import pytest

from ante.account.errors import InvalidAccountIdError
from ante.approval.errors import ApprovalNotFoundError
from ante.bot.exceptions import BotNotFoundError
from ante.broker.exceptions import AuthenticationError, TokenRateLimitError
from ante.contracts import (
    ErrorCategory,
    ErrorSpec,
    error_spec_for_exception,
    ipc_error_payload,
)
from ante.contracts.error_registry import EXCEPTION_TO_SPEC, EXECUTION_ERROR_SPEC
from ante.core.database import ReadOnlyDatabaseError
from ante.member.scopes import InvalidScopeError

# ── ErrorSpec dataclass shape ─────────────────────────────────────────────────


class TestErrorSpecShape:
    """``ErrorSpec`` dataclass 의 frozen + 기본값 shape."""

    def test_construct_with_minimum_fields(self) -> None:
        """``code`` + ``category`` 만으로 생성 가능 (나머지 default)."""
        spec = ErrorSpec(code="FOO", category="internal")
        assert spec.code == "FOO"
        assert spec.category == "internal"
        assert spec.exit_code == 1
        assert spec.retryable is False
        assert spec.default_message is None

    def test_construct_with_all_fields(self) -> None:
        spec = ErrorSpec(
            code="BAR",
            category="validation",
            exit_code=2,
            retryable=True,
            default_message="hello",
        )
        assert spec.code == "BAR"
        assert spec.category == "validation"
        assert spec.exit_code == 2
        assert spec.retryable is True
        assert spec.default_message == "hello"

    def test_is_frozen(self) -> None:
        """frozen dataclass — 필드 재할당이 거부된다."""
        from dataclasses import FrozenInstanceError

        spec = ErrorSpec(code="FOO", category="internal")
        with pytest.raises(FrozenInstanceError):
            spec.code = "BAR"  # type: ignore[misc]


# ── error_spec_for_exception ─────────────────────────────────────────────────


class TestErrorSpecForException:
    """대표 lock 4건 + .code fallback + EXECUTION_ERROR fallback resolver."""

    def test_invalid_account_id_resolves_validation_error(self) -> None:
        spec = error_spec_for_exception(InvalidAccountIdError("bad id"))
        assert spec.code == "VALIDATION_ERROR"
        assert spec.category == "validation"

    def test_bot_not_found_resolves_typed_code(self) -> None:
        spec = error_spec_for_exception(BotNotFoundError("bot-xyz"))
        assert spec.code == "BOT_NOT_FOUND"
        assert spec.category == "not_found"

    def test_approval_not_found_resolves_typed_code(self) -> None:
        spec = error_spec_for_exception(ApprovalNotFoundError("appr-1"))
        assert spec.code == "APPROVAL_NOT_FOUND"
        assert spec.category == "not_found"

    def test_member_invalid_scope_resolves_permission(self) -> None:
        spec = error_spec_for_exception(InvalidScopeError("sample:bad"))
        assert spec.code == "MEMBER_INVALID_SCOPE"
        assert spec.category == "permission"

    @pytest.mark.parametrize(
        "exc",
        [AuthenticationError("token"), TokenRateLimitError("token")],
        ids=["auth", "token_rate_limit"],
    )
    def test_broker_auth_failed_resolves_external(self, exc: Exception) -> None:
        spec = error_spec_for_exception(exc)
        assert spec.code == "BROKER_AUTH_FAILED"
        assert spec.category == "external"

    def test_unknown_exception_returns_execution_error_internal(self) -> None:
        """registry miss + ``.code`` 없음 → ``EXECUTION_ERROR`` fallback."""

        class _RandomError(Exception):
            pass

        spec = error_spec_for_exception(_RandomError("boom"))
        assert spec.code == "EXECUTION_ERROR"
        assert spec.category == "internal"
        # ``EXECUTION_ERROR_SPEC`` constant 와 동일 객체.
        assert spec is EXECUTION_ERROR_SPEC

    def test_typed_exception_with_code_attribute_uses_typed_code(self) -> None:
        """registry miss 지만 ``.code`` SCREAMING_SNAKE 속성이 있으면 사용."""

        class _TypedError(Exception):
            code: str = "X_FOO"

        spec = error_spec_for_exception(_TypedError("typed boom"))
        assert spec.code == "X_FOO"
        assert spec.category == "internal"  # 보수적 default

    def test_typed_exception_with_lowercase_code_falls_back_to_execution(
        self,
    ) -> None:
        """``.code`` 가 SCREAMING_SNAKE 규약 미준수면 fallback."""

        class _BadCodeError(Exception):
            code: str = "lowercase_code"

        spec = error_spec_for_exception(_BadCodeError("bad code"))
        assert spec.code == "EXECUTION_ERROR"

    def test_typed_exception_with_non_string_code_falls_back(self) -> None:
        """``.code`` 가 str 이 아니면 fallback (방어적)."""

        class _IntCodeError(Exception):
            code = 42  # type: ignore[var-annotated]

        spec = error_spec_for_exception(_IntCodeError("int code"))
        assert spec.code == "EXECUTION_ERROR"

    def test_subclass_resolves_via_mro(self) -> None:
        """registry 에 등록된 base class subclass 도 MRO 매칭으로 resolve."""

        class _CustomBotError(BotNotFoundError):
            pass

        spec = error_spec_for_exception(_CustomBotError("child"))
        assert spec.code == "BOT_NOT_FOUND"

    def test_account_not_found_uses_class_code_attribute_fallback(self) -> None:
        """대표 lock 에 등록되지 않은 ``AccountNotFoundError`` (``.code`` 보유)
        는 (2) 단계 ``.code`` fallback 으로 typed code 를 surface 한다.

        이는 본 PR 범위인 4건 lock 외 기존 typed exception 의 IPC envelope
        ``getattr(e, "code", "EXECUTION_ERROR")`` 패턴과 동등한 동작이다.
        """
        from ante.account.errors import AccountNotFoundError

        spec = error_spec_for_exception(AccountNotFoundError("missing"))
        assert spec.code == "ACCOUNT_NOT_FOUND"


# ── ipc_error_payload ────────────────────────────────────────────────────────


class TestIpcErrorPayload:
    """IPC envelope ``{code, message}`` shape."""

    def test_matches_shape(self) -> None:
        payload = ipc_error_payload(BotNotFoundError("bot-xyz"))
        assert set(payload.keys()) == {"code", "message"}
        assert payload["code"] == "BOT_NOT_FOUND"
        # ``BotNotFoundError`` 가 ``__init__`` 에서 만든 문구를 surface.
        assert "bot-xyz" in payload["message"]

    def test_unknown_exception_yields_execution_error_message(self) -> None:
        payload = ipc_error_payload(RuntimeError("kaboom"))
        assert payload["code"] == "EXECUTION_ERROR"
        assert payload["message"] == "kaboom"

    def test_empty_exception_message_uses_default(self) -> None:
        """``str(exc)`` 가 비어있으면 ``spec.default_message`` 로 fallback.

        대표 lock 4건은 모두 ``default_message`` 가 ``None`` 이므로 빈 문자열이
        된다 — envelope shape 호환 (``message: ""``).
        """

        class _BareError(Exception):
            pass

        payload = ipc_error_payload(_BareError())
        assert payload["code"] == "EXECUTION_ERROR"
        assert payload["message"] == ""

    def test_payload_is_json_serializable(self) -> None:
        """envelope 직렬화 호환 확인 (CLI/IPC 양쪽 모두 JSON 직렬화)."""
        payload = ipc_error_payload(InvalidAccountIdError("bad"))
        serialized = json.dumps(payload)
        decoded = json.loads(serialized)
        assert decoded == payload


# ── ErrorCategory Literal sanity ──────────────────────────────────────────────


def test_error_category_literal_covers_taxonomy_eight_values() -> None:
    """``ErrorCategory`` 가 taxonomy SSOT 의 8 카테고리를 정확히 enumerate.

    drift 가 발생하면 본 테스트가 즉시 깨진다 — taxonomy SSOT 갱신과 함께
    본 테스트의 expected set 도 갱신되어야 한다.
    """
    from typing import get_args

    expected = {
        "validation",
        "auth",
        "permission",
        "not_found",
        "state_conflict",
        "service_unavailable",
        "external",
        "internal",
    }
    assert set(get_args(ErrorCategory)) == expected


# ── registry ↔ class ``.code`` 일치 ───────────────────────────────────────────

_REGISTERED_WITHOUT_CODE = {"ReadOnlyDatabaseError"}


def test_registry_spec_code_matches_class_code_for_every_entry() -> None:
    """``EXCEPTION_TO_SPEC`` 의 모든 클래스에서 클래스 ``.code`` 는 spec 코드와
    같다. ``.code`` 가 없는 클래스는 명시한 집합뿐이다."""
    assert EXCEPTION_TO_SPEC
    without_code: set[str] = set()
    mismatched: dict[str, tuple[str, str]] = {}
    for klass, spec in EXCEPTION_TO_SPEC.items():
        class_code = getattr(klass, "code", None)
        if class_code is None:
            without_code.add(klass.__name__)
        elif class_code != spec.code:
            mismatched[klass.__name__] = (class_code, spec.code)

    assert mismatched == {}
    assert without_code == _REGISTERED_WITHOUT_CODE


class TestReadOnlyDatabaseErrorCode:
    """``.code`` 가 없는 ``ReadOnlyDatabaseError`` 의 봉투 코드는 실행 오류다."""

    def test_ipc_error_payload_code(self) -> None:
        payload = ipc_error_payload(ReadOnlyDatabaseError("read-only"))
        assert payload == {"code": "EXECUTION_ERROR", "message": "read-only"}

    def test_cli_error_envelope_code(self) -> None:
        spec = error_spec_for_exception(ReadOnlyDatabaseError("read-only"))
        assert (spec.code, spec.exit_code) == ("EXECUTION_ERROR", 1)


# ── module public surface ─────────────────────────────────────────────────────


def test_public_surface_importable() -> None:
    """``ante.contracts`` 모듈의 public API alias re-export."""
    from ante import contracts

    expected = {
        "ErrorCategory",
        "ErrorSpec",
        "error_spec_for_exception",
        "ipc_error_payload",
    }
    assert expected.issubset(set(contracts.__all__))
    for name in expected:
        assert hasattr(contracts, name), name


def test_emit_cli_error_is_gone() -> None:
    from ante import contracts
    from ante.contracts import helpers

    for module in (contracts, helpers):
        assert "emit_cli_error" not in module.__all__
        assert not hasattr(module, "emit_cli_error")
