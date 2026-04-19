"""setup_logging() 단위 테스트.

`docs/specs/logging/05-handlers-and-rotation.md` 의 이중 핸들러 구성과
환경변수 게이트(``ANTE_LOG_JSONL``) 동작을 검증한다.
"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import pytest

from ante.core.log import JsonFormatter, setup_logging


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
    assert isinstance(file_handler.formatter, JsonFormatter)
    assert file_handler.when == "MIDNIGHT"
    assert file_handler.backupCount == 30
    assert file_handler.suffix == "%Y-%m-%d"
    assert Path(file_handler.baseFilename).name == "ante.jsonl"


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
