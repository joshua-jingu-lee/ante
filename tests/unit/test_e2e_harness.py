"""e2e 하네스의 자기 검사: 제한 시간, 정리, CLI 판정, 네트워크 가드, 세션 판정."""

from __future__ import annotations

import ast
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.e2e import harness
from tests.e2e.harness import (
    CliCallError,
    DaemonHarness,
    E2ETimeoutError,
    group_alive,
    report_outcome,
    run_json_command,
    session_failure_reason,
    terminate_process_group,
    time_limit,
)

Spawn = Callable[[str], subprocess.Popen[str]]


@pytest.fixture
def restore_alarm() -> Iterator[None]:
    previous = signal.getsignal(signal.SIGALRM)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.fixture
def spawn() -> Iterator[Spawn]:
    """새 세션에서 파이썬 코드를 띄우고 ``ready`` 줄을 기다린다. 남은 그룹은 끝낸다."""
    procs: list[subprocess.Popen[str]] = []

    def _spawn(code: str) -> subprocess.Popen[str]:
        proc = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(code)],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        procs.append(proc)
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        return proc

    yield _spawn
    for proc in procs:
        if group_alive(proc.pid):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
        if proc.stdout is not None:
            proc.stdout.close()


_SLEEPER = """
    import time
    print("ready", flush=True)
    time.sleep(60)
"""

_SLOW_ON_SIGTERM = """
    import signal, sys, time
    signal.signal(signal.SIGTERM, lambda *_: (time.sleep(0.6), sys.exit(0)))
    print("ready", flush=True)
    time.sleep(60)
"""

_PARENT_WITH_STUBBORN_CHILD = """
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "print('ready', flush=True); time.sleep(60)"
    )], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "ready"
    print("ready", flush=True)
    time.sleep(60)
"""


class TestTimeLimit:
    def test_fires_at_deadline_and_disarms(self, restore_alarm: None) -> None:
        previous = signal.getsignal(signal.SIGALRM)
        started = time.monotonic()
        with pytest.raises(E2ETimeoutError), time_limit(0.2):
            time.sleep(5)
        assert time.monotonic() - started < 2
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
        assert signal.getsignal(signal.SIGALRM) is previous

    def test_disarms_on_normal_exit(self, restore_alarm: None) -> None:
        with time_limit(30):
            pass
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)

    def test_cleanup_runs_after_timeout(
        self, restore_alarm: None, spawn: Spawn
    ) -> None:
        env = DaemonHarness.create()
        env.proc = spawn(_SLEEPER)
        pgid = env.proc.pid
        with pytest.raises(E2ETimeoutError):
            try:
                with time_limit(0.3):
                    env.proc.wait()
            finally:
                env.cleanup()
        assert not group_alive(pgid)
        assert not env.root.exists()

    def test_cleanup_is_not_cut_by_a_pending_timer(
        self, restore_alarm: None, spawn: Spawn
    ) -> None:
        env = DaemonHarness.create()
        env.proc = spawn(_SLOW_ON_SIGTERM)
        pgid = env.proc.pid

        def _raise(signum: int, frame: object) -> None:
            raise E2ETimeoutError("timer leaked into cleanup")

        signal.signal(signal.SIGALRM, _raise)
        signal.setitimer(signal.ITIMER_REAL, 0.1)
        env.cleanup()
        time.sleep(0.2)
        assert not group_alive(pgid)
        assert not env.root.exists()


