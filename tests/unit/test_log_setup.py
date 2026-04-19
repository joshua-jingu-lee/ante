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

    # DateNamedTimedRotatingFileHandler 생성자에서 OSError 발생시키기
    import ante.core.log.setup as setup_mod

    monkeypatch.setattr(setup_mod, "DateNamedTimedRotatingFileHandler", _raise)

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
