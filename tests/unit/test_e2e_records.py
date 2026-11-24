"""e2e 하네스의 실행 기록(#2823): 무엇을 남기고 무엇을 남기지 않는가."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.e2e import harness
from tests.e2e.harness import DaemonHarness, run_json_command

pytest_plugins = ["pytester"]

REPO_ROOT = Path(__file__).resolve().parents[2]
STRATEGY = REPO_ROOT / "tests" / "e2e" / "strategies" / "round_trip.py"
STDOUT_MARKER = "MARKE2E-STDOUT-0001"
STDERR_MARKER = "MARKE2E-STDERR-0002"
TOKEN = "ante_ak_MARKE2E_TOKEN_0003"
NODEID = "tests/e2e/test_virtual_round_trip.py::test_y"
STRATEGY_REL = "tests/e2e/strategies/round_trip.py"
TOKEN_FIRST = "ante_ak_MARKE2E_FIRST_0005"
SECRET_VALUE = "MARKE2E_SECRET_0006"

_FAKE_DAEMON = """
    import os, pathlib, sys, time
    run = pathlib.Path(sys.argv[1])
    (run / "ante.pid").write_text(str(os.getpid()))
    (run / "ante.sock").write_text("")
    while not (run / "stop").exists():
        time.sleep(0.02)
    for name in ("stop", "ante.sock", "ante.pid"):
        (run / name).unlink()
"""

_FAKE_CLI = f"""
import json, pathlib, sys
run = pathlib.Path(sys.argv[1])
args = sys.argv[2:]
if args == ["system", "stop"]:
    (run / "stop").touch()
