"""에러 봉투의 ``details``와 text 상세 줄 (#2762).

``OutputFormatter.error``는 ``details``가 ``None``이 아닐 때만 네 번째 키로
싣고, 진입점 훅은 예외의 ``cli_details``·``cli_detail_lines``를 JSON의
``details``와 text 오류 줄 뒤의 stderr 줄로 낸다. 속성이 없는 예외는 지금과
같은 바이트다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.cli.formatter import OutputFormatter, with_cli_details
from ante.cli.middleware import AuthenticatedGroup


class _DemoError(Exception):
    code = "DEMO_ERROR"


_RAISED: list[BaseException] = []


@click.group(cls=AuthenticatedGroup)
@click.option("--format", "output_format", default="text")
def _root(output_format: str) -> None:
    """테스트 루트."""


@_root.command("boom")
def _boom() -> None:
    """``_RAISED``의 예외를 올린다."""
    raise _RAISED[0]


def _set_member(ctx: click.Context) -> None:
    ctx.ensure_object(dict)
    ctx.obj["member"] = object()


@pytest.fixture(autouse=True)
def _no_gates() -> Iterator[None]:
    with (
        patch("ante.cli.main.authenticate_member", side_effect=_set_member),
        patch.object(
            AuthenticatedGroup, "_should_enforce_encryption_gate", return_value=False
        ),
    ):
        yield
    _RAISED.clear()


def _run(exc: BaseException, mode: str) -> Result:
    _RAISED[:] = [exc]
    return CliRunner(mix_stderr=False).invoke(_root, ["--format", mode, "boom"])


_DETAILS = {"stage": "load", "errors": ["금지된 import: os", "on_step 누락"]}
_LINES = ("  - 금지된 import: os", "  - on_step 누락")


def test_exception_without_details_keeps_three_fields_and_one_line() -> None:
    json_result = _run(_DemoError("실패"), "json")
    text_result = _run(_DemoError("실패"), "text")

    assert (json_result.exit_code, json_result.stderr) == (1, "")
    assert json_result.stdout == (
        '{"status": "error", "code": "DEMO_ERROR", "message": "\\uc2e4\\ud328"}\n'
    )
    assert (text_result.exit_code, text_result.stdout) == (1, "")
    assert text_result.stderr == "Error: DEMO_ERROR: 실패\n"


def test_json_carries_details_as_the_fourth_key_on_one_line() -> None:
    result = _run(with_cli_details(_DemoError("실패"), _DETAILS, _LINES), "json")

    assert (result.exit_code, result.stderr) == (1, "")
    assert result.stdout.count("\n") == 1
    assert list(json.loads(result.stdout)) == ["status", "code", "message", "details"]
    assert json.loads(result.stdout) == {
        "status": "error",
        "code": "DEMO_ERROR",
        "message": "실패",
        "details": _DETAILS,
    }


def test_text_detail_lines_follow_the_error_line_on_stderr() -> None:
    result = _run(with_cli_details(_DemoError("실패"), _DETAILS, _LINES), "text")

    assert (result.exit_code, result.stdout) == (1, "")
    assert result.stderr == (
        "Error: DEMO_ERROR: 실패\n  - 금지된 import: os\n  - on_step 누락\n"
    )


def test_lines_without_details_change_text_only() -> None:
    exc = with_cli_details(_DemoError("실패"), None, _LINES)

    assert json.loads(_run(exc, "json").stdout) == {
        "status": "error",
        "code": "DEMO_ERROR",
        "message": "실패",
    }
    assert _run(exc, "text").stderr.splitlines()[1:] == list(_LINES)


def test_formatter_error_none_and_empty_details() -> None:
    runner = CliRunner(mix_stderr=False)

    def _emit(details: dict[str, object] | None) -> str:
        @click.command()
        def _cmd() -> None:
            OutputFormatter("json").error("m", code="C", details=details)

        return runner.invoke(_cmd).stdout

    assert _emit(None) == '{"status": "error", "code": "C", "message": "m"}\n'
    assert _emit({}) == (
        '{"status": "error", "code": "C", "message": "m", "details": {}}\n'
    )


@pytest.mark.parametrize(
    "details",
    [
        {"path": Path("strat.py")},
        {"error": ValueError("x")},
        {"errors": [Path("a")]},
        {1: "x"},
        {"nested": {"k": object()}},
    ],
    ids=["path", "exception", "path_in_list", "int_key", "nested_object"],
)
def test_helper_rejects_values_that_json_cannot_serialize(details: Any) -> None:
    with pytest.raises(TypeError):
        with_cli_details(_DemoError("x"), details)


def test_helper_rejects_empty_details_and_non_str_lines() -> None:
    with pytest.raises(ValueError):
        with_cli_details(_DemoError("x"), {})
    bad_lines: Any = (1,)
    with pytest.raises(TypeError):
        with_cli_details(_DemoError("x"), None, bad_lines)


def test_helper_returns_the_same_exception_with_both_attributes() -> None:
    exc = _DemoError("x")
    assert with_cli_details(exc, {"stage": "load"}) is exc
    assert getattr(exc, "cli_details") == {"stage": "load"}
    assert getattr(exc, "cli_detail_lines") == ()
