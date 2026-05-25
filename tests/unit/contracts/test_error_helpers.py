"""``ante.contracts`` error helper unit tests (#1840).

본 테스트 모듈은 helper 자체 동작만 검증한다. repository-wide drift assertion
(예: 모든 ``*Error`` class 가 ``EXCEPTION_TO_SPEC`` 에 등록되어야 한다는
검증) 은 의도적으로 추가하지 않는다 — drift test guard 는 #1841 책임이며
본 PR 범위 밖이다.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import click
import pytest

from ante.account.errors import InvalidAccountIdError
from ante.approval.errors import ApprovalNotFoundError
from ante.bot.exceptions import BotNotFoundError
from ante.cli.formatter import OutputFormatter
from ante.contracts import (
    ErrorCategory,
    ErrorSpec,
    emit_cli_error,
    error_spec_for_exception,
    ipc_error_payload,
)
from ante.contracts.error_registry import EXCEPTION_TO_SPEC, EXECUTION_ERROR_SPEC
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
        spec = error_spec_for_exception(InvalidScopeError("oracle:bad"))
        assert spec.code == "MEMBER_INVALID_SCOPE"
        assert spec.category == "permission"

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


# ── emit_cli_error ───────────────────────────────────────────────────────────


class TestEmitCliError:
    """``OutputFormatter`` 호출 + click ``Exit`` raise 동작."""

    def test_calls_fmt_error_with_spec_code(self) -> None:
        """대표 lock 에 대해 ``fmt.error(message, code=spec.code)`` 호출."""
        mock_fmt = MagicMock(spec=OutputFormatter)
        exc = BotNotFoundError("bot-1")

        with pytest.raises(click.exceptions.Exit) as exit_info:
            emit_cli_error(mock_fmt, exc)

        assert exit_info.value.exit_code == 1
        mock_fmt.error.assert_called_once()
        args, kwargs = mock_fmt.error.call_args
        # 첫 positional 은 message (str(exc)).
        assert args == ("Bot not found: bot-1",)
        assert kwargs == {"code": "BOT_NOT_FOUND"}

    def test_message_priority_fallback_overrides_str_exc(self) -> None:
        """``fallback_message`` 인자가 ``str(exc)`` 보다 우선."""
        mock_fmt = MagicMock(spec=OutputFormatter)
        exc = BotNotFoundError("bot-1")  # str(exc) == "Bot not found: bot-1"

        with pytest.raises(click.exceptions.Exit):
            emit_cli_error(mock_fmt, exc, fallback_message="explicit override")

        args, _ = mock_fmt.error.call_args
        assert args == ("explicit override",)

    def test_message_priority_str_exc_used_when_no_fallback(self) -> None:
        """``fallback_message`` 가 ``None`` 이면 ``str(exc)`` 가 두 번째 우선순위."""
        mock_fmt = MagicMock(spec=OutputFormatter)
        exc = BotNotFoundError("bot-2")

        with pytest.raises(click.exceptions.Exit):
            emit_cli_error(mock_fmt, exc, fallback_message=None)

        args, _ = mock_fmt.error.call_args
        assert args == ("Bot not found: bot-2",)

    def test_message_priority_default_message_used_when_exc_empty(self) -> None:
        """``str(exc)`` 가 비어있으면 ``spec.default_message`` 가 세 번째 우선순위."""
        # default_message 가 있는 ErrorSpec 을 직접 lookup 하도록
        # custom exception 을 만들고 임시 registry 에 등록한다.

        class _SilentError(Exception):
            pass

        spec_with_default = ErrorSpec(
            code="SILENT_X",
            category="internal",
            default_message="fell back to default",
        )
        EXCEPTION_TO_SPEC[_SilentError] = spec_with_default
        try:
            mock_fmt = MagicMock(spec=OutputFormatter)
            with pytest.raises(click.exceptions.Exit):
                emit_cli_error(mock_fmt, _SilentError())  # str(exc) == ""

            args, kwargs = mock_fmt.error.call_args
            assert args == ("fell back to default",)
            assert kwargs == {"code": "SILENT_X"}
        finally:
            EXCEPTION_TO_SPEC.pop(_SilentError, None)

    def test_message_falls_back_to_empty_string_when_nothing_resolves(
        self,
    ) -> None:
        """``fallback_message`` None + ``str(exc)`` empty + ``default_message``
        None 이면 빈 문자열을 ``fmt.error`` 에 넘긴다 (envelope shape 호환)."""

        class _BareError(Exception):
            pass

        mock_fmt = MagicMock(spec=OutputFormatter)
        with pytest.raises(click.exceptions.Exit):
            emit_cli_error(mock_fmt, _BareError())

        args, kwargs = mock_fmt.error.call_args
        assert args == ("",)
        assert kwargs == {"code": "EXECUTION_ERROR"}

    def test_exit_code_from_spec(self) -> None:
        """``ErrorSpec.exit_code`` 가 ``Exit`` 종료 코드로 전달된다."""

        class _CustomExitError(Exception):
            pass

        custom_spec = ErrorSpec(code="X_CUSTOM_EXIT", category="internal", exit_code=42)
        EXCEPTION_TO_SPEC[_CustomExitError] = custom_spec
        try:
            mock_fmt = MagicMock(spec=OutputFormatter)
            with pytest.raises(click.exceptions.Exit) as exit_info:
                emit_cli_error(mock_fmt, _CustomExitError("boom"))
            assert exit_info.value.exit_code == 42
        finally:
            EXCEPTION_TO_SPEC.pop(_CustomExitError, None)

    def test_integrates_with_real_output_formatter_json_mode(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """실제 ``OutputFormatter(json)`` 와 통합 — envelope shape 확인."""
        fmt = OutputFormatter("json")
        with pytest.raises(click.exceptions.Exit):
            emit_cli_error(fmt, InvalidAccountIdError("bad-id"))

        captured = capsys.readouterr()
        envelope = json.loads(captured.out)
        # envelope shape SSOT (envelopes.md #1821) — ``status``/``code``/
        # ``message`` 3-key shape.
        assert envelope["status"] == "error"
        assert envelope["code"] == "VALIDATION_ERROR"
        assert envelope["message"] == "bad-id"


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


# ── module public surface ─────────────────────────────────────────────────────


def test_public_surface_importable() -> None:
    """``ante.contracts`` 모듈의 public API alias re-export."""
    from ante import contracts

    expected = {
        "ErrorCategory",
        "ErrorSpec",
        "emit_cli_error",
        "error_spec_for_exception",
        "ipc_error_payload",
    }
    assert expected.issubset(set(contracts.__all__))
    for name in expected:
        assert hasattr(contracts, name), name
