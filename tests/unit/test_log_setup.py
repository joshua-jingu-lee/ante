"""setup_logging() 단위 테스트.

`docs/specs/logging/05-handlers-and-rotation.md` 의 이중 핸들러 구성과
환경변수 게이트(``ANTE_LOG_JSONL``) 동작을 검증한다.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import pytest

from ante.core.log import (
    DateNamedTimedRotatingFileHandler,
    JsonFormatter,
    setup_logging,
)


class _StubConfig:
    """``Config.get(key, default)`` 계약만 만족하는 최소 더블."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values = values or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """테스트 간 루트 로거 상태를 격리한다."""
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = list(root.handlers)
    for h in list(root.handlers):
        root.removeHandler(h)
    try:
        yield
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


@pytest.fixture(autouse=True)
def _cwd_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``logs/`` 디렉토리 생성이 현재 작업 디렉토리 기준이므로 격리."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ── 1. ANTE_LOG_JSONL 미설정 시 stdout 핸들러 1개만 추가 ───────


def test_stdout_only_when_jsonl_gate_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTE_LOG_JSONL", raising=False)

    setup_logging(_StubConfig())

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)
    assert not isinstance(root.handlers[0], TimedRotatingFileHandler)


# ── 2. ANTE_LOG_JSONL=1 시 stdout + 파일 핸들러 2개 ────────────


def test_dual_handlers_when_jsonl_gate_enabled(
    monkeypatch: pytest.MonkeyPatch,
    _cwd_tmp: Path,
):
    monkeypatch.setenv("ANTE_LOG_JSONL", "1")

    setup_logging(_StubConfig())

    root = logging.getLogger()
    assert len(root.handlers) == 2

    file_handlers = [
        h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)
    ]
    stream_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, TimedRotatingFileHandler)
    ]

    assert len(file_handlers) == 1
    assert len(stream_handlers) == 1

    file_handler = file_handlers[0]
    assert isinstance(file_handler, DateNamedTimedRotatingFileHandler)
    assert isinstance(file_handler.formatter, JsonFormatter)
    assert file_handler.when == "MIDNIGHT"
    assert file_handler.backupCount == 30

    # 활성 파일명 계약: ante-YYYY-MM-DD.jsonl
    name = Path(file_handler.baseFilename).name
    assert re.match(r"^ante-\d{4}-\d{2}-\d{2}\.jsonl$", name), (
        f"활성 파일명이 스펙과 불일치: {name!r}"
    )
    # logs/ 디렉토리 아래에 위치
    assert Path(file_handler.baseFilename).parent.name == "logs"


# ── 3. system.log_level 이 루트 로거 레벨에 반영 ──────────────


@pytest.mark.parametrize(
    "level_name,level_value",
    [
        ("DEBUG", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
    ],
)
def test_log_level_reflected_in_root_logger(
    monkeypatch: pytest.MonkeyPatch,
    level_name: str,
    level_value: int,
):
    monkeypatch.delenv("ANTE_LOG_JSONL", raising=False)

    setup_logging(_StubConfig({"system.log_level": level_name}))

    assert logging.getLogger().level == level_value


def test_log_level_defaults_to_info(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTE_LOG_JSONL", raising=False)

    setup_logging(_StubConfig())

    assert logging.getLogger().level == logging.INFO


# ── 4. 로그 디렉토리 자동 생성 ─────────────────────────────────


def test_logs_directory_auto_created(monkeypatch: pytest.MonkeyPatch, _cwd_tmp: Path):
    monkeypatch.setenv("ANTE_LOG_JSONL", "1")
    log_dir = _cwd_tmp / "logs"
    assert not log_dir.exists()

    setup_logging(_StubConfig())

    assert log_dir.exists()
    assert log_dir.is_dir()


# ── 5. 재호출 시 핸들러 중복 없음 ──────────────────────────────


def test_idempotent_on_repeated_calls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTE_LOG_JSONL", raising=False)

    setup_logging(_StubConfig())
    first_count = len(logging.getLogger().handlers)

    setup_logging(_StubConfig())
    setup_logging(_StubConfig())

    assert len(logging.getLogger().handlers) == first_count == 1


def test_idempotent_on_repeated_calls_with_jsonl(
    monkeypatch: pytest.MonkeyPatch, _cwd_tmp: Path
):
    monkeypatch.setenv("ANTE_LOG_JSONL", "1")

    setup_logging(_StubConfig())
    setup_logging(_StubConfig())
    setup_logging(_StubConfig())

    assert len(logging.getLogger().handlers) == 2


# ── 6. 파일 핸들러 초기화 실패 격리 ────────────────────────────


def test_file_handler_failure_does_not_break_stdout(
    monkeypatch: pytest.MonkeyPatch,
    _cwd_tmp: Path,
):
    """디스크 가득/권한 등 파일 핸들러 초기화 실패 시 stdout만 유지하고 진행."""
    monkeypatch.setenv("ANTE_LOG_JSONL", "1")

    def _raise(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("disk full (simulated)")

    # DateNamedTimedRotatingFileHandler 생성자에서 OSError 발생시키기.
    # setup.py 는 게이트 내부에서 handlers 모듈을 지연 import 하므로
    # 패치 타깃은 handlers 모듈이어야 한다.
    import ante.core.log.handlers as handlers_mod

    monkeypatch.setattr(handlers_mod, "DateNamedTimedRotatingFileHandler", _raise)

    # 예외가 전파되지 않아야 한다
    setup_logging(_StubConfig())

    root = logging.getLogger()
    # stdout 핸들러 1개만 살아있다
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)
    assert not isinstance(root.handlers[0], TimedRotatingFileHandler)


def test_file_handler_mkdir_failure_does_not_break_stdout(
    monkeypatch: pytest.MonkeyPatch,
    _cwd_tmp: Path,
):
    """``logs/`` 디렉토리 생성 실패도 stdout 전용으로 흡수된다."""
    monkeypatch.setenv("ANTE_LOG_JSONL", "1")

    original_mkdir = Path.mkdir

    def _raise_for_logs(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if self.name == "logs":
            raise PermissionError("permission denied (simulated)")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _raise_for_logs)

    # 예외가 전파되지 않아야 한다
    setup_logging(_StubConfig())

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)
    assert not isinstance(root.handlers[0], TimedRotatingFileHandler)


# ── 7. no-rename 회전 계약 검증 ─────────────────────────────

# 회전 계약 (`docs/specs/logging/05-handlers-and-rotation.md`):
#   1) 활성 파일명에 날짜가 포함되므로 기존 파일은 rename 되지 않는다
#   2) 자정에 baseFilename 이 새 날짜 파일로 교체되고 새 파일이 열린다
#   3) 회전 전에 기록된 엔트리는 이전 날 파일에 그대로 남아 있다
#   4) 회전 후 emit() 호출은 새 파일에 기록된다


def test_rollover_preserves_previous_file_and_opens_new_date(
    monkeypatch: pytest.MonkeyPatch,
    _cwd_tmp: Path,
):
    """no-rename 회전 계약: 기존 파일은 내용 보존 + 새 날짜 파일이 열린다."""
    log_dir = _cwd_tmp / "logs"
    log_dir.mkdir()

    handler = DateNamedTimedRotatingFileHandler(
        log_dir,
        prefix="ante",
        file_suffix=".jsonl",
        backup_count=30,
    )
    try:
        handler.setFormatter(logging.Formatter("%(message)s"))

        # 1) 오늘 파일에 엔트리 기록
        initial_path = Path(handler.baseFilename)
        initial_name = initial_path.name
        assert re.match(r"^ante-\d{4}-\d{2}-\d{2}\.jsonl$", initial_name)

        pre_rollover_record = logging.LogRecord(
            name="ante.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="PRE_ROLLOVER_ENTRY",
            args=None,
            exc_info=None,
        )
        handler.emit(pre_rollover_record)
        handler.flush()

        # 기록이 실제로 디스크에 반영됐는지 확인
        pre_content = initial_path.read_text(encoding="utf-8")
        assert "PRE_ROLLOVER_ENTRY" in pre_content

        # 2) _make_filename() 을 "다음 날" 로 monkeypatch
        next_day = "ante-2099-01-01.jsonl"
        next_path = log_dir / next_day
        monkeypatch.setattr(
            handler,
            "_make_filename",
            lambda: str(next_path),
        )

        # 3) 회전 실행
        handler.doRollover()

        # 4) 어서션: no-rename 계약
        #    (a) baseFilename 이 새 날짜 파일로 교체됨
        assert Path(handler.baseFilename).name == next_day

        #    (b) 기존 파일이 여전히 존재하고 기록된 엔트리를 보존
        assert initial_path.exists(), (
            f"기존 파일이 사라졌다 (rename 의심): {initial_name}"
        )
        assert "PRE_ROLLOVER_ENTRY" in initial_path.read_text(encoding="utf-8"), (
            "기존 파일 내용이 손실됨 — no-rename 계약 위반"
        )

        #    (c) 새 날짜 파일이 생성됨
        assert next_path.exists(), "새 baseFilename 파일이 열리지 않음"

        #    (d) 기존 파일이 ".bak" / 무날짜 ante.jsonl 등으로 rename 되지 않음
        suspicious = [
            p.name for p in log_dir.iterdir() if p.name not in {initial_name, next_day}
        ]
        assert suspicious == [], (
            f"회전 과정에서 예상 외 파일이 생성됨 (rename 의심): {suspicious}"
        )
        assert not (log_dir / "ante.jsonl").exists(), (
            "무날짜 활성 파일이 생성됨 — 표준 TimedRotatingFileHandler 로 회귀"
        )
        for bak_pattern in (".bak", ".1", ".old"):
            assert not (log_dir / f"{initial_name}{bak_pattern}").exists(), (
                f"기존 파일이 {bak_pattern} suffix 로 rename 됨"
            )

        # 5) 회전 후 emit() 이 새 파일에 기록되는지 검증
        post_rollover_record = logging.LogRecord(
            name="ante.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="POST_ROLLOVER_ENTRY",
            args=None,
            exc_info=None,
        )
        handler.emit(post_rollover_record)
        handler.flush()

        # 새 파일에만 POST 엔트리가 있어야 한다
        assert next_path.stat().st_size > 0
        assert "POST_ROLLOVER_ENTRY" in next_path.read_text(encoding="utf-8")
        # 기존 파일에는 POST 엔트리가 없어야 한다 (스트림이 전환됐음을 확인)
        assert "POST_ROLLOVER_ENTRY" not in initial_path.read_text(encoding="utf-8")
    finally:
        handler.close()


# ── 7b. 게이트-off 경로 tzdata 독립성 ────


def test_gate_off_does_not_trigger_zoneinfo(monkeypatch: pytest.MonkeyPatch):
    """``ANTE_LOG_JSONL`` 미설정 시 ``ZoneInfo("Asia/Seoul")`` 가 호출되지 않는다.

    스펙 ``docs/specs/logging/02-design-decisions.md`` 의 "미설정 시 기존 동작
    유지" 계약. tzdata 가 없는 경량 컨테이너에서 부팅 경로가
    ``ZoneInfoNotFoundError`` 로 깨지지 않도록 보호한다.
    """
    monkeypatch.delenv("ANTE_LOG_JSONL", raising=False)

    import ante.core.log.handlers as handlers_mod

    # _KST 캐시가 이전 테스트로 이미 채워졌을 수 있으므로 초기화
    monkeypatch.setattr(handlers_mod, "_KST", None)

    call_count = {"n": 0}
    original = handlers_mod.ZoneInfo

    def _tracked_zoneinfo(key: str):  # noqa: ANN202
        call_count["n"] += 1
        return original(key)

    monkeypatch.setattr(handlers_mod, "ZoneInfo", _tracked_zoneinfo)

    setup_logging(_StubConfig())

    assert call_count["n"] == 0, (
        "게이트-off 경로에서 ZoneInfo 가 호출됨 — tzdata 의존 회귀"
    )


def test_cold_import_gate_off_does_not_call_zoneinfo(
    monkeypatch: pytest.MonkeyPatch,
):
    """Cold import 회귀 고정: fresh Python process 부팅 경로를 재현한다.

    실제 부팅 경로는 ``src/ante/main.py`` 의 ``from ante.core.log import
    setup_logging`` 으로 시작하고, 이 import 가 ``ante.core.log.__init__`` →
    ``ante.core.log.handlers`` 까지 함께 로드한다. tzdata 가 없는
    ``python:3.12-slim`` 기반 경량 이미지에서 과거처럼
    ``_KST = ZoneInfo("Asia/Seoul")`` 을 handlers 모듈 레벨에 두면 이 import
    만으로도 ``ZoneInfoNotFoundError`` 가 발생해 경량 컨테이너 부팅이 중단된다.

    본 테스트는 ``sys.modules`` 에서 ``ante.core.log.*`` 를 제거해 다음 import
    를 "콜드" 로 만들고, 그 직전에 ``zoneinfo.ZoneInfo`` 를 추적 래퍼로 교체한다.
    이어서 콜드 import + 게이트-off ``setup_logging()`` 까지 수행한 뒤
    ``ZoneInfo("Asia/Seoul")`` 호출이 0 회임을 검증한다. 모듈-레벨 ``ZoneInfo``
    회귀가 들어오면 handlers import 시점에 카운터가 증가해 이 테스트가 실패한다.
    """
    import importlib
    import sys
    import zoneinfo

    # 1) zoneinfo.ZoneInfo 추적기 설치.
    #    handlers 모듈이 콜드 재import 될 때 ``from zoneinfo import ZoneInfo``
    #    가 이 패치된 속성을 집도록, 재import 보다 먼저 설치해야 한다.
    call_tracker: list[str] = []
    original_zoneinfo = zoneinfo.ZoneInfo

    def _tracked(key: str, *args: Any, **kwargs: Any) -> Any:
        call_tracker.append(key)
        return original_zoneinfo(key, *args, **kwargs)

    monkeypatch.setattr(zoneinfo, "ZoneInfo", _tracked)

    # 2) ante.core.log.* 를 sys.modules 에서 제거해 다음 import 를 콜드로 강제.
    for name in list(sys.modules):
        if name == "ante.core.log" or name.startswith("ante.core.log."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    # 3) main.py 부팅 경로 재현: 게이트 off.
    monkeypatch.delenv("ANTE_LOG_JSONL", raising=False)

    # 4) 콜드 import (handlers 모듈-레벨 코드가 재실행된다) + setup_logging().
    log_pkg = importlib.import_module("ante.core.log")
    log_pkg.setup_logging(_StubConfig())

    # 5) ZoneInfo("Asia/Seoul") 는 한 번도 호출되면 안 된다.
    seoul_calls = [k for k in call_tracker if k == "Asia/Seoul"]
    assert seoul_calls == [], (
        f"Cold import + 게이트-off 경로에서 ZoneInfo('Asia/Seoul') 가 "
        f"{len(seoul_calls)} 회 호출됨 — tzdata 부재 경량 이미지 부팅 차단 회귀. "
        f"전체 호출 기록: {call_tracker}"
    )


# ── 8. backup_count 초과 시 가장 오래된 파일 삭제 ─────────────


def test_rollover_deletes_oldest_files_beyond_backup_count(
    monkeypatch: pytest.MonkeyPatch,
    _cwd_tmp: Path,
):
    """``backup_count=2`` 에서 이미 3개 파일이 있다면 회전 후 가장 오래된 1개 삭제."""
    log_dir = _cwd_tmp / "logs"
    log_dir.mkdir()

    # 더미 옛날 파일들 (오름차순 정렬 시 가장 오래된 것이 맨 앞)
    old1 = log_dir / "ante-2024-01-01.jsonl"
    old2 = log_dir / "ante-2024-06-01.jsonl"
    old3 = log_dir / "ante-2025-01-01.jsonl"
    for p in (old1, old2, old3):
        p.write_text("dummy\n", encoding="utf-8")

    handler = DateNamedTimedRotatingFileHandler(
        log_dir,
        prefix="ante",
        file_suffix=".jsonl",
        backup_count=2,
    )
    try:
        # 회전 후 새 파일명
        next_day = "ante-2099-01-01.jsonl"
        monkeypatch.setattr(
            handler,
            "_make_filename",
            lambda: str(log_dir / next_day),
        )

        handler.doRollover()

        # backup_count=2 이므로 활성 파일 제외 최대 2개만 남아야 한다
        remaining = sorted(p.name for p in log_dir.glob("ante-*.jsonl"))
        # 활성 파일 + 최신 2개 backup 유지; 가장 오래된 old1 은 삭제
        assert old1.name not in remaining, (
            f"가장 오래된 파일이 삭제되지 않음: {remaining}"
        )
        # 활성 파일은 보존
        assert next_day in remaining
    finally:
        handler.close()