class TestTerminateProcessGroup:
    def test_empty_group(self, spawn: Spawn) -> None:
        proc = spawn(_SLEEPER)
        proc.kill()
        proc.wait()
        assert terminate_process_group(proc.pid, reap=proc.poll) == "gone"

    def test_sigterm_is_enough(self, spawn: Spawn) -> None:
        proc = spawn(_SLEEPER)
        assert terminate_process_group(proc.pid, reap=proc.poll) == "sigterm"
        assert not group_alive(proc.pid)

    def test_group_ignoring_sigterm_gets_sigkill(self, spawn: Spawn) -> None:
        proc = spawn(_PARENT_WITH_STUBBORN_CHILD)
        used = terminate_process_group(proc.pid, reap=proc.poll, term_seconds=0.5)
        assert used == "sigkill"
        assert not group_alive(proc.pid)
        assert proc.returncode == -signal.SIGTERM

    def test_unreaped_zombie_keeps_group_until_reaped(self, spawn: Spawn) -> None:
        proc = spawn(_SLEEPER)
        os.kill(proc.pid, signal.SIGKILL)
        time.sleep(0.3)
        assert group_alive(proc.pid)
        assert terminate_process_group(proc.pid, reap=proc.poll) == "gone"
        assert proc.returncode == -signal.SIGKILL
        assert not group_alive(proc.pid)


def _emit(tmp_path: Path, payload: object, code: int, **kwargs: bool) -> object:
    script = f"import sys; print({json.dumps(json.dumps(payload))}); sys.exit({code})"
    return run_json_command(
        [sys.executable, "-c", script],
        env={"PATH": os.environ.get("PATH", "")},
        cwd=tmp_path,
        **kwargs,
    )


class TestRunJsonCommand:
    def test_exit_zero_with_status_error_fails(self, tmp_path: Path) -> None:
        with pytest.raises(CliCallError, match="returncode: 0"):
            _emit(tmp_path, {"status": "error", "code": "X"}, 0)

    def test_exit_one_without_status_fails(self, tmp_path: Path) -> None:
        with pytest.raises(CliCallError, match="returncode: 1"):
            _emit(tmp_path, {"submitted": False}, 1)

    def test_exit_zero_without_status_passes(self, tmp_path: Path) -> None:
        result = _emit(tmp_path, {"token": "t"}, 0)
        assert isinstance(result, harness.CliResult)
        assert result.payload == {"token": "t"}

    def test_exit_zero_with_status_ok_passes(self, tmp_path: Path) -> None:
        result = _emit(tmp_path, {"status": "ok", "data": {}}, 0)
        assert isinstance(result, harness.CliResult)
        assert result.failed is False

    def test_expected_failure(self, tmp_path: Path) -> None:
        result = _emit(tmp_path, {"submitted": False}, 1, expect_failure=True)
        assert isinstance(result, harness.CliResult)
        assert result.returncode == 1
        with pytest.raises(CliCallError, match="실패가 기대됐지만"):
            _emit(tmp_path, {"token": "t"}, 0, expect_failure=True)

    def test_non_json_stdout_fails(self, tmp_path: Path) -> None:
        with pytest.raises(CliCallError, match="JSON"):
            run_json_command(
                [sys.executable, "-c", "print('not json')"],
                env={"PATH": os.environ.get("PATH", "")},
                cwd=tmp_path,
            )


_GUARD_PROBE = """
    import os, socket, tempfile
    print(os.getpid())
    for attempt in (
        lambda: socket.create_connection(("127.0.0.1", 9), timeout=1),
        lambda: socket.socket(socket.AF_INET).connect(("127.0.0.1", 9)),
        lambda: socket.getaddrinfo("example.invalid", 443),
    ):
        try:
            attempt()
        except OSError as exc:
            print("blocked", "netguard" in str(exc))
        else:
            print("allowed")
    d = tempfile.mkdtemp(dir="/tmp")
    path = os.path.join(d, "s")
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(1)
    client = socket.socket(socket.AF_UNIX)
    client.connect(path)
    print("unix ok")
    client.close(); server.close(); os.unlink(path); os.rmdir(d)
"""


def test_netguard_blocks_and_records_inet(tmp_path: Path) -> None:
    log = tmp_path / "net.jsonl"
    marker = tmp_path / "pids"
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_GUARD_PROBE)],
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(harness.NETGUARD_DIR),
            "PYTHONDONTWRITEBYTECODE": "1",
            harness.NETGUARD_LOG_ENV: str(log),
            harness.NETGUARD_MARKER_ENV: str(marker),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    pid, *results = proc.stdout.split("\n")
    assert results[:4] == ["blocked True"] * 3 + ["unix ok"]
    assert marker.read_text().split() == [pid]
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["kind"] for r in records] == [
        "create_connection",
        "connect",
        "getaddrinfo",
    ]
    assert {r["pid"] for r in records} == {int(pid)}
    assert all("__main__" in r["modules"] for r in records)
    assert "sitecustomize" not in records[0]["modules"]


