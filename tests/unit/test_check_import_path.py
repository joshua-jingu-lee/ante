"""Import path guard tests (#1236)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_import_guard() -> ModuleType:
    guard_path = REPO_ROOT / "scripts" / "check_import_path.py"
    spec = importlib.util.spec_from_file_location("check_import_path", guard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import guard: {guard_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_import_path_accepts_current_worktree(tmp_path: Path) -> None:
    guard = _load_import_guard()
    expected = tmp_path / "repo" / "src" / "ante" / "__init__.py"
    expected.parent.mkdir(parents=True)
    expected.write_text("", encoding="utf-8")

    result = guard.validate_import_path(
        actual_path=expected,
        project_root=tmp_path / "repo",
    )

    assert result.actual_path == expected.resolve()
    assert result.expected_package_dir == expected.parent.resolve()


def test_validate_import_path_rejects_other_checkout(tmp_path: Path) -> None:
    guard = _load_import_guard()
    project_root = tmp_path / "repo"
    expected = project_root / "src" / "ante" / "__init__.py"
    expected.parent.mkdir(parents=True)
    expected.write_text("", encoding="utf-8")
    actual = tmp_path / "other" / "src" / "ante" / "__init__.py"
    actual.parent.mkdir(parents=True)
    actual.write_text("", encoding="utf-8")

    with pytest.raises(guard.ImportPathCheckError) as exc_info:
        guard.validate_import_path(actual_path=actual, project_root=project_root)

    message = str(exc_info.value)
    assert f"expected repo root: {project_root.resolve()}" in message
    assert f"expected package dir: {expected.parent.resolve()}" in message
    assert f"actual import path: {actual.resolve()}" in message
    assert "PYTHONPATH=$PWD/src" in message


def test_cli_reports_current_checkout(capsys: pytest.CaptureFixture[str]) -> None:
    guard = _load_import_guard()
    assert guard.main(["--repo-root", str(REPO_ROOT)]) == 0

    captured = capsys.readouterr()
    assert "OK: ante imports from" in captured.out
    assert str((REPO_ROOT / "src" / "ante").resolve()) in captured.out
