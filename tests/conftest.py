"""공통 pytest 설정."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import importlib.util
import os
import pwd
import shutil
import sys
import tempfile
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from unittest import mock

import pytest


def _load_import_guard():
    guard_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_import_path.py"
    )
    spec = importlib.util.spec_from_file_location("check_import_path", guard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import guard: {guard_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── 단위 테스트 샤드 (#2786) ──────────────────────────────────────────────
#
# --shard=<i>/<n>은 테스트 파일을 n개로 나눠 i번째만 남긴다. 나누는 법은
# tests/shard_durations.json의 파일별 소요 시간으로 부하를 고르게 맞추고, 기록이
# 없거나 깨졌거나 수집된 파일과 겹치지 않으면 파일 경로의 crc32다 (#3036).
# --shard-manifest=<path>는 실행된(setup 보고가 있는) 테스트의 nodeid를 쓴다.
# --shard-durations=<path>는 파일별 소요 시간(setup·call·teardown 합, 정수
# 센티초)을 기록 파일과 같은 형식으로 쓴다. 쓰기는 xdist 컨트롤러가 한다.
# 셋 다 없으면 아무 일도 하지 않는다.
# --shard가 있으면 머리말에 기록의 상태를 찍는다. 로컬 확인용이다. -q에서는
# 머리말이 나오지 않는다(CI의 샤드 잡이 그렇다).

_SHARD_KEY = pytest.StashKey["tuple[int, int] | None"]()
_SHARD_MANIFEST: dict[str, object] = {}
_SHARD_DURATIONS: dict[str, object] = {}


def _load_shard_tools():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_test_shards.py"
    spec = importlib.util.spec_from_file_location("_ante_test_shards", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shard tools: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SHARD_TOOLS = _load_shard_tools()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("ante-shards", "unit test shards (#2786)")
    group.addoption(
        "--shard",
        default=None,
        metavar="I/N",
        help=(
            "run only the I-th of N test file groups, balanced by "
            "tests/shard_durations.json (path crc32 %% N == I - 1 without it)"
        ),
    )
    group.addoption(
        "--shard-manifest",
        default=None,
        metavar="PATH",
        help="write the sorted nodeids of the tests that ran to PATH",
    )
    group.addoption(
        "--shard-durations",
        default=None,
        metavar="PATH",
        help="write per-file durations (centiseconds) of the tests that ran to PATH",
    )


def _configure_shard(config: pytest.Config) -> None:
    value = config.getoption("--shard")
    shard = None
    if value is not None:
        try:
            shard = _SHARD_TOOLS.parse_shard(value)
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc
    config.stash[_SHARD_KEY] = shard
    manifest = config.getoption("--shard-manifest")
    if manifest is not None:
        path = _SHARD_TOOLS.resolve_manifest(manifest, config.invocation_params.dir)
        _SHARD_MANIFEST.update(path=str(path), ran=set())
    durations = config.getoption("--shard-durations")
    if durations is not None:
        path = _SHARD_TOOLS.resolve_manifest(durations, config.invocation_params.dir)
        _SHARD_DURATIONS.update(path=str(path), seconds={})


def pytest_report_header(config: pytest.Config) -> str | None:
    if config.stash.get(_SHARD_KEY, None) is None:
        return None
    record_path = _SHARD_TOOLS.RECORD_PATH
    if not record_path.is_file():
        return "ante-shards: record missing → hash"
    record = _SHARD_TOOLS.load_record(record_path)
    if record is None:
        return "ante-shards: record invalid → hash"
    version = _SHARD_TOOLS.RECORD_VERSION
    return f"ante-shards: record valid (version {version}, {len(record)} files)"


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    shard = config.stash.get(_SHARD_KEY, None)
    if shard is None:
        return
    index, total = shard
    counts: dict[str, int] = {}
    for item in items:
        path = item.nodeid.split("::", 1)[0]
        counts[path] = counts.get(path, 0) + 1
    record = _SHARD_TOOLS.load_record(_SHARD_TOOLS.RECORD_PATH)
    assignment = _SHARD_TOOLS.assign_shards(counts, record, total)
    keep: list[pytest.Item] = []
    drop: list[pytest.Item] = []
    for item in items:
        path = item.nodeid.split("::", 1)[0]
        (keep if assignment[path] == index else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    ran = _SHARD_MANIFEST.get("ran")
    if isinstance(ran, set) and report.when == "setup":
        ran.add(report.nodeid)
    seconds = _SHARD_DURATIONS.get("seconds")
    if isinstance(seconds, dict):
        path = report.nodeid.split("::", 1)[0]
        seconds[path] = seconds.get(path, 0.0) + report.duration


def _write_shard_durations() -> None:
    path, seconds = _SHARD_DURATIONS.get("path"), _SHARD_DURATIONS.get("seconds")
    if isinstance(path, str) and isinstance(seconds, dict):
        files = {name: round(value * 100) for name, value in seconds.items()}
        Path(path).write_text(_SHARD_TOOLS.record_text(files), encoding="utf-8")


def _write_shard_manifest() -> None:
    path, ran = _SHARD_MANIFEST.get("path"), _SHARD_MANIFEST.get("ran")
    if isinstance(path, str) and isinstance(ran, set):
        Path(path).write_text(
            "".join(f"{nodeid}\n" for nodeid in sorted(ran)), encoding="utf-8"
        )


# ── 설정 디렉터리 격리 (#2592) ────────────────────────────────────────────
#
# 테스트는 실제 설정 디렉터리(원래 HOME과 pwd 홈의 .config/ante, 원래
# ANTE_CONFIG_DIR)와 저장소의 config/에 닿지 못한다. 환경 변수를 임시
# 디렉터리로 돌려 기본 해석을 막고, audit hook이 남은 접근을 기록해 실패로 만든다.

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ORIG_HOME_ENV = "ANTE_TEST_ORIG_HOME"
_ORIG_CONFIG_DIR_ENV = "ANTE_TEST_ORIG_CONFIG_DIR"
_WORKEROUTPUT_KEY = "ante_config_violations"
# 개발자 셸에 남아 있으면 테스트의 분기를 바꾸는 변수들.
_SCRUBBED_ENV = (
    "ANTE_MEMBER_TOKEN",
    "ANTE_TOKEN_FILE",
    "ANTE_DB_PATH",
    "ANTE_DATA_PATH",
    "ANTE_ENV",
    "ANTE_LOG_JSONL",
)
# 이벤트 이름 → (경로 인자의 위치, 그 경로의 dir_fd 인자 위치) 목록.
# dir_fd가 주어진 상대 경로는 작업 디렉터리 기준이 아니어서 풀 수 없으므로 건너뛴다.
_PATH_EVENTS: dict[str, tuple[tuple[int, int | None], ...]] = {
    "open": ((0, None),),
    "os.mkdir": ((0, 2),),
    "os.remove": ((0, 1),),
    "os.rmdir": ((0, 1),),
    "os.rename": ((0, 2), (1, 3)),
    "os.replace": ((0, 2), (1, 3)),
    "os.listdir": ((0, None),),
    "os.scandir": ((0, None),),
    "os.chmod": ((0, 2),),
    "os.truncate": ((0, None),),
    "os.utime": ((0, 3),),
    "shutil.rmtree": ((0, 1),),
    "sqlite3.connect": ((0, None),),
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


class ConfigIsolationViolationError(RuntimeError):
    """테스트가 금지된 설정 디렉터리에 닿았다.

    ``OSError`` 계열이 아니어서 ``except OSError``에 삼켜지지 않는다.
    """


def _path_forms(path: str) -> tuple[str, str]:
    return os.path.abspath(path), os.path.realpath(path)


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


class _ConfigIsolationGuard:
    """audit hook으로 금지 루트 아래의 파일 접근을 막고 기록한다."""

    violation_type = ConfigIsolationViolationError

    def __init__(self) -> None:
        self.active = False
        self.orig_home = ""
        # (token, 경로 형들). 훅은 튜플을 통째로 읽으므로 교체만 한다.
        self._roots: tuple[tuple[object, tuple[str, ...]], ...] = ()
        self._example_reads: frozenset[str] = frozenset()
        # (이벤트, abspath, realpath). list.append는 스레드 사이에서 원자적이다.
        self.records: list[tuple[str, str, str]] = []
        self._local = threading.local()
        self._take_lock = threading.Lock()

    @property
    def forbidden_roots(self) -> tuple[str, ...]:
        return tuple(form for _, forms in self._roots for form in forms)

    def add_root(self, root: str | os.PathLike[str]) -> object:
        token = object()
        forms = tuple(dict.fromkeys(_path_forms(os.fspath(root))))
        self._roots = (*self._roots, (token, forms))
        return token

    def remove_root(self, token: object) -> None:
        self._roots = tuple(entry for entry in self._roots if entry[0] is not token)

    def allow_reads(self, paths: list[str]) -> None:
        self._example_reads = frozenset(
            form for path in paths for form in _path_forms(path)
        )

    def take_records(self) -> list[tuple[str, str, str]]:
        # 훅은 끝에 append만 한다. 꺼내는 쪽끼리만 잠그면 앞의 len(taken)개가
        # 곧 taken이라 그 사이에 더해진 기록을 지우지 않는다.
        with self._take_lock:
            taken = self.records[:]
            del self.records[: len(taken)]
        return taken

    @contextlib.contextmanager
    def expect_violation(
        self, root: str | os.PathLike[str]
    ) -> Iterator[list[tuple[str, str, str]]]:
        """``root``를 잠시 금지하고, 그 아래에서 난 기록만 꺼내 돌려준다."""
        token = self.add_root(root)
        forms = _path_forms(os.fspath(root))
        caught: list[tuple[str, str, str]] = []
        try:
            yield caught
        finally:
            self.remove_root(token)
            kept = []
            for record in self.take_records():
                if any(_under(p, f) for p in record[1:] for f in forms):
                    caught.append(record)
                else:
                    kept.append(record)
            self.records.extend(kept)

    def hook(self, event: str, args: tuple) -> None:
        # 이 본문은 audit 이벤트를 내는 호출(open, logging, id 등)을 하지 않는다.
        if not self.active:
            return
        positions = _PATH_EVENTS.get(event)
        if positions is None:
            return
        local = self._local
        if getattr(local, "busy", False):
            return
        local.busy = True
        try:
            self._check(event, args, positions)
        finally:
            local.busy = False

    def _check(
        self,
        event: str,
        args: tuple,
        positions: tuple[tuple[int, int | None], ...],
    ) -> None:
        roots = self._roots
        if not roots:
            return
        for position, dir_fd_position in positions:
            if position >= len(args):
                continue
            path = _event_path(event, args[position])
            if path is None:
                continue
            forms = _path_forms(path)
            hit = any(
                _under(form, root)
                for _, root_forms in roots
                for root in root_forms
                for form in forms
            )
            if not hit:
                continue
            if not os.path.isabs(path) and _maybe_dir_fd_relative(
                event, args, dir_fd_position
            ):
                continue
            if event == "open" and not _is_write_open(args):
                if forms[0] in self._example_reads or forms[1] in self._example_reads:
                    continue
            self.records.append((event, forms[0], forms[1]))
            raise ConfigIsolationViolationError(
                f"테스트가 금지된 설정 경로에 닿았다: {event} {forms[0]}"
            )


def _event_path(event: str, value: object) -> str | None:
    if value is None:
        return "." if event in ("os.listdir", "os.scandir") else None
    if isinstance(value, int):
        return None
    if isinstance(value, bytes):
        path = os.fsdecode(value)
    elif isinstance(value, str):
        path = value
    elif isinstance(value, os.PathLike):
        path = os.fsdecode(os.fspath(value))
    else:
        return None
    if event == "sqlite3.connect":
        if path.startswith("file:"):
            path = path[len("file:") :].split("?", 1)[0].split("#", 1)[0]
        if path in ("", ":memory:"):
            return None
    return path


def _maybe_dir_fd_relative(
    event: str, args: tuple, dir_fd_position: int | None
) -> bool:
    if event == "open":
        # os.open의 이벤트는 mode가 None이고 dir_fd가 실리지 않는다. 면제는
        # shutil(rmtree가 dir_fd 기준 이름으로 연다)이 부른 경우뿐이다.
        return len(args) > 1 and args[1] is None and _os_open_caller_is_shutil()
    if dir_fd_position is None or dir_fd_position >= len(args):
        return False
    # os.* 이벤트는 dir_fd가 없으면 -1, shutil.rmtree는 None을 넘긴다.
    dir_fd = args[dir_fd_position]
    return isinstance(dir_fd, int) and dir_fd >= 0


def _os_open_caller_is_shutil() -> bool:
    # 깊이를 고정하지 않고 이 파일의 프레임을 건너뛴다. os.open은 C 함수라
    # 프레임이 없으므로 처음 만나는 다른 파일의 프레임이 os.open을 부른 코드다.
    # f_code는 감사 이벤트를 내므로 f_globals의 __file__로 가른다.
    frame = sys._getframe(1)
    while frame is not None and frame.f_globals.get("__file__") == __file__:
        frame = frame.f_back
    return frame is not None and frame.f_globals.get("__file__") == shutil.__file__


def _is_write_open(args: tuple) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    if isinstance(mode, str) and any(ch in mode for ch in "wax+"):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


_GUARD = _ConfigIsolationGuard()
_GUARD_STATE: dict[str, object] = {}
_COLLECTED_WORKER_VIOLATIONS: list[str] = []


def _install_config_isolation(config: pytest.Config) -> None:
    saved: dict[str, str | None] = {}
    for name in (
        "HOME",
        "ANTE_CONFIG_DIR",
        _ORIG_HOME_ENV,
        _ORIG_CONFIG_DIR_ENV,
        *_SCRUBBED_ENV,
    ):
        saved[name] = os.environ.get(name)

    is_worker = hasattr(config, "workerinput")
    if is_worker:
        orig_home = os.environ.get(_ORIG_HOME_ENV, "")
        orig_config_dir = os.environ.get(_ORIG_CONFIG_DIR_ENV, "")
    else:
        orig_home = os.environ.get("HOME", "")
        orig_config_dir = os.environ.get("ANTE_CONFIG_DIR", "")
        os.environ[_ORIG_HOME_ENV] = orig_home
        os.environ[_ORIG_CONFIG_DIR_ENV] = orig_config_dir

    for name in _SCRUBBED_ENV:
        os.environ.pop(name, None)

    roots = [os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".config", "ante")]
    if orig_home:
        roots.append(os.path.join(orig_home, ".config", "ante"))
    if orig_config_dir:
        roots.append(orig_config_dir)
    repo_config = _REPO_ROOT / "config"
    roots.append(str(repo_config))
    for root in roots:
        _GUARD.add_root(root)
    _GUARD.allow_reads(
        [
            str(repo_config / "system.toml.example"),
            str(repo_config / "secrets.env.example"),
        ]
    )
    _GUARD.orig_home = orig_home

    base = tempfile.mkdtemp(prefix="ante-pytest-")
    home = os.path.join(base, "home")
    os.makedirs(os.path.join(home, ".config", "ante"))
    os.environ["HOME"] = home
    os.environ["ANTE_CONFIG_DIR"] = os.path.join(home, ".config", "ante")
    _GUARD_STATE.update(base=base, saved=saved)

    if not _GUARD_STATE.get("hooked"):
        sys.addaudithook(_GUARD.hook)
        _GUARD_STATE["hooked"] = True
    _GUARD.active = True


def _uninstall_config_isolation() -> None:
    _GUARD.active = False
    saved = _GUARD_STATE.pop("saved", None)
    if isinstance(saved, dict):
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    base = _GUARD_STATE.pop("base", None)
    if isinstance(base, str):
        shutil.rmtree(base, ignore_errors=True)


def _format_record(record: tuple[str, str, str]) -> str:
    event, abspath, realpath = record
    return f"{event} {abspath}" + ("" if abspath == realpath else f" ({realpath})")


def pytest_configure(config: pytest.Config) -> None:
    """Fail collection if ``ante`` resolves outside this checkout."""
    _configure_shard(config)
    guard = _load_import_guard()
    try:
        guard.check_import_path()
    except guard.ImportPathCheckError as exc:
        raise pytest.UsageError(str(exc)) from exc
    _install_config_isolation(config)


def pytest_unconfigure(config: pytest.Config) -> None:
    _uninstall_config_isolation()
    # sessionfinish 뒤에 남은 스레드가 낸 위반. 종료 코드는 정해졌으니 출력만 한다.
    late = _GUARD.take_records()
    if late:
        sys.stderr.write(
            "설정 디렉터리 격리 위반 (#2592, 세션 종료 뒤):\n"
            + "".join(f"  {_format_record(r)}\n" for r in late)
        )


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error) -> None:
    """xdist 컨트롤러: 작업자가 넘긴 남은 위반 기록을 모은다."""
    output = getattr(node, "workeroutput", None) or {}
    _COLLECTED_WORKER_VIOLATIONS.extend(output.get(_WORKEROUTPUT_KEY, []))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """테스트 밖(세션 fixture, 수집, 남은 스레드)에서 난 위반으로 세션을 실패시킨다."""
    leftover = [_format_record(record) for record in _GUARD.take_records()]
    config = session.config
    if hasattr(config, "workerinput"):
        config.workeroutput[_WORKEROUTPUT_KEY] = leftover
        return
    _write_shard_manifest()
    _write_shard_durations()
    violations = _COLLECTED_WORKER_VIOLATIONS + leftover
    if not violations:
        return
    lines = ["", "설정 디렉터리 격리 위반 (#2592):", *(f"  {v}" for v in violations)]
    sys.stderr.write("\n".join(lines) + "\n")
    if session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path_factory, monkeypatch):
    """테스트마다 새 HOME과 설정 디렉터리를 주고, 끝에서 위반 기록을 검사한다.

    CLI의 catch-all이 위반 예외를 삼켜도 이 teardown이 테스트를 실패시킨다.
    """
    home = tmp_path_factory.mktemp("ante-home")
    config_dir = home / ".config" / "ante"
    config_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
    yield
    records = _GUARD.take_records()
    if records:
        pytest.fail(
            "설정 디렉터리 격리 위반 (#2592):\n"
            + "\n".join(f"  {_format_record(r)}" for r in records),
            pytrace=False,
        )


@pytest.fixture(scope="session")
def config_isolation_guard() -> _ConfigIsolationGuard:
    """설정 디렉터리 격리 가드. 가드 자체의 테스트가 쓴다."""
    return _GUARD


@pytest.fixture(autouse=True, scope="session")
def _set_encryption_key():
    """테스트용 Fernet 키 자동 설정 (session scope — 전체 세션에서 1회만 생성)."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    os.environ["ANTE_DB_ENCRYPTION_KEY"] = key
    yield
    os.environ.pop("ANTE_DB_ENCRYPTION_KEY", None)


