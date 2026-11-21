"""보존 표의 기록기 (#2664).

환경변수 ``ANTE_PRESERVATION_RECORD``가 없으면 아무것도 하지 않는다. 있으면
``click.testing.CliRunner.invoke``를 감싸 호출마다 한 행을 그 경로에 JSON
Lines로 덧붙인다. 단언보다 먼저 쓰므로 기대값을 고친 테스트도 기록된다.

행: ``nodeid``, ``n``(테스트 안의 호출 순번, 0부터), ``args``, ``exit``,
``stdout``·``stderr``(base64. stderr를 따로 잡지 않는 호출은 ``null``),
``raised``(``invoke``가 예외를 내보냈으면 그 타입 이름).

``coverage run``으로 돌리면 호출마다 동적 문맥을 ``<nodeid>#<n>``으로 바꾼다.
순번은 테스트가 시작할 때마다 0이다. 같은 테스트가 다시 돌면(재실행 플러그인
등) 같은 키의 행이 두 번 쓰이고 비교 스크립트가 입력 오류로 멈춘다.
비교는 ``scripts/compare_error_exit_records.py``가 한다. xdist로 돌리지 않는다.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

ENV_VAR = "ANTE_PRESERVATION_RECORD"

_current: dict[str, Any] = {"nodeid": "?", "counts": {}}


def _b64(data: bytes | None) -> str | None:
    return None if data is None else base64.b64encode(data).decode("ascii")


def _coverage() -> Any:
    try:
        import coverage
    except ImportError:
        return None
    return coverage.Coverage.current()


def _install(out: Path) -> None:
    original = CliRunner.invoke

    def invoke(self: CliRunner, cli: Any, args: Any = None, *a: Any, **k: Any) -> Any:
        nodeid = _current["nodeid"]
        n = _current["counts"].get(nodeid, 0)
        _current["counts"][nodeid] = n + 1
        row: dict[str, Any] = {
            "nodeid": nodeid,
            "n": n,
            "args": args if isinstance(args, str) else [str(x) for x in args or ()],
            "exit": None,
            "stdout": None,
            "stderr": None,
            "raised": None,
        }
        cov = _coverage()
        if cov is not None:
            cov.switch_context(f"{nodeid}#{n}")
        try:
            result = original(self, cli, args, *a, **k)
        except BaseException as exc:
            row["raised"] = type(exc).__name__
            _write(out, row)
            raise
        finally:
            if cov is not None:
                cov.switch_context("")
        row["exit"] = result.exit_code
        row["stdout"] = _b64(result.stdout_bytes)
        row["stderr"] = _b64(result.stderr_bytes)
        _write(out, row)
        return result

    CliRunner.invoke = invoke


def _write(out: Path, row: dict[str, Any]) -> None:
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def pytest_configure(config: pytest.Config) -> None:
    out = os.environ.get(ENV_VAR)
    if out:
        _install(Path(out))


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    _current["counts"][item.nodeid] = 0


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: object) -> Iterator[None]:
    _current["nodeid"] = item.nodeid
    try:
        return (yield)
    finally:
        _current["nodeid"] = "?"
