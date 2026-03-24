"""버전 확인 유틸리티 — 현재 버전과 PyPI 최신 버전 비교."""

from __future__ import annotations

import asyncio
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


def _check_and_log() -> None:
    """동기 버전 확인 + 로그 출력. 스레드에서 실행된다."""
    current = get_current_version()
    if current == "dev":
        return

    latest = get_latest_version()
    if latest is None:
        return

    if is_update_available(current, latest):
        logger.info(
            "새 버전 사용 가능: v%s (현재 v%s). ante update 실행",
            latest,
            current,
        )


async def check_update_on_startup() -> None:
    """서버 시작 시 비동기로 최신 버전을 확인한다.

    블로킹 네트워크 I/O를 별도 스레드에서 실행하여
    서버 시작을 지연시키지 않는다. 모든 예외를 무시한다.
    """
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _check_and_log)
    except Exception:
        # 네트워크 오류 등 어떤 예외든 서버 시작을 방해하지 않는다
        logger.debug("시작 시 버전 확인 실패 (무시)", exc_info=True)
