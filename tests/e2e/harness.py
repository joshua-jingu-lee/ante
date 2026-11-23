"""데몬을 하위 프로세스로 띄우는 e2e 시나리오 하네스.

하위 프로세스는 임시 루트 하나 아래에서만 돈다. 환경은 새로 만들고,
유닉스 소켓이 아닌 접속은 ``netguard/sitecustomize.py``가 모두 막는다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

E2E_NODEID_PREFIX = "tests/e2e/"
TEST_TIME_LIMIT_SECONDS = 180.0
CLI_TIMEOUT_SECONDS = 60.0
READY_DEADLINE_SECONDS = 30.0
STOP_WAIT_SECONDS = 40.0
GROUP_TERM_SECONDS = 40.0
GROUP_KILL_SECONDS = 10.0
POLL_SECONDS = 0.05
SOCKET_PATH_MAX_BYTES = 100
LOG_TAIL_LINES = 80

WAIT_INTERVAL_SECONDS = 0.5

NETGUARD_DIR = Path(__file__).resolve().parent / "netguard"
NETGUARD_LOG_ENV = "ANTE_E2E_NETGUARD_LOG"
NETGUARD_MARKER_ENV = "ANTE_E2E_NETGUARD_MARKER"


class HarnessError(AssertionError):
    """하네스가 시나리오를 더 진행할 수 없을 때."""


class CliCallError(HarnessError):
    """CLI 호출의 결과가 기대와 다를 때."""


class E2ETimeoutError(Exception):
    """테스트별 제한 시간이 지났을 때."""


@dataclass(frozen=True)
class CliResult:
    """JSON 출력 명령 한 번의 결과."""

    argv: tuple[str, ...]
    returncode: int
    payload: Any
    stdout: str
    stderr: str

    @property
    def failed(self) -> bool:
        return is_failure(self.returncode, self.payload)


def is_failure(returncode: int, payload: Any) -> bool:
    """종료 코드가 0이 아니거나 ``status == "error"``이면 실패다."""
    if returncode != 0:
        return True
    return isinstance(payload, dict) and payload.get("status") == "error"


def run_json_command(
    argv: Sequence[str],
    *,
    env: dict[str, str],
    cwd: Path,
    expect_failure: bool = False,
    timeout: float = CLI_TIMEOUT_SECONDS,
) -> CliResult:
    """명령을 실행하고 stdout을 JSON 하나로 읽어 성공과 실패를 판정한다."""
    proc = subprocess.run(
        list(argv),
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    try:
        payload: Any = json.loads(proc.stdout)
        parsed = True
    except json.JSONDecodeError:
        payload = None
        parsed = False
    result = CliResult(tuple(argv), proc.returncode, payload, proc.stdout, proc.stderr)
    if expect_failure:
        if not result.failed:
            raise CliCallError(_describe("실패가 기대됐지만 성공했다", result))
        return result
    if not parsed:
        raise CliCallError(_describe("stdout이 JSON 하나가 아니다", result))
    if result.failed:
        raise CliCallError(_describe("명령이 실패했다", result))
    return result


def _describe(headline: str, result: CliResult) -> str:
    return (
        f"{headline}\n argv: {list(result.argv)}\n returncode: {result.returncode}\n"
        f" stdout:\n{result.stdout}\n stderr:\n{result.stderr[-4000:]}"
    )


@contextmanager
def time_limit(seconds: float) -> Iterator[None]:
    """기한이 지나면 ``E2ETimeoutError``를 내고, 빠져나올 때 타이머를 푼다."""

    def _on_alarm(signum: int, frame: object) -> None:
        raise E2ETimeoutError(f"테스트 제한 시간 {seconds:g}초를 넘었다")

    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def group_alive(pgid: int) -> bool:
    """그룹에 프로세스가 남았는지. 좀비만 남은 그룹에 macOS는 EPERM을 낸다."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def terminate_process_group(
    pgid: int,
    *,
    reap: Callable[[], object] | None = None,
    term_seconds: float = GROUP_TERM_SECONDS,
    kill_seconds: float = GROUP_KILL_SECONDS,
) -> str:
    """그룹이 빌 때까지 SIGTERM, 그래도 남으면 SIGKILL. 쓴 수단을 돌려준다.

    ``reap``은 그룹에 속한 자식을 거둔다(좀비도 그룹에 남아 있다).
    """
    if not _wait_group_gone(pgid, 0, reap):
        return "gone"
    _signal_group(pgid, signal.SIGTERM)
    if not _wait_group_gone(pgid, term_seconds, reap):
        return "sigterm"
    _signal_group(pgid, signal.SIGKILL)
    if not _wait_group_gone(pgid, kill_seconds, reap):
        return "sigkill"
    raise HarnessError(f"프로세스 그룹 {pgid}가 SIGKILL 뒤에도 남았다")


