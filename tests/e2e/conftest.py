"""E2E 테스트 fixture — Docker 환경 기동/정리.

사용법:
    pytest tests/e2e/ --base-url http://localhost:8000

Docker 환경이 이미 실행 중이어야 한다:
    docker compose -f docker-compose.test.yml up --build -d
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """E2E 테스트 옵션."""
    parser.addoption(
        "--base-url",
        default=os.environ.get("E2E_BASE_URL", "http://localhost:8000"),
        help="Ante 서버 base URL (기본: http://localhost:8000)",
    )
    parser.addoption(
        "--docker-up",
        action="store_true",
        default=False,
        help="테스트 전에 docker compose up 자동 실행",
    )


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str:
    """Ante 서버 base URL."""
    return request.config.getoption("--base-url")


@pytest.fixture(scope="session")
def docker_compose(request: pytest.FixtureRequest) -> None:  # noqa: PT004
    """Docker Compose 테스트 환경 기동/정리.

    --docker-up 옵션 사용 시에만 자동 기동한다.
    """
    if not request.config.getoption("--docker-up"):
        return

    compose_file = "docker-compose.test.yml"

    # 기동
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "--build", "-d"],
        check=True,
    )

    # 헬스체크 대기 (최대 60초)
    base = request.config.getoption("--base-url")
    _wait_for_healthy(f"{base}/api/system/health", timeout=60)

    yield

    # 정리
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "down", "-v"],
        check=True,
    )


def _wait_for_healthy(url: str, timeout: int = 60) -> None:
    """서버 헬스체크 대기."""
    import urllib.request

    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        time.sleep(2)
    msg = f"서버가 {timeout}초 내에 응답하지 않음: {url}"
    raise TimeoutError(msg)


@pytest.fixture(scope="session")
def api_url(base_url: str) -> str:
    """API base URL (예: http://localhost:8000/api)."""
    return f"{base_url}/api"
