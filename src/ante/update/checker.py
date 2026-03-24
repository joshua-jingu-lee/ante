"""버전 확인 유틸리티 — 현재 버전과 PyPI 최신 버전 비교."""

from __future__ import annotations

import json
import logging
import urllib.request
from importlib.metadata import version as pkg_version

logger = logging.getLogger(__name__)
PYPI_URL = "https://pypi.org/pypi/ante/json"


def get_current_version() -> str:
    """설치된 ante 패키지 버전을 반환한다. 실패 시 'dev'."""
    try:
        return pkg_version("ante")
    except Exception:
        return "dev"


def get_latest_version() -> str | None:
    """PyPI에서 최신 버전을 조회한다. 실패 시 None."""
    try:
        req = urllib.request.Request(PYPI_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return data["info"]["version"]
    except Exception as e:
        logger.warning("PyPI 버전 조회 실패: %s", e)
        return None


def is_update_available(current: str, latest: str) -> bool:
    """latest가 current보다 높은지 비교한다."""
    from packaging.version import Version

    try:
        return Version(latest) > Version(current)
    except Exception:
        return False
