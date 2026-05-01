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


def test_read_pid_file_returns_none_when_only_legacy_pid_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """canonical 부재 + legacy ``db/ante.pid``만 존재 → None, warning 없음.

    Refs #1157, docs/specs/config/03-design-decisions.md (1.0 단일 active
    runtime 정책). 1.0 single-canonical resolver 모델에서 legacy cwd-relative
    read-fallback은 비대칭이므로 cutover로 제거되었다. 본 테스트는 그 회귀를
    보호한다 — 새 ``read_pid_file``은 canonical만 보고, legacy는 무시하며,
    deprecation warning도 emit하지 않는다. (legacy unlink는 ``_remove_pid_file``
    이 별도로 책임진다.)
    """
    from ante.main import read_pid_file

    config_dir = tmp_path / "ante-config"
    config_dir.mkdir()
    cwd = tmp_path / "workdir"
    cwd.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
    monkeypatch.chdir(cwd)

    # canonical 부재 — 만들지 않는다
    canonical = config_dir / "run" / "ante.pid"
    assert not canonical.exists()

    # legacy 존재 (cwd 기준 ``db/ante.pid``)
    legacy = cwd / "db" / "ante.pid"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("9999")

    with caplog.at_level(logging.WARNING, logger="ante.main"):
        result = read_pid_file()

    # legacy 무시 → None 반환
    assert result is None
    # ``ante.main`` logger에서 legacy 관련 warning이 한 건도 emit되지 않아야 한다
    main_records = [rec for rec in caplog.records if rec.name == "ante.main"]
    assert not any("legacy" in rec.message.lower() for rec in main_records)


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


# ── #1160: startup booting marker cold-path guard ────────────────


def test_account_cold_path_guard_blocks_during_booting_with_matching_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PID alive + socket absent여도 matching marker가 있으면 starting으로 차단."""
    from ante.cli.commands.account import _assert_no_active_runtime
    from ante.cli.formatter import OutputFormatter
    from ante.main import _write_pid_file, _write_starting_marker

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
    config = Config.load(config_dir=tmp_path)
    _write_starting_marker(config)
    _write_pid_file(config)

    assert not config.runtime_socket_path().exists()

    fmt = OutputFormatter(fmt="text")
    with pytest.raises(SystemExit) as exc_info:
        _assert_no_active_runtime(fmt)

    assert exc_info.value.code == 1


def test_account_cold_path_guard_passes_when_marker_has_different_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """다른 PID가 적힌 marker는 stale/recycled marker로 보고 통과한다."""
    from ante.cli.commands.account import _assert_no_active_runtime
    from ante.cli.formatter import OutputFormatter
    from ante.main import _starting_marker_path, _write_pid_file

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
    config = Config.load(config_dir=tmp_path)
    _write_pid_file(config)
    marker = _starting_marker_path(config)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(os.getpid() + 1))

    assert not config.runtime_socket_path().exists()

    _assert_no_active_runtime(OutputFormatter(fmt="text"))


def test_account_cold_path_guard_passes_when_neither_socket_nor_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PID alive지만 socket/marker가 모두 없으면 기존 stale 판정을 유지한다."""
    from ante.cli.commands.account import _assert_no_active_runtime
    from ante.cli.formatter import OutputFormatter
    from ante.main import _write_pid_file

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
    config = Config.load(config_dir=tmp_path)
    _write_pid_file(config)

    assert not config.runtime_socket_path().exists()

    _assert_no_active_runtime(OutputFormatter(fmt="text"))


def test_account_cold_path_guard_passes_when_marker_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """손상된 marker는 stale marker로 보고 차단하지 않는다."""
    from ante.cli.commands.account import _assert_no_active_runtime
    from ante.cli.formatter import OutputFormatter
    from ante.main import _starting_marker_path, _write_pid_file

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
    config = Config.load(config_dir=tmp_path)
    _write_pid_file(config)
    marker = _starting_marker_path(config)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("not-a-pid")

    assert not config.runtime_socket_path().exists()

    _assert_no_active_runtime(OutputFormatter(fmt="text"))


# ── Codex attempt 1 P1 회귀: --config-dir 경로 PID 격리 ─────────────
#
# `read_pid_file()` 0-arg 분기는 `Config.load()` → `resolve_config_dir(None)` →
# env `ANTE_CONFIG_DIR` 또는 default를 본다. CLI 호출부가 ctx의 `--config-dir A`를
# env에 주입하지 않은 채 0-arg로 호출하면, A가 아니라 default config_dir의 PID를
# 본다. 결과:
#   - `system stop`: A의 server PID를 못 찾음 → 잘못된 PID_NOT_FOUND
#   - account cold-path guard: A의 alive server를 누락 → split-brain mutation 허용
#   - update.check_server_running: A의 server를 못 찾음 → server 중에 update 진행
#
# 아래 3개 테스트는 default와 다른 ``config_dir`` A를 ``--config-dir``로 명시해
# 호출했을 때, 각 가드가 *A* 의 canonical PID 파일을 정확히 보는지 검증한다.
# `ante.main.read_pid_file`을 monkeypatch하지 않고 실제 파일을 통해 검증하므로,
# CLI 호출부가 명시적 ``Config``를 전달하지 않으면 이 테스트가 깨진다 (attempt 1
# 재현). 호출부 수정 후에는 GREEN.


