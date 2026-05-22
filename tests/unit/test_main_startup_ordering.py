"""Refs #1160 — startup booting marker ordering tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from ante.config import Config


def test_starting_marker_path_derives_from_runtime_pid_dir(tmp_path: Path) -> None:
    """Marker는 canonical runtime PID directory에서 파생된다."""
    from ante.main import _starting_marker_path

    config = Config.load(config_dir=tmp_path)

    assert _starting_marker_path(config) == tmp_path / "run" / ".starting"


def test_write_starting_marker_creates_file_with_current_pid(
    tmp_path: Path,
) -> None:
    """Marker write는 현재 PID를 기록한다."""
    from ante.main import (
        _read_starting_marker_pid,
        _remove_starting_marker,
        _starting_marker_path,
        _write_starting_marker,
    )

    config = Config.load(config_dir=tmp_path)
    try:
        _write_starting_marker(config)

        assert _starting_marker_path(config).exists()
        assert _read_starting_marker_pid(config) == os.getpid()
    finally:
        _remove_starting_marker(config)


def test_remove_starting_marker_unlinks_file(tmp_path: Path) -> None:
    """Marker remove는 기존 marker를 제거한다."""
    from ante.main import (
        _remove_starting_marker,
        _starting_marker_path,
        _write_starting_marker,
    )

    config = Config.load(config_dir=tmp_path)
    _write_starting_marker(config)

    _remove_starting_marker(config)

    assert not _starting_marker_path(config).exists()


def test_remove_starting_marker_safe_when_missing(tmp_path: Path) -> None:
    """Marker가 없어도 cleanup은 예외를 내지 않는다."""
    from ante.main import _remove_starting_marker, _starting_marker_path

    config = Config.load(config_dir=tmp_path)

    _remove_starting_marker(config)

    assert not _starting_marker_path(config).exists()


def test_read_starting_marker_pid_returns_none_when_absent_or_corrupt(
    tmp_path: Path,
) -> None:
    """Marker 부재/손상은 stale marker로 해석된다."""
    from ante.main import _read_starting_marker_pid, _starting_marker_path

    config = Config.load(config_dir=tmp_path)
    marker = _starting_marker_path(config)

    assert _read_starting_marker_pid(config) is None

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("not-a-pid")

    assert _read_starting_marker_pid(config) is None


@pytest.mark.asyncio
async def test_main_writes_marker_before_pid_and_removes_after_init_ipc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main()은 marker → PID → IPC ready → marker 제거 순서를 보존한다."""
    import ante.db.migrations as migrations
    import ante.main as main_module
    import ante.update.checker as update_checker

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        main_module,
        "_LEGACY_PID_FALLBACK",
        tmp_path / "legacy" / "ante.pid",
    )

    calls: list[str] = []

    original_write_marker = main_module._write_starting_marker
    original_write_pid = main_module._write_pid_file
    original_remove_marker = main_module._remove_starting_marker

    def tracked_write_marker(config: Config) -> None:
        calls.append("write_marker")
        original_write_marker(config)

    def tracked_write_pid(config: Config) -> None:
        calls.append("write_pid")
        original_write_pid(config)

    def tracked_remove_marker(config: Config) -> None:
        calls.append("remove_marker")
        original_remove_marker(config)

    monkeypatch.setattr(main_module, "_write_starting_marker", tracked_write_marker)
    monkeypatch.setattr(main_module, "_write_pid_file", tracked_write_pid)
    monkeypatch.setattr(main_module, "_remove_starting_marker", tracked_remove_marker)

    async def fake_check_update_on_startup() -> None:
        return None

    async def fake_run_migrations(db: object, data_path: Path) -> list[str]:
        return []

    monkeypatch.setattr(
        update_checker, "check_update_on_startup", fake_check_update_on_startup
    )
    monkeypatch.setattr(migrations, "run_migrations", fake_run_migrations)

    async def fake_init_core(s: main_module.Services) -> None:
        calls.append("init_core")
        s.db = object()

    async def fake_init_ipc(s: main_module.Services) -> None:
        assert s.config is not None
        calls.append("init_ipc")
        assert main_module._read_starting_marker_pid(s.config) == os.getpid()
        assert s.config.runtime_pid_path().exists()
        s.config.runtime_socket_path().parent.mkdir(parents=True, exist_ok=True)
        s.config.runtime_socket_path().touch()

    async def fake_run(s: main_module.Services) -> None:
        assert s.config is not None
        calls.append("run")
        assert not main_module._starting_marker_path(s.config).exists()
        assert s.config.runtime_pid_path().exists()

    async def fake_init_step(s: main_module.Services) -> None:
        return None

    for name in (
        "_init_services",
        "_init_account",
        "_init_trading",
        "_init_gateway",
        "_init_feed",
        "_init_approval",
        "_init_notification",
    ):
        monkeypatch.setattr(main_module, name, fake_init_step)
    monkeypatch.setattr(main_module, "_init_core", fake_init_core)
    monkeypatch.setattr(main_module, "_init_ipc", fake_init_ipc)
    monkeypatch.setattr(main_module, "_run", fake_run)

    await main_module.main()

    config = Config.load(config_dir=tmp_path)
    assert not main_module._starting_marker_path(config).exists()
    assert not config.runtime_pid_path().exists()
    assert calls[:4] == ["write_marker", "write_pid", "init_core", "init_ipc"]
    assert calls[calls.index("init_ipc") + 1] == "remove_marker"
    assert calls[-1] == "remove_marker"


@pytest.mark.asyncio
async def test_main_removes_marker_on_init_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """초기화 실패 시에도 marker와 PID를 cleanup한다."""
    import ante.main as main_module

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        main_module,
        "_LEGACY_PID_FALLBACK",
        tmp_path / "legacy" / "ante.pid",
    )

    async def failing_init_core(s: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "_init_core", failing_init_core)

    with pytest.raises(RuntimeError, match="boom"):
        await main_module.main()

    config = Config.load(config_dir=tmp_path)
    assert not main_module._starting_marker_path(config).exists()
    assert not config.runtime_pid_path().exists()