@pytest.fixture(autouse=True)
def _reset_kis_token_state():
    """매 테스트 전후 KIS module-level 토큰 캐시/lock/cooldown 초기화 (#2399).

    글로벌 격리(메타 P2): EGW00133 ``_token_cooldowns`` 상태가 테스트 간 누출되면
    KIS 토큰을 건드리는 후속 테스트의 발급이 cooldown 내로 오판돼 flaky 가 된다.
    기존엔 토큰 single-flight/backoff 테스트 2개 파일에만 reset autouse fixture 가
    있어 cross-test 오염 위험이 있었으므로, 전 테스트가 공유하는 본 글로벌 conftest
    autouse fixture 로 승격해 ``_token_cache``/``_token_locks``/``_token_cooldowns``
    를 매 테스트 경계에서 초기화한다. closed event loop 에 묶인 Lock 재사용(T1
    closed-loop) 방지도 겸한다. ``ante.broker.kis`` 는 import 가드 안에서 안전하게
    lazy import 한다(collection 시 부작용 회피).
    """
    from ante.broker.kis import _reset_token_cache

    _reset_token_cache()
    yield
    _reset_token_cache()


CLOCK_LEAK_MESSAGE = (
    "테스트가 바꾼 시계를 되돌리지 않았다 (#2768). "
    "manual_clock 픽스처나 use_clock으로 바꾼다."
)
DEFAULT_MANUAL_CLOCK_AT = datetime(2026, 1, 2, 3, 0, 0, tzinfo=UTC)


