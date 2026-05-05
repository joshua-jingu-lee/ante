#!/usr/bin/env python3
"""Fail fast when local validation imports Ante from another checkout."""

from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PACKAGE = "ante"


@dataclass(frozen=True)
class ImportPathResult:
    package: str
    project_root: Path
    expected_package_dir: Path
    expected_init: Path
    actual_path: Path


class ImportPathCheckError(RuntimeError):
    """Raised when a package resolves outside the current worktree."""


def _default_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _expected_package_dir(project_root: Path, package: str) -> Path:
    package_path = Path(*package.split("."))
    return (project_root / "src" / package_path).resolve()


def _recovery_command() -> str:
    return "PYTHONPATH=$PWD/src .venv/bin/python scripts/check_import_path.py"


def _format_failure(
    *,
    package: str,
    project_root: Path,
    expected_package_dir: Path,
    expected_init: Path,
    actual: str,
) -> str:
    return "\n".join(
        [
            f"Import path sanity check failed for package '{package}'.",
            f"expected repo root: {project_root}",
            f"expected package dir: {expected_package_dir}",
            f"expected package init: {expected_init}",
            f"actual import path: {actual}",
            f"recovery: {_recovery_command()}",
        ]
    )


def validate_import_path(
    *,
    actual_path: Path,
    project_root: Path,
    package: str = DEFAULT_PACKAGE,
) -> ImportPathResult:
    project_root = project_root.resolve()
    expected_package_dir = _expected_package_dir(project_root, package)
    expected_init = expected_package_dir / "__init__.py"
    actual_path = actual_path.resolve()

    try:
        actual_path.relative_to(expected_package_dir)
    except ValueError as exc:
        raise ImportPathCheckError(
            _format_failure(
                package=package,
                project_root=project_root,
                expected_package_dir=expected_package_dir,
                expected_init=expected_init,
                actual=str(actual_path),
            )
        ) from exc

    return ImportPathResult(
        package=package,
        project_root=project_root,
        expected_package_dir=expected_package_dir,
        expected_init=expected_init,
        actual_path=actual_path,
    )


def check_import_path(
    project_root: Path | None = None,
    *,
    package: str = DEFAULT_PACKAGE,
) -> ImportPathResult:
    project_root = (project_root or _default_project_root()).resolve()
    expected_package_dir = _expected_package_dir(project_root, package)
    expected_init = expected_package_dir / "__init__.py"

    try:
        module = importlib.import_module(package)
    except Exception as exc:  # pragma: no cover - exact import errors vary by env
        raise ImportPathCheckError(
            _format_failure(
                package=package,
                project_root=project_root,
                expected_package_dir=expected_package_dir,
                expected_init=expected_init,
                actual=f"<import failed: {exc}>",
            )
        ) from exc

    module_file = getattr(module, "__file__", None)
    if module_file is None:
        raise ImportPathCheckError(
            _format_failure(
                package=package,
                project_root=project_root,
                expected_package_dir=expected_package_dir,
                expected_init=expected_init,
                actual="<module has no __file__>",
            )
        )

    return validate_import_path(
        actual_path=Path(module_file),
        project_root=project_root,
        package=package,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that Ante imports from the current worktree.",
    )
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--repo-root", type=Path, default=_default_project_root())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = check_import_path(args.repo_root, package=args.package)
    except ImportPathCheckError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        f"OK: {result.package} imports from {result.actual_path} "
        f"(expected under {result.expected_package_dir})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