def _wait_group_gone(
    pgid: int, seconds: float, reap: Callable[[], object] | None
) -> bool:
    """기한 안에 그룹이 비면 False, 남아 있으면 True."""
    deadline = time.monotonic() + seconds
    while True:
        if reap is not None:
            reap()
        if not group_alive(pgid):
            return False
        if time.monotonic() >= deadline:
            return True
        time.sleep(POLL_SECONDS)


def report_outcome(when: str, passed: bool, skipped: bool, wasxfail: bool) -> str:
    """테스트 리포트 한 건을 세션 판정의 결과 이름으로 옮긴다."""
    if wasxfail:
        return "xfailed" if skipped else "xpassed"
    if skipped:
        return "skipped"
    if not passed:
        return "failed"
    return "passed" if when == "call" else "setup-or-teardown-passed"


def session_failure_reason(results: Sequence[tuple[str, str]]) -> str | None:
    """e2e 리포트에 skip·xfail이 있거나 통과가 0이면 실패 사유를 돌려준다."""
    e2e = [(n, o) for n, o in results if n.startswith(E2E_NODEID_PREFIX)]
    if not e2e:
        return None
    soft = sorted({n for n, o in e2e if o in {"skipped", "xfailed", "xpassed"}})
    if soft:
        return f"e2e 항목이 skip·xfail로 끝났다: {soft}"
    if not any(o == "passed" for _, o in e2e):
        return "e2e 항목이 수집됐지만 통과가 0이다"
    return None


def wait_until[T](
    fetch: Callable[[], T],
    done: Callable[[T], bool],
    *,
    seconds: float,
    interval: float = WAIT_INTERVAL_SECONDS,
) -> T:
    """``done``이 참이거나 기한이 지날 때까지 ``fetch``를 부르고 마지막 값을 낸다."""
    deadline = time.monotonic() + seconds
    while True:
        value = fetch()
        if done(value) or time.monotonic() >= deadline:
            return value
        time.sleep(interval)


def ante_src_dir() -> Path:
    """``ante`` 패키지를 담은 디렉터리(설정을 풀지 않고 위치만 찾는다)."""
    spec = importlib.util.find_spec("ante")
    if spec is None or spec.origin is None:
        raise HarnessError("ante 패키지를 찾을 수 없다")
    return Path(spec.origin).resolve().parent.parent


