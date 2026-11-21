"""Ante — AI-Native Trading Engine.

패키지 버전을 단일 출처(pyproject.toml)에서 제공한다.
CLI와 패키징 표면은 이 값을 참조한다.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

_FALLBACK_VERSION = "0.0.0"


def _read_checkout_version() -> str | None:
    """현재 checkout의 pyproject.toml에서 ante 패키지 버전을 읽는다."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        with pyproject.open("rb") as fp:
            data = tomllib.load(fp)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project")
    if not isinstance(project, dict) or project.get("name") != "ante":
        return None
    version = project.get("version")
    return version if isinstance(version, str) else None


def _resolve_version() -> str:
    """공개 버전 표면을 반환."""
    checkout_version = _read_checkout_version()
    if checkout_version is not None:
        return checkout_version
    try:
        return _pkg_version("ante")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


__version__ = _resolve_version()

__all__ = ["__version__"]
