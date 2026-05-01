"""Refs #1157 — runtime path resolver 회귀 테스트.

`runtime.pid_path`/`runtime.socket_path`을 ``config_dir`` 기준으로 정규화하는
편의 메서드(`Config.runtime_pid_path()`/`runtime_socket_path()`)와 그 소비자
(`main._write_pid_file`/`_remove_pid_file`/`read_pid_file`,
`cli.commands.ipc_helpers.get_socket_path`, account cold-path guard)가 cwd와
무관하게 동일한 절대 경로를 보는지 검증한다.

SSOT:
- ``docs/specs/config/03-design-decisions.md`` (canonical resource table 200-202,
  default 표 280-281)
- ``docs/specs/cli/02-design-decisions.md`` 62-70 (resolver 우선순위)
- ``docs/specs/cli/03-commands.md`` 300-302 (init이 기록하는 키)
- ``docs/specs/ipc/ipc.md`` 181-186 (socket 경로 정의)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ante.config import Config

# ── Task 1: config resolver 회귀 ─────────────────────────────────


def test_runtime_pid_path_default_uses_config_dir(tmp_path: Path) -> None:
    """default 값으로 ``<config_dir>/run/ante.pid`` 절대 경로를 반환해야 한다."""
    config = Config.load(config_dir=tmp_path)

    assert config.runtime_pid_path() == tmp_path / "run" / "ante.pid"


def test_runtime_socket_path_default_uses_config_dir(tmp_path: Path) -> None:
    """default 값으로 ``<config_dir>/run/ante.sock`` 절대 경로를 반환해야 한다."""
    config = Config.load(config_dir=tmp_path)

    assert config.runtime_socket_path() == tmp_path / "run" / "ante.sock"


def test_runtime_pid_path_override_in_toml(tmp_path: Path) -> None:
    """``[runtime] pid_path`` 사용자 override가 적용돼야 한다."""
    (tmp_path / "system.toml").write_text(
        '[runtime]\npid_path = "custom/x.pid"\n', encoding="utf-8"
    )

    config = Config.load(config_dir=tmp_path)

    assert config.runtime_pid_path() == tmp_path / "custom" / "x.pid"


def test_runtime_paths_independent_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cwd가 달라져도 같은 ``config_dir``이면 절대 경로가 동일해야 한다."""
    cwd_a = tmp_path / "cwd_a"
    cwd_b = tmp_path / "cwd_b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    config_dir = tmp_path / "ante-config"
    config_dir.mkdir()

    monkeypatch.chdir(cwd_a)
    pid_a = Config.load(config_dir=config_dir).runtime_pid_path()
    sock_a = Config.load(config_dir=config_dir).runtime_socket_path()

    monkeypatch.chdir(cwd_b)
    pid_b = Config.load(config_dir=config_dir).runtime_pid_path()
    sock_b = Config.load(config_dir=config_dir).runtime_socket_path()

    assert pid_a == pid_b == config_dir / "run" / "ante.pid"
    assert sock_a == sock_b == config_dir / "run" / "ante.sock"


def test_runtime_paths_isolated_per_config_dir(tmp_path: Path) -> None:
    """서로 다른 ``config_dir``은 서로 다른 PID/socket 경로를 반환해야 한다."""
    cfg_a = tmp_path / "a"
    cfg_b = tmp_path / "b"
    cfg_a.mkdir()
    cfg_b.mkdir()

    pid_a = Config.load(config_dir=cfg_a).runtime_pid_path()
    pid_b = Config.load(config_dir=cfg_b).runtime_pid_path()
    sock_a = Config.load(config_dir=cfg_a).runtime_socket_path()
    sock_b = Config.load(config_dir=cfg_b).runtime_socket_path()

    assert pid_a != pid_b
    assert sock_a != sock_b


# ── Task 2: main.py PID 회귀 ─────────────────────────────────────


def test_main_pid_file_uses_runtime_pid_path(tmp_path: Path) -> None:
    """``_write_pid_file(config)``이 ``<config_dir>/run/ante.pid``에 기록해야 한다."""
    from ante.main import _remove_pid_file, _write_pid_file

    config = Config.load(config_dir=tmp_path)
    expected = tmp_path / "run" / "ante.pid"

    try:
        _write_pid_file(config)
        assert expected.exists()
        assert expected.read_text().strip() == str(os.getpid())
    finally:
        _remove_pid_file(config)
        assert not expected.exists()


