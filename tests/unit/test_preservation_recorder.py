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


_PATH_TARGET = """\
import os

import click
from click.testing import CliRunner


@click.command()
@click.argument("where")
def show(where):
    click.echo(where)
    click.echo(f"other {os.environ['OTHER_PATH']}", err=True)


def test_paths(tmp_path):
    CliRunner(mix_stderr=False).invoke(show, [os.environ.get("HOME", "nohome") + "/db"])
    CliRunner(mix_stderr=False).invoke(show, [str(tmp_path / "x")])
"""


def _run_paths(tmp_path: Path, env_over: dict[str, str | None]) -> list[dict]:
    record = tmp_path / "rec.jsonl"
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_target.py").write_text(_PATH_TARGET, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "ANTE_CONFIG_DIR"}
    env["ANTE_PRESERVATION_RECORD"] = str(record)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), env.get("PYTHONPATH")) if p
    )
    for key, value in env_over.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "tests.preservation_recorder",
            "--rootdir",
            str(tmp_path),
            "-c",
            str(tmp_path / "pytest.ini"),
            "--basetemp",
            str(tmp_path / "bt"),
            str(tmp_path / "test_target.py"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line) for line in record.read_text().splitlines()]


def _decoded(row: dict, field: str) -> str:
    return base64.b64decode(row[field]).decode()


def test_env_paths_are_recorded_as_placeholders(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    rows = _run_paths(
        tmp_path, {"HOME": str(tmp_path / "home"), "OTHER_PATH": str(other)}
    )
    assert rows[0]["args"] == ["<HOME>/db"]
    assert _decoded(rows[0], "stdout") == "<HOME>/db\n"
    assert _decoded(rows[0], "stderr") == f"other {other}\n"
    assert rows[1]["args"] == ["<TMP>/test_paths0/x"]
    assert _decoded(rows[1], "stdout") == "<TMP>/test_paths0/x\n"


def test_config_dir_is_replaced_before_the_shorter_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    rows = _run_paths(
        tmp_path,
        {
            "HOME": str(home),
            "ANTE_CONFIG_DIR": str(home / "db"),
            "OTHER_PATH": "/nowhere",
        },
    )
    assert rows[0]["args"] == ["<ANTE_CONFIG_DIR>"]
    assert _decoded(rows[0], "stdout") == "<ANTE_CONFIG_DIR>\n"


def test_unset_env_path_is_not_replaced(tmp_path: Path) -> None:
    rows = _run_paths(tmp_path, {"HOME": None, "OTHER_PATH": "/nowhere"})
    assert rows[0]["args"] == ["nohome/db"]
    assert _decoded(rows[0], "stdout") == "nohome/db\n"
    assert _decoded(rows[0], "stderr") == "other /nowhere\n"