class ManualClock:
    """테스트의 시계 대역. 시각과 단조 값을 고정하고 ``advance``로만 움직인다.

    ``now(tz)``는 고정 시각을 그 tz로, ``now(None)``은 로컬 naive 시각으로
    돌려준다(``datetime.now()``와 같은 뜻).
    """

    def __init__(self, at: datetime, monotonic: float = 1000.0) -> None:
        if at.tzinfo is None:
            raise ValueError("ManualClock needs an aware datetime")
        self._at = at
        self._monotonic = monotonic

    def now(self, tz: tzinfo | None) -> datetime:
        if tz is None:
            return self._at.astimezone().replace(tzinfo=None)
        return self._at.astimezone(tz)

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("ManualClock does not go back")
        self._at += timedelta(seconds=seconds)
        self._monotonic += seconds


@pytest.fixture
def manual_clock(request: pytest.FixtureRequest) -> Iterator[ManualClock]:
    """고정 시계를 현재 시계로 둔다. 시각은 ``indirect`` 파라미터로 줄 수 있다.

    기본 시각은 ``DEFAULT_MANUAL_CLOCK_AT``(2026-01-02 12:00 KST)이다.
    """
    from ante.core import clock

    manual = ManualClock(getattr(request, "param", DEFAULT_MANUAL_CLOCK_AT))
    with clock.use_clock(manual):
        yield manual