def test_main_pid_file_independent_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cwd를 바꿔도 PID 파일은 ``config_dir`` 기준 canonical 위치에 기록되어야 한다."""
    from ante.main import _remove_pid_file, _write_pid_file

    config_dir = tmp_path / "ante-config"
    config_dir.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)

    config = Config.load(config_dir=config_dir)
    expected = config_dir / "run" / "ante.pid"

    try:
        _write_pid_file(config)
        assert expected.exists()
        # cwd-relative legacy 경로에는 파일이 없어야 한다
        assert not (other / "db" / "ante.pid").exists()
    finally:
        _remove_pid_file(config)


def test_read_pid_file_zero_arg_uses_canonical_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0-arg form: ``Config.load().runtime_pid_path()`` canonical을 본다."""
    from ante.main import read_pid_file

    config_dir = tmp_path / "ante-config"
    config_dir.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))

    canonical = config_dir / "run" / "ante.pid"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("12345")

    assert read_pid_file() == 12345


def test_read_pid_file_legacy_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """canonical 부재 + legacy ``db/ante.pid`` 존재 → legacy 읽고 warning."""
    from ante import main as main_mod
    from ante.main import read_pid_file

    config_dir = tmp_path / "ante-config"
    config_dir.mkdir()
    cwd = tmp_path / "workdir"
    cwd.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
    monkeypatch.chdir(cwd)

    # 다른 테스트가 이미 deprecation warning을 1회 emit했을 수 있으므로
    # 본 테스트 진입 시점에 모듈 가드를 명시적으로 reset한다 (Refs #1157,
    # plan v3 권고: 1회 emit 전제이므로 테스트 격리만 위해 reset).
    monkeypatch.setattr(main_mod, "_legacy_pid_warning_emitted", False)

    # canonical 부재 — 만들지 않는다
    canonical = config_dir / "run" / "ante.pid"
    assert not canonical.exists()

    # legacy 존재
    legacy = cwd / "db" / "ante.pid"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("9999")

    with caplog.at_level(logging.WARNING, logger="ante.main"):
        result = read_pid_file()

    assert result == 9999
    main_records = [rec for rec in caplog.records if rec.name == "ante.main"]
    assert any("legacy" in rec.message.lower() for rec in main_records)
    # 두 번째 호출에서는 warning이 emit되지 않는다 (1회 emit 가드 회귀)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="ante.main"):
        second = read_pid_file()
    assert second == 9999
    main_records_2 = [rec for rec in caplog.records if rec.name == "ante.main"]
    assert not any("legacy" in rec.message.lower() for rec in main_records_2)


# ── Task 4: ipc_helpers 회귀 ─────────────────────────────────────


def test_get_socket_path_uses_runtime_socket_path(tmp_path: Path) -> None:
    """``get_socket_path(config_dir=...)`` == ``<config_dir>/run/ante.sock``."""
    from ante.cli.commands.ipc_helpers import get_socket_path

    expected = tmp_path / "run" / "ante.sock"
    assert get_socket_path(config_dir=tmp_path) == str(expected)


def test_get_socket_path_isolated_from_db_path_parent(tmp_path: Path) -> None:
    """``db.path``와 무관하게 socket은 ``runtime.socket_path``로만 결정된다."""
    from ante.cli.commands.ipc_helpers import get_socket_path

    (tmp_path / "system.toml").write_text(
        '[db]\npath = "custom_db/x.db"\n\n[runtime]\nsocket_path = "run/ante.sock"\n',
        encoding="utf-8",
    )

    expected = tmp_path / "run" / "ante.sock"
    assert get_socket_path(config_dir=tmp_path) == str(expected)


# ── Task 6: cold-path guard cwd 독립성 ───────────────────────────


def test_account_cold_path_guard_uses_runtime_resolver_under_chdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cwd 이동 후에도 cold-path guard가 ``config_dir`` 기준 socket을 본다."""
    from ante.cli.commands.account import _assert_no_active_runtime
    from ante.cli.formatter import OutputFormatter

    tmp_config = tmp_path / "ante-config"
    tmp_config.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_config))

    tmp_other = tmp_path / "elsewhere"
    tmp_other.mkdir()
    monkeypatch.chdir(tmp_other)

    # config_dir 기준 socket이 존재 → active runtime 표식
    (tmp_config / "run").mkdir()
    (tmp_config / "run" / "ante.sock").touch()

    # 현재 cwd(tmp_other)에는 run/ante.sock 없음 → guard가 cwd 무관임을 입증
    assert not (tmp_other / "run" / "ante.sock").exists()

    fmt = OutputFormatter(fmt="text")

    with patch("ante.main.read_pid_file", return_value=os.getpid()):
        with pytest.raises(SystemExit) as exc_info:
            _assert_no_active_runtime(fmt)

    assert exc_info.value.code == 1
