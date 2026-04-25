"""Ante — AI-Native Trading Engine.

패키지 버전을 단일 출처(pyproject.toml)에서 제공한다.
Web API/OpenAPI/CLI 등 공개 버전 표면은 모두 이 값을 참조한다.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("ante")
except PackageNotFoundError:  # editable 설치 전 개발 환경
    __version__ = "0.0.0"

__all__ = ["__version__"]
