"""IPC 응답 코드 보존 조사 (#2641).

IPC 서버의 코드 결정이 ``getattr(e, "code", "EXECUTION_ERROR")``에서
``ipc_error_payload(e)``로 바뀌어도 ``ante.*`` 예외의 코드와 메시지가 바뀌지
않음을 introspection으로 보인다.

- 대상: ``src/ante``의 모든 모듈(``__main__`` 제외)을 import한 뒤
  ``BaseException``의 하위 클래스 중 ``__module__``이 ``ante.``로 시작하는 것.
- 인스턴스: ``cls.__new__(cls)``, 실패하면 ``cls("x")``.
- 서드파티 예외는 실제 인스턴스로 따로 본다. 문자열이 아닌 ``code``(정수)가
  ``EXECUTION_ERROR``가 되는 것은 의도한 변경이다.

조사 표를 파일로 쓰려면 이 파일을 스크립트로 실행한다::

    python tests/unit/contracts/test_error_code_preservation.py <출력 경로>
"""

from __future__ import annotations

import importlib
import pkgutil
import sqlite3
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import pydantic
import pytest
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close
from yarl import URL

import ante
from ante.contracts.helpers import error_spec_for_exception, ipc_error_payload

_ABSENT = "<없음>"


@dataclass(frozen=True)
class SurveyRow:
    """조사 표의 한 행."""

    name: str
    old_code: object
    new_code: object
    old_message: object
    new_message: object

    @property
    def changed(self) -> bool:
        return (self.old_code, self.old_message) != (self.new_code, self.new_message)


def _outcome(fn: Callable[[], object]) -> object:
    """값 또는 ``<raises 예외타입>``. 두 규칙이 같은 이유로 실패하면 같은 행이 된다."""
    try:
        return fn()
    except Exception as exc:
        return f"<raises {type(exc).__name__}>"