class TestDaemonHarnessEnv:
    def test_env_is_built_fresh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "parent-key")
        monkeypatch.setenv("ANTE_E2E_SENTINEL", "1")
        env = DaemonHarness.create()
        try:
            child = env.env()
            assert "ANTE_DB_ENCRYPTION_KEY" not in child
            assert "ANTE_E2E_SENTINEL" not in child
            for key in ("HOME", "ANTE_CONFIG_DIR", "ANTE_TOKEN_FILE"):
                assert Path(child[key]).is_relative_to(env.root)
            src, guard = child["PYTHONPATH"].split(os.pathsep)
            assert (Path(src) / "ante" / "__init__.py").is_file()
            assert Path(guard) == harness.NETGUARD_DIR
            assert str(env.root).startswith("/tmp/ante-e2e-")
        finally:
            env.cleanup()
        assert not env.root.exists()


_FAKE_DAEMON = """
    import os, pathlib, sys, time
    run = pathlib.Path(sys.argv[1])
    print("boot", os.getpid(), flush=True)
    (run / "ante.pid").write_text(str(os.getpid()))
    (run / "ante.sock").write_text("")
    while not (run / "stop").exists():
        time.sleep(0.02)
    for name in ("stop", "ante.sock", "ante.pid"):
        (run / name).unlink()
    print("bye", os.getpid(), flush=True)
"""


@pytest.fixture
def fake_daemon(monkeypatch: pytest.MonkeyPatch) -> Iterator[DaemonHarness]:
    """``system start``·``system stop``을 가짜 데몬으로 바꾼 하네스."""
    env = DaemonHarness.create()
    run_dir = env.socket_path.parent
    run_dir.mkdir()
    env.token = "t"

    def _argv(*args: str) -> list[str]:
        return [sys.executable, "-c", textwrap.dedent(_FAKE_DAEMON), str(run_dir)]

    def _cli(*args: str, expect_failure: bool = False) -> dict[str, object]:
        if args == ("system", "stop"):
            (run_dir / "stop").touch()
        return {}

    monkeypatch.setattr(env, "cli_argv", _argv)
    monkeypatch.setattr(env, "cli", _cli)
    try:
        yield env
    finally:
        env.cleanup()


class TestRestart:
    def test_restart_appends_log_and_closes_previous_handle(
        self, fake_daemon: DaemonHarness
    ) -> None:
        fake_daemon.start()
        first_pid = fake_daemon.daemon_pid
        first_log = fake_daemon._log_file
        assert first_log is not None

        fake_daemon.restart()

        assert first_log.closed
        assert fake_daemon._log_file is not None
        assert fake_daemon._log_file is not first_log
        assert not fake_daemon._log_file.closed
        second_pid = fake_daemon.daemon_pid
        assert second_pid != first_pid
        assert fake_daemon.stop() == 0
        lines = fake_daemon.daemon_log_path.read_text().split("\n")
        assert lines[:4] == [
            f"boot {first_pid}",
            f"bye {first_pid}",
            f"boot {second_pid}",
            f"bye {second_pid}",
        ]

    def test_fresh_start_truncates_log(self, fake_daemon: DaemonHarness) -> None:
        fake_daemon.daemon_log_path.write_text("stale\n")
        fake_daemon.start()
        assert fake_daemon.stop() == 0
        assert "stale" not in fake_daemon.daemon_log_path.read_text()

    def test_start_refuses_while_previous_wrapper_runs(
        self, fake_daemon: DaemonHarness
    ) -> None:
        fake_daemon.start()
        with pytest.raises(harness.HarnessError, match="아직 끝나지 않았다"):
            fake_daemon.start(append_log=True)
        assert fake_daemon.stop() == 0