print("{STDERR_MARKER}", file=sys.stderr)
failed = args[:1] == ["fail"]
print(json.dumps({{
    "status": "error" if failed else "ok",
    "code": "E2E_FAKE" if failed else None,
    "message": "{STDOUT_MARKER}",
    "data": {{"echo": args}},
}}))
sys.exit(1 if failed else 0)
"""


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _only_record(record_dir: Path) -> dict[str, Any]:
    (path,) = sorted(record_dir.glob("*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def record_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "records"
    monkeypatch.setenv(harness.RECORD_DIR_ENV, str(path))
    return path


@pytest.fixture
def fake(record_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[DaemonHarness]:
    """``system start``는 가짜 데몬, 나머지 CLI는 가짜 CLI 파일로 바꾼 하네스."""
    env = DaemonHarness.create()
    run_dir = env.socket_path.parent
    run_dir.mkdir()
    daemon_script = env.root / "fake_daemon.py"
    daemon_script.write_text(textwrap.dedent(_FAKE_DAEMON), encoding="utf-8")
    cli_script = env.root / "fake_cli.py"
    cli_script.write_text(_FAKE_CLI, encoding="utf-8")
    env.token = TOKEN

    def _argv(*args: str) -> list[str]:
        if args == ("system", "start"):
            return [sys.executable, str(daemon_script), str(run_dir)]
        return [sys.executable, str(cli_script), str(run_dir), *args]

    monkeypatch.setattr(env, "cli_argv", _argv)
    try:
        yield env
    finally:
        env.cleanup()


@pytest.fixture
def restore_alarm() -> Iterator[None]:
    previous = signal.getsignal(signal.SIGALRM)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _save(env: DaemonHarness, outcome: str = "passed") -> None:
    harness.save_record(env, NODEID, outcome, 1.5)


class TestRecordContent:
    def test_start_and_two_calls_are_recorded_in_order(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        fake.cli("account", "list")
        fake.start()
        fake.cli("fail", "now", expect_failure=True)
        assert fake.stop() == 0
        fake.cleanup()
        _save(fake)
        record = _only_record(record_dir)
        assert record["version"] == harness.RECORD_VERSION
        assert record["nodeid"] == NODEID
        assert record["outcome"] == "passed"
        assert record["seconds"] == 1.5
        assert record["net_attempts"] == 0
        steps = record["steps"]
        assert [s["kind"] for s in steps] == ["cli", "start", "cli", "cli", "cli"]
        assert steps[0]["args"][-2:] == ["account", "list"]
        assert steps[0]["returncode"] == 0
        assert (steps[0]["status"], steps[0]["code"]) == ("ok", None)
        assert isinstance(steps[1]["ready_seconds"], float)
        assert steps[1]["ok"] is True
        assert steps[2]["args"][-2:] == ["bot", "list"]
        assert steps[3]["args"][-2:] == ["fail", "now"]
        assert (steps[3]["returncode"], steps[3]["status"]) == (1, "error")
        assert steps[3]["code"] == "E2E_FAKE"
        assert steps[3]["failed"] is True
        assert steps[3]["expect_failure"] is True
        assert steps[4]["args"][-2:] == ["system", "stop"]

    def test_root_path_becomes_placeholder(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        fake.cli("bot", "list")
        _save(fake)
        (step,) = _only_record(record_dir)["steps"]
        assert step["args"] == [
            "<root>/fake_cli.py",
            "<root>/config/run",
            "bot",
            "list",
        ]

    def test_output_text_is_not_recorded(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        fake.cli("bot", "list")
        fake.cli("fail", expect_failure=True)
        _save(fake)
        text = next(record_dir.glob("*.json")).read_text(encoding="utf-8")
        assert STDOUT_MARKER not in text
        assert STDERR_MARKER not in text
        assert "message" not in text
        assert "echo" not in text

    def test_no_string_starts_with_slash(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        recorder = fake.recorder
        assert recorder is not None
        real = DaemonHarness.cli_argv(fake, "strategy", "submit", str(STRATEGY))
        recorder.record_cli(real, 0, {"status": "ok"}, 0.1, expect_failure=False)
        recorder.record_cli(
            [sys.executable, "/elsewhere/x.py", f"--path={REPO_ROOT}/a", "/etc"],
            0,
            None,
            0.1,
            expect_failure=False,
        )
        fake.cli("bot", "list")
        _save(fake)
        record = _only_record(record_dir)
        assert record["steps"][0]["args"] == [
            "strategy",
            "submit",
            "tests/e2e/strategies/round_trip.py",
        ]
        assert record["steps"][1]["args"] == ["<redacted>", "--path=a", "<redacted>"]
        leaked = [s for s in _strings(record) if s.startswith("/")]
        assert leaked == []
        assert sys.executable not in json.dumps(record)

    def test_direct_run_json_command_is_recorded(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        result = run_json_command(
            fake.cli_argv("bot", "start", "nope"),
            env=fake.env(),
            cwd=fake.work_dir,
        )
        assert result.returncode == 0
        _save(fake)
        (step,) = _only_record(record_dir)["steps"]
        assert step["args"][-3:] == ["bot", "start", "nope"]

    def test_repeated_identical_calls_fold(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        for _ in range(3):
            fake.cli("treasury", "transactions")
        fake.cli("bot", "list")
        fake.cli("treasury", "transactions")
        _save(fake)
        steps = _only_record(record_dir)["steps"]
        assert [(s["args"][-1], s["count"]) for s in steps] == [
            ("transactions", 3),
            ("list", 1),
            ("transactions", 1),
        ]
        assert steps[0]["seconds"] > 0


class TestRecordGuards:
    def test_no_file_without_variable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(harness.RECORD_DIR_ENV, raising=False)
        monkeypatch.chdir(tmp_path)
        env = DaemonHarness.create()
        try:
            assert env.recorder is None
            run_json_command(
                [sys.executable, "-c", "print('{}')"],
                env=env.env(),
                cwd=env.work_dir,
            )
        finally:
            env.cleanup()
        harness.save_record(env, NODEID, "passed", 1.0)
        assert list(tmp_path.rglob("*.json")) == []

    def test_token_in_record_drops_file_and_warns(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        fake.cli("member", "show", TOKEN)
        with pytest.warns(harness.RecordWarning, match="토큰"):
            _save(fake)
        assert list(record_dir.glob("*.json")) == []

    def test_write_error_only_warns(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        record_dir.parent.mkdir(exist_ok=True)
        record_dir.write_text("not a directory")
        fake.cli("bot", "list")
        with pytest.warns(harness.RecordWarning):
            _save(fake)

    def test_file_name_is_safe(self) -> None:
        name = harness.record_file_name("tests/e2e/test_a.py::test_b[x/../y]")
        assert name.endswith(".json")
        assert "/" not in name
        assert name != harness.record_file_name("tests/e2e/test_a.py::test_b[x]")


def _args(env: DaemonHarness, *args: str) -> list[str]:
    assert env.recorder is not None
    return env.recorder.command_args([sys.executable, *args])


class TestPathAllowList:
    """``/``·``\\``가 든 문자열은 허용 모양일 때만 실린다(#2823 리뷰)."""

    @pytest.mark.parametrize(
        "value",
        [
            '{"path":"/Users/x"}',
            "-I/usr/include",
            "t[/home/u/x]",
            "'/opt/x'",
            '"/opt/x"',
            "(/opt/x)",
            "[/opt/x]",
            "~/x",
            "../tmp/x",
            "C:\\Users\\x",
            "a\\b",
            "a/b",
            "key=/abs",
            "/etc",
            "tests/e2e/../e2e/strategies/round_trip.py",
            "tests/e2e/strategies/no_such.py",
        ],
    )
    def test_disallowed_shapes_are_redacted(
        self, fake: DaemonHarness, value: str
    ) -> None:
        assert _args(fake, value) == ["<redacted>"]
        assert not harness.is_allowed_string(value)

    def test_allowed_shapes_are_kept(self, fake: DaemonHarness) -> None:
        root = str(fake.root)
        assert _args(
            fake,
            STRATEGY_REL,
            str(REPO_ROOT / STRATEGY_REL),
            f"key={REPO_ROOT / STRATEGY_REL}",
            f"prices_file={root}/prices.json",
            f"{root}/config/run",
            "plain",
            "max_position_amount=35000",
        ) == [
            STRATEGY_REL,
            STRATEGY_REL,
            f"key={STRATEGY_REL}",
            "prices_file=<root>/prices.json",
            "<root>/config/run",
            "plain",
            "max_position_amount=35000",
        ]

    def test_temp_path_given_relative_is_redacted(self, fake: DaemonHarness) -> None:
        rel = os.path.relpath(fake.root / "x", REPO_ROOT)
        assert rel.startswith("..")
        assert _args(fake, rel) == ["<redacted>"]

    @pytest.mark.parametrize(
        ("nodeid", "expected"),
        [
            (NODEID, NODEID),
            ("test_inner.py::test_a", "test_inner.py::test_a"),
            (f"{NODEID}[/home/u/x]", f"{NODEID}[<redacted>]"),
            (f"{NODEID}[a-C:\\x]", f"{NODEID}[<redacted>]"),
            ("tests/e2e/no_such.py::test_a", "<redacted>::test_a"),
            ("/abs/test_a.py::test_a", "<redacted>::test_a"),
        ],
    )
    def test_nodeid(self, nodeid: str, expected: str) -> None:
        assert harness.sanitize_nodeid(nodeid) == expected
        assert harness.is_allowed_string(expected)

    def test_file_name_comes_from_sanitized_nodeid(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        fake.cli("bot", "list")
        harness.save_record(fake, f"{NODEID}[/home/u/secretdir]", "passed", 1.0)
        (path,) = record_dir.glob("*.json")
        assert "home" not in path.name
        assert "secretdir" not in path.name
        assert "secretdir" not in path.read_text(encoding="utf-8")

    def test_guard_blocks_without_sanitizer(self) -> None:
        """방어선에 직접 넣는다: 치환기에 구멍이 있어도 방어선이 막는다."""
        bad = [
            '{"path":"/Users/x"}',
            "-I/usr/include",
            "t[/home/u/x]",
            "a/b",
            "~/x",
            "C:\\x",
        ]
        for value in bad:
            for record in (
                {"steps": [{"args": [value]}]},
                {value: 1},
                {"nodeid": value},
                [[{"k": value}]],
            ):
                assert harness.disallowed_strings(record) == [value]
        good = {
            "nodeid": NODEID,
            "steps": [{"args": [STRATEGY_REL, "<root>/a.json", "k=<root>/b"]}],
        }
        assert harness.disallowed_strings(good) == []

    def test_guard_drops_record_with_unallowed_string(
        self, fake: DaemonHarness, record_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert fake.recorder is not None
        monkeypatch.setattr(fake.recorder, "sanitize", lambda value: value)
        fake.recorder.record_cli(
            [sys.executable, "-I/usr/include"], 0, None, 0.1, expect_failure=False
        )
        with pytest.warns(harness.RecordWarning, match="허용"):
            _save(fake)
        assert list(record_dir.glob("*.json")) == []

    def test_every_token_is_checked(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        assert fake.recorder is not None
        fake.recorder.record_cli(
            [sys.executable, "-m", "ante", "--format", "json", "init"],
            0,
            {"token": TOKEN_FIRST},
            0.1,
            expect_failure=False,
        )
        fake.recorder.record_cli(
            [sys.executable, "-m", "ante", "--format", "json", "init"],
            0,
            {"data": {"member": {"token": TOKEN}}},
            0.1,
            expect_failure=False,
        )
        fake.token = TOKEN
        fake.cli("member", "show", TOKEN_FIRST)
        with pytest.warns(harness.RecordWarning, match="토큰"):
            _save(fake)
        assert list(record_dir.glob("*.json")) == []

    @pytest.mark.parametrize(
        "payload",
        [
            {"recovery_key": SECRET_VALUE},
            {"data": {"app_secret": SECRET_VALUE}},
            {"api_key": [SECRET_VALUE]},
        ],
        ids=["key-suffix", "secret-suffix", "list-under-secret-key"],
    )
    def test_secret_shaped_keys_are_checked(
        self, fake: DaemonHarness, record_dir: Path, payload: dict[str, Any]
    ) -> None:
        assert fake.recorder is not None
        fake.recorder.record_cli(
            [sys.executable, "-m", "ante", "--format", "json", "init"],
            0,
            payload,
            0.1,
            expect_failure=False,
        )
        fake.cli("member", "show", SECRET_VALUE)
        with pytest.warns(harness.RecordWarning, match="토큰"):
            _save(fake)
        assert list(record_dir.glob("*.json")) == []

    def test_non_secret_key_is_not_collected(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        assert fake.recorder is not None
        fake.recorder.record_cli(
            [sys.executable, "-m", "ante", "--format", "json", "init"],
            0,
            {"data": {"key_name": SECRET_VALUE, "monkey": [SECRET_VALUE]}},
            0.1,
            expect_failure=False,
        )
        fake.cli("member", "show", SECRET_VALUE)
        _save(fake)
        record = _only_record(record_dir)
        assert len(record["steps"]) == 2
        assert SECRET_VALUE in json.dumps(record)


class TestCallJudgement:
    def test_exit_zero_non_json_is_failed(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        with pytest.raises(harness.CliCallError):
            run_json_command(
                [sys.executable, "-c", "print('not json')"],
                env=fake.env(),
                cwd=fake.work_dir,
            )
        _save(fake)
        (step,) = _only_record(record_dir)["steps"]
        assert (step["returncode"], step["failed"]) == (0, True)

    def test_timeout_and_oserror_are_recorded(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        with pytest.raises(subprocess.TimeoutExpired):
            run_json_command(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                env=fake.env(),
                cwd=fake.work_dir,
                timeout=0.3,
            )
        with pytest.raises(OSError):
            run_json_command(
                [str(fake.root / "no-such-binary")],
                env=fake.env(),
                cwd=fake.work_dir,
            )
        _save(fake)
        steps = _only_record(record_dir)["steps"]
        assert [(s["returncode"], s["failed"]) for s in steps] == [
            (None, True),
            (None, True),
        ]

    def test_test_time_limit_is_recorded(
        self, fake: DaemonHarness, record_dir: Path, restore_alarm: None
    ) -> None:
        previous = signal.getsignal(signal.SIGALRM)
        with pytest.raises(harness.E2ETimeoutError), harness.time_limit(0.3):
            run_json_command(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                env=fake.env(),
                cwd=fake.work_dir,
            )
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
        assert signal.getsignal(signal.SIGALRM) is previous
        _save(fake)
        steps = _only_record(record_dir)["steps"]
        assert [(s["returncode"], s["failed"]) for s in steps] == [(None, True)]

    def test_fold_key_includes_expect_failure(
        self, fake: DaemonHarness, record_dir: Path
    ) -> None:
        assert fake.recorder is not None
        argv = [sys.executable, "-m", "ante", "--format", "json", "bot", "list"]
        payload = {"status": "error", "code": "X"}
        fake.recorder.record_cli(argv, 1, payload, 0.1, expect_failure=False)
        fake.recorder.record_cli(argv, 1, payload, 0.1, expect_failure=True)
        _save(fake)
        steps = _only_record(record_dir)["steps"]
        assert [s["expect_failure"] for s in steps] == [False, True]


INNER_ARGS = ("-p", "no:cacheprovider", "-p", "no:asyncio")
_INNER_CONFTEST = "from tests.e2e.conftest import *  # noqa: F403\n"

_INNER_TEST = """
import sys
from tests.e2e.harness import run_json_command


def _call(daemon):
    run_json_command(
        [sys.executable, "-c", "print('{\\"status\\": \\"ok\\"}')"],
        env=daemon.env(),
        cwd=daemon.work_dir,
    )


def test_passes(daemon):
    _call(daemon)


def test_fails(daemon):
    _call(daemon)
    assert False, "MARKE2E-ASSERT-0004"
"""


_CLEANUP_MARKER = "MARKE2E-CLEANUP-0007"

_INNER_CLEANUP_FAILS = f"""
import pytest


@pytest.fixture(autouse=True)
def _failing_cleanup(monkeypatch, daemon):
    original = daemon.cleanup

    def _cleanup():
        original()
        raise RuntimeError("{_CLEANUP_MARKER}")

    monkeypatch.setattr(daemon, "cleanup", _cleanup)
"""


class TestScenarioOutcome:
    def test_cleanup_failure_is_recorded_as_failed(
        self, pytester: pytest.Pytester, record_dir: Path
    ) -> None:
        pytester.makeconftest(_INNER_CONFTEST + _INNER_CLEANUP_FAILS)
        pytester.makepyfile(test_inner=_INNER_TEST)
        result = pytester.runpytest_inprocess(*INNER_ARGS)
        result.assert_outcomes(passed=1, failed=1, errors=2)
        records = {
            r["nodeid"]: r
            for r in (
                json.loads(p.read_text(encoding="utf-8"))
                for p in record_dir.glob("*.json")
            )
        }
        assert records["test_inner.py::test_passes"]["outcome"] == "failed"
        assert records["test_inner.py::test_fails"]["outcome"] == "failed"
        for path in record_dir.glob("*.json"):
            assert _CLEANUP_MARKER not in path.read_text(encoding="utf-8")

    def test_failed_scenario_is_recorded_as_failed(
        self, pytester: pytest.Pytester, record_dir: Path
    ) -> None:
        pytester.makeconftest(_INNER_CONFTEST)
        pytester.makepyfile(test_inner=_INNER_TEST)
        result = pytester.runpytest_inprocess(*INNER_ARGS)
        result.assert_outcomes(passed=1, failed=1)
        records = {
            r["nodeid"]: r
            for r in (
                json.loads(p.read_text(encoding="utf-8"))
                for p in record_dir.glob("*.json")
            )
        }
        assert records["test_inner.py::test_passes"]["outcome"] == "passed"
        assert records["test_inner.py::test_fails"]["outcome"] == "failed"
        assert len(records["test_inner.py::test_fails"]["steps"]) == 1
        for path in record_dir.glob("*.json"):
            assert "MARKE2E-ASSERT-0004" not in path.read_text(encoding="utf-8")

    def test_write_failure_keeps_outcome(
        self, pytester: pytest.Pytester, record_dir: Path
    ) -> None:
        record_dir.parent.mkdir(exist_ok=True)
        record_dir.write_text("not a directory")
        pytester.makeconftest(_INNER_CONFTEST)
        pytester.makepyfile(test_inner=_INNER_TEST)
        result = pytester.runpytest_inprocess(*INNER_ARGS)
        outcomes = result.parseoutcomes()
        assert outcomes.get("passed") == 1
        assert outcomes.get("failed") == 1
        assert "errors" not in outcomes
        result.stdout.fnmatch_lines(["*RecordWarning*쓰지 못했다*"])