class DaemonHarness:
    """임시 루트 하나와 그 아래에서 도는 CLI·데몬 하위 프로세스."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.config_dir = root / "config"
        self.home_dir = root / "home"
        self.work_dir = root / "work"
        self.logs_dir = root / "logs"
        run_dir = self.config_dir / "run"
        self.socket_path = run_dir / "ante.sock"
        self.pid_path = run_dir / "ante.pid"
        self.starting_path = run_dir / ".starting"
        self.daemon_log_path = self.logs_dir / "daemon.log"
        self.net_log_path = root / "net-attempts.jsonl"
        self.net_marker_path = root / "netguard-pids"
        self.token: str | None = None
        self.proc: subprocess.Popen[bytes] | None = None
        self.daemon_pid: int | None = None
        self._log_file: IO[bytes] | None = None
        self._final_diagnostics: str | None = None

    @classmethod
    def create(cls) -> DaemonHarness:
        root = Path(tempfile.mkdtemp(prefix="ante-e2e-", dir="/tmp"))
        harness = cls(root)
        try:
            for path in (
                harness.config_dir,
                harness.home_dir,
                harness.work_dir,
                harness.logs_dir,
            ):
                path.mkdir()
            size = len(os.fsencode(harness.socket_path))
            if size > SOCKET_PATH_MAX_BYTES:
                raise HarnessError(
                    f"소켓 경로가 {size}바이트로 상한 {SOCKET_PATH_MAX_BYTES}바이트를"
                    f" 넘는다: {harness.socket_path}"
                )
        except BaseException:
            shutil.rmtree(root)
            raise
        return harness

    def env(self) -> dict[str, str]:
        """하위 프로세스의 환경. ``os.environ``을 복사하지 않는다."""
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.home_dir),
            "ANTE_CONFIG_DIR": str(self.config_dir),
            "ANTE_TOKEN_FILE": str(self.root / "no-token"),
            "PYTHONPATH": os.pathsep.join([str(ante_src_dir()), str(NETGUARD_DIR)]),
            "PYTHONDONTWRITEBYTECODE": "1",
            "LC_ALL": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8",
            NETGUARD_LOG_ENV: str(self.net_log_path),
            NETGUARD_MARKER_ENV: str(self.net_marker_path),
        }
        if self.token is not None:
            env["ANTE_MEMBER_TOKEN"] = self.token
        return env

    def cli_argv(self, *args: str) -> list[str]:
        return [sys.executable, "-m", "ante", "--format", "json", *args]

    def cli(self, *args: str, expect_failure: bool = False) -> Any:
        """CLI를 JSON 형식으로 부르고 출력을 돌려준다."""
        result = run_json_command(
            self.cli_argv(*args),
            env=self.env(),
            cwd=self.work_dir,
            expect_failure=expect_failure,
        )
        return result.payload

    def init(self) -> dict[str, Any]:
        payload = self.cli("init")
        self.token = payload["token"]
        return payload

    def start(self, *, append_log: bool = False) -> float:
        """``system start``로 데몬을 띄우고 준비를 기다린다. 걸린 초를 돌려준다.

        ``append_log``이면 데몬 로그를 이어 쓴다(재기동). 이전 핸들은 닫는다.
        """
        if self.token is None:
            raise HarnessError("init 전에는 데몬을 띄울 수 없다")
        if self.proc is not None and self.proc.poll() is None:
            raise HarnessError("이전 데몬의 래퍼가 아직 끝나지 않았다")
        self._close_log()
        self._log_file = open(self.daemon_log_path, "ab" if append_log else "wb")
        started = time.monotonic()
        self.proc = subprocess.Popen(
            self.cli_argv("system", "start"),
            env=self.env(),
            cwd=self.work_dir,
            stdin=subprocess.DEVNULL,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = started + READY_DEADLINE_SECONDS
        while True:
            returncode = self.proc.poll()
            if returncode is not None:
                raise HarnessError(
                    f"데몬이 준비 전에 끝났다(래퍼 종료 코드 {returncode})\n"
                    + self.diagnostics()
                )
            if self.socket_path.exists() and not self.starting_path.exists():
                break
            if time.monotonic() >= deadline:
                raise HarnessError(
                    f"데몬이 {READY_DEADLINE_SECONDS:g}초 안에 준비되지 않았다\n"
                    + self.diagnostics()
                )
            time.sleep(POLL_SECONDS)
        self.daemon_pid = int(self.pid_path.read_text().strip())
        self.cli("bot", "list")
        return time.monotonic() - started

    def stop(self) -> int:
        """``system stop`` 뒤 래퍼가 끝나기를 기다려 그 종료 코드를 돌려준다."""
        if self.proc is None:
            raise HarnessError("띄운 데몬이 없다")
        self.cli("system", "stop")
        try:
            return self.proc.wait(timeout=STOP_WAIT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise HarnessError(
                f"system stop 뒤 {STOP_WAIT_SECONDS:g}초 안에 래퍼가 끝나지 않았다\n"
                + self.diagnostics()
            ) from exc

    def restart(self) -> float:
        """같은 루트에서 ``system stop`` → ``system start`` → 준비 대기.

        래퍼가 0으로 끝나지 않으면 멈춘다. 로그는 이어 쓴다. 준비에 걸린 초를 돌려준다.
        """
        returncode = self.stop()
        if returncode != 0:
            raise HarnessError(
                f"재기동 전 system stop의 래퍼가 {returncode}로 끝났다\n"
                + self.diagnostics()
            )
        return self.start(append_log=True)

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def guarded_pids(self) -> set[int]:
        if not self.net_marker_path.exists():
            return set()
        text = self.net_marker_path.read_text(encoding="utf-8")
        return {int(line) for line in text.split()}

    def net_attempts(self) -> list[dict[str, Any]]:
        if not self.net_log_path.exists():
            return []
        lines = self.net_log_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def diagnostics(self) -> str:
        """데몬 로그의 꼬리와 접속 시도 기록."""
        if self._final_diagnostics is not None:
            return self._final_diagnostics
        parts = [f"root: {self.root}"]
        if self.daemon_log_path.exists():
            raw = self.daemon_log_path.read_bytes().decode("utf-8", "replace")
            tail = "\n".join(raw.splitlines()[-LOG_TAIL_LINES:])
            parts.append(f"--- daemon log (last {LOG_TAIL_LINES} lines)\n{tail}")
        if self.net_log_path.exists():
            parts.append(
                "--- net attempts\n" + self.net_log_path.read_text(encoding="utf-8")
            )
        return "\n".join(parts)

    def cleanup(self) -> None:
        """타이머를 끄고, 프로세스 그룹을 비우고, 임시 루트를 지운다."""
        signal.setitimer(signal.ITIMER_REAL, 0)
        try:
            if self.proc is not None:
                terminate_process_group(self.proc.pid, reap=self.proc.poll)
                self.proc.wait(timeout=GROUP_KILL_SECONDS)
        finally:
            self._close_log()
            if self.root.exists():
                try:
                    self._final_diagnostics = self.diagnostics()
                finally:
                    shutil.rmtree(self.root)
