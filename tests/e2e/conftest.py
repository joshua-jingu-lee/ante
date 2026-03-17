"""E2E 테스트 fixture — Docker 환경 + Playwright 설정.

사용법:
    # Docker 내부 (e2e-runner 컨테이너)
    pytest tests/e2e/ -m e2e --base-url http://ante-test:8000

    # 로컬 개발 (ante-test 컨테이너 실행 중)
    pytest tests/e2e/ -m e2e --base-url http://localhost:8000
"""

from __future__ import annotations

import os
import subprocess
import time

import httpx
import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """E2E 테스트 옵션."""
    parser.addoption(
        "--docker-up",
        action="store_true",
        default=False,
        help="테스트 전에 docker compose up 자동 실행",
    )


# ── Session-scoped fixtures ──────────────────────────


@pytest.fixture(scope="session")
def base_url(base_url: str) -> str:  # noqa: ANN001
    """Ante 서버 base URL — pytest-playwright의 --base-url을 그대로 사용.

    E2E_BASE_URL 환경변수가 설정되어 있고 --base-url이 기본값이면 환경변수를 우선한다.
    """
    env_url = os.environ.get("E2E_BASE_URL")
    if env_url and base_url == "http://localhost:8000":
        return env_url
    return base_url


@pytest.fixture(scope="session")
def api_url(base_url: str) -> str:
    """API base URL (예: http://ante-test:8000/api)."""
    return f"{base_url}/api"


@pytest.fixture(scope="session")
def docker_compose(request: pytest.FixtureRequest) -> None:  # noqa: PT004
    """Docker Compose 테스트 환경 기동/정리.

    --docker-up 옵션 사용 시에만 자동 기동한다.
    """
    if not request.config.getoption("--docker-up"):
        return

    compose_file = "docker-compose.test.yml"

    subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "--build", "-d"],
        check=True,
    )

    base = request.config.getoption("--base-url")
    _wait_for_healthy(f"{base}/api/system/health", timeout=60)

    yield

    subprocess.run(
        ["docker", "compose", "-f", compose_file, "down", "-v"],
        check=True,
    )


@pytest.fixture(scope="session")
def browser_type_launch_args() -> dict:
    """Playwright 브라우저 실행 인자 (Docker 내 실행용)."""
    return {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}


@pytest.fixture(scope="session")
def browser_context_args() -> dict:
    """Playwright 브라우저 컨텍스트 설정."""
    return {
        "viewport": {"width": 1280, "height": 720},
        "locale": "ko-KR",
    }


# ── Module-scoped fixtures ───────────────────────────


@pytest.fixture(scope="module")
def seed_scenario(request: pytest.FixtureRequest, base_url: str) -> str:
    """모듈의 SCENARIO 변수를 읽고 시드 데이터를 리셋한다.

    각 테스트 모듈 상단에 ``SCENARIO = "scenario-name"`` 을 선언하면
    해당 시나리오로 DB를 리셋한다.
    """
    scenario = getattr(request.module, "SCENARIO", None)
    if scenario is None:
        pytest.skip("SCENARIO가 정의되지 않은 모듈")

    resp = httpx.post(
        f"{base_url}/api/test/reset",
        params={"scenario": scenario},
        timeout=30,
    )
    assert resp.status_code == 200, f"시드 리셋 실패: {resp.text}"
    return scenario


# ── Function-scoped fixtures ─────────────────────────


@pytest.fixture()
def authenticated_page(page, base_url: str, seed_scenario: str):  # noqa: ANN001, ARG001
    """로그인 완료된 Playwright page를 반환한다."""
    password = os.environ.get("E2E_TEST_PASSWORD", "test1234")

    page.goto(f"{base_url}/login", wait_until="commit")
    # React SPA 렌더링 안정화 대기
    page.wait_for_selector('input[type="text"]', state="visible", timeout=15000)
    page.wait_for_timeout(500)

    page.locator('input[type="text"]').fill("owner", force=True)
    page.locator('input[type="password"]').fill(password, force=True)
    page.locator('button[type="submit"]').click(force=True)

    # 로그인 후 대시보드 이동 대기
    page.wait_for_timeout(3000)

    return page


@pytest.fixture(autouse=True)
def _screenshot_on_failure(request: pytest.FixtureRequest, page) -> None:  # noqa: ANN001, PT004
    """테스트 실패 시 자동 스크린샷 저장."""
    yield

    if hasattr(request.node, "rep_call") and request.node.rep_call.failed:
        name = request.node.name.replace("[", "_").replace("]", "")
        screenshot_path = f"test-results/{name}.png"
        try:
            page.screenshot(path=screenshot_path)
        except Exception:
            pass


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):  # noqa: ANN001, ARG001
    """테스트 결과를 request.node에 저장 (스크린샷 fixture에서 사용)."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


# ── 헬퍼 ─────────────────────────────────────────────


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