def _reset_clock() -> bool:
    """현재 시계가 ``SystemClock``이 아니면 되돌리고 True를 돌려준다."""
    from ante.core import clock

    if type(clock.current_clock()) is clock.SystemClock:
        return False
    clock.set_clock(clock.SystemClock())
    return True


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """전역 시계가 다음 테스트로 새지 않게 한다 (#2768).

    검사는 이 테스트의 정리가 모두 끝난 뒤, 곧 모든 conftest와 플러그인의
    함수 범위 픽스처(그리고 이 테스트에서 끝나는 module·session 범위
    픽스처)가 정리된 뒤에 돈다. 그때까지 되돌려진 시계는 실패가 아니다.
    남아 있으면 되돌리고 정리 단계의 오류로 그 테스트를 실패시킨다.
    module·session 범위의 픽스처가 시계를 바꾸면 그 범위의 첫 테스트가
    실패한다. 정리 자체가 실패하면 시계만 되돌리고 그 오류를 그대로 낸다.
    """
    try:
        result = yield
    except BaseException:
        _reset_clock()
        raise
    if _reset_clock():
        pytest.fail(CLOCK_LEAK_MESSAGE, pytrace=False)
    return result


@pytest.fixture(autouse=True)
def _sync_boundary_cleanup():
    """모든 테스트(sync + async) 경계에서 ``patch.stopall`` 보장.

    Refs #2304: 기존 ``_cleanup_tasks`` 는 ``async def`` autouse fixture 라
    async 테스트 경계에서만 ``mock.patch.stopall()`` 을 수행한다. 반면 sync
    테스트(예: ``CliRunner.invoke`` 가 내부적으로 ``asyncio.run(coro)`` 을
    호출하는 ``ante bot remove`` 표면)는 같은 보장 밖에 있어, ``patch.start()``
    후 ``stop()`` 누락(예: ``try`` 진입 전 예외)으로 module attribute 가 mock
    으로 영구 leak 되는 cross-test contamination 이 발생할 수 있다. 본 sync
    autouse fixture 는 sync + async 두 경계 **모두** 에서 매 테스트 종료 직후
    ``mock.patch.stopall()`` 을 한 번 더 수행해 그 leak 을 차단한다(idempotent —
    ``_cleanup_tasks`` async 와 중복 호출되어도 회귀 없음).

    Refs #2309: 본 fixture 에서 매-테스트 ``gc.collect()`` 는 제거했다.
    - ``#2304`` 의 실제 flaky(``test_cli_direct_not_found_via_remove`` 의
      ``EXECUTION_ERROR`` 오분류)는 GC 가능한 누수가 아니라 ``bot remove`` 의
      ``is_active_runtime()`` runtime-state 분기가 비결정적이었던 것이며, 해당
      테스트에 ``is_active_runtime`` mock 을 추가해 결정화했다. broad
      ``gc.collect()`` 는 이 flaky 에 무효였다.
    - ``#2304`` transport 누수는 ``test_server_client.py`` 의 server-side
      transport 명시 ``close()`` (source-close, ``_settle_server_side_transports``)
      로 이미 결정적으로 해소돼 broad GC 안전망이 불필요하다.
    - 매-테스트 ``gc.collect()`` 는 full-suite 시간을 ~2x 로 회귀시키는 고비용
      연산이라 제거해 성능을 회복한다.
    - async 경계의 ``gc.collect()`` 는 ``_cleanup_tasks`` (Refs #1897) 에 그대로
      유지된다.
    """
    yield
    # Refs #1904 / #2304: stop-orphaned patch leak 방어 (idempotent).
    mock.patch.stopall()


