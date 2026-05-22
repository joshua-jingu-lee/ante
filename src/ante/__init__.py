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
    """현재 checkout의 pyproject.toml에서 ante 패키지 버전을 읽는다.

    src layout(`src/ante/__init__.py`) 기준, 두 단계 위 디렉터리(repo root)에서
    `pyproject.toml`을 찾고 `[project].name == "ante"`일 때만 그 버전을 반환한다.
    site-packages 배치(휠 설치 등)에서는 인접 pyproject.toml이 없으므로 None.
    """
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
    """공개 버전 표면을 반환.

    1) 현재 checkout의 pyproject.toml(SSOT) — `PYTHONPATH=$PWD/src` 등
       editable/소스 실행 경로에서도 일관된 버전을 노출하기 위함.
    2) 설치된 패키지 메타데이터 — 휠 설치 환경에서 사용.
    3) 최종 폴백.
    """
    checkout_version = _read_checkout_version()
    if checkout_version is not None:
        return checkout_version
    try:
        return _pkg_version("ante")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


__version__ = _resolve_version()

__all__ = ["__version__"]