def test_system_start_uses_explicit_config_dir_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``system start``가 ``--config-dir`` A의 canonical PID를 본다.

    Attempt 1 P1 finding 재현: A에 alive PID가 있고 default config_dir에는
    PID 파일이 없는 환경에서, ``ante --config-dir A system start``가 default를
    봐 A의 server를 누락하면 ``ALREADY_RUNNING`` 차단을 우회해 중복 실행
    위험이 발생한다. 명시적 ``Config`` 전달 후에는 A를 정확히 보고 차단해야
    한다.
    """
    from click.testing import CliRunner

    from ante.cli.main import cli
    from ante.member.models import Member, MemberRole, MemberType

    mock_master = Member(
        member_id="test-master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Test Master",
        status="active",
        scopes=[],
    )

    cfg_a = tmp_path / "config-a"
    cfg_a.mkdir()
    cfg_default = tmp_path / "default-config"
    cfg_default.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    # default와 다른 경로
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(cfg_default))
    monkeypatch.chdir(cwd)

    # A에 alive PID (self pid). default에는 PID 없음.
    (cfg_a / "run").mkdir()
    (cfg_a / "run" / "ante.pid").write_text(str(os.getpid()))
    assert not (cfg_default / "run" / "ante.pid").exists()

    runner = CliRunner()
    # 인증 우회: ``authenticate_member``를 mock해 master 멤버를 ctx.obj에 주입.
    with patch("ante.cli.main.authenticate_member") as mock_auth:

        def _set_member(ctx) -> None:  # type: ignore[no-untyped-def]
            ctx.ensure_object(dict)
            ctx.obj["member"] = mock_master

        mock_auth.side_effect = _set_member

        # _is_process_alive는 self pid에 대해 True를 반환해야 한다 (alive PID).
        # subprocess.run이 호출되면 안 된다 — ALREADY_RUNNING으로 차단되어야 함.
        with patch(
            "ante.cli.commands.system._is_process_alive", return_value=True
        ) as mock_alive:
            with patch("ante.cli.commands.system.subprocess.run") as mock_subprocess:
                result = runner.invoke(
                    cli,
                    ["--config-dir", str(cfg_a), "system", "start"],
                    catch_exceptions=False,
                )

    # 명시 전달이 안 되어 default를 보면 PID 파일 부재로 ALREADY_RUNNING이
    # 발동하지 않고 subprocess가 실행된다 (중복 실행 위험).
    assert result.exit_code == 1, (
        f"start가 A의 alive PID를 무시하고 진행함 (중복 실행 위험). "
        f"exit_code={result.exit_code}, output={result.output!r}"
    )
    assert "ALREADY_RUNNING" in result.output or "이미 실행 중" in result.output, (
        f"start가 default config_dir만 봐 A의 alive PID를 누락 — "
        f"중복 실행 차단 실패. output={result.output!r}"
    )
    mock_subprocess.assert_not_called()
    mock_alive.assert_called_with(os.getpid())


def test_account_cold_path_guard_uses_explicit_config_dir_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cold-path guard가 ``--config-dir`` A의 canonical PID/socket을 본다.

    A에 alive PID + socket 둘 다 있고 default에는 둘 다 없을 때, cold-path
    guard는 A 기준으로 active runtime을 감지해 차단해야 한다.
    """
    import click

    from ante.cli.commands.account import _assert_no_active_runtime
    from ante.cli.formatter import OutputFormatter

    cfg_a = tmp_path / "config-a"
    cfg_a.mkdir()
    cfg_default = tmp_path / "default-config"
    cfg_default.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(cfg_default))
    monkeypatch.chdir(cwd)

    # A: alive PID + socket
    (cfg_a / "run").mkdir()
    (cfg_a / "run" / "ante.pid").write_text(str(os.getpid()))
    (cfg_a / "run" / "ante.sock").touch()

    # default: 비어 있음
    assert not (cfg_default / "run" / "ante.pid").exists()
    assert not (cfg_default / "run" / "ante.sock").exists()

    fmt = OutputFormatter(fmt="text")

    # ctx.obj["config_dir"]에 A를 넣어 get_config_dir()이 A를 반환하도록 한다.
    @click.command()
    def _runner() -> None:
        _assert_no_active_runtime(fmt)

    runner_ctx = click.Context(_runner, obj={"config_dir": cfg_a})
    with runner_ctx:
        with pytest.raises(SystemExit) as exc_info:
            _assert_no_active_runtime(fmt)

    assert exc_info.value.code == 1, (
        f"cold-path guard가 A의 active runtime을 감지하지 못했다 — "
        f"default config_dir만 본 것. exit_code={exc_info.value.code}"
    )


def test_update_check_server_running_uses_explicit_config_dir_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``update.check_server_running``이 ``--config-dir`` A의 PID를 본다.

    A에 alive PID가 있고 default에는 없을 때 ``check_server_running()``이
    True를 반환해야 한다. default를 보면 False가 되어 update가 server
    실행 중에 진행될 수 있다.
    """
    import click

    from ante.cli.commands.update import check_server_running

    cfg_a = tmp_path / "config-a"
    cfg_a.mkdir()
    cfg_default = tmp_path / "default-config"
    cfg_default.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(cfg_default))
    monkeypatch.chdir(cwd)

    # A: alive PID (self pid)
    (cfg_a / "run").mkdir()
    (cfg_a / "run" / "ante.pid").write_text(str(os.getpid()))

    # default: 비어 있음
    assert not (cfg_default / "run" / "ante.pid").exists()

    @click.command()
    def _runner() -> None:
        pass

    runner_ctx = click.Context(_runner, obj={"config_dir": cfg_a})
    with runner_ctx:
        result = check_server_running()

    assert result is True, (
        "update.check_server_running이 A의 alive PID를 감지하지 못했다 — "
        "default config_dir만 본 것."
    )