class TestWaitUntil:
    def test_returns_first_value_that_is_done(self) -> None:
        values = iter([1, 2, 3, 4])
        assert (
            harness.wait_until(
                lambda: next(values), lambda v: v >= 3, seconds=5, interval=0
            )
            == 3
        )

    def test_returns_last_value_at_deadline(self) -> None:
        started = time.monotonic()
        value = harness.wait_until(
            lambda: 0, lambda v: False, seconds=0.2, interval=0.05
        )
        assert value == 0
        assert 0.2 <= time.monotonic() - started < 2


E2E = "tests/e2e/test_virtual_round_trip.py::test_a"
E2E_B = "tests/e2e/test_virtual_round_trip.py::test_b"
UNIT = "tests/unit/test_x.py::test_a"


class TestSessionFailureReason:
    @pytest.mark.parametrize(
        "results",
        [
            [(E2E, "skipped")],
            [(E2E, "failed")],
            [(E2E, "setup-or-teardown-passed")],
            [(E2E, "passed"), (E2E_B, "xfailed")],
            [(E2E, "passed"), (E2E_B, "xpassed")],
            [(E2E, "passed"), (E2E_B, "skipped")],
        ],
    )
    def test_fails(self, results: list[tuple[str, str]]) -> None:
        assert session_failure_reason(results) is not None

    @pytest.mark.parametrize(
        "results",
        [
            [],
            [(UNIT, "skipped")],
            [(UNIT, "xfailed"), (UNIT, "passed")],
            [(E2E, "setup-or-teardown-passed"), (E2E, "passed"), (UNIT, "skipped")],
        ],
    )
    def test_passes(self, results: list[tuple[str, str]]) -> None:
        assert session_failure_reason(results) is None


E2E_DIR = Path(__file__).resolve().parents[1] / "e2e"
SMOKE_TEST_NAME = "test_boot_and_stop"
MIN_SCENARIOS = 5


def _daemon_scenarios(e2e_dir: Path) -> list[str]:
    """``daemon`` fixture를 인자로 받는 모듈 최상위 테스트 함수(스모크 제외)."""
    found: list[str] = []
    for path in sorted(e2e_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith("test_") or node.name == SMOKE_TEST_NAME:
                continue
            args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            if any(a.arg == "daemon" for a in args):
                found.append(f"{path.name}::{node.name}")
    return found


class TestScenarioCount:
    def test_e2e_has_at_least_five_scenarios(self) -> None:
        found = _daemon_scenarios(E2E_DIR)
        assert len(found) >= MIN_SCENARIOS, (
            f"데몬 시나리오가 {len(found)}개로 {MIN_SCENARIOS}개보다 적다: {found}"
        )

    def test_counter_skips_smoke_and_non_daemon_tests(self, tmp_path: Path) -> None:
        (tmp_path / "test_a.py").write_text(
            textwrap.dedent(
                """
                def test_boot_and_stop(daemon): ...
                def test_one(daemon): ...
                async def test_two(tmp_path, daemon): ...
                def test_no_daemon(tmp_path): ...
                def helper(daemon): ...
                class TestX:
                    def test_method(self, daemon): ...
                """
            ),
            encoding="utf-8",
        )
        (tmp_path / "other.py").write_text("def test_x(daemon): ...\n")
        assert _daemon_scenarios(tmp_path) == [
            "test_a.py::test_one",
            "test_a.py::test_two",
        ]


@pytest.mark.parametrize(
    ("when", "passed", "skipped", "wasxfail", "expected"),
    [
        ("call", True, False, False, "passed"),
        ("setup", True, False, False, "setup-or-teardown-passed"),
        ("call", False, False, False, "failed"),
        ("setup", False, True, False, "skipped"),
        ("call", False, True, True, "xfailed"),
        ("call", True, False, True, "xpassed"),
    ],
)
def test_report_outcome(
    when: str, passed: bool, skipped: bool, wasxfail: bool, expected: str
) -> None:
    assert report_outcome(when, passed, skipped, wasxfail) == expected
