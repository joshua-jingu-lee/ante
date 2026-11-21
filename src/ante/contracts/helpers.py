"""CLI/IPC error helper functions.

본 모듈은 ``docs/specs/contracts/error-taxonomy.md`` 가 normative 로 lock 한
``ErrorSpec`` taxonomy 를 CLI direct path 와 IPC path 가 공통으로 사용할 수
있도록 도입한 helper SSOT 다.

API 3종:

- ``error_spec_for_exception(exc)`` — exception → ``ErrorSpec`` resolver.
- ``emit_cli_error(fmt, exc, ...)`` — CLI ``OutputFormatter.error`` callsite를
  taxonomy-정렬된 형태로 호출하는 helper. ``NoReturn`` 으로 click ``Exit`` 를
  raise 한다.
- ``ipc_error_payload(exc)`` — IPC 서버 envelope ``{code, message}``
  shape 의 payload helper.

"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NoReturn

import click

from ante.contracts.error_registry import EXCEPTION_TO_SPEC, EXECUTION_ERROR_SPEC
from ante.contracts.errors import ErrorSpec

if TYPE_CHECKING:
    from ante.cli.formatter import OutputFormatter

__all__ = [
    "emit_cli_error",
    "error_spec_for_exception",
    "ipc_error_payload",
]


_SCREAMING_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def error_spec_for_exception(exc: BaseException) -> ErrorSpec:
    """Exception 인스턴스를 ``ErrorSpec`` 으로 resolve.

    resolver 우선순위:

    1. ``EXCEPTION_TO_SPEC`` registry 의 MRO lookup — ``type(exc).__mro__`` 를
       따라 첫 매치를 반환한다 (subclass 도 base class registry entry로 매칭).
    2. ``getattr(exc, "code", None)`` 이 SCREAMING_SNAKE_CASE 규약을 만족하면
       해당 코드를 ``category="internal"`` 으로 보수적 ErrorSpec 으로 wrap한다.
       기존 typed exception (예: ``AccountNotFoundError.code =
       "ACCOUNT_NOT_FOUND"``) 가 본 fallback 으로 IPC envelope 의 안정 코드를
       유지한다.
    3. 위 둘 다 매치되지 않으면 ``EXECUTION_ERROR_SPEC`` (internal fallback).

    Args:
        exc: 분류할 exception 인스턴스.

    Returns:
        ``ErrorSpec`` — code/category 가 채워진 frozen dataclass.
    """

    for klass in type(exc).__mro__:
        spec = EXCEPTION_TO_SPEC.get(klass)
        if spec is not None:
            return spec

    code_attr = getattr(exc, "code", None)
    if isinstance(code_attr, str) and _SCREAMING_SNAKE_RE.match(code_attr):
        return ErrorSpec(code=code_attr, category="internal")

    return EXECUTION_ERROR_SPEC


def _resolve_message(
    exc: BaseException,
    spec: ErrorSpec,
    *,
    fallback_message: str | None,
) -> str:
    """``emit_cli_error`` / ``ipc_error_payload`` 가 공유하는 message resolution."""

    if fallback_message:
        return fallback_message
    exc_text = str(exc)
    if exc_text:
        return exc_text
    if spec.default_message:
        return spec.default_message
    return ""


def emit_cli_error(
    fmt: OutputFormatter,
    exc: BaseException,
    *,
    fallback_message: str | None = None,
) -> NoReturn:
    """``ErrorSpec`` 기반 CLI error envelope 출력 + click ``Exit`` raise.

    호출자는 본 helper 를 CLI direct path 의 ``except`` 블록에서 사용해
    taxonomy-정렬된 ``code`` 를 ``OutputFormatter.error`` 로 surface 한다.

    동작:

    - ``error_spec_for_exception(exc)`` 로 ``ErrorSpec`` 을 resolve.
    - ``OutputFormatter.error(message, code=spec.code)`` 호출 — ``src/ante/cli/
      formatter.py`` 의 ``error(message, code="")`` 시그니처와 정렬.
    - ``click.exceptions.Exit(spec.exit_code)`` 를 raise — ``NoReturn``.

    Args:
        fmt: ``OutputFormatter`` 인스턴스 (CLI ctx 의 ``ctx.obj["formatter"]``).
        exc: surface 할 exception.
        fallback_message: 호출자가 명시 제공할 도메인 문구. ``None`` 이면
            ``str(exc)`` → ``spec.default_message`` 순서로 fallback.

    Raises:
        click.exceptions.Exit: 항상 ``spec.exit_code`` (기본 1) 로 click
            이 exit 하게 한다.
    """

    spec = error_spec_for_exception(exc)
    message = _resolve_message(exc, spec, fallback_message=fallback_message)
    fmt.error(message, code=spec.code)
    raise click.exceptions.Exit(spec.exit_code)


def ipc_error_payload(exc: BaseException) -> dict[str, str]:
    """``{"code", "message"}`` IPC error payload helper.

    IPC 서버 ``getattr(e, "code", "EXECUTION_ERROR")`` 패턴 대응 helper.

    Args:
        exc: 직렬화할 exception.

    Returns:
        ``{"code": <ErrorSpec.code>, "message": <resolved message>}``. 양쪽
        모두 str 이다 — envelope shape (envelopes.md) 와 정렬.
    """

    spec = error_spec_for_exception(exc)
    message = _resolve_message(exc, spec, fallback_message=None)
    return {"code": spec.code, "message": message}