@pytest.fixture(autouse=True)
async def _cleanup_tasks():
    """각 async 테스트 후 잔여 asyncio 태스크를 강제 정리.

    pytest-asyncio가 function-scope event loop를 사용할 때,
    start된 봇의 background task가 남아있으면 다음 테스트에서
    event loop 생성이 블로킹될 수 있음 (Python 3.11 Ubuntu 환경).

    Refs #1897: 각 async 테스트 종료 직후 ``gc.collect()`` 를 한 번 강제해
    이전 테스트가 남긴 ``_SelectorTransport`` / ``aiosqlite.Connection`` /
    ``sqlite3.Connection`` 가 같은 테스트 경계 안에서 GC 되도록 한다. 다음
    테스트로 누수 attribution 이 전이되어 ``PytestUnraisableExceptionWarning``
    / ``ResourceWarning`` 이 무관 테스트에 표시되는 회귀를 방지한다.

    Refs #1904 follow-up: 매 테스트 종료 직후 ``mock.patch.stopall()`` 을
    호출해 ``patch.start()`` 후 ``stop()`` 누락(예: ``try`` 진입 전 예외)으로
    인해 module attribute (``ante.cli.commands.*._create_*``,
    ``ante.cli.main.authenticate_member`` 등) 가 mock 으로 영구 leak 되는
    cross-test contamination 을 차단한다. xdist 환경에서 worker 별 random
    fail (assert exit_code==0 인데 1, ``WARNING ante.config.config`` 가
    captured log 에 잡히는 패턴) 의 baseline 누수원이다.

    Refs #2304: 잔여 task 획득에 deprecated ``asyncio.get_event_loop()`` 대신
    ``asyncio.get_running_loop()`` 을 사용한다. async 테스트 경계에서는 항상
    running loop 이 존재하므로 정상 동작하며, 닫힌/신규 loop 을 잘못 획득해
    엉뚱한 loop 의 task 를 건드리거나 ``DeprecationWarning`` 을 유발하는 경로를
    제거한다.
    """
    yield
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # running loop 이 없으면(async fixture teardown 에서는 정상적으로
        # 발생하지 않음) task 정리를 건너뛰고 GC/stopall 만 수행한다.
        gc.collect()
        mock.patch.stopall()
        return
    pending = [
        t
        for t in asyncio.all_tasks(loop)
        if not t.done() and t is not asyncio.current_task()
    ]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    # Refs #1897: 남은 transport / DB Connection 객체를 결정적으로 정리한다.
    gc.collect()
    # Refs #1904: stop-orphaned patch leak 방어. 정상 패스의 with-block /
    # try-finally 는 already stop 했으므로 idempotent. start() 직후
    # stop() 호출 전 예외가 발생한 leak 만 정리한다.
    mock.patch.stopall()
