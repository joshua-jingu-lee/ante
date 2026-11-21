"""``tests/preservation_recorder.py``: 환경변수가 있을 때만 호출마다 한 행 (#2664).

플러그인은 하위 pytest에 ``-p``로 싣고, 대상은 임시 디렉터리의 작은 테스트다.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_TARGET = """\
import click
from click.testing import CliRunner


@click.command()
@click.argument("name")
def hello(name):
    if name == "bad":
        click.echo("Error: bad", err=True)
        raise SystemExit(1)
    click.echo(f"hi {name}")


def test_calls():
    CliRunner(mix_stderr=False).invoke(hello, ["ok"])
    CliRunner(mix_stderr=False).invoke(hello, ["bad"])
    CliRunner().invoke(hello, "bad")


def test_invoke_owner():
    print(f"INVOKE_MODULE={CliRunner.invoke.__module__}")
"""


_RERUN_CONFTEST = """\
import pytest
from _pytest.runner import runtestprotocol


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if item.name != "test_calls":
        return None
    item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    runtestprotocol(item, nextitem=nextitem, log=False)
    runtestprotocol(item, nextitem=nextitem)
    item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
"""


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _run(
    tmp_path: Path, record: str | None, *, rerun: bool = False
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    if rerun:
        (tmp_path / "conftest.py").write_text(_RERUN_CONFTEST, encoding="utf-8")
    (tmp_path / "test_target.py").write_text(_TARGET, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "ANTE_PRESERVATION_RECORD"}
    if record is not None:
        env["ANTE_PRESERVATION_RECORD"] = record
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), env.get("PYTHONPATH")) if p
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-s",
            "-p",
            "no:cacheprovider",
            "-p",
            "tests.preservation_recorder",
            "--rootdir",
            str(tmp_path),
            "-c",
            str(tmp_path / "pytest.ini"),
            str(tmp_path / "test_target.py"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_writes_one_row_per_call_including_failures(tmp_path: Path) -> None:
    record = tmp_path / "out" / "rec.jsonl"
    record.parent.mkdir()
    result = _run(tmp_path, str(record))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INVOKE_MODULE=tests.preservation_recorder\n" in result.stdout
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    nodeid = "test_target.py::test_calls"
    assert rows == [
        {
            "nodeid": nodeid,
            "n": 0,
            "args": ["ok"],
            "exit": 0,
            "stdout": _b64("hi ok\n"),
            "stderr": _b64(""),
            "raised": None,
        },
        {
            "nodeid": nodeid,
            "n": 1,
            "args": ["bad"],
            "exit": 1,
            "stdout": _b64(""),
            "stderr": _b64("Error: bad\n"),
            "raised": None,
        },
        {
            "nodeid": nodeid,
            "n": 2,
            "args": "bad",
            "exit": 1,
            "stdout": _b64("Error: bad\n"),
            "stderr": None,
            "raised": None,
        },
    ]


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_writes_nothing_without_the_variable(tmp_path: Path, value: str | None) -> None:
    out = tmp_path / "out"
    out.mkdir()
    result = _run(tmp_path, value)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INVOKE_MODULE=click.testing\n" in result.stdout
    assert list(out.iterdir()) == []


def test_sequence_restarts_when_a_test_runs_again(tmp_path: Path) -> None:
    record = tmp_path / "out" / "rec.jsonl"
    record.parent.mkdir()
    result = _run(tmp_path, str(record), rerun=True)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [json.loads(line) for line in record.read_text().splitlines()]
    assert [(r["nodeid"], r["n"]) for r in rows] == [
        ("test_target.py::test_calls", n) for n in (0, 1, 2, 0, 1, 2)
    ]