def _old_rule(exc: BaseException) -> tuple[object, object]:
    """바뀌기 전 ``_dispatch``의 규칙: ``getattr(e, "code", ...)``와 ``str(e)``."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        code = _outcome(lambda: getattr(exc, "code", "EXECUTION_ERROR"))
    return code, _outcome(lambda: str(exc))


def _new_rule(exc: BaseException) -> tuple[object, object]:
    """바뀐 뒤의 규칙: ``error_spec_for_exception``와 ``ipc_error_payload``."""
    code = _outcome(lambda: error_spec_for_exception(exc).code)
    return code, _outcome(lambda: ipc_error_payload(exc)["message"])


def _row(name: str, exc: BaseException) -> SurveyRow:
    old_code, old_message = _old_rule(exc)
    new_code, new_message = _new_rule(exc)
    return SurveyRow(name, old_code, new_code, old_message, new_message)


def ante_exception_classes() -> list[type[BaseException]]:
    """``ante`` 패키지 전체를 import하고 ``ante.*`` 예외 클래스를 모은다."""
    for info in pkgutil.walk_packages(ante.__path__, "ante."):
        if info.name.endswith("__main__"):
            continue
        importlib.import_module(info.name)
    seen: set[type[BaseException]] = set()
    stack: list[type[BaseException]] = [BaseException]
    while stack:
        for sub in stack.pop().__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    found = [c for c in seen if c.__module__.startswith("ante.")]
    return sorted(found, key=lambda c: (c.__module__, c.__qualname__))


def make_instance(cls: type[BaseException]) -> BaseException:
    """``cls.__new__(cls)``, 실패하면 ``cls("x")``."""
    try:
        return cls.__new__(cls)
    except Exception:
        return cls("x")


def ante_rows() -> list[SurveyRow]:
    return [
        _row(f"{cls.__module__}.{cls.__qualname__}", make_instance(cls))
        for cls in ante_exception_classes()
    ]


def _pydantic_error() -> pydantic.ValidationError:
    class _Model(pydantic.BaseModel):
        x: int

    try:
        _Model(x="not-int")
    except pydantic.ValidationError as exc:
        return exc
    raise AssertionError("pydantic이 검증 오류를 내지 않았다")


def third_party_instances() -> list[tuple[str, BaseException]]:
    url = URL("http://example.invalid/")
    info = aiohttp.RequestInfo(url, "GET", {}, url)
    return [
        ("sqlite3.OperationalError", sqlite3.OperationalError("database is locked")),
        ("sqlite3.IntegrityError", sqlite3.IntegrityError("UNIQUE constraint")),
        ("sqlite3.DatabaseError", sqlite3.DatabaseError("file is not a database")),
        ("pydantic.ValidationError", _pydantic_error()),
        ("TimeoutError", TimeoutError("timed out")),
        (
            "aiohttp.ClientResponseError",
            aiohttp.ClientResponseError(info, (), status=500, message="boom"),
        ),
        (
            "websockets.ConnectionClosed",
            ConnectionClosed(Close(1006, "gone"), None),
        ),
    ]


def third_party_rows() -> list[SurveyRow]:
    return [_row(name, exc) for name, exc in third_party_instances()]


# ── 테스트 ────────────────────────────────────────────────────────────────


def test_ante_exception_codes_and_messages_are_preserved() -> None:
    rows = ante_rows()
    assert rows, "ante.* 예외 클래스를 하나도 찾지 못했다(빈 통과 방지)"
    changed = [r for r in rows if r.changed]
    assert changed == []


def test_survey_covers_known_ante_exceptions() -> None:
    """수집이 실제 예외를 보는지: 잘 알려진 클래스 셋이 대상에 있다."""
    names = {f"{c.__module__}.{c.__qualname__}" for c in ante_exception_classes()}
    assert {
        "ante.bot.exceptions.BotNotFoundError",
        "ante.member.errors.MemberInvalidRecoveryCredentialError",
        "ante.approval.errors.ApprovalNotFoundError",
    } <= names


def test_new_fails_then_falls_back_to_single_argument() -> None:
    """``MemberInvalidRecoveryCredentialError``: ``__new__``가 실패해 ``cls("x")``."""
    from ante.member.errors import MemberInvalidRecoveryCredentialError

    with pytest.raises(TypeError):
        MemberInvalidRecoveryCredentialError.__new__(
            MemberInvalidRecoveryCredentialError
        )
    exc = make_instance(MemberInvalidRecoveryCredentialError)
    assert str(exc) == "x"
    assert ipc_error_payload(exc) == {
        "code": "MEMBER_INVALID_RECOVERY_CREDENTIAL",
        "message": "x",
    }


def test_third_party_survey_table() -> None:
    """서드파티: 정수 ``code``만 ``EXECUTION_ERROR``로 바뀌고 메시지는 그대로다."""
    rows = {r.name: r for r in third_party_rows()}
    got = {
        name: (r.old_code, r.new_code, r.old_message == r.new_message)
        for name, r in rows.items()
    }
    assert got == {
        "sqlite3.OperationalError": ("EXECUTION_ERROR", "EXECUTION_ERROR", True),
        "sqlite3.IntegrityError": ("EXECUTION_ERROR", "EXECUTION_ERROR", True),
        "sqlite3.DatabaseError": ("EXECUTION_ERROR", "EXECUTION_ERROR", True),
        "pydantic.ValidationError": ("EXECUTION_ERROR", "EXECUTION_ERROR", True),
        "TimeoutError": ("EXECUTION_ERROR", "EXECUTION_ERROR", True),
        "aiohttp.ClientResponseError": (500, "EXECUTION_ERROR", True),
        "websockets.ConnectionClosed": (1006, "EXECUTION_ERROR", True),
    }
    assert rows["sqlite3.OperationalError"].new_message == "database is locked"


# ── 조사 표 쓰기 ──────────────────────────────────────────────────────────


def _cell(value: object) -> str:
    text = _ABSENT if value == "" else repr(value)
    return text.replace("|", "\\|").replace("\n", "\\n")


def survey_table() -> str:
    lines: list[str] = []
    for title, rows in (
        ("ante.* 예외", ante_rows()),
        ("서드파티 예외(실제 인스턴스)", third_party_rows()),
    ):
        changed = sum(r.changed for r in rows)
        lines += [
            f"### {title}: {len(rows)}개, 다른 행 {changed}개",
            "",
            "| 클래스 | 전 코드 | 후 코드 | 전 메시지 | 후 메시지 | 다름 |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| `{r.name}` | {_cell(r.old_code)} | {_cell(r.new_code)} | "
            f"{_cell(r.old_message)} | {_cell(r.new_message)} | "
            f"{'예' if r.changed else ''} |"
            for r in rows
        ]
        lines.append("")
    return "\n".join(lines)


def write_survey_table(path: Path) -> None:
    path.write_text(survey_table(), encoding="utf-8")


if __name__ == "__main__":
    write_survey_table(Path(sys.argv[1]))
