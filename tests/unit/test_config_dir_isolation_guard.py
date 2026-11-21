"""설정 디렉터리 격리 가드의 회귀 테스트 (#2592)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from ante.config.config import resolve_config_dir

REPO_ROOT = Path(__file__).resolve().parents[2]

_written_config_dirs: list[Path] = []


def _is_under(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _forbidden(guard, path: Path) -> bool:
    candidates = {os.path.abspath(path), os.path.realpath(path)}
    return any(
        c == root or c.startswith(root + os.sep)
        for c in candidates
        for root in guard.forbidden_roots
    )


def test_default_config_dir_is_per_test_tmp(tmp_path_factory) -> None:
    basetemp = tmp_path_factory.getbasetemp()
    config_dir = resolve_config_dir()
    assert config_dir.is_absolute(), config_dir
    assert _is_under(config_dir, basetemp), config_dir
    assert _is_under(Path.home(), basetemp), Path.home()


def test_default_config_dir_outside_forbidden_roots(config_isolation_guard) -> None:
    assert not _forbidden(config_isolation_guard, resolve_config_dir())
    assert not _forbidden(config_isolation_guard, Path.home() / ".config" / "ante")


def test_global_path_exists_patch_still_isolated(tmp_path_factory) -> None:
    basetemp = tmp_path_factory.getbasetemp()
    with patch("pathlib.Path.exists", return_value=False):
        config_dir = resolve_config_dir()
    assert config_dir.is_absolute(), config_dir
    assert _is_under(config_dir, basetemp), config_dir


def test_config_dir_fresh_per_test_writer(tmp_path_factory) -> None:
    config_dir = resolve_config_dir()
    # 격리가 없으면 저장소의 config/에 쓰게 되므로 쓰기 전에 멈춘다.
    assert _is_under(config_dir, tmp_path_factory.getbasetemp()), config_dir
    (config_dir / "system.toml").write_text("[marker]\n", encoding="utf-8")
    _written_config_dirs.append(config_dir)


def test_config_dir_fresh_per_test() -> None:
    config_dir = resolve_config_dir()
    assert not (config_dir / "system.toml").exists()
    for written in _written_config_dirs:
        assert written != config_dir
        assert (written / "system.toml").exists()


def test_guard_blocks_open(config_isolation_guard, tmp_path: Path) -> None:
    root = tmp_path / "forbidden"
    root.mkdir()
    with config_isolation_guard.expect_violation(root) as records:
        with pytest.raises(config_isolation_guard.violation_type):
            open(root / "system.toml", "w")  # noqa: SIM115
        with pytest.raises(config_isolation_guard.violation_type):
            open(root / "secrets.env")  # noqa: SIM115
    assert len(records) == 2
    assert not (root / "system.toml").exists()


def test_guard_blocks_sqlite(config_isolation_guard, tmp_path: Path) -> None:
    root = tmp_path / "forbidden"
    root.mkdir()
    with config_isolation_guard.expect_violation(root) as records:
        with pytest.raises(config_isolation_guard.violation_type):
            sqlite3.connect(root / "ante.db")
        with pytest.raises(config_isolation_guard.violation_type):
            sqlite3.connect(f"file:{root / 'ante.db'}?mode=ro", uri=True)
    assert len(records) == 2
    assert not (root / "ante.db").exists()


def test_guard_blocks_mkdir(config_isolation_guard, tmp_path: Path) -> None:
    root = tmp_path / "forbidden"
    root.mkdir()
    with config_isolation_guard.expect_violation(root) as records:
        with pytest.raises(config_isolation_guard.violation_type):
            os.mkdir(root / "db")
        with pytest.raises(config_isolation_guard.violation_type):
            (root / "run").mkdir(parents=True)
    assert len(records) == 2
    assert not (root / "db").exists()


def test_guard_follows_symlink(config_isolation_guard, tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with config_isolation_guard.expect_violation(link) as via_link_root:
        with pytest.raises(config_isolation_guard.violation_type):
            open(real / "system.toml", "w")  # noqa: SIM115
    with config_isolation_guard.expect_violation(real) as via_real_root:
        with pytest.raises(config_isolation_guard.violation_type):
            open(link / "system.toml", "w")  # noqa: SIM115
    assert len(via_link_root) == 1
    assert len(via_real_root) == 1


def test_guard_records_swallowed_violation(
    config_isolation_guard, tmp_path: Path
) -> None:
    root = tmp_path / "forbidden"
    root.mkdir()
    with config_isolation_guard.expect_violation(root) as records:
        try:
            open(root / "system.toml", "w")  # noqa: SIM115
        except Exception:
            pass
    assert len(records) == 1


def test_guard_records_violation_from_thread(
    config_isolation_guard, tmp_path: Path
) -> None:
    root = tmp_path / "forbidden"
    root.mkdir()

    def _touch() -> None:
        try:
            sqlite3.connect(root / "ante.db")
        except Exception:
            pass

    with config_isolation_guard.expect_violation(root) as records:
        thread = threading.Thread(target=_touch)
        thread.start()
        thread.join()
    assert len(records) == 1


def test_guard_blocks_repo_config_but_allows_example_read(
    config_isolation_guard,
) -> None:
    repo_config = REPO_ROOT / "config"
    with config_isolation_guard.expect_violation(repo_config) as records:
        with pytest.raises(config_isolation_guard.violation_type):
            open(repo_config / "system.toml")  # noqa: SIM115
        with open(repo_config / "system.toml.example", encoding="utf-8") as fh:
            assert fh.read(1)
    assert len(records) == 1


def test_forbidden_roots_include_real_and_repo(config_isolation_guard) -> None:
    import pwd

    roots = config_isolation_guard.forbidden_roots
    orig_home = config_isolation_guard.orig_home
    pw_home = pwd.getpwuid(os.getuid()).pw_dir
    assert os.path.abspath(os.path.join(orig_home, ".config", "ante")) in roots
    assert os.path.abspath(os.path.join(pw_home, ".config", "ante")) in roots
    assert os.path.abspath(REPO_ROOT / "config") in roots
    # xdist 작업자가 컨트롤러의 임시 HOME을 원래 값으로 오인하지 않는다.
    assert not any(part.startswith("ante-pytest-") for part in Path(orig_home).parts)
    assert not os.path.abspath(orig_home).startswith(
        os.path.join(tempfile.gettempdir(), "ante-pytest-")
    )
