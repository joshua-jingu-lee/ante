"""CLI 출력 포맷터 — text/json 모드 지원."""

from __future__ import annotations

import functools
import json
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from collections.abc import Callable


def _sanitize_non_finite(obj: object) -> object:
    """비표준 JSON 토큰(Infinity/NaN) 방지: non-finite float를 None으로 정규화."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_non_finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_non_finite(v) for v in obj]
    return obj


_DETAIL_SCALARS = (str, int, float, bool, type(None))


def _check_detail_value(value: object) -> None:
    if isinstance(value, _DETAIL_SCALARS):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _check_detail_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"cli_details key must be str, not {type(key).__name__}"
                )
            _check_detail_value(item)
        return
    raise TypeError(f"cli_details value is not JSON: {type(value).__name__}")


def with_cli_details(
    exc: BaseException,
    details: dict[str, Any] | None = None,
    lines: tuple[str, ...] = (),
) -> BaseException:
    if details is not None:
        if not details:
            raise ValueError("cli_details must be None or a non-empty dict")
        _check_detail_value(details)
    if not all(isinstance(line, str) for line in lines):
        raise TypeError("cli_detail_lines must be str")
    setattr(exc, "cli_details", details)
    setattr(exc, "cli_detail_lines", tuple(lines))
    return exc


def _checked_lines(text: object) -> tuple[str, ...]:
    if isinstance(text, str):
        raise TypeError("CommandResult.text must be a tuple of lines, not a str")
    if not isinstance(text, tuple):
        raise TypeError("CommandResult.text must be None or a tuple of lines")
    if text == ():
        raise TypeError("CommandResult.text must be None or a non-empty tuple")
    if not all(isinstance(line, str) for line in text):
        raise TypeError("CommandResult.text lines must all be str")
    return text


@dataclass(frozen=True)
class CommandResult:
    data: dict[str, Any] | list[Any] = field(default_factory=dict, repr=False)
    message: str = ""
    text: tuple[str, ...] | Callable[[], tuple[str, ...]] | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        if self.text is not None and not callable(self.text):
            _checked_lines(self.text)

    def text_lines(self) -> tuple[str, ...] | None:
        if self.text is None:
            return None
        if callable(self.text):
            return _checked_lines(self.text())
        return self.text


def table_lines(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["(no data)"]
    header = " | ".join(f"{c:>12}" for c in columns)
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(" | ".join(f"{str(row.get(c, '')):>12}" for c in columns))
    return lines


def format_option(fn: Callable[..., Any]) -> Callable[..., Any]:
    """서브커맨드용 --format 옵션 데코레이터.

    루트 그룹의 --format 보다 서브커맨드의 --format이 우선한다.
    ``ante account list --format json`` 형태 호출을 지원한다.
    """

    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["text", "json"]),
        default=None,
        help="출력 형식 (text 또는 json)",
    )
    @functools.wraps(fn)
    def wrapper(
        *args: object, output_format: str | None = None, **kwargs: object
    ) -> object:
        if output_format is not None:
            ctx = click.get_current_context()
            ctx.obj["format"] = output_format
            ctx.obj["formatter"] = OutputFormatter(output_format)
        return fn(*args, **kwargs)

    return wrapper


class OutputFormatter:
    """CLI 출력 포맷터."""

    def __init__(self, fmt: str = "text") -> None:
        self._format = fmt

    @property
    def is_json(self) -> bool:
        return self._format == "json"

    def output(self, data: dict[str, Any] | list[Any], text_template: str = "") -> None:
        """데이터 출력."""
        if self._format == "json":
            click.echo(
                json.dumps(
                    _sanitize_non_finite(data),
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
        elif text_template and isinstance(data, dict):
            click.echo(text_template.format(**data))
        else:
            click.echo(str(data))

    def table(self, rows: list[dict[str, Any]], columns: list[str]) -> None:
        """테이블 형태 출력."""
        if self._format == "json":
            click.echo(
                json.dumps(
                    _sanitize_non_finite(rows),
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
            return
        for line in table_lines(rows, columns):
            click.echo(line)

    def error(
        self, message: str, code: str = "", details: dict[str, Any] | None = None
    ) -> None:
        """에러 출력. JSON은 ``details``가 ``None``이 아닐 때만 네 번째 키로 싣는다."""
        if self._format == "json":
            payload: dict[str, Any] = {
                "status": "error",
                "code": code,
                "message": message,
            }
            if details is not None:
                payload["details"] = details
            click.echo(json.dumps(_sanitize_non_finite(payload), allow_nan=False))
        else:
            click.echo(f"Error: {message}", err=True)

    def success(self, message: str, data: dict[str, Any] | None = None) -> None:
        """성공 메시지 출력."""
        if self._format == "json":
            result = {
                "status": "ok",
                "message": message,
                "data": data if data is not None else {},
            }
            click.echo(
                json.dumps(
                    _sanitize_non_finite(result),
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
        else:
            click.echo(message)
